"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, type ApiError } from "@/lib/api/client";
import { getEventStore, queryKeys } from "@/lib/api/queries";
import { isTerminal, type RunDetail, type RunEvent } from "@/lib/api/types";
import { applyEventsToDetail, mergeEvents, needsDetailRefetch } from "@/lib/run-events";

import { runStream, type BackoffOptions, type ConnectionStatus } from "./run-stream";

export interface RunStreamState {
  status: ConnectionStatus;
  /** Failed connects in a row; 0 while live. */
  attempt: number;
  error: ApiError | null;
}

export interface UseRunStreamOptions {
  enabled?: boolean;
  /** Coalesces detail refetches when many idea/status events arrive together. */
  refetchDelayMs?: number;
  backoff?: BackoffOptions;
}

/**
 * Streams a run's events into the Query cache (ADR 0005):
 * - `["runs","events",id]` gets every event once, in id order (replays are dropped by id);
 * - `["runs","detail",id]` is patched in place for status, error and budget, and refetched
 *   (debounced) when ideas or the run lifecycle change, and after every reconnect.
 *
 * It resumes from the cached cursor, so remounting (or Next showing a hidden page again)
 * continues where it stopped instead of replaying the whole run.
 */
export function useRunStream(runId: string, options: UseRunStreamOptions = {}): RunStreamState {
  const { enabled = true } = options;
  const client = useQueryClient();
  // Tuning options are read when used, so passing a fresh object each render does not reconnect.
  const tuning = useRef(options);
  useEffect(() => {
    tuning.current = options;
  });
  const [state, setState] = useState<RunStreamState>({
    status: "connecting",
    attempt: 0,
    error: null,
  });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let refetchTimer: ReturnType<typeof setTimeout> | undefined;

    function scheduleRefetch() {
      clearTimeout(refetchTimer);
      refetchTimer = setTimeout(() => {
        void client.invalidateQueries({ queryKey: queryKeys.run(runId) });
      }, tuning.current.refetchDelayMs ?? 250);
    }

    function onEvents(events: RunEvent[]) {
      const before = getEventStore(client, runId);
      const after = mergeEvents(before, events);
      if (after === before) return;
      const fresh = after.events.slice(before.events.length);
      client.setQueryData(queryKeys.runEvents(runId), after);
      client.setQueryData<RunDetail>(queryKeys.run(runId), (detail) =>
        detail ? applyEventsToDetail(detail, fresh) : detail,
      );
      if (needsDetailRefetch(fresh)) scheduleRefetch();
    }

    void runStream({
      url: api.streamUrl(runId),
      signal: controller.signal,
      backoff: tuning.current.backoff,
      getCursor: () => getEventStore(client, runId).lastId,
      isTerminal: () => {
        const streamed = getEventStore(client, runId).status;
        const cached = client.getQueryData<RunDetail>(queryKeys.run(runId))?.status;
        return isTerminal(streamed ?? cached);
      },
      onEvents,
      onOpen: (reconnected) => {
        if (reconnected) scheduleRefetch();
      },
      onStatus: (status, detail) => {
        if (controller.signal.aborted) return;
        setState({ status, attempt: detail.attempt, error: detail.error ?? null });
      },
    });

    return () => {
      controller.abort();
      clearTimeout(refetchTimer);
    };
  }, [client, runId, enabled]);

  return state;
}

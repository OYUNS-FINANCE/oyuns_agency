import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getEventStore, queryKeys, useRun } from "@/lib/api/queries";
import type { RunDetail } from "@/lib/api/types";
import {
  RUN_ID,
  event,
  jsonResponse,
  runDetail,
  sse,
  statusEvent,
  streamResponse,
} from "@/test/fixtures";

import { useRunStream } from "./use-run-stream";

const FAST = { initialMs: 1, maxMs: 2, random: () => 0 };
const thought = (id: number) => event(id, "agent.thought", { text: `note ${id}` }, "scout");

function setup(streams: Response[], detail: () => RunDetail = () => runDetail()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const streamHeaders: Record<string, string>[] = [];
  const detailCalls = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/stream")) {
        streamHeaders.push({ ...(init?.headers as Record<string, string>) });
        const next = streams.shift();
        return next
          ? Promise.resolve(next)
          : new Promise<Response>((_, reject) =>
              init?.signal?.addEventListener("abort", () =>
                reject(new DOMException("aborted", "AbortError")),
              ),
            );
      }
      detailCalls();
      return Promise.resolve(jsonResponse(detail()));
    }),
  );
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, streamHeaders, detailCalls, wrapper };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRunStream", () => {
  it("merges a replay after reconnect without duplicating events", async () => {
    const { client, streamHeaders, wrapper } = setup([
      streamResponse([sse([statusEvent(1, "running"), thought(2), thought(3)])], { fail: true }),
      // The server replays from the cursor; an overlapping event (3) must be dropped.
      streamResponse([sse([thought(3), thought(4), statusEvent(5, "awaiting_human")])]),
      streamResponse([sse([statusEvent(6, "completed")])]),
    ]);
    const { result } = renderHook(
      () => useRunStream(RUN_ID, { backoff: FAST, refetchDelayMs: 0 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.status).toBe("closed"));
    const store = getEventStore(client, RUN_ID);
    expect(store.events.map((e) => e.id)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(store.lastId).toBe(6);
    expect(store.status).toBe("completed");
    expect(streamHeaders.map((h) => h["Last-Event-ID"])).toEqual([undefined, "3", "5"]);
  });

  it("reports reconnecting while the API is down, then goes live again", async () => {
    // The third connection delivers one event and then stays open, like a healthy live stream.
    const openStream = new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(sse([thought(2)])));
        },
      }),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
    const { client, streamHeaders, wrapper } = setup([
      streamResponse([sse([statusEvent(1, "running")])], { fail: true }),
      jsonResponse({ error: { code: "internal_error", message: "down" } }, 502),
      openStream,
    ]);
    const { result } = renderHook(
      () => useRunStream(RUN_ID, { backoff: { ...FAST, initialMs: 400, maxMs: 400 } }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.status).toBe("reconnecting"));
    expect(result.current.attempt).toBeGreaterThan(0);
    await waitFor(() => expect(result.current.status).toBe("live"), { timeout: 2_000 });
    expect(result.current.attempt).toBe(0);
    expect(getEventStore(client, RUN_ID).events.map((e) => e.id)).toEqual([1, 2]);
    expect(streamHeaders.map((h) => h["Last-Event-ID"])).toEqual([undefined, "1", "1"]);
  });

  it("patches the cached run detail and refetches it when ideas arrive", async () => {
    const created = event(3, "idea.created", {
      idea_id: "22222222-2222-4222-8222-222222222222",
      key: "opp-01",
      title: "Receipt-to-ledger",
      rank: 1,
      composite_score: 7.4,
      version: 1,
    });
    const { client, detailCalls, wrapper } = setup([
      streamResponse([
        sse([
          statusEvent(1, "running"),
          event(2, "budget.warning", { kind: "searches", used: 85, limit: 100 }),
          created,
          statusEvent(4, "completed"),
        ]),
      ]),
    ]);

    const { result } = renderHook(
      () => {
        useRun(RUN_ID); // an observer, so invalidation refetches
        return useRunStream(RUN_ID, { refetchDelayMs: 0 });
      },
      { wrapper },
    );
    await waitFor(() => expect(result.current.status).toBe("closed"));
    // The initial load, then one debounced refetch for the whole chunk of events.
    await waitFor(() => expect(detailCalls).toHaveBeenCalledTimes(2));
    expect(client.getQueryData<RunDetail>(queryKeys.run(RUN_ID))?.id).toBe(RUN_ID);
  });

  it("applies event fields to the detail before the refetch lands", async () => {
    const { client, wrapper } = setup([
      streamResponse([
        sse([
          statusEvent(1, "running"),
          event(2, "budget.warning", { kind: "searches", used: 85, limit: 100 }),
        ]),
      ]),
    ]);
    client.setQueryData(queryKeys.run(RUN_ID), runDetail({ status: "queued" }));
    renderHook(() => useRunStream(RUN_ID, { refetchDelayMs: 60_000 }), { wrapper });
    await waitFor(() =>
      expect(client.getQueryData<RunDetail>(queryKeys.run(RUN_ID))?.status).toBe("running"),
    );
    expect(client.getQueryData<RunDetail>(queryKeys.run(RUN_ID))?.budget.searches_used).toBe(85);
  });

  it("resumes from the cached cursor when remounted", async () => {
    const { streamHeaders, wrapper } = setup([
      streamResponse([sse([statusEvent(1, "running"), thought(2)])]),
    ]);
    const first = renderHook(() => useRunStream(RUN_ID, { backoff: FAST }), { wrapper });
    await waitFor(() => expect(streamHeaders).toHaveLength(2));
    first.unmount();
    renderHook(() => useRunStream(RUN_ID, { backoff: FAST }), { wrapper });
    await waitFor(() => expect(streamHeaders).toHaveLength(3));
    expect(streamHeaders[2]?.["Last-Event-ID"]).toBe("2");
  });

  it("stops with an error for an unknown run", async () => {
    const { streamHeaders, wrapper } = setup([
      jsonResponse({ error: { code: "not_found", message: "Run not found" } }, 404),
    ]);
    const { result } = renderHook(() => useRunStream(RUN_ID, { backoff: FAST }), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.status).toBe(404);
    expect(streamHeaders).toHaveLength(1);
  });

  it("does nothing while disabled", () => {
    const { streamHeaders, wrapper } = setup([]);
    const { result } = renderHook(() => useRunStream(RUN_ID, { enabled: false }), { wrapper });
    expect(result.current.status).toBe("connecting");
    expect(streamHeaders).toHaveLength(0);
  });
});

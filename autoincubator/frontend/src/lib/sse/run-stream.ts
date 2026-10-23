/**
 * The connection loop behind `useRunStream`, kept free of React so it can be tested with a fake
 * `fetch`. See ADR 0005.
 *
 * It uses `fetch` rather than `EventSource` so that it can send a real `Last-Event-ID` header on
 * every connect, back off exponentially, and tell a missing run (404, stop) from an API that is
 * down (5xx or network error, retry). `EventSource` gives up for good on any non-200 response,
 * which is exactly what the Next proxy returns while the API restarts.
 */
import { errorFromResponse, type ApiError } from "@/lib/api/client";
import type { RunEvent } from "@/lib/api/types";

import { SseParser } from "./parse";

export type ConnectionStatus = "connecting" | "live" | "reconnecting" | "closed" | "error";

export interface BackoffOptions {
  initialMs: number;
  maxMs: number;
  /** Returns a number in [0, 1); injectable for tests. */
  random: () => number;
}

export const DEFAULT_BACKOFF: BackoffOptions = {
  initialMs: 500,
  maxMs: 15_000,
  random: Math.random,
};

/** Exponential backoff with "equal jitter": half the step is fixed, half is random. */
export function backoffDelay(attempt: number, options: BackoffOptions): number {
  const step = Math.min(options.maxMs, options.initialMs * 2 ** Math.max(0, attempt - 1));
  return Math.round(step / 2 + (options.random() * step) / 2);
}

export interface RunStreamOptions {
  url: string;
  signal: AbortSignal;
  /** Id of the last event already applied; sent as `Last-Event-ID` (0 = from the start). */
  getCursor: () => number;
  /** Whether the run has reached a terminal status, read when the server closes the stream. */
  isTerminal: () => boolean;
  /** Events parsed from one network chunk, in order. Callers drop ids at or below the cursor. */
  onEvents: (events: RunEvent[]) => void;
  onStatus: (status: ConnectionStatus, detail: { attempt: number; error?: ApiError }) => void;
  /** Called on every successful connect; `reconnected` is false only for the first one. */
  onOpen?: (reconnected: boolean) => void;
  fetchImpl?: typeof fetch;
  backoff?: BackoffOptions;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
}

function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });
}

/** 4xx other than timeouts and rate limits will not fix themselves by retrying. */
function isFatal(status: number): boolean {
  return status >= 400 && status < 500 && status !== 408 && status !== 429;
}

function parseEvent(data: string): RunEvent | null {
  try {
    const value: unknown = JSON.parse(data);
    if (
      typeof value === "object" &&
      value !== null &&
      typeof (value as { id?: unknown }).id === "number" &&
      typeof (value as { type?: unknown }).type === "string"
    ) {
      return value as RunEvent;
    }
  } catch {
    // Fall through: a malformed message is skipped rather than retried forever.
  }
  return null;
}

/** Reads one response body to its end, handing parsed events over chunk by chunk. */
async function consume(body: ReadableStream<Uint8Array>, options: RunStreamOptions): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      const text = done ? decoder.decode() : decoder.decode(value, { stream: true });
      const events = parser
        .push(text)
        .map((message) => parseEvent(message.data))
        .filter((event): event is RunEvent => event !== null);
      if (events.length > 0) options.onEvents(events);
      if (done) return;
    }
  } finally {
    reader.releaseLock();
  }
}

/** Runs until the run is terminal, the run is not found, or `signal` aborts. Never throws. */
export async function runStream(options: RunStreamOptions): Promise<void> {
  const { signal } = options;
  const fetchImpl = options.fetchImpl ?? fetch;
  const backoff = options.backoff ?? DEFAULT_BACKOFF;
  const sleep = options.sleep ?? abortableSleep;
  let attempt = 0;
  let connected = false;

  while (!signal.aborted) {
    options.onStatus(connected || attempt > 0 ? "reconnecting" : "connecting", { attempt });
    try {
      const cursor = options.getCursor();
      const headers: Record<string, string> = { accept: "text/event-stream" };
      if (cursor > 0) headers["Last-Event-ID"] = String(cursor);
      const response = await fetchImpl(options.url, { headers, signal, cache: "no-store" });
      if (isFatal(response.status)) {
        options.onStatus("error", { attempt, error: await errorFromResponse(response) });
        return;
      }
      if (!response.ok || response.body === null) {
        throw new Error(`stream HTTP ${response.status}`);
      }
      options.onOpen?.(connected);
      connected = true;
      attempt = 0;
      options.onStatus("live", { attempt });
      await consume(response.body, options);
      // The server closes the stream only once the run is terminal. Any other close means the
      // API (or the proxy in front of it) went away, so reconnect.
      if (options.isTerminal()) {
        options.onStatus("closed", { attempt });
        return;
      }
    } catch {
      if (signal.aborted) return;
    }
    attempt += 1;
    options.onStatus("reconnecting", { attempt });
    await sleep(backoffDelay(attempt, backoff), signal);
  }
}

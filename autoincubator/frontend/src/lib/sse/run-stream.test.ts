import { describe, expect, it, vi } from "vitest";

import type { RunEvent } from "@/lib/api/types";
import { jsonResponse, sse, statusEvent, streamResponse, event } from "@/test/fixtures";

import {
  backoffDelay,
  runStream,
  type ConnectionStatus,
  type RunStreamOptions,
} from "./run-stream";

const thought = (id: number) => event(id, "agent.thought", { text: `note ${id}` }, "scout");

/** Drives `runStream` against scripted responses; records statuses, headers and sleeps. */
function harness(responses: (Response | Error)[], overrides: Partial<RunStreamOptions> = {}) {
  const received: RunEvent[] = [];
  const statuses: ConnectionStatus[] = [];
  const sleeps: number[] = [];
  const headers: Record<string, string>[] = [];
  const controller = new AbortController();
  const fetchImpl = vi.fn((_url: string | URL | Request, init?: RequestInit) => {
    headers.push({ ...(init?.headers as Record<string, string>) });
    const next = responses.shift();
    if (next === undefined) {
      controller.abort();
      return Promise.reject(new DOMException("aborted", "AbortError"));
    }
    return next instanceof Error ? Promise.reject(next) : Promise.resolve(next);
  });
  const options: RunStreamOptions = {
    url: "/api/incubator/runs/x/stream",
    signal: controller.signal,
    getCursor: () => received.at(-1)?.id ?? 0,
    isTerminal: () =>
      received.some(
        (e) => e.type === "run.status" && ["completed", "failed"].includes(e.data.status),
      ),
    onEvents: (events) => received.push(...events),
    onStatus: (status) => statuses.push(status),
    fetchImpl: fetchImpl as unknown as typeof fetch,
    backoff: { initialMs: 100, maxMs: 1_000, random: () => 0.5 },
    sleep: (ms) => {
      sleeps.push(ms);
      return Promise.resolve();
    },
    ...overrides,
  };
  return { options, received, statuses, sleeps, headers, fetchImpl, controller };
}

describe("backoffDelay", () => {
  it("doubles per attempt with jitter and caps at maxMs", () => {
    const opts = { initialMs: 500, maxMs: 15_000, random: () => 1 };
    expect([1, 2, 3, 4, 5, 6, 7].map((a) => backoffDelay(a, opts))).toEqual([
      500, 1_000, 2_000, 4_000, 8_000, 15_000, 15_000,
    ]);
    expect(backoffDelay(3, { ...opts, random: () => 0 })).toBe(1_000);
  });
});

describe("runStream", () => {
  it("delivers events and closes once the run is terminal", async () => {
    const h = harness([
      streamResponse([sse([statusEvent(1, "running"), thought(2), statusEvent(3, "completed")])]),
    ]);
    await runStream(h.options);
    expect(h.received.map((e) => e.id)).toEqual([1, 2, 3]);
    expect(h.statuses).toEqual(["connecting", "live", "closed"]);
    expect(h.headers[0]).not.toHaveProperty("Last-Event-ID");
  });

  it("reconnects with Last-Event-ID and exponential backoff after drops and 5xx", async () => {
    const h = harness([
      streamResponse([sse([statusEvent(1, "running"), thought(2)])], { fail: true }),
      jsonResponse({ error: { code: "bad_gateway", message: "down" } }, 502),
      new TypeError("Failed to fetch"),
      streamResponse([sse([thought(3), statusEvent(4, "completed")])]),
    ]);
    await runStream(h.options);
    expect(h.received.map((e) => e.id)).toEqual([1, 2, 3, 4]);
    expect(h.headers.map((x) => x["Last-Event-ID"])).toEqual([undefined, "2", "2", "2"]);
    // random() = 0.5 → 3/4 of each step: 100, 200, 400 ms.
    expect(h.sleeps).toEqual([75, 150, 300]);
    expect(h.statuses).toEqual([
      "connecting",
      "live",
      "reconnecting",
      "reconnecting",
      "reconnecting",
      "reconnecting",
      "reconnecting",
      "reconnecting",
      "live",
      "closed",
    ]);
  });

  it("resets the backoff after a successful connect", async () => {
    const h = harness([
      new TypeError("Failed to fetch"),
      new TypeError("Failed to fetch"),
      streamResponse([sse([thought(1)])], { fail: true }),
      streamResponse([sse([statusEvent(2, "completed")])]),
    ]);
    await runStream(h.options);
    expect(h.sleeps).toEqual([75, 150, 75]);
  });

  it("reconnects when the server ends the stream before the run is terminal", async () => {
    const h = harness([
      streamResponse([sse([statusEvent(1, "running")])]),
      streamResponse([sse([statusEvent(2, "completed")])]),
    ]);
    await runStream(h.options);
    expect(h.fetchImpl).toHaveBeenCalledTimes(2);
    expect(h.headers[1]?.["Last-Event-ID"]).toBe("1");
  });

  it("stops without retrying when the run does not exist", async () => {
    const onStatus = vi.fn();
    const h = harness(
      [jsonResponse({ error: { code: "not_found", message: "Run not found" } }, 404)],
      {
        onStatus,
      },
    );
    await runStream(h.options);
    expect(h.fetchImpl).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenLastCalledWith(
      "error",
      expect.objectContaining({
        error: expect.objectContaining({ status: 404, code: "not_found" }),
      }),
    );
  });

  it("skips malformed messages instead of failing the stream", async () => {
    const h = harness([
      streamResponse([`id: 1\ndata: not json\n\n`, sse([statusEvent(2, "completed")])]),
    ]);
    await runStream(h.options);
    expect(h.received.map((e) => e.id)).toEqual([2]);
  });

  it("stops quietly when aborted", async () => {
    const h = harness([]);
    h.controller.abort();
    await runStream(h.options);
    expect(h.fetchImpl).not.toHaveBeenCalled();
  });
});

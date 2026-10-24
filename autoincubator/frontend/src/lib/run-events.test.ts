import { describe, expect, it } from "vitest";

import { event, runDetail, statusEvent } from "@/test/fixtures";

import {
  EMPTY_EVENT_STORE,
  applyEventsToDetail,
  mergeEvents,
  needsDetailRefetch,
} from "./run-events";

const thought = (id: number) => event(id, "agent.thought", { text: "t" }, "scout");

describe("mergeEvents", () => {
  it("appends new events, tracks the cursor and the latest status", () => {
    const store = mergeEvents(EMPTY_EVENT_STORE, [statusEvent(1, "running"), thought(2)]);
    expect(store.events.map((e) => e.id)).toEqual([1, 2]);
    expect(store.lastId).toBe(2);
    expect(store.status).toBe("running");
  });

  it("drops replayed ids and returns the same object when nothing is new", () => {
    const store = mergeEvents(EMPTY_EVENT_STORE, [thought(1), thought(2)]);
    expect(mergeEvents(store, [thought(1), thought(2)])).toBe(store);
    const next = mergeEvents(store, [thought(2), thought(3)]);
    expect(next.events.map((e) => e.id)).toEqual([1, 2, 3]);
  });
});

describe("applyEventsToDetail", () => {
  it("applies status, error and interrupt fields in order", () => {
    const detail = applyEventsToDetail(runDetail({ status: "queued" }), [
      statusEvent(1, "running"),
      event(2, "run.interrupted", { viable_count: 2, shortfall: "Only 2", idea_ids: [] }),
      event(3, "run.error", { code: "boom", message: "It broke" }),
      statusEvent(4, "failed"),
    ]);
    expect(detail.status).toBe("failed");
    expect(detail.viable_count).toBe(2);
    expect(detail.shortfall).toBe("Only 2");
    expect(detail.error).toEqual({ code: "boom", message: "It broke" });
  });

  it("never moves budget counters backwards on replay", () => {
    const base = runDetail();
    const fresh = { ...base, budget: { ...base.budget, tokens_used: 900_000 } };
    const detail = applyEventsToDetail(fresh, [
      event(1, "budget.warning", { kind: "tokens", used: 800_000, limit: 1_000_000 }),
      event(2, "budget.exhausted", { kind: "searches", used: 100, limit: 100 }),
    ]);
    expect(detail.budget.tokens_used).toBe(900_000);
    expect(detail.budget.searches_used).toBe(100);
  });

  it("reads the daily cost cap in cents", () => {
    const detail = applyEventsToDetail(runDetail(), [
      event(1, "budget.exhausted", { kind: "daily_cost", used: 2_550, limit: 2_500 }),
    ]);
    expect(detail.budget.daily_spent_usd).toBe(25.5);
    expect(detail.budget.daily_cap_usd).toBe(25);
    expect(detail.budget.max_searches).toBe(100);
  });

  it("returns the same object when no event changes the detail", () => {
    const detail = runDetail();
    expect(applyEventsToDetail(detail, [thought(1)])).toBe(detail);
  });
});

describe("needsDetailRefetch", () => {
  it("is true for idea and lifecycle events only", () => {
    expect(needsDetailRefetch([thought(1)])).toBe(false);
    expect(needsDetailRefetch([thought(1), statusEvent(2, "completed")])).toBe(true);
  });
});

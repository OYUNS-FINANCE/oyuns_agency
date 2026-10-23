import { describe, expect, it } from "vitest";

import { IDEA_ID, event } from "@/test/fixtures";

import { IN_FLIGHT_STALE_MS, inFlight } from "./cowork";

const started = (id: number, node: string, ideaId: string | null = null) =>
  event(id, "agent.started", { node, iteration: null, items: 1, idea_id: ideaId }, "skeptic");
const completed = (id: number, node: string, ideaId: string | null = null) =>
  event(id, "agent.completed", { node, duration_ms: 5, summary: {}, idea_id: ideaId }, "skeptic");

describe("inFlight", () => {
  it("tracks re-scores per idea and merges until they complete", () => {
    const now = Date.now();
    const fresh = (e: ReturnType<typeof started>) => ({ ...e, ts: new Date(now).toISOString() });
    const open = inFlight([fresh(started(1, "rescore", IDEA_ID)), fresh(started(2, "merge"))], now);
    expect([...open.rescoring]).toEqual([IDEA_ID]);
    expect(open.merges).toBe(1);

    const done = inFlight(
      [
        fresh(started(1, "rescore", IDEA_ID)),
        fresh(started(2, "merge")),
        completed(3, "rescore", IDEA_ID),
        completed(4, "merge"),
      ],
      now,
    );
    expect(done.rescoring.size).toBe(0);
    expect(done.merges).toBe(0);
  });

  it("ignores Phase-1 passes and starts whose job was lost long ago", () => {
    const old = started(1, "rescore", IDEA_ID);
    const later = Date.parse(old.ts) + IN_FLIGHT_STALE_MS + 1;
    expect(inFlight([started(2, "scout"), old], later).rescoring.size).toBe(0);
  });
});

import { describe, expect, it } from "vitest";

import { event, statusEvent } from "@/test/fixtures";

import { announcedIdeas, buildTimeline } from "./activity";

describe("buildTimeline", () => {
  it("groups agent events into passes and keeps run markers between them", () => {
    const items = buildTimeline([
      statusEvent(1, "running"),
      event(2, "agent.started", { node: "scout", iteration: 1, items: null }, "scout"),
      event(
        3,
        "agent.tool_call",
        { tool: "search", query: "cafe receipts", result_count: 5, idea_key: null },
        "scout",
      ),
      event(4, "agent.thought", { text: "6 candidates" }, "scout"),
      event(
        5,
        "agent.completed",
        { node: "scout", duration_ms: 1200, summary: { kept: 4 } },
        "scout",
      ),
      event(6, "agent.started", { node: "analyst", iteration: null, items: 4 }, "analyst"),
      event(7, "agent.started", { node: "scout", iteration: 2, items: null }, "scout"),
    ]);
    expect(
      items.map((i) => (i.kind === "pass" ? `${i.pass.agent}#${i.pass.pass}` : i.event.type)),
    ).toEqual(["run.status", "scout#1", "analyst#1", "scout#2"]);
    const scout = items[1];
    expect(scout?.kind === "pass" && scout.pass).toMatchObject({
      completed: true,
      durationMs: 1200,
      summary: { kept: 4 },
      iteration: 1,
    });
    expect(scout?.kind === "pass" && scout.pass.entries.map((e) => e.kind)).toEqual([
      "tool",
      "thought",
    ]);
    const analyst = items[2];
    expect(analyst?.kind === "pass" && analyst.pass).toMatchObject({ completed: false, items: 4 });
  });

  it("opens a pass for an agent that never announced a start", () => {
    const items = buildTimeline([
      event(1, "agent.thought", { text: "ranking 3 ideas" }, "ranker"),
      event(2, "agent.completed", { node: "rank", duration_ms: 3, summary: {} }, "ranker"),
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]?.kind === "pass" && items[0].pass.completed).toBe(true);
  });
});

describe("announcedIdeas", () => {
  it("returns ideas by rank, latest event per idea", () => {
    const created = (id: number, ideaId: string, rank: number, title: string) =>
      event(id, "idea.created", {
        idea_id: ideaId,
        key: `opp-${rank}`,
        title,
        rank,
        composite_score: 7,
        version: 1,
      });
    const ideas = announcedIdeas([created(1, "b", 2, "Second"), created(2, "a", 1, "First")]);
    expect(ideas.map((i) => i.title)).toEqual(["First", "Second"]);
  });
});

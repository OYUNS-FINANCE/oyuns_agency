import { describe, expect, it } from "vitest";

import { idea, version } from "@/test/fixtures";

import { compareVersions, diffWords, pathLabel } from "./diff";

describe("diffWords", () => {
  it("marks removed and added words and keeps the rest", () => {
    expect(diffWords("Photograph paper receipts weekly", "Photograph all receipts weekly")).toEqual(
      [
        { kind: "same", text: "Photograph " },
        { kind: "removed", text: "paper" },
        { kind: "added", text: "all" },
        { kind: "same", text: " receipts weekly" },
      ],
    );
  });

  it("handles empty sides", () => {
    expect(diffWords("", "new text")).toEqual([{ kind: "added", text: "new text" }]);
    expect(diffWords("old", "")).toEqual([{ kind: "removed", text: "old" }]);
  });
});

describe("compareVersions", () => {
  it("lists only changed leaf fields with readable labels", () => {
    const base = idea();
    const edited = version(2, {
      opportunity: { ...base.opportunity, one_liner: "Ledgers for café chains." },
      analysis: {
        ...base.analysis,
        segments: [...base.analysis.segments, { name: "Chains", description: "5+ sites" }],
      },
    });
    const changes = compareVersions(version(1), edited);
    expect(changes.map((c) => c.label)).toEqual([
      "Idea › one liner",
      "Market › segments › Chains › name",
      "Market › segments › Chains › description",
    ]);
    expect(changes[0]).toMatchObject({
      before: base.opportunity.one_liner,
      after: "Ledgers for café chains.",
    });
    expect(changes[1]).toMatchObject({ before: null, after: "Chains" });
  });

  it("labels rubric rows by dimension", () => {
    const base = idea();
    const scores = base.critique.scores.map((s, i) => (i === 0 ? { ...s, score: 9 } : s));
    const rescored = version(2, { critique: { ...base.critique, scores } });
    expect(compareVersions(version(1), rescored).map((c) => c.label)).toEqual([
      "Scorecard › scores › cac risk › score",
    ]);
  });

  it("finds no changes between identical versions", () => {
    expect(compareVersions(version(1), version(2))).toEqual([]);
  });
});

it("labels JSON pointers", () => {
  expect(pathLabel("/opportunity/target_customer")).toBe("Idea › target customer");
  expect(pathLabel("/analysis/segments/-")).toBe("Market › segments › new");
});

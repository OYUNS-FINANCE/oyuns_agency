import { describe, expect, it } from "vitest";

import type { PlanResponse } from "@/lib/api/types";
import planFixture from "@/test/plan.json";

import {
  assumptionRows,
  chartGeometry,
  contradictionsFor,
  figure,
  money,
  nearestIndex,
  niceStep,
  pct,
  planSources,
  sortedContradictions,
} from "./plan";

const { plan } = planFixture as unknown as PlanResponse;
const FRAME = { width: 100, height: 60, left: 10, right: 10, top: 5, bottom: 5 };

describe("plan formatting", () => {
  it("formats money and shares like the exported dossier", () => {
    expect(money(1234.4)).toBe("$1,234");
    expect(money(63.7)).toBe("$63.70");
    expect(money(-3040)).toBe("-$3,040");
    expect(money(null)).toBe("n/a");
    expect(pct(0.907)).toBe("90.7%");
    expect(figure({ value: 0.04, unit: "share/month", assumption: "x" })).toBe("4.0%");
    expect(figure({ value: 80, unit: "signups", assumption: "x" })).toBe("80");
  });
});

describe("plan contents", () => {
  it("groups contradictions by section and sorts them by severity", () => {
    expect(contradictionsFor(plan, "gtm").map((c) => c.code)).toEqual([
      "channel_cac_mismatch",
      "editor_review",
    ]);
    expect(contradictionsFor(plan, "financials").map((c) => c.code)).toEqual([
      "channel_cac_mismatch",
    ]);
    expect(contradictionsFor(plan, "launch")).toEqual([]);
    expect(sortedContradictions(plan)[0]?.severity).toBe("high");
  });

  it("numbers each cited source once and lists every assumption", () => {
    const sources = planSources(plan);
    expect(new Set(sources).size).toBe(sources.length);
    expect(sources.length).toBeGreaterThan(0);
    const rows = assumptionRows(plan);
    expect(rows.find((r) => r.label === "Monthly churn")?.figure.value).toBe(
      plan.assumptions.monthly_churn.value,
    );
    expect(rows.every((r) => r.figure.source_url || r.figure.assumption)).toBe(true);
  });
});

describe("chart geometry", () => {
  it("picks nice tick steps", () => {
    expect(niceStep(10_000)).toBe(5_000);
    expect(niceStep(37)).toBe(10);
    expect(niceStep(0)).toBe(1);
  });

  it("includes zero, spans the frame and maps values into it", () => {
    const geo = chartGeometry([{ key: "base", values: [-500, 0, 1500] }], FRAME);
    expect(geo.ticks[0]).toBeLessThanOrEqual(-500);
    expect(geo.ticks.at(-1)).toBeGreaterThanOrEqual(1500);
    expect(geo.ticks).toContain(0);
    expect(geo.x(0)).toBe(10);
    expect(geo.x(2)).toBe(90);
    expect(geo.y(geo.ticks.at(-1)!)).toBe(5);
    expect(geo.y(geo.ticks[0]!)).toBe(55);
    expect(geo.zero).toBe(geo.y(0));
    expect(geo.paths[0]?.d.startsWith("M10.0,")).toBe(true);
    expect(geo.paths[0]?.d.split("L")).toHaveLength(3);
  });

  it("snaps a pointer to the nearest month", () => {
    expect(nearestIndex(10, 12, FRAME)).toBe(0);
    expect(nearestIndex(90, 12, FRAME)).toBe(11);
    expect(nearestIndex(48, 12, FRAME)).toBe(5); // (48 - 10) / 80 * 11 = 5.2
    expect(nearestIndex(-40, 12, FRAME)).toBe(0);
  });
});

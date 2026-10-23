import { describe, expect, it } from "vitest";

import { toProfile, toValues } from "./profile-form";

describe("profile form mapping", () => {
  it("round-trips a saved profile", () => {
    const profile = {
      skills: ["sales"],
      region: "Mongolia",
      capital_usd: 15000,
      risk_tolerance: "high" as const,
      weekly_hours: 20,
      rejected_idea_reasons: ["hardware"],
    };
    expect(toProfile(toValues(profile))).toEqual({ ok: true, profile });
  });

  it("turns blank fields into nulls and validates numbers", () => {
    const values = toValues({ risk_tolerance: "medium" });
    expect(toProfile(values)).toMatchObject({
      ok: true,
      profile: { region: null, capital_usd: null, weekly_hours: null, risk_tolerance: "medium" },
    });
    expect(toProfile({ ...values, weeklyHours: "200", capital: "abc" })).toEqual({
      ok: false,
      errors: {
        capital: "Enter a positive amount.",
        weeklyHours: "Whole hours between 1 and 168.",
      },
    });
  });
});

"use client";

import { Check, Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ChipInput } from "@/components/common/chip-input";
import { Segmented } from "@/components/common/segmented";
import { ErrorState, LoadingState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useProfile, useSaveProfile } from "@/lib/api/queries";
import type { FounderProfile, ProfileResponse, RiskTolerance } from "@/lib/api/types";
import { describeError, formatDateTime } from "@/lib/format";

const RISK = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
] as const satisfies readonly { value: RiskTolerance; label: string }[];

export interface ProfileValues {
  skills: string[];
  region: string;
  capital: string;
  risk: RiskTolerance;
  weeklyHours: string;
  rejectedReasons: string[];
}

export function toValues(profile: FounderProfile): ProfileValues {
  return {
    skills: profile.skills ?? [],
    region: profile.region ?? "",
    capital: profile.capital_usd == null ? "" : String(profile.capital_usd),
    risk: profile.risk_tolerance ?? "medium",
    weeklyHours: profile.weekly_hours == null ? "" : String(profile.weekly_hours),
    rejectedReasons: profile.rejected_idea_reasons ?? [],
  };
}

type FieldErrors = Partial<Record<"capital" | "weeklyHours", string>>;

/** Maps the form to the API body, or returns field errors. Exported for tests. */
export function toProfile(
  values: ProfileValues,
): { ok: true; profile: FounderProfile } | { ok: false; errors: FieldErrors } {
  const errors: FieldErrors = {};
  let capital: number | null = null;
  if (values.capital.trim() !== "") {
    capital = Number(values.capital);
    if (!Number.isFinite(capital) || capital < 0) errors.capital = "Enter a positive amount.";
  }
  let hours: number | null = null;
  if (values.weeklyHours.trim() !== "") {
    hours = Number(values.weeklyHours);
    if (!Number.isInteger(hours) || hours < 1 || hours > 168) {
      errors.weeklyHours = "Whole hours between 1 and 168.";
    }
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    profile: {
      skills: values.skills,
      region: values.region.trim() || null,
      capital_usd: capital,
      risk_tolerance: values.risk,
      weekly_hours: hours,
      rejected_idea_reasons: values.rejectedReasons,
    },
  };
}

function Editor({ saved }: { saved: ProfileResponse }) {
  const save = useSaveProfile();
  const [values, setValues] = useState<ProfileValues>(() => toValues(saved.profile));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [dirty, setDirty] = useState(false);

  const set = <K extends keyof ProfileValues>(key: K, value: ProfileValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setErrors({});
    setDirty(true);
  };

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const result = toProfile(values);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    save.mutate(result.profile, { onSuccess: () => setDirty(false) });
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="skills">Skills</Label>
        <ChipInput
          id="skills"
          values={values.skills}
          onChange={(next) => set("skills", next)}
          placeholder="e.g. backend engineering, B2B sales"
        />
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="region">Region</Label>
          <Input
            id="region"
            value={values.region}
            placeholder="e.g. Ulaanbaatar, Mongolia"
            onChange={(event) => set("region", event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="capital">Capital available (USD)</Label>
          <Input
            id="capital"
            inputMode="decimal"
            value={values.capital}
            placeholder="e.g. 15000"
            aria-invalid={errors.capital ? true : undefined}
            onChange={(event) => set("capital", event.target.value)}
            className="tabular font-mono"
          />
          {errors.capital && <p className="text-destructive text-sm">{errors.capital}</p>}
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Risk tolerance</span>
          <Segmented
            label="Risk tolerance"
            value={values.risk}
            options={RISK}
            onChange={(value) => set("risk", value)}
            className="w-full sm:w-fit"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="hours">Hours per week</Label>
          <Input
            id="hours"
            inputMode="numeric"
            value={values.weeklyHours}
            placeholder="e.g. 20"
            aria-invalid={errors.weeklyHours ? true : undefined}
            onChange={(event) => set("weeklyHours", event.target.value)}
            className="tabular font-mono"
          />
          {errors.weeklyHours && <p className="text-destructive text-sm">{errors.weeklyHours}</p>}
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="rejected">Reasons you rejected past ideas</Label>
        <ChipInput
          id="rejected"
          values={values.rejectedReasons}
          onChange={(next) => set("rejectedReasons", next)}
          placeholder="e.g. needs a sales team, hardware inventory"
        />
        <p className="text-muted-foreground text-xs">Autonomous runs steer away from these.</p>
      </div>

      {save.isError && (
        <p role="alert" className="text-destructive text-sm">
          Could not save: {describeError(save.error)}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending || !dirty}>
          {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
          Save profile
        </Button>
        <span role="status" className="text-muted-foreground flex items-center gap-1 text-xs">
          {save.isSuccess && !dirty ? (
            <>
              <Check className="text-signal size-3.5" aria-hidden /> Saved
            </>
          ) : saved.updated_at ? (
            `Last saved ${formatDateTime(saved.updated_at)}`
          ) : (
            "Not saved yet — these are the defaults"
          )}
        </span>
      </div>
    </form>
  );
}

export function ProfileForm() {
  const { data, error, isPending, refetch } = useProfile();
  if (isPending) return <LoadingState label="Loading profile…" />;
  if (error) {
    return (
      <ErrorState
        title="Could not load your profile"
        message={describeError(error)}
        onRetry={() => void refetch()}
      />
    );
  }
  return <Editor saved={data} />;
}

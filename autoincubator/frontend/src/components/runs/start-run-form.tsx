"use client";

import { ChevronDown, Compass, Lightbulb, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ChipInput } from "@/components/common/chip-input";
import { Segmented } from "@/components/common/segmented";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCreateRun, useProfile } from "@/lib/api/queries";
import type { BusinessModel, CreateRunRequest, RunConstraints, RunMode } from "@/lib/api/types";
import { describeError } from "@/lib/format";
import { cn } from "@/lib/utils";

export const SEED_MIN = 3;
export const SEED_MAX = 500;

const MODES: { value: RunMode; title: string; body: string; icon: typeof Lightbulb }[] = [
  {
    value: "seeded",
    title: "Start from my idea",
    body: "Scout researches around your seed, then the ideas are sized and attacked.",
    icon: Lightbulb,
  },
  {
    value: "autonomous",
    title: "Scan for opportunities",
    body: "Scout hunts for signals across industries, steered by your founder profile.",
    icon: Compass,
  },
];

const BUSINESS_MODELS = [
  { value: "any", label: "Any" },
  { value: "b2b", label: "B2B" },
  { value: "b2c", label: "B2C" },
] as const satisfies readonly { value: BusinessModel; label: string }[];

export interface StartRunValues {
  mode: RunMode;
  seed: string;
  region: string;
  budgetCeiling: string;
  businessModel: BusinessModel;
  soloFounder: boolean;
  excludedIndustries: string[];
}

const INITIAL: StartRunValues = {
  mode: "seeded",
  seed: "",
  region: "",
  budgetCeiling: "",
  businessModel: "any",
  soloFounder: false,
  excludedIndustries: [],
};

/** Maps the form to the API body, or returns a field error. Exported for tests. */
export function toCreateRunRequest(
  values: StartRunValues,
): { ok: true; body: CreateRunRequest } | { ok: false; field: "seed" | "budget"; error: string } {
  const seed = values.seed.trim();
  if (values.mode === "seeded" && seed.length < SEED_MIN) {
    return {
      ok: false,
      field: "seed",
      error: `Describe your idea in at least ${SEED_MIN} characters.`,
    };
  }
  let budget: number | null = null;
  if (values.budgetCeiling.trim() !== "") {
    budget = Number(values.budgetCeiling);
    if (!Number.isFinite(budget) || budget < 0) {
      return { ok: false, field: "budget", error: "Enter a positive amount in USD." };
    }
  }
  const constraints: RunConstraints = {
    region: values.region.trim() || null,
    budget_ceiling_usd: budget,
    business_model: values.businessModel,
    solo_founder: values.soloFounder,
    excluded_industries: values.excludedIndustries,
  };
  return {
    ok: true,
    body: {
      mode: values.mode,
      seed: values.mode === "seeded" ? seed : null,
      constraints,
    },
  };
}

function constraintCount(v: StartRunValues): number {
  return [
    v.region.trim() !== "",
    v.budgetCeiling.trim() !== "",
    v.businessModel !== "any",
    v.soloFounder,
    v.excludedIndustries.length > 0,
  ].filter(Boolean).length;
}

export function StartRunForm() {
  const router = useRouter();
  const createRun = useCreateRun();
  const profile = useProfile();
  const [values, setValues] = useState<StartRunValues>(INITIAL);
  const [fieldError, setFieldError] = useState<{ field: "seed" | "budget"; error: string } | null>(
    null,
  );
  const [constraintsOpen, setConstraintsOpen] = useState(false);

  const set = <K extends keyof StartRunValues>(key: K, value: StartRunValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setFieldError(null);
  };

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const result = toCreateRunRequest(values);
    if (!result.ok) {
      setFieldError(result);
      if (result.field === "budget") setConstraintsOpen(true);
      return;
    }
    createRun.mutate(result.body, {
      onSuccess: ({ run_id }) => router.push(`/runs/${run_id}`),
    });
  }

  const activeConstraints = constraintCount(values);
  const hasProfile = profile.data?.updated_at != null;
  const seedLength = values.seed.trim().length;

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6">
      <fieldset className="grid gap-2 sm:grid-cols-2">
        <legend className="sr-only">Mode</legend>
        {MODES.map(({ value, title, body, icon: Icon }) => {
          const checked = values.mode === value;
          return (
            <label
              key={value}
              className={cn(
                "has-focus-visible:ring-ring/50 flex cursor-pointer gap-3 rounded-lg border p-3.5 transition-colors has-focus-visible:ring-3",
                checked ? "border-foreground/60 bg-card shadow-xs" : "hover:bg-card/60",
              )}
            >
              <input
                type="radio"
                name="mode"
                value={value}
                checked={checked}
                onChange={() => set("mode", value)}
                className="sr-only"
              />
              <Icon
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  checked ? "text-signal" : "text-muted-foreground",
                )}
                aria-hidden
              />
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{title}</span>
                <span className="text-muted-foreground text-xs leading-relaxed">{body}</span>
              </span>
            </label>
          );
        })}
      </fieldset>

      {values.mode === "seeded" ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <Label htmlFor="seed">Your seed idea</Label>
            <span className="text-muted-foreground tabular font-mono text-xs">
              {seedLength}/{SEED_MAX}
            </span>
          </div>
          <Textarea
            id="seed"
            value={values.seed}
            maxLength={SEED_MAX}
            rows={3}
            placeholder="e.g. Bookkeeping for small cafés that still run on paper receipts"
            aria-invalid={fieldError?.field === "seed" || undefined}
            aria-describedby={fieldError?.field === "seed" ? "seed-error" : undefined}
            onChange={(event) => set("seed", event.target.value)}
            className="min-h-24 text-base"
          />
          {fieldError?.field === "seed" && (
            <p id="seed-error" className="text-destructive text-sm">
              {fieldError.error}
            </p>
          )}
        </div>
      ) : (
        <div className="bg-card text-muted-foreground rounded-lg border p-3.5 text-sm">
          {hasProfile ? (
            <>
              Scout will use your{" "}
              <Link
                href="/settings/profile"
                className="text-foreground underline underline-offset-4"
              >
                founder profile
              </Link>{" "}
              (skills, region, capital, risk) to choose where to look.
            </>
          ) : (
            <>
              No founder profile yet. Autonomous runs work without one, but{" "}
              <Link
                href="/settings/profile"
                className="text-foreground underline underline-offset-4"
              >
                adding your skills and constraints
              </Link>{" "}
              makes the scan far more relevant.
            </>
          )}
        </div>
      )}

      <Collapsible open={constraintsOpen} onOpenChange={setConstraintsOpen}>
        <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm">
          <ChevronDown
            className={cn(
              "size-4 transition-transform",
              constraintsOpen ? "rotate-0" : "-rotate-90",
            )}
            aria-hidden
          />
          Constraints
          {activeConstraints > 0 && (
            <span className="bg-secondary text-foreground tabular rounded-full px-1.5 font-mono text-xs">
              {activeConstraints}
            </span>
          )}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-3 grid gap-4 rounded-lg border p-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="region">Region</Label>
              <Input
                id="region"
                value={values.region}
                placeholder="e.g. Mongolia, DACH, US Midwest"
                onChange={(event) => set("region", event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="budget">Starting budget ceiling (USD)</Label>
              <Input
                id="budget"
                inputMode="decimal"
                value={values.budgetCeiling}
                placeholder="e.g. 20000"
                aria-invalid={fieldError?.field === "budget" || undefined}
                onChange={(event) => set("budgetCeiling", event.target.value)}
                className="tabular font-mono"
              />
              {fieldError?.field === "budget" && (
                <p className="text-destructive text-sm">{fieldError.error}</p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">Business model</span>
              <Segmented
                label="Business model"
                value={values.businessModel}
                options={BUSINESS_MODELS}
                onChange={(value) => set("businessModel", value)}
                className="w-full sm:w-fit"
              />
            </div>
            <div className="flex items-center justify-between gap-3 sm:justify-start sm:self-end">
              <Label htmlFor="solo">Solo founder</Label>
              <Switch
                id="solo"
                checked={values.soloFounder}
                onCheckedChange={(checked) => set("soloFounder", checked)}
              />
            </div>
            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <Label htmlFor="excluded">Excluded industries</Label>
              <ChipInput
                id="excluded"
                values={values.excludedIndustries}
                onChange={(next) => set("excludedIndustries", next)}
                placeholder="Type and press Enter, e.g. crypto"
              />
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      {createRun.isError && (
        <p role="alert" className="text-destructive text-sm">
          Could not start the run: {describeError(createRun.error)}
        </p>
      )}

      <div>
        <Button type="submit" size="lg" disabled={createRun.isPending} className="h-10 px-4">
          {createRun.isPending ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <Sparkles aria-hidden />
          )}
          Discover &amp; Incubate
        </Button>
      </div>
    </form>
  );
}

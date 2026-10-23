import type { RubricScore } from "@/lib/api/types";
import { RUBRIC, scoreTone } from "@/lib/ideas";
import { cn } from "@/lib/utils";

const TONE = {
  strong: "bg-signal",
  fair: "bg-warning",
  weak: "bg-destructive",
} as const;

/** Seven 1–10 bars, favourable end on the right, in a fixed order so cards compare at a glance. */
export function RubricBars({ scores }: { scores: readonly RubricScore[] }) {
  const byDimension = new Map(scores.map((s) => [s.dimension, s]));
  return (
    <dl className="grid grid-cols-[4.75rem_1fr_1.25rem] items-center gap-x-2 gap-y-1 text-xs">
      {RUBRIC.map(({ dimension, label, hint }) => {
        const score = byDimension.get(dimension);
        const value = score?.score ?? 0;
        return (
          <div key={dimension} className="contents" title={score?.justification ?? hint}>
            <dt className="text-muted-foreground truncate">{label}</dt>
            <dd className="bg-muted h-1.5 overflow-hidden rounded-full" aria-hidden>
              <div
                className={cn("h-full rounded-full", TONE[scoreTone(value)])}
                style={{ width: `${value * 10}%` }}
              />
            </dd>
            <dd className="tabular text-right font-mono" aria-label={`${hint}: ${value} of 10`}>
              {score ? value : "–"}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

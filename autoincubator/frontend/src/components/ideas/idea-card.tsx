"use client";

import { ChevronDown, Link2, Skull } from "lucide-react";
import { useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { EventOf, IdeaView } from "@/lib/api/types";
import { formatFigure } from "@/lib/format";
import { scoreTone, sourceUrls } from "@/lib/ideas";
import { cn } from "@/lib/utils";

import { RubricBars } from "./rubric-bars";

const SCORE_TONE = {
  strong: "text-signal",
  fair: "text-warning",
  weak: "text-destructive",
} as const;

function Score({ value }: { value: number | null }) {
  return (
    <div className="flex flex-col items-end leading-none">
      <span
        className={cn(
          "tabular font-mono text-2xl font-medium",
          value == null ? "text-muted-foreground" : SCORE_TONE[scoreTone(value)],
        )}
      >
        {value == null ? "–" : value.toFixed(1)}
      </span>
      <span className="text-muted-foreground mt-1 text-[0.65rem] tracking-wider uppercase">
        score
      </span>
    </div>
  );
}

function Rank({ rank }: { rank: number | null }) {
  return (
    <span className="text-muted-foreground tabular w-6 shrink-0 pt-0.5 font-mono text-sm">
      {rank == null ? "·" : `#${rank}`}
    </span>
  );
}

export function IdeaCard({ idea }: { idea: IdeaView }) {
  const [open, setOpen] = useState(false);
  const { opportunity, analysis, critique } = idea;
  const sources = sourceUrls(idea);
  const { tam, sam, som } = analysis.sizing;

  return (
    <article
      aria-labelledby={`idea-${idea.id}`}
      className="bg-card flex flex-col gap-4 rounded-lg border p-4 shadow-xs"
    >
      <header className="flex gap-3">
        <Rank rank={idea.rank} />
        <div className="min-w-0 flex-1">
          <h3 id={`idea-${idea.id}`} className="font-serif text-xl leading-tight">
            {idea.title}
          </h3>
          <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
            {opportunity.one_liner}
          </p>
        </div>
        <Score value={idea.composite_score} />
      </header>

      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] sm:pl-9">
        <RubricBars scores={critique.scores} />
        <div className="flex flex-col gap-1.5 text-sm">
          <p className="text-destructive flex items-center gap-1.5 text-xs font-medium tracking-wider uppercase">
            <Skull className="size-3.5" aria-hidden /> Most likely failure
          </p>
          <p className="leading-relaxed">{critique.most_likely_failure_cause}</p>
        </div>
      </div>

      <Collapsible open={open} onOpenChange={setOpen} className="sm:pl-9">
        <footer className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="flex items-center gap-1" title={sources.join("\n")}>
            <Link2 className="size-3.5" aria-hidden />
            <span className="tabular font-mono">{sources.length}</span>{" "}
            {sources.length === 1 ? "source" : "sources"}
          </span>
          <span>{opportunity.industry}</span>
          <span className="uppercase">{opportunity.business_model}</span>
          {idea.version > 1 && <span className="font-mono">v{idea.version}</span>}
          <CollapsibleTrigger className="hover:text-foreground ml-auto flex items-center gap-1">
            Market
            <ChevronDown
              className={cn("size-3.5 transition-transform", open && "rotate-180")}
              aria-hidden
            />
          </CollapsibleTrigger>
        </footer>
        <CollapsibleContent>
          <div className="mt-3 flex flex-col gap-3 border-t pt-3 text-sm">
            <dl className="grid grid-cols-3 gap-2">
              {(
                [
                  ["TAM", tam],
                  ["SAM", sam],
                  ["SOM", som],
                ] as const
              ).map(([label, figure]) => (
                <div key={label} className="bg-muted/60 rounded-md p-2">
                  <dt className="text-muted-foreground text-[0.65rem] tracking-wider uppercase">
                    {label}
                  </dt>
                  <dd className="tabular font-mono text-sm">
                    {figure.source_url ? (
                      <a
                        href={figure.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="underline decoration-dotted underline-offset-4"
                      >
                        {formatFigure(figure.value, figure.unit)}
                      </a>
                    ) : (
                      <span title={figure.assumption ?? undefined}>
                        {formatFigure(figure.value, figure.unit)}*
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-muted-foreground leading-relaxed">{analysis.summary}</p>
            <p className="leading-relaxed">
              <span className="font-medium">The attack: </span>
              {critique.attack_summary}
            </p>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </article>
  );
}

/** Shown for an `idea.created` event until `GET /runs/{id}` returns the full idea. */
export function IdeaCardPending({ idea }: { idea: EventOf<"idea.created">["data"] }) {
  return (
    <article className="bg-card flex flex-col gap-4 rounded-lg border p-4 shadow-xs">
      <header className="flex gap-3">
        <Rank rank={idea.rank} />
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-xl leading-tight">{idea.title}</h3>
          <div className="bg-muted mt-2 h-3 w-3/4 animate-pulse rounded" />
        </div>
        <Score value={idea.composite_score} />
      </header>
      <div className="bg-muted h-20 animate-pulse rounded sm:ml-9" />
    </article>
  );
}

export function IdeaCardSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-dashed p-4" aria-hidden>
      <div className="flex gap-3">
        <div className="bg-muted h-4 w-6 rounded" />
        <div className="flex flex-1 flex-col gap-2">
          <div className="bg-muted h-5 w-2/3 rounded" />
          <div className="bg-muted/70 h-3 w-full rounded" />
        </div>
        <div className="bg-muted h-7 w-10 rounded" />
      </div>
      <div className="bg-muted/60 h-16 rounded sm:ml-9" />
    </div>
  );
}

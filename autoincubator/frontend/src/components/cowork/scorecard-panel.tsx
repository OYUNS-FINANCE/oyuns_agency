import { ExternalLink, Skull } from "lucide-react";
import type { ReactNode } from "react";

import type { IdeaView, SourcedFigure } from "@/lib/api/types";
import { formatFigure } from "@/lib/format";
import { RUBRIC, scoreTone } from "@/lib/ideas";
import { cn } from "@/lib/utils";

const TONE = { strong: "bg-signal", fair: "bg-warning", weak: "bg-destructive" } as const;

function Source({ url }: { url: string }) {
  let host = url;
  try {
    host = new URL(url).host;
  } catch {
    // Not a URL we can parse: show it as is.
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline decoration-dotted underline-offset-4"
    >
      {host} <ExternalLink className="size-3" aria-hidden />
    </a>
  );
}

function FigureRow({ label, figure }: { label: string; figure: SourcedFigure }) {
  return (
    <li className="flex flex-col gap-0.5 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm">{label}</span>
        <span className="tabular font-mono text-sm">
          {formatFigure(figure.value, figure.unit)}
          {!figure.source_url && "*"}
        </span>
      </div>
      {figure.source_url ? (
        <Source url={figure.source_url} />
      ) : (
        <p className="text-muted-foreground text-xs">
          <span className="font-medium">Estimate:</span> {figure.assumption}
        </p>
      )}
    </li>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-muted-foreground text-xs font-medium tracking-wider uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** The full rubric with every justification, and every figure with its source or assumption. */
export function ScorecardPanel({ idea }: { idea: IdeaView }) {
  const { critique, analysis, opportunity } = idea;
  const byDimension = new Map(critique.scores.map((s) => [s.dimension, s]));
  const figures: { label: string; figure: SourcedFigure }[] = [
    { label: "TAM", figure: analysis.sizing.tam },
    { label: "SAM", figure: analysis.sizing.sam },
    { label: "SOM", figure: analysis.sizing.som },
    ...(analysis.competitors ?? []).flatMap((c) =>
      c.price ? [{ label: `${c.name} price`, figure: c.price }] : [],
    ),
    ...(analysis.pricing_benchmarks ?? []).map((p) => ({
      label: `${p.product} (${p.billing.replace("_", " ")})`,
      figure: p.price,
    })),
    ...analysis.segments.flatMap((s) =>
      s.size ? [{ label: `${s.name} size`, figure: s.size }] : [],
    ),
  ];

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto px-4 py-4 sm:px-5">
      {idea.score_stale && (
        <p className="border-warning/40 bg-warning-soft/70 rounded-md border px-3 py-2 text-sm">
          This scorecard is for an earlier version. Re-score to update it.
        </p>
      )}
      <Section title="Rubric">
        <ol className="flex flex-col divide-y">
          {RUBRIC.map(({ dimension, hint }) => {
            const score = byDimension.get(dimension);
            const value = score?.score ?? 0;
            return (
              <li key={dimension} className="flex flex-col gap-1 py-2.5">
                <div className="flex items-center gap-3">
                  <span className="flex-1 text-sm">{hint}</span>
                  <span className="bg-muted h-1.5 w-24 overflow-hidden rounded-full" aria-hidden>
                    <span
                      className={cn("block h-full rounded-full", TONE[scoreTone(value)])}
                      style={{ width: `${value * 10}%` }}
                    />
                  </span>
                  <span className="tabular w-10 text-right font-mono text-sm">{value}/10</span>
                </div>
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {score?.justification}
                </p>
              </li>
            );
          })}
        </ol>
      </Section>
      <Section title="Most likely failure">
        <p className="flex gap-2 text-sm leading-relaxed">
          <Skull className="text-destructive mt-0.5 size-4 shrink-0" aria-hidden />
          {critique.most_likely_failure_cause}
        </p>
        <p className="text-muted-foreground text-sm leading-relaxed">{critique.attack_summary}</p>
      </Section>
      <Section title="Figures">
        <p className="text-muted-foreground text-xs">
          {analysis.sizing.method.replace("_", "-")}: {analysis.sizing.method_explanation}
        </p>
        <ul className="flex flex-col divide-y">
          {figures.map((f) => (
            <FigureRow key={f.label} {...f} />
          ))}
        </ul>
      </Section>
      <Section title="Signals">
        <ul className="flex flex-col gap-3">
          {opportunity.signals.map((s, i) => (
            <li key={i} className="flex flex-col gap-0.5 text-sm">
              <span className="text-muted-foreground text-xs">
                {s.category.replaceAll("_", " ")}
              </span>
              <p className="leading-relaxed">{s.evidence}</p>
              <Source url={s.url} />
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

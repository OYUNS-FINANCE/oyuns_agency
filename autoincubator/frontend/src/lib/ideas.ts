import type { IdeaView, RubricDimension, RunStatus } from "@/lib/api/types";

/** Display order and short labels for the Skeptic's rubric. 10 is always the favourable end. */
export const RUBRIC: readonly { dimension: RubricDimension; label: string; hint: string }[] = [
  { dimension: "cac_risk", label: "CAC", hint: "Customer acquisition cost risk" },
  { dimension: "channel_dependency", label: "Channel", hint: "Dependence on a single channel" },
  { dimension: "churn_risk", label: "Churn", hint: "Churn risk" },
  { dimension: "defensibility", label: "Moat", hint: "Defensibility" },
  { dimension: "regulatory_risk", label: "Regulation", hint: "Regulatory risk" },
  { dimension: "time_to_first_revenue", label: "Time to $", hint: "Time to first revenue" },
  { dimension: "solo_founder_feasibility", label: "Solo", hint: "Feasible for a solo founder" },
];

/** Every distinct URL the idea's claims cite: Scout signals and Analyst figures/competitors. */
export function sourceUrls(idea: IdeaView): string[] {
  const urls = new Set<string>();
  const add = (url: string | null | undefined) => {
    if (url) urls.add(url);
  };
  for (const signal of idea.opportunity.signals) add(signal.url);
  const { sizing, competitors, pricing_benchmarks, segments } = idea.analysis;
  add(sizing.tam.source_url);
  add(sizing.sam.source_url);
  add(sizing.som.source_url);
  for (const c of competitors ?? []) {
    add(c.url);
    add(c.price?.source_url);
  }
  for (const p of pricing_benchmarks ?? []) add(p.price.source_url);
  for (const s of segments) add(s.size?.source_url);
  return [...urls];
}

export type ScoreTone = "strong" | "fair" | "weak";

export function scoreTone(score: number): ScoreTone {
  if (score >= 7) return "strong";
  if (score >= 5) return "fair";
  return "weak";
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  awaiting_human: "Awaiting review",
  completed: "Completed",
  failed: "Failed",
  budget_exhausted: "Budget exhausted",
};

export const AGENT_LABEL: Record<string, string> = {
  scout: "Trend Scout",
  analyst: "Market Analyst",
  skeptic: "Devil's Advocate",
  ranker: "Ranker",
  run: "Run",
  product_architect: "Product Architect",
  gtm_strategist: "GTM Strategist",
  financial_modeler: "Financial Modeler",
  editor: "Editor",
};

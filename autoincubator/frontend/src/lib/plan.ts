/** Pure helpers for the business plan view (ADR 0007). Numbers are formatted the same way
 * as the exported dossier (`backend/app/services/plan_format.py`). */
import type {
  BusinessPlan,
  ChannelType,
  Contradiction,
  PlanFigure,
  PlanSection,
  ScenarioName,
} from "@/lib/api/types";

export const PLAN_SECTIONS = [
  { id: "summary", label: "Summary" },
  { id: "opportunity", label: "Opportunity" },
  { id: "product", label: "Product" },
  { id: "gtm", label: "Go-to-market" },
  { id: "financials", label: "Financials" },
  { id: "contradictions", label: "Contradictions" },
  { id: "risks", label: "Risks" },
  { id: "launch", label: "30/60/90 plan" },
  { id: "appendix", label: "Sources & assumptions" },
] as const;
export type PlanSectionId = (typeof PLAN_SECTIONS)[number]["id"];

export const SCENARIOS: readonly { value: ScenarioName; label: string }[] = [
  { value: "base", label: "Base" },
  { value: "bear", label: "Bear" },
  { value: "bull", label: "Bull" },
];

/** Fixed per scenario (never by rank), validated as a categorical palette. */
export const SCENARIO_STROKE: Record<ScenarioName, string> = {
  base: "var(--scenario-base)",
  bear: "var(--scenario-bear)",
  bull: "var(--scenario-bull)",
};

export const CHANNEL_LABEL: Record<ChannelType, string> = {
  paid_search: "Paid search",
  paid_social: "Paid social",
  content_seo: "Content & SEO",
  outbound_email: "Outbound email",
  partnerships: "Partnerships",
  marketplace_listing: "Marketplace listing",
  community: "Community",
  referral_program: "Referral program",
  events: "Events",
  influencers: "Influencers",
  app_store: "App store",
};

const whole = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const cents = new Intl.NumberFormat("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const oneDp = new Intl.NumberFormat("en", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  return `${sign}$${a >= 100 ? whole.format(a) : cents.format(a)}`;
}

export function moneyCompact(v: number): string {
  return `${v < 0 ? "-" : ""}$${compact.format(Math.abs(v))}`;
}

export const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `${oneDp.format(v * 100)}%`;
export const num = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : oneDp.format(v);
export const ratio = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `${oneDp.format(v)}x`;
export const monthLabel = (m: number | null | undefined) =>
  m === null || m === undefined ? "Not within 12 months" : `Month ${m}`;

/** A figure by its unit: money, a share, or a count. */
export function figure(f: PlanFigure): string {
  const unit = f.unit.toLowerCase();
  if (unit.includes("share") || unit.includes("fraction")) return pct(f.value);
  if (unit.includes("usd") || unit.includes("$")) return money(f.value);
  return Number.isInteger(f.value) ? whole.format(f.value) : cents.format(f.value);
}

export function contradictionsFor(plan: BusinessPlan, section: PlanSection): Contradiction[] {
  return plan.contradictions.filter((c) => c.sections.includes(section));
}

export const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 } as const;

export function sortedContradictions(plan: BusinessPlan): Contradiction[] {
  return [...plan.contradictions].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );
}

/** Every URL the plan cites, numbered in order of first appearance (S1, S2, …). */
export function planSources(plan: BusinessPlan): string[] {
  const urls: string[] = [];
  const add = (u: string | null | undefined) => {
    if (u && !urls.includes(u)) urls.push(u);
  };
  plan.brief.opportunity.signals.forEach((s) => add(s.url));
  const a = plan.brief.analysis;
  [a.sizing.tam, a.sizing.sam, a.sizing.som].forEach((f) => add(f.source_url));
  a.competitors.forEach((c) => add(c.price?.source_url));
  a.pricing_benchmarks.forEach((p) => add(p.price.source_url));
  plan.gtm.channels.forEach((c) => add(c.expected_cac.source_url));
  return urls;
}

export interface AssumptionRow {
  group: string;
  label: string;
  figure: PlanFigure;
}

/** The figures the plan rests on, by where they came from. */
export function assumptionRows(plan: BusinessPlan): AssumptionRow[] {
  const a = plan.assumptions;
  const sizing = plan.brief.analysis.sizing;
  const rows: AssumptionRow[] = [
    { group: "Market", label: "TAM", figure: sizing.tam },
    { group: "Market", label: "SAM", figure: sizing.sam },
    { group: "Market", label: "SOM", figure: sizing.som },
    ...plan.gtm.channels.map((c) => ({
      group: "Go-to-market",
      label: `${CHANNEL_LABEL[c.channel]} expected CAC`,
      figure: c.expected_cac,
    })),
    ...a.price_tiers.flatMap((t) => [
      { group: "Financial model", label: `${t.name} price`, figure: t.price_monthly },
      { group: "Financial model", label: `${t.name} share`, figure: t.mix },
    ]),
    ...a.channels.flatMap((c) => [
      { group: "Financial model", label: `${CHANNEL_LABEL[c.channel]} CAC`, figure: c.cac },
      {
        group: "Financial model",
        label: `${CHANNEL_LABEL[c.channel]} monthly spend`,
        figure: c.monthly_spend,
      },
    ]),
    {
      group: "Financial model",
      label: "Organic signups (launch month)",
      figure: a.organic_signups_m1,
    },
    { group: "Financial model", label: "Organic growth", figure: a.organic_growth },
    { group: "Financial model", label: "Free-to-paid conversion", figure: a.free_to_paid },
    { group: "Financial model", label: "Monthly churn", figure: a.monthly_churn },
    { group: "Financial model", label: "Payment fee", figure: a.payment_fee_pct },
    {
      group: "Financial model",
      label: "Variable cost per customer",
      figure: a.variable_cost_per_customer,
    },
    { group: "Financial model", label: "Starting cash", figure: a.starting_cash },
    ...a.fixed_costs.map((c) => ({ group: "Financial model", label: c.name, figure: c.monthly })),
  ];
  return rows;
}

// --- Chart geometry ---------------------------------------------------------------------

export interface ChartSeries {
  key: ScenarioName;
  values: readonly number[];
}

export interface ChartFrame {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface ChartGeometry {
  x: (index: number) => number;
  y: (value: number) => number;
  paths: { key: ScenarioName; d: string }[];
  ticks: number[];
  /** y of the zero line (the domain always includes zero). */
  zero: number;
}

/** A "nice" step (1, 2 or 5 × 10^n) giving about `count` ticks over `span`. */
export function niceStep(span: number, count = 4): number {
  if (span <= 0) return 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
}

export function chartGeometry(series: readonly ChartSeries[], frame: ChartFrame): ChartGeometry {
  const all = series.flatMap((s) => s.values);
  const count = Math.max(1, ...series.map((s) => s.values.length));
  const rawMin = Math.min(0, ...all);
  const rawMax = Math.max(0, ...all);
  const step = niceStep(rawMax - rawMin || 1);
  const lo = Math.floor(rawMin / step) * step;
  const hi = Math.ceil(rawMax / step) * step || step;
  const innerW = frame.width - frame.left - frame.right;
  const innerH = frame.height - frame.top - frame.bottom;
  const x = (i: number) => frame.left + (count === 1 ? innerW / 2 : (i / (count - 1)) * innerW);
  const y = (v: number) => frame.top + ((hi - v) / (hi - lo)) * innerH;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Math.round(t * 1e6) / 1e6);
  return {
    x,
    y,
    ticks,
    zero: y(0),
    paths: series.map((s) => ({
      key: s.key,
      d: s.values
        .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
        .join(" "),
    })),
  };
}

/** Index of the data point nearest to a pointer x (in chart units). */
export function nearestIndex(px: number, count: number, frame: ChartFrame): number {
  const innerW = frame.width - frame.left - frame.right;
  if (count <= 1) return 0;
  const i = Math.round(((px - frame.left) / innerW) * (count - 1));
  return Math.max(0, Math.min(count - 1, i));
}

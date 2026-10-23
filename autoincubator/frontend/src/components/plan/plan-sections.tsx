"use client";

import { CircleAlert, ExternalLink, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Segmented } from "@/components/common/segmented";
import type {
  BusinessPlan,
  Contradiction,
  EngineFormula,
  PlanFigure,
  ScenarioName,
} from "@/lib/api/types";
import {
  CHANNEL_LABEL,
  SCENARIOS,
  assumptionRows,
  contradictionsFor,
  figure,
  money,
  monthLabel,
  num,
  pct,
  planSources,
  ratio,
  sortedContradictions,
  type PlanSectionId,
} from "@/lib/plan";
import { cn } from "@/lib/utils";

import { ScenarioChart } from "./scenario-chart";

export function Section({
  id,
  title,
  children,
}: {
  id: PlanSectionId;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-24 flex-col gap-4">
      <h2 id={`${id}-title`} className="font-serif text-2xl leading-tight sm:text-3xl">
        {title}
      </h2>
      {children}
    </section>
  );
}

function H3({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
      {children}
    </h3>
  );
}

function Prose({ children }: { children: ReactNode }) {
  return <p className="max-w-prose text-sm leading-relaxed break-words">{children}</p>;
}

/** Horizontal scroll inside the card, never on the page. */
function TableWrap({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div
      className="bg-card max-w-full overflow-x-auto rounded-lg border"
      role="region"
      aria-label={label}
      tabIndex={0}
    >
      <table className="w-full text-sm [&_tbody_tr:last-child>td]:border-b-0">{children}</table>
    </div>
  );
}

const th =
  "text-muted-foreground border-b px-3 py-2 text-left text-xs font-medium whitespace-nowrap";
const td = "border-b px-3 py-2 align-top";
const tdNum = "border-b px-3 py-2 text-right font-mono tabular whitespace-nowrap";

function Basis({ fig }: { fig: PlanFigure }) {
  if (fig.source_url) {
    return (
      <a
        href={fig.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-signal inline-flex items-center gap-1 underline-offset-2 hover:underline"
      >
        Source <ExternalLink className="size-3" aria-hidden />
      </a>
    );
  }
  return (
    <span className="text-muted-foreground">
      <span className="text-foreground/80 font-medium">Assumption:</span> {fig.assumption}
    </span>
  );
}

// --- Contradictions -----------------------------------------------------------------------

const SEVERITY_STYLE = {
  high: "border-destructive/30 bg-destructive/5",
  medium: "border-warning/40 bg-warning-soft/60",
  low: "border-border bg-muted/40",
} as const;

export function ContradictionCallout({ item }: { item: Contradiction }) {
  const untraced = item.untraced ?? [];
  const Icon = item.severity === "high" ? CircleAlert : TriangleAlert;
  return (
    <div
      role="note"
      data-contradiction={item.code}
      className={cn("flex gap-3 rounded-lg border p-3 text-sm", SEVERITY_STYLE[item.severity])}
    >
      <Icon
        className={cn(
          "mt-0.5 size-4 shrink-0",
          item.severity === "high" ? "text-destructive" : "text-warning",
        )}
        aria-hidden
      />
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-xs">
          <span className="font-medium capitalize">{item.severity}</span>
          <span className="text-muted-foreground">
            {" "}
            · {item.origin === "check" ? "Automated check" : "Editor review"} ·{" "}
            {item.sections.join(", ")}
          </span>
        </p>
        <p className="break-words">{item.description}</p>
        {untraced.length > 0 && (
          <p className="text-muted-foreground">
            Unverified:{" "}
            {untraced.map((t) => (
              <code key={t} className="bg-destructive/10 mr-1 rounded px-1 font-mono text-xs">
                {t}
              </code>
            ))}
          </p>
        )}
        {item.resolution && (
          <p className="text-muted-foreground">
            <span className="text-foreground/80 font-medium">Suggested resolution:</span>{" "}
            {item.resolution}
          </p>
        )}
      </div>
    </div>
  );
}

function Callouts({ items }: { items: Contradiction[] }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {items.map((c, i) => (
        <ContradictionCallout key={`${c.code}-${i}`} item={c} />
      ))}
    </div>
  );
}

// --- Sections ------------------------------------------------------------------------------

export function SummarySection({ plan }: { plan: BusinessPlan }) {
  const n = plan.contradictions.length;
  return (
    <Section id="summary" title="Executive summary">
      <Prose>{plan.executive_summary}</Prose>
      {n > 0 && (
        <a
          href="#contradictions"
          className="border-warning/40 bg-warning-soft/60 flex items-center gap-2 self-start rounded-lg border px-3 py-2 text-sm"
        >
          <TriangleAlert className="text-warning size-4" aria-hidden />
          {n} {n === 1 ? "contradiction" : "contradictions"} between sections — listed, not hidden
        </a>
      )}
    </Section>
  );
}

export function OpportunitySection({ plan }: { plan: BusinessPlan }) {
  const { opportunity: opp, analysis, critique } = plan.brief;
  return (
    <Section id="opportunity" title="The opportunity">
      <Callouts items={contradictionsFor(plan, "opportunity")} />
      <dl className="grid gap-3 text-sm sm:grid-cols-[9rem_1fr]">
        {(
          [
            ["One-liner", opp.one_liner],
            ["Problem", opp.problem],
            ["Target customer", opp.target_customer],
            ["Model", `${opp.industry} · ${opp.business_model.toUpperCase()}`],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="break-words">{v}</dd>
          </div>
        ))}
      </dl>
      <H3>Market size · {analysis.sizing.method.replace("_", " ")}</H3>
      <TableWrap label="Market size">
        <thead>
          <tr>
            <th className={th}>Market</th>
            <th className={cn(th, "text-right")}>Value</th>
            <th className={th}>Basis</th>
          </tr>
        </thead>
        <tbody>
          {(
            [
              ["TAM", analysis.sizing.tam],
              ["SAM", analysis.sizing.sam],
              ["SOM", analysis.sizing.som],
            ] as const
          ).map(([k, f]) => (
            <tr key={k}>
              <td className={td}>{k}</td>
              <td className={tdNum}>{money(f.value)}</td>
              <td className={cn(td, "min-w-48")}>
                <Basis fig={f} />
              </td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
      <Prose>
        <span className="text-muted-foreground">Devil&apos;s Advocate: </span>
        composite score{" "}
        <span className="font-mono tabular">{plan.brief.composite_score.toFixed(1)}</span> / 10.
        Most likely cause of failure: {critique.most_likely_failure_cause}
      </Prose>
    </Section>
  );
}

export function ProductSection({ plan }: { plan: BusinessPlan }) {
  const p = plan.product;
  const mvpDays = p.features
    .filter((f) => f.scope === "now")
    .reduce((s, f) => s + f.estimate_days, 0);
  return (
    <Section id="product" title="Product">
      <Callouts items={contradictionsFor(plan, "product")} />
      <Prose>{p.mvp_summary}</Prose>
      <TableWrap label="Features">
        <thead>
          <tr>
            <th className={th}>Feature</th>
            <th className={th}>Scope</th>
            <th className={cn(th, "text-right")}>Days</th>
          </tr>
        </thead>
        <tbody>
          {p.features.map((f) => (
            <tr key={f.name}>
              <td className={cn(td, "min-w-48")}>
                <span className="font-medium">{f.name}</span>
                <span className="text-muted-foreground block text-xs">{f.description}</span>
              </td>
              <td className={td}>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-xs",
                    f.scope === "now"
                      ? "bg-signal-soft text-signal"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {f.scope === "now" ? "MVP" : "Later"}
                </span>
              </td>
              <td className={tdNum}>{f.estimate_days}</td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
      <p className="text-sm">
        MVP: <span className="font-mono tabular">{mvpDays}</span> days of work · build estimate{" "}
        <span className="font-mono tabular">{p.build_estimate_weeks}</span> full-time weeks.{" "}
        <span className="text-muted-foreground">{p.build_estimate_basis}</span>
      </p>
      <H3>Architecture</H3>
      <Prose>{p.architecture}</Prose>
      <ul className="grid gap-2 text-sm sm:grid-cols-2">
        {p.components.map((c) => (
          <li key={c.name} className="bg-card rounded-lg border p-3">
            <span className="font-medium">{c.name}</span>
            <span className="text-muted-foreground block">{c.responsibility}</span>
          </li>
        ))}
      </ul>
      <H3>Data model & stack</H3>
      <ul className="flex flex-col gap-1 text-sm">
        {p.data_model.map((e) => (
          <li key={e.name} className="break-words">
            <span className="font-medium">{e.name}</span>{" "}
            <span className="text-muted-foreground font-mono text-xs">{e.fields.join(", ")}</span>
          </li>
        ))}
      </ul>
      <ul className="flex flex-col gap-1 text-sm">
        {p.stack.map((s) => (
          <li key={s.layer} className="break-words">
            <span className="text-muted-foreground">{s.layer}:</span> {s.choice} — {s.why}
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function GtmSection({ plan }: { plan: BusinessPlan }) {
  const g = plan.gtm;
  return (
    <Section id="gtm" title="Go-to-market">
      <Callouts items={contradictionsFor(plan, "gtm")} />
      <Prose>{g.positioning}</Prose>
      <div className="bg-card rounded-lg border p-3 text-sm">
        <p className="mb-2">{g.icp.description}</p>
        <dl className="grid gap-1 sm:grid-cols-[7rem_1fr]">
          <dt className="text-muted-foreground">Who</dt>
          <dd>{g.icp.attributes.join("; ")}</dd>
          <dt className="text-muted-foreground">Pains</dt>
          <dd>{g.icp.pains.join("; ")}</dd>
          <dt className="text-muted-foreground">Trigger</dt>
          <dd>{g.icp.buying_trigger}</dd>
        </dl>
      </div>
      <H3>Channels, ranked by expected CAC</H3>
      <TableWrap label="Channels">
        <thead>
          <tr>
            <th className={cn(th, "text-right")}>#</th>
            <th className={th}>Channel</th>
            <th className={cn(th, "text-right")}>Expected CAC</th>
            <th className={th}>Why</th>
          </tr>
        </thead>
        <tbody>
          {g.channels.map((c, i) => (
            <tr key={c.channel}>
              <td className={tdNum}>{i + 1}</td>
              <td className={cn(td, "whitespace-nowrap")}>{CHANNEL_LABEL[c.channel]}</td>
              <td className={tdNum}>{money(c.expected_cac.value)}</td>
              <td className={cn(td, "min-w-48 text-muted-foreground")}>{c.rationale}</td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <H3>Zero-budget tactics</H3>
          <ul className="flex flex-col gap-1 text-sm">
            {[...g.zero_budget_tactics, ...g.viral_loops].map((t) => (
              <li key={t.name}>
                <span className="font-medium">{t.name}:</span>{" "}
                <span className="text-muted-foreground">{t.description}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-2">
          <H3>The first 100 customers</H3>
          <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm">
            {g.first_100_customers.map((s) => (
              <li key={s.step}>
                <span className="font-medium">{s.step}:</span>{" "}
                <span className="text-muted-foreground">{s.description}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </Section>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-card flex min-w-0 flex-col gap-0.5 rounded-lg border p-3">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="font-mono tabular text-lg leading-tight">{value}</span>
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </div>
  );
}

export function FinancialsSection({ plan }: { plan: BusinessPlan }) {
  const [scenario, setScenario] = useState<ScenarioName>("base");
  const all = SCENARIOS.map((s) => plan.financials.scenarios[s.value]).filter(
    (s): s is NonNullable<typeof s> => s !== undefined,
  );
  const s = plan.financials.scenarios[scenario] ?? all[0];
  if (!s) return null;
  const ue = s.unit_economics;
  const m12 = s.months[s.months.length - 1];
  return (
    <Section id="financials" title="Financials">
      <Callouts items={contradictionsFor(plan, "financials")} />
      <p className="text-muted-foreground max-w-prose text-sm">
        Every number here is computed by the studio&apos;s engine from the assumptions in the
        appendix — none comes from a language model.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Scenario" value={scenario} options={SCENARIOS} onChange={setScenario} />
        {scenario !== "base" && (
          <span className="text-muted-foreground text-xs">
            CAC ×{s.multipliers.cac}, conversion ×{s.multipliers.free_to_paid}, churn ×
            {s.multipliers.monthly_churn}, growth ×{s.multipliers.organic_growth}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile
          label="ARPA / month"
          value={money(ue.arpa)}
          hint={`Gross margin ${pct(ue.gross_margin_pct)}`}
        />
        <Tile
          label="Blended CAC"
          value={money(ue.blended_cac)}
          hint={`Payback ${num(ue.payback_months)} mo`}
        />
        <Tile label="LTV" value={money(ue.ltv)} hint={`LTV:CAC ${ratio(ue.ltv_to_cac)}`} />
        <Tile
          label="Month-12 MRR"
          value={money(m12?.mrr)}
          hint={`Break-even: ${monthLabel(s.break_even_month).toLowerCase()}`}
        />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <ScenarioChart title="MRR" metric="mrr" scenarios={all} selected={scenario} />
        <ScenarioChart title="Cash" metric="cash" scenarios={all} selected={scenario} />
      </div>
      <p className="text-sm" data-testid="runway">
        {s.cash_out_month !== null && s.cash_out_month !== undefined
          ? `Cash runs out in month ${s.cash_out_month}.`
          : "Cash does not run out within 12 months."}{" "}
        {s.runway_after_m12 !== null && s.runway_after_m12 !== undefined
          ? `After month 12, cash lasts ${num(s.runway_after_m12)} more months at the month-12 burn.`
          : "Not burning cash at month 12."}
      </p>
      <H3>12-month projection · {scenario}</H3>
      <TableWrap label={`12-month projection, ${scenario} case`}>
        <thead>
          <tr>
            {[
              "Month",
              "Customers",
              "New",
              "MRR",
              "Gross profit",
              "Opex",
              "Net cash flow",
              "Cash",
            ].map((h, i) => (
              <th key={h} className={cn(th, i > 0 && "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {s.months.map((m) => (
            <tr key={m.month}>
              <td className={tdNum}>{m.month}</td>
              <td className={tdNum}>{num(m.customers)}</td>
              <td className={tdNum}>{num(m.new_customers)}</td>
              <td className={tdNum}>{money(m.mrr)}</td>
              <td className={tdNum}>{money(m.gross_profit)}</td>
              <td className={tdNum}>{money(m.opex)}</td>
              <td className={cn(tdNum, m.net_cash_flow < 0 && "text-destructive")}>
                {money(m.net_cash_flow)}
              </td>
              <td className={cn(tdNum, m.cash < 0 && "text-destructive")}>{money(m.cash)}</td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
      <H3>Pricing</H3>
      <ul className="flex flex-wrap gap-2 text-sm">
        {plan.assumptions.price_tiers.map((t) => (
          <li key={t.name} className="bg-card rounded-lg border px-3 py-2">
            <span className="font-medium">{t.name}</span>{" "}
            <span className="font-mono tabular">{money(t.price_monthly.value)}</span>
            <span className="text-muted-foreground">
              {" "}
              / month · {pct(t.mix.value)} of customers
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function ContradictionsSection({ plan }: { plan: BusinessPlan }) {
  const items = sortedContradictions(plan);
  return (
    <Section id="contradictions" title="Contradictions & open questions">
      {items.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No contradictions were found between the sections.
        </p>
      ) : (
        <Callouts items={items} />
      )}
    </Section>
  );
}

export function RisksSection({ plan }: { plan: BusinessPlan }) {
  return (
    <Section id="risks" title="Risks">
      <ul className="flex flex-col gap-2 text-sm">
        {plan.risks.map((r) => (
          <li key={r.risk} className="bg-card rounded-lg border p-3">
            <p className="font-medium break-words">{r.risk}</p>
            <p className="text-muted-foreground break-words">Mitigation: {r.mitigation}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function LaunchSection({ plan }: { plan: BusinessPlan }) {
  const columns = [
    ["By day 30", plan.checklist.day_30],
    ["By day 60", plan.checklist.day_60],
    ["By day 90", plan.checklist.day_90],
  ] as const;
  return (
    <Section id="launch" title="30/60/90-day launch checklist">
      <Callouts items={contradictionsFor(plan, "launch")} />
      <div className="grid gap-3 sm:grid-cols-3">
        {columns.map(([title, items]) => (
          <div key={title} className="bg-card rounded-lg border p-3">
            <H3>{title}</H3>
            <ul className="mt-2 flex flex-col gap-1.5 text-sm">
              {items.map((item) => (
                <li key={item} className="flex gap-2 break-words">
                  <span
                    className="border-input mt-1 size-3 shrink-0 rounded-sm border"
                    aria-hidden
                  />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Section>
  );
}

export function AppendixSection({
  plan,
  formulas,
}: {
  plan: BusinessPlan;
  formulas: readonly EngineFormula[];
}) {
  const sources = planSources(plan);
  return (
    <Section id="appendix" title="Sources & assumptions">
      <H3>Sources</H3>
      {sources.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No sources cited; every figure is a stated assumption.
        </p>
      ) : (
        <ol className="flex flex-col gap-1 text-sm">
          {sources.map((u, i) => (
            <li key={u} className="flex gap-2 break-all">
              <span className="text-muted-foreground font-mono tabular">S{i + 1}</span>
              <a
                href={u}
                target="_blank"
                rel="noopener noreferrer"
                className="text-signal hover:underline"
              >
                {u}
              </a>
            </li>
          ))}
        </ol>
      )}
      <H3>Figures and their basis</H3>
      <TableWrap label="Figures and their basis">
        <thead>
          <tr>
            <th className={th}>Group</th>
            <th className={th}>Figure</th>
            <th className={cn(th, "text-right")}>Value</th>
            <th className={th}>Basis</th>
          </tr>
        </thead>
        <tbody>
          {assumptionRows(plan).map((r) => (
            <tr key={`${r.group}-${r.label}`}>
              <td className={cn(td, "text-muted-foreground whitespace-nowrap")}>{r.group}</td>
              <td className={cn(td, "min-w-32")}>{r.label}</td>
              <td className={tdNum}>{figure(r.figure)}</td>
              <td className={cn(td, "min-w-48")}>
                <Basis fig={r.figure} />
              </td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
      <H3>Engine calculations</H3>
      <TableWrap label="Engine calculations">
        <thead>
          <tr>
            <th className={th}>Output</th>
            <th className={th}>Formula</th>
            <th className={th}>Computed from</th>
          </tr>
        </thead>
        <tbody>
          {formulas.map((f) => (
            <tr key={f.key}>
              <td className={cn(td, "whitespace-nowrap")}>{f.label}</td>
              <td className={cn(td, "min-w-48 font-mono text-xs")}>{f.formula}</td>
              <td className={cn(td, "min-w-48 text-muted-foreground text-xs")}>
                {f.inputs.map((i) => i.replace(/_/g, " ")).join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
    </Section>
  );
}

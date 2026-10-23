"use client";

import { ArrowLeft, Download, FileText, Hourglass } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { buttonVariants } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";
import { usePlan, useRun } from "@/lib/api/queries";
import type { PlanResponse, RunStatus } from "@/lib/api/types";
import { describeError, formatDateTime } from "@/lib/format";
import { PLAN_SECTIONS, type PlanSectionId } from "@/lib/plan";
import { cn } from "@/lib/utils";

import {
  AppendixSection,
  ContradictionsSection,
  FinancialsSection,
  GtmSection,
  LaunchSection,
  OpportunitySection,
  ProductSection,
  RisksSection,
  SummarySection,
} from "./plan-sections";

const NOT_READY: Partial<Record<RunStatus, { title: string; body: string }>> = {
  queued: {
    title: "The run has not started yet",
    body: "The plan is written after you select an idea.",
  },
  running: {
    title: "The business plan is being written",
    body: "The Product Architect, GTM Strategist and Financial Modeler work in parallel, then the Editor reconciles them. Follow along on the run page.",
  },
  awaiting_human: {
    title: "No idea selected yet",
    body: "Choose an idea on the run page and develop it into a full business plan.",
  },
  failed: {
    title: "The run failed before the plan was written",
    body: "See the run page for the error.",
  },
  budget_exhausted: {
    title: "The budget ran out before the plan was written",
    body: "See the run page for details.",
  },
};

/** Highlights the section nearest the top of the viewport. */
function useActiveSection(): PlanSectionId {
  const [active, setActive] = useState<PlanSectionId>("summary");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const id = visible[0]?.target.id;
        if (id) setActive(id as PlanSectionId);
      },
      { rootMargin: "-80px 0px -60% 0px" },
    );
    for (const { id } of PLAN_SECTIONS) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);
  return active;
}

function SectionNav({ active }: { active: PlanSectionId }) {
  return (
    <>
      <label className="flex flex-col gap-1 text-sm lg:hidden">
        <span className="text-muted-foreground text-xs">Jump to section</span>
        <select
          className="bg-card border-input h-9 rounded-md border px-2"
          value={active}
          onChange={(e) =>
            document.getElementById(e.target.value)?.scrollIntoView({ behavior: "smooth" })
          }
        >
          {PLAN_SECTIONS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <nav aria-label="Plan sections" className="hidden lg:block">
        <ol className="sticky top-20 flex flex-col gap-0.5 text-sm">
          {PLAN_SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                aria-current={active === s.id ? "location" : undefined}
                className={cn(
                  "block rounded-md px-2 py-1 transition-colors",
                  active === s.id
                    ? "bg-muted text-foreground font-medium"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {s.label}
              </a>
            </li>
          ))}
        </ol>
      </nav>
    </>
  );
}

function ExportButtons({ runId }: { runId: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <a href={api.exportUrl(runId, "pdf")} download className={buttonVariants({ size: "sm" })}>
        <Download className="size-4" aria-hidden /> Export PDF
      </a>
      <a
        href={api.exportUrl(runId, "md")}
        download
        className={buttonVariants({ size: "sm", variant: "outline" })}
      >
        <FileText className="size-4" aria-hidden /> Markdown
      </a>
    </div>
  );
}

export function PlanDocument({ runId, data }: { runId: string; data: PlanResponse }) {
  const { plan } = data;
  const active = useActiveSection();
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <Link
          href={`/runs/${runId}`}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 self-start text-sm"
        >
          <ArrowLeft className="size-4" aria-hidden /> Back to the run
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">Business plan</p>
            <h1 className="font-serif text-3xl leading-tight break-words sm:text-4xl">
              {plan.brief.opportunity.title}
            </h1>
            <p className="text-muted-foreground text-sm">
              Version {data.version} · {formatDateTime(data.created_at)}
            </p>
          </div>
          <ExportButtons runId={runId} />
        </div>
      </header>
      <div className="grid gap-6 lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-10">
        <SectionNav active={active} />
        <div className="flex min-w-0 flex-col gap-12">
          <SummarySection plan={plan} />
          <OpportunitySection plan={plan} />
          <ProductSection plan={plan} />
          <GtmSection plan={plan} />
          <FinancialsSection plan={plan} />
          <ContradictionsSection plan={plan} />
          <RisksSection plan={plan} />
          <LaunchSection plan={plan} />
          <AppendixSection plan={plan} formulas={data.engine_formulas} />
        </div>
      </div>
    </div>
  );
}

export function PlanView({ runId }: { runId: string }) {
  const run = useRun(runId);
  const status = run.data?.status;
  const plan = usePlan(runId, status === "completed");

  if (run.isPending) return <LoadingState label="Loading plan…" />;
  if (run.isError) {
    const missing = run.error instanceof ApiError && run.error.status === 404;
    return (
      <ErrorState
        title={missing ? "Run not found" : "Could not load the run"}
        message={describeError(run.error)}
        onRetry={missing ? undefined : () => void run.refetch()}
      >
        <Link href="/runs" className={buttonVariants({ size: "sm", variant: "outline" })}>
          All runs
        </Link>
      </ErrorState>
    );
  }
  if (status !== "completed") {
    const copy = (status && NOT_READY[status]) ?? NOT_READY.running!;
    return (
      <EmptyState icon={Hourglass} title={copy.title}>
        <p>{copy.body}</p>
        <Link
          href={`/runs/${runId}`}
          className={cn(buttonVariants({ size: "sm", variant: "outline" }), "mt-3")}
        >
          Go to the run
        </Link>
      </EmptyState>
    );
  }
  if (plan.isPending) return <LoadingState label="Loading plan…" />;
  if (plan.isError) {
    return (
      <ErrorState
        title="Could not load the business plan"
        message={describeError(plan.error)}
        onRetry={() => void plan.refetch()}
      />
    );
  }
  return <PlanDocument runId={runId} data={plan.data} />;
}

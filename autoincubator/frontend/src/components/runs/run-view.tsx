"use client";

import {
  CircleAlert,
  CirclePause,
  Lightbulb,
  SearchX,
  TriangleAlert,
  WalletCards,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState } from "@/components/common/states";
import { IdeaCard, IdeaCardPending, IdeaCardSkeleton } from "@/components/ideas/idea-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { useRun, useRunEvents } from "@/lib/api/queries";
import { isTerminal, type BudgetUsage, type RunDetail } from "@/lib/api/types";
import { announcedIdeas } from "@/lib/activity";
import { describeError, formatDateTime, formatInteger, formatUsd } from "@/lib/format";
import type { ConnectionStatus } from "@/lib/sse/run-stream";
import { useRunStream, type RunStreamState } from "@/lib/sse/use-run-stream";
import { cn } from "@/lib/utils";

import { ActivityPanel } from "./activity-panel";
import { RunStatusBadge } from "./run-status-badge";

const CONNECTION: Record<ConnectionStatus, { label: string; dot: string }> = {
  connecting: { label: "Connecting", dot: "bg-muted-foreground/50 animate-pulse" },
  live: { label: "Live", dot: "bg-signal animate-pulse" },
  reconnecting: { label: "Reconnecting", dot: "bg-warning animate-pulse" },
  closed: { label: "Final", dot: "bg-muted-foreground/50" },
  error: { label: "Disconnected", dot: "bg-destructive" },
};

function ConnectionIndicator({ stream }: { stream: RunStreamState }) {
  const { label, dot } = CONNECTION[stream.status];
  return (
    <span
      role="status"
      data-connection={stream.status}
      className="text-muted-foreground inline-flex items-center gap-1.5 text-xs"
    >
      <span className={cn("size-1.5 rounded-full", dot)} aria-hidden />
      {label}
      {stream.status === "reconnecting" && stream.attempt > 1 && (
        <span className="tabular font-mono">#{stream.attempt}</span>
      )}
    </span>
  );
}

function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="flex min-w-36 flex-1 flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular truncate font-mono">
          {formatInteger(used)}
          <span className="text-muted-foreground"> / {formatInteger(limit)}</span>
        </span>
      </div>
      <div
        className="bg-muted h-1 overflow-hidden rounded-full"
        role="meter"
        aria-label={`${label} used`}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width]",
            pct >= 100 ? "bg-destructive" : pct >= 80 ? "bg-warning" : "bg-foreground/70",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function BudgetMeter({ budget }: { budget: BudgetUsage }) {
  return (
    <div className="flex flex-wrap items-start gap-x-4 gap-y-2 sm:max-w-lg sm:flex-nowrap">
      <Meter label="Tokens" used={budget.tokens_used} limit={budget.max_tokens} />
      <Meter label="Searches" used={budget.searches_used} limit={budget.max_searches} />
      <div className="flex shrink-0 items-baseline gap-2 text-xs">
        <span className="text-muted-foreground">Cost</span>
        <span className="tabular font-mono">{formatUsd(budget.cost_usd)}</span>
      </div>
    </div>
  );
}

function Banner({
  icon: Icon,
  tone,
  title,
  children,
}: {
  icon: LucideIcon;
  tone: "info" | "warn" | "bad";
  title: string;
  children?: ReactNode;
}) {
  return (
    <div
      role={tone === "bad" ? "alert" : "status"}
      className={cn(
        "flex gap-3 rounded-lg border p-3 text-sm",
        tone === "info" && "border-signal/30 bg-signal-soft/60",
        tone === "warn" && "border-warning/40 bg-warning-soft/70",
        tone === "bad" && "border-destructive/30 bg-destructive/5",
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 size-4 shrink-0",
          tone === "info" && "text-signal",
          tone === "warn" && "text-warning",
          tone === "bad" && "text-destructive",
        )}
        aria-hidden
      />
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="font-medium">{title}</p>
        {children && <div className="text-muted-foreground break-words">{children}</div>}
      </div>
    </div>
  );
}

function RunBanners({ run, stream }: { run: RunDetail; stream: RunStreamState }) {
  const banners: ReactNode[] = [];
  if (stream.status === "reconnecting" && !isTerminal(run.status)) {
    banners.push(
      <Banner key="conn" icon={WifiOff} tone="warn" title="Connection lost — reconnecting…">
        The run keeps going on the server. Missed activity will be replayed when the connection is
        back.
      </Banner>,
    );
  }
  if (stream.status === "error") {
    banners.push(
      <Banner key="conn-err" icon={WifiOff} tone="bad" title="Live updates stopped">
        {stream.error ? describeError(stream.error) : "The stream could not be opened."} Reload the
        page to try again.
      </Banner>,
    );
  }
  if (run.status === "budget_exhausted") {
    banners.push(
      <Banner key="budget" icon={WalletCards} tone="bad" title="Budget exhausted">
        {run.error?.message ?? "The run stopped because it reached its token or search budget."}{" "}
        Ideas scored before the stop are not shown, because none reached the checkpoint.
      </Banner>,
    );
  } else if (run.status === "failed") {
    banners.push(
      <Banner key="failed" icon={CircleAlert} tone="bad" title="The run failed">
        {run.error ? (
          <>
            <span className="font-mono text-xs">{run.error.code}</span> — {run.error.message}
          </>
        ) : (
          "The worker stopped this run with an error."
        )}
      </Banner>,
    );
  } else if (run.status === "awaiting_human") {
    const n = run.viable_count ?? run.ideas.length;
    banners.push(
      <Banner
        key="review"
        icon={CirclePause}
        tone={run.shortfall ? "warn" : "info"}
        title={`Discovery complete — ${n} ${n === 1 ? "idea is" : "ideas are"} ready for your review`}
      >
        {run.shortfall}
      </Banner>,
    );
  } else if (run.status === "running" && run.budget.max_tokens > 0) {
    const tokenPct = run.budget.tokens_used / run.budget.max_tokens;
    const searchPct = run.budget.searches_used / Math.max(1, run.budget.max_searches);
    if (Math.max(tokenPct, searchPct) >= 0.8) {
      banners.push(
        <Banner key="budget-warn" icon={TriangleAlert} tone="warn" title="Budget above 80%">
          The run stops cleanly if it reaches its limit.
        </Banner>,
      );
    }
  }
  return banners.length > 0 ? <div className="flex flex-col gap-2">{banners}</div> : null;
}

function IdeaList({ run, events }: { run: RunDetail; events: ReturnType<typeof useRunEvents> }) {
  const announced = useMemo(() => announcedIdeas(events.events), [events.events]);
  const known = new Set(run.ideas.map((i) => i.id));
  const pending = announced.filter((i) => !known.has(i.idea_id));
  const ideas = [...run.ideas].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const working = run.status === "queued" || run.status === "running";

  if (ideas.length === 0 && pending.length === 0) {
    if (working) {
      return (
        <div className="flex flex-col gap-3">
          <p className="text-muted-foreground text-sm">
            Ranked ideas appear here once the Devil&apos;s Advocate has scored them.
          </p>
          <IdeaCardSkeleton />
          <IdeaCardSkeleton />
        </div>
      );
    }
    return (
      <EmptyState icon={SearchX} title="No ranked ideas">
        {run.shortfall ??
          (run.status === "awaiting_human" || run.status === "completed"
            ? "No idea reached the quality threshold."
            : "The run stopped before any idea was ranked.")}
      </EmptyState>
    );
  }
  return (
    <ol className="flex flex-col gap-3">
      {ideas.map((idea) => (
        <li key={idea.id}>
          <IdeaCard idea={idea} />
        </li>
      ))}
      {pending.map((idea) => (
        <li key={idea.idea_id}>
          <IdeaCardPending idea={idea} />
        </li>
      ))}
    </ol>
  );
}

function RunViewSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true">
      <span className="sr-only" role="status">
        Loading run…
      </span>
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
      </div>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Skeleton className="h-64" />
        <div className="flex flex-col gap-3">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      </div>
    </div>
  );
}

type Pane = "activity" | "ideas";

export function RunView({ runId }: { runId: string }) {
  const run = useRun(runId);
  const notFound = run.error instanceof ApiError && run.error.status === 404;
  const stream = useRunStream(runId, { enabled: !notFound });
  const events = useRunEvents(runId);
  const [pane, setPane] = useState<Pane | null>(null);

  if (run.isPending) return <RunViewSkeleton />;
  if (run.isError) {
    return notFound ? (
      <EmptyState icon={SearchX} title="Run not found">
        It may have been deleted, or the link is wrong.{" "}
        <Link href="/runs" className="text-foreground underline underline-offset-4">
          See all runs
        </Link>
        .
      </EmptyState>
    ) : (
      <ErrorState
        title="Could not load this run"
        message={describeError(run.error)}
        onRetry={() => void run.refetch()}
      />
    );
  }

  const detail = run.data;
  const ideaCount = Math.max(detail.ideas.length, announcedIdeas(events.events).length);
  // On narrow screens show one pane at a time; jump to Ideas once there are some.
  const activePane: Pane = pane ?? (ideaCount > 0 ? "ideas" : "activity");

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <RunStatusBadge status={detail.status} />
          <ConnectionIndicator stream={stream} />
          <span className="text-muted-foreground ml-auto text-xs">
            {detail.mode === "seeded" ? "Seeded" : "Autonomous"} ·{" "}
            <time dateTime={detail.created_at}>{formatDateTime(detail.created_at)}</time>
          </span>
        </div>
        <h1 className="font-serif text-2xl leading-tight tracking-tight sm:text-3xl">
          {detail.seed ?? "Autonomous opportunity scan"}
        </h1>
        <BudgetMeter budget={detail.budget} />
      </header>

      <RunBanners run={detail} stream={stream} />

      <Segmented
        label="Panel"
        value={activePane}
        onChange={setPane}
        options={[
          { value: "activity", label: "Activity" },
          { value: "ideas", label: ideaCount > 0 ? `Ideas (${ideaCount})` : "Ideas" },
        ]}
        className="w-full lg:hidden"
      />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <ActivityPanel
          events={events.events}
          runStatus={detail.status}
          className={cn(
            activePane === "activity" ? "flex" : "hidden",
            "lg:sticky lg:top-20 lg:flex lg:self-start",
          )}
        />
        <section
          aria-labelledby="ideas-heading"
          className={cn(activePane === "ideas" ? "flex" : "hidden", "flex-col gap-2 lg:flex")}
        >
          <h2
            id="ideas-heading"
            className="text-muted-foreground flex items-center gap-1.5 pb-2 text-xs font-medium tracking-wider uppercase"
          >
            <Lightbulb className="size-3.5" aria-hidden /> Ranked ideas
          </h2>
          <IdeaList run={detail} events={events} />
        </section>
      </div>
    </div>
  );
}

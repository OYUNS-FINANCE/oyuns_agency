"use client";

import { ChevronLeft, ChevronRight, ChevronRightIcon, Inbox } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { useRunList } from "@/lib/api/queries";
import type { RunSummary } from "@/lib/api/types";
import { describeError, formatRelative } from "@/lib/format";

import { RunStatusBadge } from "./run-status-badge";

function RunRow({ run }: { run: RunSummary }) {
  return (
    <li>
      <Link
        href={`/runs/${run.id}`}
        className="hover:bg-card group grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 px-3 py-3 transition-colors sm:grid-cols-[1fr_auto_6rem_1rem]"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">
            {run.seed ?? <span className="text-muted-foreground italic">Autonomous scan</span>}
          </span>
          <span className="text-muted-foreground flex flex-wrap gap-x-1.5 text-xs whitespace-nowrap">
            <span>{run.mode === "seeded" ? "Seeded" : "Autonomous"}</span>
            {run.viable_count != null && (
              <span>
                · <span className="tabular font-mono">{run.viable_count}</span> viable
              </span>
            )}
            <span className="sm:hidden">· {formatRelative(run.created_at)}</span>
          </span>
        </span>
        <RunStatusBadge status={run.status} />
        <span className="text-muted-foreground hidden text-right text-xs sm:block">
          <time dateTime={run.created_at}>{formatRelative(run.created_at)}</time>
        </span>
        <ChevronRightIcon
          className="text-muted-foreground hidden size-4 transition-transform group-hover:translate-x-0.5 sm:block"
          aria-hidden
        />
      </Link>
    </li>
  );
}

export function RunHistory({
  pageSize = 20,
  compact = false,
}: {
  pageSize?: number;
  compact?: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const { data, error, isPending, refetch } = useRunList(pageSize, offset);

  if (isPending) return <LoadingState label="Loading runs…" />;
  if (error) {
    return (
      <ErrorState
        title="Could not load runs"
        message={describeError(error)}
        onRetry={() => void refetch()}
      />
    );
  }
  if (data.total === 0) {
    return (
      <EmptyState icon={Inbox} title="No runs yet">
        Start one from the{" "}
        <Link href="/" className="text-foreground underline underline-offset-4">
          new run
        </Link>{" "}
        screen.
      </EmptyState>
    );
  }

  const end = Math.min(offset + data.items.length, data.total);
  return (
    <div className="flex flex-col gap-3">
      <ul className="divide-y rounded-lg border">
        {data.items.map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </ul>
      {!compact && data.total > pageSize && (
        <div className="text-muted-foreground flex items-center justify-between text-xs">
          <span className="tabular font-mono">
            {offset + 1}–{end} of {data.total}
          </span>
          <div className="flex gap-1">
            <Button
              size="icon-sm"
              variant="outline"
              aria-label="Newer runs"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
            >
              <ChevronLeft aria-hidden />
            </Button>
            <Button
              size="icon-sm"
              variant="outline"
              aria-label="Older runs"
              disabled={end >= data.total}
              onClick={() => setOffset(offset + pageSize)}
            >
              <ChevronRight aria-hidden />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

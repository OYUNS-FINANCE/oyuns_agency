import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CirclePause,
  Loader2,
  WalletCards,
  type LucideIcon,
} from "lucide-react";

import type { RunStatus } from "@/lib/api/types";
import { STATUS_LABEL } from "@/lib/ideas";
import { cn } from "@/lib/utils";

const STYLE: Record<RunStatus, { icon: LucideIcon; className: string; spin?: boolean }> = {
  queued: { icon: CircleDashed, className: "border-border text-muted-foreground" },
  running: { icon: Loader2, className: "border-signal/30 bg-signal-soft text-signal", spin: true },
  awaiting_human: {
    icon: CirclePause,
    className: "border-warning/40 bg-warning-soft text-warning",
  },
  completed: { icon: CircleCheck, className: "border-border bg-secondary text-foreground" },
  failed: {
    icon: CircleAlert,
    className: "border-destructive/30 bg-destructive/10 text-destructive",
  },
  budget_exhausted: {
    icon: WalletCards,
    className: "border-destructive/30 bg-destructive/10 text-destructive",
  },
};

export function RunStatusBadge({ status, className }: { status: RunStatus; className?: string }) {
  const { icon: Icon, className: tone, spin } = STYLE[status];
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium whitespace-nowrap",
        tone,
        className,
      )}
    >
      <Icon className={cn("size-3.5", spin && "animate-spin")} aria-hidden />
      {STATUS_LABEL[status]}
    </span>
  );
}

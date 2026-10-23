"use client";

import { Check, ChevronRight, Loader2, Search, Square } from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Switch } from "@/components/ui/switch";
import { isTerminal, type RunEvent, type RunStatus } from "@/lib/api/types";
import { buildTimeline, type AgentPass, type RunMarker } from "@/lib/activity";
import { formatClock, formatDuration, formatInteger } from "@/lib/format";
import { AGENT_LABEL, STATUS_LABEL } from "@/lib/ideas";
import { cn } from "@/lib/utils";

const AGENT_DOT: Record<string, string> = {
  scout: "bg-agent-scout",
  analyst: "bg-agent-analyst",
  skeptic: "bg-agent-skeptic",
  ranker: "bg-agent-ranker",
};

function humanize(key: string): string {
  return key.replace(/_/g, " ");
}

function PassView({
  pass,
  stopped,
  showNotes,
}: {
  pass: AgentPass;
  stopped: boolean;
  showNotes: boolean;
}) {
  // Open while working; a finished pass folds to its header unless the user opened it.
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? !pass.completed;
  const tools = pass.entries.filter((e) => e.kind === "tool").length;
  const visible = showNotes ? pass.entries : pass.entries.filter((e) => e.kind === "tool");
  const latestThought = [...pass.entries].reverse().find((e) => e.kind === "thought");

  return (
    <li>
      <Collapsible open={open} onOpenChange={setUserOpen}>
        <CollapsibleTrigger className="hover:bg-muted/60 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm">
          <ChevronRight
            className={cn(
              "text-muted-foreground size-3.5 shrink-0 transition-transform",
              open && "rotate-90",
            )}
            aria-hidden
          />
          <span
            className={cn("size-2 shrink-0 rounded-full", AGENT_DOT[pass.agent] ?? "bg-agent-run")}
            aria-hidden
          />
          <span className="font-medium">{AGENT_LABEL[pass.agent] ?? humanize(pass.agent)}</span>
          {pass.task ? (
            <span className="bg-muted rounded px-1.5 text-xs">{pass.task}</span>
          ) : (
            pass.pass > 1 && (
              <span className="text-muted-foreground font-mono text-xs">pass {pass.pass}</span>
            )
          )}
          {pass.items != null && (
            <span className="text-muted-foreground tabular font-mono text-xs">
              {pass.items} {pass.items === 1 ? "idea" : "ideas"}
            </span>
          )}
          <span className="text-muted-foreground ml-auto flex shrink-0 items-center gap-1.5 text-xs">
            {tools > 0 && (
              <span className="tabular flex items-center gap-0.5 font-mono">
                <Search className="size-3" aria-hidden />
                {tools}
              </span>
            )}
            {pass.completed ? (
              <span className="tabular flex items-center gap-1 font-mono">
                <Check className="text-signal size-3.5" aria-label="done" />
                {pass.durationMs != null && formatDuration(pass.durationMs)}
              </span>
            ) : stopped ? (
              <Square className="size-3" aria-label="stopped" />
            ) : (
              <Loader2 className="text-signal size-3.5 animate-spin" aria-label="working" />
            )}
          </span>
        </CollapsibleTrigger>
        {!open && !pass.completed && latestThought && (
          <p className="text-muted-foreground truncate pl-[2.1rem] text-xs">{latestThought.text}</p>
        )}
        <CollapsibleContent>
          <ol className="border-border mt-0.5 mb-1 ml-[1.1rem] flex flex-col gap-1 border-l pl-3.5">
            {visible.map((entry) =>
              entry.kind === "tool" ? (
                <li key={entry.id} className="flex items-start gap-2 text-xs">
                  <Search className="text-muted-foreground mt-0.5 size-3 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1 font-mono break-words">{entry.query}</span>
                  {entry.ideaKey && (
                    <span className="text-muted-foreground shrink-0 font-mono">
                      {entry.ideaKey}
                    </span>
                  )}
                  <span className="text-muted-foreground tabular shrink-0 font-mono">
                    {entry.resultCount}
                  </span>
                </li>
              ) : (
                <li key={entry.id} className="text-muted-foreground text-xs leading-relaxed">
                  {entry.text}
                </li>
              ),
            )}
            {pass.completed && Object.keys(pass.summary).length > 0 && (
              <li className="flex flex-wrap gap-x-3 gap-y-0.5 pt-0.5 text-xs">
                {Object.entries(pass.summary).map(([key, value]) => (
                  <span key={key}>
                    <span className="text-muted-foreground">{humanize(key)}</span>{" "}
                    <span className="tabular font-mono">{value}</span>
                  </span>
                ))}
              </li>
            )}
            {visible.length === 0 && !pass.completed && (
              <li className="text-muted-foreground text-xs">Starting…</li>
            )}
          </ol>
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}

function markerText(event: RunMarker): { text: string; tone: "plain" | "warn" | "bad" } {
  switch (event.type) {
    case "run.status":
      return {
        text: event.data.detail
          ? `${STATUS_LABEL[event.data.status]}: ${event.data.detail}`
          : STATUS_LABEL[event.data.status],
        tone:
          event.data.status === "failed" || event.data.status === "budget_exhausted"
            ? "bad"
            : "plain",
      };
    case "run.interrupted":
      return {
        text: `${event.data.viable_count} viable ${event.data.viable_count === 1 ? "idea" : "ideas"}`,
        tone: event.data.shortfall ? "warn" : "plain",
      };
    case "run.error":
      return { text: `${event.data.code}: ${event.data.message}`, tone: "bad" };
    case "budget.warning":
      return {
        text: `${event.data.kind} budget at ${Math.round((event.data.used / event.data.limit) * 100)}% (${formatInteger(event.data.used)} / ${formatInteger(event.data.limit)})`,
        tone: "warn",
      };
    case "budget.exhausted":
      return {
        text: `${event.data.kind} budget exhausted (${formatInteger(event.data.used)} / ${formatInteger(event.data.limit)})`,
        tone: "bad",
      };
  }
}

function MarkerView({ event }: { event: RunMarker }) {
  const { text, tone } = markerText(event);
  return (
    <li className="flex items-center gap-2 px-2 py-1 text-xs">
      <span className="text-muted-foreground tabular font-mono">{formatClock(event.ts)}</span>
      <span className="bg-border h-px w-3" aria-hidden />
      <span
        className={cn(
          "first-letter:uppercase",
          tone === "plain" && "text-muted-foreground",
          tone === "warn" && "text-warning",
          tone === "bad" && "text-destructive",
        )}
      >
        {text}
      </span>
    </li>
  );
}

export function ActivityPanel({
  events,
  runStatus,
  className,
}: {
  events: readonly RunEvent[];
  runStatus: RunStatus;
  className?: string;
}) {
  const [showNotes, setShowNotes] = useState(true);
  const timeline = useMemo(() => buildTimeline(events), [events]);
  const scroller = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const stopped = isTerminal(runStatus) || runStatus === "awaiting_human";

  // Follow new activity while the user is at the bottom; leave them alone once they scroll up.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <section
      aria-labelledby="activity-heading"
      // Exposed for end-to-end checks: the event log size and the stream cursor.
      data-event-count={events.length}
      data-last-event-id={events.at(-1)?.id ?? 0}
      className={cn("flex min-h-0 flex-col", className)}
    >
      <div className="flex items-center justify-between gap-2 pb-2">
        <h2
          id="activity-heading"
          className="text-muted-foreground text-xs font-medium tracking-wider uppercase"
        >
          Activity
        </h2>
        <label className="text-muted-foreground flex items-center gap-2 text-xs">
          Notes
          <Switch
            size="sm"
            checked={showNotes}
            onCheckedChange={(checked) => setShowNotes(checked)}
          />
        </label>
      </div>
      <div
        ref={scroller}
        onScroll={(event) => {
          const el = event.currentTarget;
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        className="min-h-0 flex-1 overflow-y-auto lg:max-h-[calc(100dvh-14rem)]"
      >
        {timeline.length === 0 ? (
          <p className="text-muted-foreground px-2 py-6 text-sm">
            {runStatus === "queued"
              ? "Waiting for a worker to pick up the run…"
              : "No activity yet."}
          </p>
        ) : (
          <ol aria-live="polite" aria-relevant="additions" className="flex flex-col gap-0.5">
            {timeline.map((item) =>
              item.kind === "pass" ? (
                <PassView
                  key={item.pass.key}
                  pass={item.pass}
                  stopped={stopped}
                  showNotes={showNotes}
                />
              ) : (
                <MarkerView key={item.event.id} event={item.event} />
              ),
            )}
          </ol>
        )}
      </div>
    </section>
  );
}

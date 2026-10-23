"use client";

import {
  Ban,
  ClipboardList,
  GitCompareArrows,
  Loader2,
  MessagesSquare,
  RefreshCw,
  Rocket,
} from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { useIdea, useReject, useRescore, useSelectIdea } from "@/lib/api/queries";
import type { IdeaView, RunDetail } from "@/lib/api/types";
import { VERSION_SOURCE_LABEL } from "@/lib/cowork";
import { describeError } from "@/lib/format";
import type { CoworkTab, useCoworkParams } from "@/lib/use-cowork-params";
import { cn } from "@/lib/utils";

import { ChatPanel } from "./chat-panel";
import { DevelopDialog, RejectDialog } from "./dialogs";
import { ScorecardPanel } from "./scorecard-panel";
import { VersionsPanel } from "./versions-panel";

type Params = ReturnType<typeof useCoworkParams>;

function StatusNote({ idea }: { idea: IdeaView }) {
  if (idea.status === "rejected") {
    return (
      <p className="text-destructive text-xs">
        Rejected{idea.reject_reason ? `: ${idea.reject_reason}` : ""}
      </p>
    );
  }
  if (idea.status === "selected") {
    return <p className="text-signal text-xs font-medium">Selected for the business plan</p>;
  }
  return null;
}

function Actions({
  run,
  idea,
  rescoring,
  onSelected,
}: {
  run: RunDetail;
  idea: IdeaView;
  rescoring: boolean;
  onSelected: () => void;
}) {
  const rescore = useRescore(run.id);
  const reject = useReject(run.id);
  const select = useSelectIdea(run.id);
  const [dialog, setDialog] = useState<"reject" | "develop" | null>(null);
  // A second click can land before React re-renders the button as disabled: only the first
  // one sends. (The server is idempotent as well.)
  const selecting = useRef(false);
  const editable = run.status === "awaiting_human" && idea.status === "active";
  if (!editable) return null;
  const error = rescore.error;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setDialog("develop")}>
          <Rocket aria-hidden /> Develop full business plan
        </Button>
        <Button
          size="sm"
          variant={idea.score_stale ? "secondary" : "outline"}
          disabled={rescoring || rescore.isPending}
          onClick={() => rescore.mutate(idea.id)}
        >
          {rescoring || rescore.isPending ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <RefreshCw aria-hidden />
          )}
          {rescoring ? "Re-scoring…" : "Re-score"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setDialog("reject")}>
          <Ban aria-hidden /> Reject
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {describeError(error)}
        </p>
      )}
      <RejectDialog
        open={dialog === "reject"}
        onOpenChange={(open) => setDialog(open ? "reject" : null)}
        title={idea.title}
        pending={reject.isPending}
        error={reject.error}
        onReject={(reason) =>
          reject.mutate({ ideaId: idea.id, reason }, { onSuccess: () => setDialog(null) })
        }
      />
      <DevelopDialog
        open={dialog === "develop"}
        onOpenChange={(open) => setDialog(open ? "develop" : null)}
        title={idea.title}
        // Disabled from the first click until the request settles; the server is idempotent
        // too, so a second tab or a retried request cannot resume the run twice.
        pending={select.isPending || select.isSuccess}
        error={select.error}
        onConfirm={() => {
          if (selecting.current) return;
          selecting.current = true;
          select.mutate(idea.id, {
            onSuccess: () => {
              setDialog(null);
              onSelected();
            },
            onError: () => {
              selecting.current = false;
            },
          });
        }}
      />
    </div>
  );
}

const TAB_ICONS: Record<CoworkTab, typeof MessagesSquare> = {
  chat: MessagesSquare,
  versions: GitCompareArrows,
  scorecard: ClipboardList,
};

export function CoworkDrawer({
  run,
  params,
  rescoring,
}: {
  run: RunDetail;
  params: Params;
  rescoring: ReadonlySet<string>;
}) {
  const detail = useIdea(run.id, params.ideaId);
  const fromRun = run.ideas.find((i) => i.id === params.ideaId);
  const idea = detail.data?.idea ?? fromRun;
  const paused = run.status === "awaiting_human";

  return (
    <Sheet open={params.ideaId !== null} onOpenChange={(open) => !open && params.close()}>
      <SheetContent aria-describedby={undefined}>
        {!idea ? (
          <div className="flex flex-col gap-2 p-5">
            <SheetTitle>Idea</SheetTitle>
            {detail.isError ? (
              <p role="alert" className="text-destructive text-sm">
                {describeError(detail.error)}
              </p>
            ) : (
              <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
                <Loader2 className="size-4 animate-spin" aria-hidden /> Loading idea…
              </p>
            )}
          </div>
        ) : (
          <>
            <header className="flex flex-col gap-3 border-b px-4 pt-4 pb-3 pr-12 sm:px-5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <SheetTitle>{idea.title}</SheetTitle>
                  <SheetDescription className="mt-1">{idea.opportunity.one_liner}</SheetDescription>
                </div>
                <div className="flex shrink-0 flex-col items-end leading-none">
                  <span className="tabular font-mono text-2xl">
                    {idea.composite_score?.toFixed(1) ?? "–"}
                  </span>
                  <span
                    className={cn(
                      "mt-1 text-[0.65rem] tracking-wider uppercase",
                      idea.score_stale ? "text-warning" : "text-muted-foreground",
                    )}
                  >
                    {idea.score_stale ? "out of date" : "score"}
                  </span>
                </div>
              </div>
              <p className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
                <span className="font-mono">{idea.key}</span>
                <span>
                  v{idea.version} · {VERSION_SOURCE_LABEL[idea.version_source]}
                </span>
                {idea.rank !== null && <span>rank #{idea.rank}</span>}
                {idea.merged_from.length > 0 && <span>hybrid of {idea.merged_from.length}</span>}
              </p>
              <StatusNote idea={idea} />
              <Actions
                run={run}
                idea={idea}
                rescoring={rescoring.has(idea.id)}
                onSelected={params.close}
              />
            </header>
            <Tabs
              value={params.tab}
              onValueChange={(tab) => params.setTab(tab as CoworkTab)}
              className="flex min-h-0 flex-1 flex-col"
            >
              <TabsList>
                {(["chat", "versions", "scorecard"] as const).map((tab) => {
                  const Icon = TAB_ICONS[tab];
                  return (
                    <TabsTab key={tab} value={tab}>
                      <Icon className="size-3.5" aria-hidden />
                      {tab === "chat" ? "Chat" : tab === "versions" ? "Versions" : "Scorecard"}
                      {tab === "versions" && detail.data && (
                        <span className="tabular text-muted-foreground font-mono text-xs">
                          {detail.data.versions.length}
                        </span>
                      )}
                    </TabsTab>
                  );
                })}
              </TabsList>
              <TabsPanel value="chat">
                <ChatPanel
                  runId={run.id}
                  idea={idea}
                  agent={params.agent}
                  onAgentChange={params.setAgent}
                  paused={paused && idea.status === "active"}
                />
              </TabsPanel>
              <TabsPanel value="versions">
                {detail.data ? (
                  <VersionsPanel versions={detail.data.versions} />
                ) : (
                  <p className="text-muted-foreground p-5 text-sm" role="status">
                    Loading versions…
                  </p>
                )}
              </TabsPanel>
              <TabsPanel value="scorecard">
                <ScorecardPanel idea={idea} />
              </TabsPanel>
            </Tabs>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

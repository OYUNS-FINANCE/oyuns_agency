"use client";

import { Check, CircleAlert, GitPullRequestArrow, Loader2, SendHorizontal } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Segmented } from "@/components/common/segmented";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useApplyVersion, useCoworkMessages } from "@/lib/api/queries";
import type { CoworkAgent, CoworkMessage, IdeaView, PatchOperation } from "@/lib/api/types";
import { COWORK_AGENTS } from "@/lib/cowork";
import { useCoworkChat } from "@/lib/cowork-chat";
import { pathLabel } from "@/lib/diff";
import { describeError } from "@/lib/format";
import { cn } from "@/lib/utils";

const AGENT_TEXT: Record<CoworkAgent, string> = {
  scout: "text-agent-scout",
  analyst: "text-agent-analyst",
  skeptic: "text-agent-skeptic",
};

function preview(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 1);
}

function ProposedChange({
  message,
  idea,
  paused,
  runId,
}: {
  message: CoworkMessage;
  idea: IdeaView;
  paused: boolean;
  runId: string;
}) {
  const apply = useApplyVersion(runId, idea.id);
  const ops: PatchOperation[] = message.proposed_patch ?? [];
  const applied = message.applied_version ?? (apply.data ? apply.data.version : null);
  return (
    <div className="bg-card mt-2 flex flex-col gap-2 rounded-md border p-3 text-sm">
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium tracking-wider uppercase">
        <GitPullRequestArrow className="size-3.5" aria-hidden /> Proposed change
      </p>
      <ul className="flex flex-col gap-1.5">
        {ops.map((op, i) => (
          <li key={i} className="flex flex-col gap-0.5">
            <span className="text-muted-foreground text-xs">
              {op.op === "remove" ? "Remove" : op.op === "add" ? "Add" : "Change"}{" "}
              <span className="text-foreground">{pathLabel(op.path)}</span>
            </span>
            {op.op !== "remove" && (
              <span className="bg-signal-soft/60 rounded px-1.5 py-0.5 break-words whitespace-pre-wrap">
                {preview(op.value)}
              </span>
            )}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        {applied !== null ? (
          <span className="text-signal flex items-center gap-1 text-xs font-medium">
            <Check className="size-3.5" aria-hidden /> Applied as v{applied}
          </span>
        ) : (
          <Button
            size="sm"
            disabled={!paused || apply.isPending}
            onClick={() => apply.mutate(message.id)}
          >
            {apply.isPending && <Loader2 className="animate-spin" aria-hidden />}
            Apply change
          </Button>
        )}
        {message.based_on_version !== idea.version && applied === null && (
          <span className="text-muted-foreground text-xs">
            Proposed for v{message.based_on_version}; the idea is now v{idea.version}.
          </span>
        )}
        {apply.isError && (
          <span role="alert" className="text-destructive text-xs">
            {describeError(apply.error)}
          </span>
        )}
      </div>
    </div>
  );
}

function Bubble({
  message,
  streamingText,
  children,
}: {
  message: CoworkMessage;
  streamingText: string | null;
  children?: ReactNode;
}) {
  const agent = COWORK_AGENTS.find((a) => a.value === message.agent);
  if (message.role === "user") {
    return (
      <li className="flex flex-col items-end gap-1">
        <span className="text-muted-foreground text-xs">You → {agent?.label}</span>
        <p className="bg-primary text-primary-foreground max-w-[85%] rounded-lg rounded-tr-sm px-3 py-2 text-sm whitespace-pre-wrap">
          {message.content}
        </p>
      </li>
    );
  }
  const pending = message.state === "pending";
  const text = pending ? (streamingText ?? "") : message.content;
  return (
    <li className="flex flex-col items-start gap-1" data-state={message.state}>
      <span className={cn("text-xs font-medium", AGENT_TEXT[message.agent])}>{agent?.label}</span>
      <div className="bg-muted/70 max-w-[92%] rounded-lg rounded-tl-sm px-3 py-2 text-sm">
        {message.state === "failed" ? (
          <p className="text-destructive flex items-start gap-1.5">
            <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {message.error ?? "The agent could not reply."}
          </p>
        ) : (
          <p className="whitespace-pre-wrap" aria-live={pending ? "polite" : undefined}>
            {text}
            {pending && (
              <span className="text-muted-foreground inline-flex items-center gap-1 align-middle">
                {text === "" && "Thinking"}
                <span className="bg-foreground/60 ml-0.5 inline-block h-3.5 w-1 animate-pulse" />
              </span>
            )}
          </p>
        )}
        {children}
      </div>
    </li>
  );
}

export function ChatPanel({
  runId,
  idea,
  agent,
  onAgentChange,
  paused,
}: {
  runId: string;
  idea: IdeaView;
  agent: CoworkAgent;
  onAgentChange: (agent: CoworkAgent) => void;
  paused: boolean;
}) {
  const messages = useCoworkMessages(runId, idea.id);
  const chat = useCoworkChat(runId, idea.id);
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const items = messages.data?.items ?? [];
  const busy = chat.sending || items.some((m) => m.state === "pending");
  const role = COWORK_AGENTS.find((a) => a.value === agent)?.role;

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [items.length, chat.streaming?.text]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const content = draft.trim();
    if (!content || busy || !paused) return;
    setDraft("");
    void chat.send(agent, content);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col gap-1.5 border-b px-4 py-3 sm:px-5">
        <Segmented
          label="Agent"
          value={agent}
          onChange={onAgentChange}
          options={COWORK_AGENTS.map((a) => ({ value: a.value, label: a.label }))}
          className="w-full"
        />
        <p className="text-muted-foreground text-xs">{role}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        {messages.isPending ? (
          <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Loading conversation…
          </p>
        ) : items.length === 0 ? (
          <p className="text-muted-foreground text-sm leading-relaxed">
            Ask the agent to question an assumption, narrow the customer or rethink the pricing.
            When you agree on a change, it proposes an edit you can apply as a new version.
          </p>
        ) : (
          <ol className="flex flex-col gap-4" aria-label="Conversation">
            {items.map((m) => (
              <Bubble
                key={m.id}
                message={m}
                streamingText={chat.streaming?.messageId === m.id ? chat.streaming.text : null}
              >
                {m.role === "assistant" && m.state === "complete" && m.proposed_patch && (
                  <ProposedChange message={m} idea={idea} paused={paused} runId={runId} />
                )}
              </Bubble>
            ))}
          </ol>
        )}
        <div ref={bottom} />
      </div>
      <form onSubmit={submit} className="flex flex-col gap-2 border-t px-4 py-3 sm:px-5">
        {chat.error && (
          <p role="alert" className="text-destructive text-xs">
            {describeError(chat.error)}
          </p>
        )}
        <div className="flex items-end gap-2">
          <Textarea
            aria-label={`Message to the ${COWORK_AGENTS.find((a) => a.value === agent)?.label}`}
            placeholder={paused ? "Message…" : "Co-working is closed for this run"}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={!paused}
            maxLength={4000}
            className="max-h-40 min-h-10"
          />
          <Button
            type="submit"
            size="icon"
            aria-label="Send"
            disabled={!paused || busy || draft.trim() === ""}
          >
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <SendHorizontal />}
          </Button>
        </div>
      </form>
    </div>
  );
}

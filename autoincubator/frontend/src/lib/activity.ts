/** Groups the event log into agent passes for the activity panel. */
import type { EventOf, RunEvent } from "@/lib/api/types";

export type ActivityEntry =
  | { kind: "thought"; id: number; ts: string; text: string }
  | {
      kind: "tool";
      id: number;
      ts: string;
      query: string;
      resultCount: number;
      ideaKey: string | null;
    };

/** One run of one agent, from its `agent.started` to its `agent.completed`. */
export interface AgentPass {
  key: string;
  agent: string;
  /** 1-based count of how many times this agent has started in the run. */
  pass: number;
  iteration: number | null;
  items: number | null;
  startedAt: string;
  completed: boolean;
  durationMs: number | null;
  summary: Record<string, number>;
  entries: ActivityEntry[];
}

export type RunMarker =
  | EventOf<"run.status">
  | EventOf<"run.interrupted">
  | EventOf<"run.error">
  | EventOf<"budget.warning">
  | EventOf<"budget.exhausted">;

export type TimelineItem = { kind: "pass"; pass: AgentPass } | { kind: "marker"; event: RunMarker };

/**
 * Each `agent.started` opens a new pass; thoughts, tool calls and the completion attach to the
 * open pass of the same agent. Run-level events become markers between passes.
 */
export function buildTimeline(events: readonly RunEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const open = new Map<string, AgentPass>();
  const passCounts = new Map<string, number>();

  function openPass(agent: string, event: RunEvent, started?: EventOf<"agent.started">): AgentPass {
    const count = (passCounts.get(agent) ?? 0) + 1;
    passCounts.set(agent, count);
    const pass: AgentPass = {
      key: `${agent}:${event.id}`,
      agent,
      pass: count,
      iteration: started?.data.iteration ?? null,
      items: started?.data.items ?? null,
      startedAt: event.ts,
      completed: false,
      durationMs: null,
      summary: {},
      entries: [],
    };
    open.set(agent, pass);
    items.push({ kind: "pass", pass });
    return pass;
  }

  function passFor(agent: string, event: RunEvent): AgentPass {
    return open.get(agent) ?? openPass(agent, event);
  }

  for (const event of events) {
    const agent = event.agent ?? "run";
    switch (event.type) {
      case "agent.started":
        openPass(agent, event, event);
        break;
      case "agent.thought":
        passFor(agent, event).entries.push({
          kind: "thought",
          id: event.id,
          ts: event.ts,
          text: event.data.text,
        });
        break;
      case "agent.tool_call":
        passFor(agent, event).entries.push({
          kind: "tool",
          id: event.id,
          ts: event.ts,
          query: event.data.query,
          resultCount: event.data.result_count,
          ideaKey: event.data.idea_key ?? null,
        });
        break;
      case "agent.completed": {
        const pass = passFor(agent, event);
        pass.completed = true;
        pass.durationMs = event.data.duration_ms;
        pass.summary = event.data.summary ?? {};
        open.delete(agent);
        break;
      }
      case "run.status":
      case "run.interrupted":
      case "run.error":
      case "budget.warning":
      case "budget.exhausted":
        items.push({ kind: "marker", event });
        break;
      default:
        break;
    }
  }
  return items;
}

/** Ideas announced by `idea.created` events, newest version wins; used before the refetch lands. */
export function announcedIdeas(events: readonly RunEvent[]): EventOf<"idea.created">["data"][] {
  const byId = new Map<string, EventOf<"idea.created">["data"]>();
  for (const event of events) {
    if (event.type === "idea.created") byId.set(event.data.idea_id, event.data);
  }
  return [...byId.values()].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
}

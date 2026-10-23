/** Co-working view helpers: what is in flight, derived from the run's event log (ADR 0006). */
import type { CoworkAgent, IdeaVersionSource, RunEvent } from "@/lib/api/types";

export const COWORK_AGENTS: readonly { value: CoworkAgent; label: string; role: string }[] = [
  { value: "scout", label: "Trend Scout", role: "Problem, customer and signals" },
  { value: "analyst", label: "Market Analyst", role: "Sizing, competitors and pricing" },
  { value: "skeptic", label: "Devil's Advocate", role: "Risks and how to lower them" },
];

export const VERSION_SOURCE_LABEL: Record<IdeaVersionSource, string> = {
  agent: "Discovered",
  cowork: "Edited in chat",
  rescore: "Re-scored",
  merge: "Merged",
};

export interface InFlight {
  /** Ideas the Skeptic is re-scoring right now. */
  rescoring: ReadonlySet<string>;
  /** Merges started and not yet finished. */
  merges: number;
}

/** Longer than the worker's co-working job timeouts: a start older than this was lost. */
export const IN_FLIGHT_STALE_MS = 20 * 60_000;

/**
 * Replays `agent.started` / `agent.completed` pairs for co-working nodes. Derived from the
 * persisted log, so a reload mid-job shows the same "working" state as before.
 */
export function inFlight(events: readonly RunEvent[], now: number = Date.now()): InFlight {
  const rescoring = new Map<string, number>();
  let merges = 0;
  for (const e of events) {
    if (e.type !== "agent.started" && e.type !== "agent.completed") continue;
    if (e.type === "agent.started" && now - Date.parse(e.ts) > IN_FLIGHT_STALE_MS) continue;
    const delta = e.type === "agent.started" ? 1 : -1;
    if (e.data.node === "rescore" && e.data.idea_id) {
      const n = (rescoring.get(e.data.idea_id) ?? 0) + delta;
      if (n > 0) rescoring.set(e.data.idea_id, n);
      else rescoring.delete(e.data.idea_id);
    } else if (e.data.node === "merge") {
      merges = Math.max(0, merges + delta);
    }
  }
  return { rescoring: new Set(rescoring.keys()), merges };
}

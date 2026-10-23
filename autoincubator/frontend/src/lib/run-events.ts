/**
 * Pure reducers that fold SSE events into the TanStack Query cache (ADR 0005):
 * - the per-run event log, which dedups by id, and
 * - the cached `RunDetail`, patched in place for status, error, shortfall and budget.
 */
import type { RunDetail, RunEvent, RunEventType, RunStatus } from "@/lib/api/types";

export interface RunEventStore {
  events: RunEvent[];
  /** Highest event id applied; the stream's `Last-Event-ID` cursor. */
  lastId: number;
  /** Latest status seen in a `run.status` event, if any. */
  status: RunStatus | null;
}

export const EMPTY_EVENT_STORE: RunEventStore = { events: [], lastId: 0, status: null };

/**
 * Appends events newer than the cursor. Ids are per-run and strictly increasing (ADR 0003), so
 * anything at or below `lastId` is a replay and is dropped: this is what keeps a reconnect from
 * duplicating events. Returns the same object when nothing is new.
 */
export function mergeEvents(store: RunEventStore, incoming: readonly RunEvent[]): RunEventStore {
  let { lastId, status } = store;
  const fresh: RunEvent[] = [];
  for (const event of incoming) {
    if (event.id <= lastId) continue;
    fresh.push(event);
    lastId = event.id;
    if (event.type === "run.status") status = event.data.status;
  }
  if (fresh.length === 0) return store;
  return { events: [...store.events, ...fresh], lastId, status };
}

/**
 * Patches the fields of a cached `RunDetail` that events carry. Budget counters only move up, so
 * replayed warnings never roll back a fresher snapshot.
 */
export function applyEventsToDetail(detail: RunDetail, events: readonly RunEvent[]): RunDetail {
  let next = detail;
  for (const event of events) {
    switch (event.type) {
      case "run.status":
        if (next.status !== event.data.status) next = { ...next, status: event.data.status };
        break;
      case "run.error":
        next = { ...next, error: { code: event.data.code, message: event.data.message } };
        break;
      case "run.interrupted":
        next = {
          ...next,
          viable_count: event.data.viable_count,
          shortfall: event.data.shortfall ?? null,
        };
        break;
      case "budget.warning":
      case "budget.exhausted": {
        const { kind, used, limit } = event.data;
        const budget = { ...next.budget };
        if (kind === "tokens") {
          budget.tokens_used = Math.max(budget.tokens_used, used);
          budget.max_tokens = limit;
        } else {
          budget.searches_used = Math.max(budget.searches_used, used);
          budget.max_searches = limit;
        }
        next = { ...next, budget };
        break;
      }
      default:
        break;
    }
  }
  return next;
}

const REFETCH_TYPES: ReadonlySet<RunEventType> = new Set<RunEventType>([
  "run.status",
  "run.interrupted",
  "run.resumed",
  "run.completed",
  "run.error",
  "idea.created",
  "idea.updated",
  "budget.exhausted",
]);

/** Events whose full effect (idea bodies, timestamps, cost) only `GET /runs/{id}` can show. */
export function needsDetailRefetch(events: readonly RunEvent[]): boolean {
  return events.some((event) => REFETCH_TYPES.has(event.type));
}

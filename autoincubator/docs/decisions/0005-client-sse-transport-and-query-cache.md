# 0005 — Client SSE transport and how events map into the Query cache
Date: 2026-10-23    Status: accepted

## Context
`/runs/[runId]` must show a run live, survive the API restarting mid-run ("reconnecting",
then catch up with no duplicates), and rebuild the same view after a hard reload at any status.
The server side is fixed by ADR 0003: per-run, strictly increasing event ids; replay after
`Last-Event-ID` (header) or `?last_event_id=`; the stream closes only once the run is terminal.
The browser talks to the API through the Next rewrite proxy (ADR 0001). While the API is down,
that proxy answers with a 5xx.

## Options considered
1. **Native `EventSource`.** Built-in reconnect and `Last-Event-ID`. However, it treats any non-200
   response as fatal and closes for good, which is exactly what the proxy returns during a
   restart. It cannot set headers on the first connect, its retry delay is fixed (no exponential
   backoff), and it can't tell a missing run from an outage.
2. **`fetch` + streamed body + a small SSE parser.** About 150 lines of our own code. It sends a
   real `Last-Event-ID` header on every connect, backs off exponentially with jitter, stops on a
   4xx, retries on 5xx or network errors, and is easy to test with a fake `fetch`.
3. **Push events into component state.** Simple, but the state is lost on unmount, and it is
   separate from the `GET /runs/{id}` data, so two sources of truth drift apart.

## Decision
Option 2, with the TanStack Query cache as the only store:
- `src/lib/sse/run-stream.ts` holds the connection loop (no React):
  - statuses `connecting | live | reconnecting | closed | error`
  - backoff from 0.5 s doubling to a 15 s cap with equal jitter, reset after each successful
    connect
  - a 404 or another non-retryable 4xx means stop
  - a clean end of the body while the run is not terminal means reconnect
- `["runs","events",id]` is a `RunEventStore {events, lastId, status}`:
  - `mergeEvents` appends only ids above `lastId`, so an overlapping replay can never
    duplicate events
  - `lastId` is the cursor sent as `Last-Event-ID`
  - `useRunStream` is the only writer; the query function just returns the cached value
- `["runs","detail",id]` is the `GET /runs/{id}` result:
  - events patch status, error, viable count/shortfall and budget in place (budget counters
    only move up, so a replay never rolls back a fresher snapshot)
  - idea and lifecycle events, and every reconnect, trigger one debounced invalidation, because
    `idea.created` does not carry the full idea
- Page restore: on mount the page loads `GET /runs/{id}` and streams from the cached cursor
  (0 on a fresh load, so a full replay rebuilds the activity panel).
- The hook reads tuning options through a ref. Its effect depends only on
  `(client, runId, enabled)`, so an inline options object can't restart the stream on every
  render.

## Consequences
- **Hidden pages:** with `cacheComponents`, Next keeps hidden pages mounted inside `<Activity>`
  and tears down their effects. Showing the page again resumes from the cached cursor instead
  of replaying the whole run.
- **One request per browser tab:** each open tab holds one streaming `fetch`, and each stream
  costs the API one connection. That's fine for single-user mode; revisit with auth and
  multi-tenancy (Phase 7).
- **Server `retry:` ignored:** the client ignores the server's `retry:` hint. It owns its
  backoff policy.
- **Agent re-runs after a crash:** re-run steps re-emit their `agent.*` events with new ids
  (Phase 2 known issue). The activity panel shows them as a second pass of that agent, which is
  accurate.

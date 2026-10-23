# 0003 — SSE notification via Postgres LISTEN/NOTIFY, with per-run ordered event ids
Date: 2026-10-23    Status: accepted

## Context
Workers produce run events; API processes stream them to browsers over SSE. Events are
persisted in `agent_events` (bigserial `id`) and replayed after reconnects via
`Last-Event-ID`. A reconnecting client must lose nothing and see nothing twice. SPEC §6
allows either Postgres `LISTEN/NOTIFY` or Redis pub/sub for waking streams.

## Options considered
1. **Redis pub/sub.** Fast fan-out, but the publish is a second write next to the DB
   insert. A subscriber can be woken for a row that has not committed yet, or the publish
   can be lost after the commit. The DB must be re-read anyway.
2. **Postgres LISTEN/NOTIFY (chosen).** `pg_notify` inside the inserting transaction is
   delivered only on commit and dropped on rollback. No dual write and no extra moving
   part. Payloads are limited to 8 kB, which doesn't matter because they carry only ids.
3. **Polling only.** Simple but slow; it costs a query per stream per interval.

Ordering: a bigserial id is drawn at insert time, but transactions can commit out of id
order. A stream that has sent id 11 could then miss id 10 when it commits later.
1. Single-writer per run (the worker). This doesn't hold: parallel agent tasks, the API's
   `queued` event and a recovering worker all write.
2. **A per-run advisory transaction lock before the insert (chosen).**

## Decision
- `insert_event` runs `pg_advisory_xact_lock(hashtext('run-events:' || run_id))`, inserts
  the row, then runs `pg_notify('agent_events', '<run_id>:<event_id>')`, all in the
  caller's transaction. The lock is held until commit, so for any one run, id order equals
  commit order. Ids are global, so a run's ids have gaps; that is fine for a cursor.
- Each API process holds one asyncpg `LISTEN` connection (`EventBroker`). Notifications
  only set a per-run `asyncio.Event`. They are wake-ups, never data.
- The SSE handler subscribes first, then loops:
  1. clear the wake-up,
  2. read the run status,
  3. read events `id > cursor` (500 per batch) and send each with `id:` = event id,
  4. close if the status read in step 2 was terminal and the batch was not full,
  5. otherwise wait for a wake-up or `SSE_POLL_INTERVAL_S` (default 5 s).
  
  The status is read before the events, so a terminal status's own event is always in the
  batch. The fallback poll covers a dropped LISTEN connection; the broker reconnects every
  5 s and wakes every stream when it does.
- The cursor comes from the `Last-Event-ID` header (EventSource reconnects) or
  `?last_event_id=`. The first event carries `retry: 3000`. FastAPI's built-in
  `EventSourceResponse` sends `: ping` keep-alives after 15 s idle.
- The stream closes on `completed`, `failed` and `budget_exhausted`. It stays open on
  `awaiting_human`, because the run continues after the checkpoint (Phase 4).
- Producers emit through an `EventSink` protocol in `GraphDeps`; nodes never touch the DB.
- The `agent_events.type` column is `varchar`, not a Postgres enum, so new event types need
  no migration. The Pydantic `Event` union is the validator. It is exported in
  `openapi.json` as `components/schemas/Event`.
- The same-origin Next.js rewrite (ADR 0001) was checked with `pnpm dev`. Events arrive
  incrementally (no buffering), and `Last-Event-ID` is forwarded.

## Consequences
- Every event insert takes a short per-run lock, which serialises one run's writers. At a
  few events per second per run this is negligible.
- Each API process needs one dedicated Postgres connection for LISTEN. Behind a
  transaction-pooling proxy (PgBouncer in transaction mode), LISTEN does not work. Point
  the broker at a direct connection when deploying (Phase 7).
- A missed notification costs at most `SSE_POLL_INTERVAL_S` of latency, never an event.
- Events emitted by a graph step that is re-run after a crash appear again with new ids
  (ADR 0004). Clients see them as new events, not SSE duplicates.

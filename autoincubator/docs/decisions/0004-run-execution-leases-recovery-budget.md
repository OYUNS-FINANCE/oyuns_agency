# 0004 — Run execution: status machine, job leases, crash recovery and budgets
Date: 2026-10-23    Status: accepted

## Context
`POST /runs` must return immediately. An arq worker executes the graph up to the
interrupt and persists the ideas. Phase 2 requires a decision on what happens when a
worker is killed mid-run: resume from the checkpoint, or mark the run `failed` cleanly.
Each run also has token and search caps that must stop it gracefully.

arq's own redelivery is too slow to rely on. A killed job is retried only after its
in-progress key expires (`job_timeout + 10 s`, about an hour here). arq can also deliver a
job twice: its retry plus anything we enqueue.

## Options considered
1. **Mark interrupted runs `failed`.** Simple, but it throws away paid-for work, and SPEC
   priority 2 is resumability.
2. **Rely on arq retries.** Up to an hour of delay, and nothing stops two deliveries from
   driving one run.
3. **DB lease per job, plus a recovery sweep, resuming from the LangGraph checkpoint
   (chosen).**

## Decision
**Status machine** (`services/runs.py`, enforced by a conditional `SELECT … FOR UPDATE`
and `UPDATE`):

```
queued ──► running ──► awaiting_human ──(Phase 4)──► running ──► completed
  └► failed    ├──► failed
               └──► budget_exhausted
```

- Every change emits `run.status` in the same transaction.
- Terminal statuses are `completed`, `failed` and `budget_exhausted`. A stop writes
  `runs.error = {code, message}`, then emits `run.error` and the final `run.status`, so the
  status change is always the last event. A refused transition writes nothing (savepoint).
- `budget_exhausted` is a separate status, not `failed` with a code, because the UI has a
  dedicated budget-exhausted state (SPEC §7).

**Leases** (`runs.lease_owner`, `runs.lease_expires_at`, TTL `RUN_LEASE_TTL_S` = 60 s):
- `start_run` claims the lease atomically for an active run whose lease is free, expired,
  or its own. The owner is **the job** (`<host:pid:rand>/<arq job id>`), not the worker
  process. A first version used the worker id. A test run then caught one worker driving a
  run twice: arq's retry plus a recovery job, both "owned" by that worker. One persisted
  the ideas, and the other marked the run failed.
- A background task renews the lease every TTL/3. If renewal finds the lease taken, it
  cancels the job.
- The job's final writes (ideas plus `awaiting_human`, `completed`, or a stop) are
  conditional on still holding the lease (`lease_owner` in the `FOR UPDATE` row lock).
  A job that lost its lease rolls back and ends as `lease_lost`.
- A failure path only moves a run out of `running`; it can never overwrite
  `awaiting_human`.

**Recovery:**
- The arq cron job `recover_runs` runs at worker start and every 15 s. It finds `running`
  runs with an expired lease, and active runs with no lease created more than one TTL ago
  (a lost or never-enqueued job, e.g. Redis was down during `POST`). For each, it enqueues
  `start_run` under a fresh job id.
- The recovering job emits `run.status running→running` ("Recovered after a worker
  stopped…"). It then calls `graph.ainvoke(None)`, which continues from the last committed
  checkpoint.
- The worker runs the graph with `durability="sync"`: each step's checkpoint is committed
  before the next step starts, so a crash loses at most the step in progress.
- If the graph had already reached the interrupt, only persistence is redone. Idea writes
  are idempotent (`UNIQUE (run_id, key)`, `ON CONFLICT DO NOTHING`).
- On cancellation (SIGTERM, job timeout), the job releases its lease, so the next sweep
  recovers the run immediately.

**Budget** (`services/budget.py`):
- Each run snapshots `RUN_MAX_TOKENS` and `RUN_MAX_SEARCHES`. A request may only lower them.
- The check runs before every LLM attempt (a `before_call` hook in the retry loop, so
  validation retries count) and before every search-provider call (cache misses only).
- After each call, the usage hook writes a `run_costs` row and increments the run's
  counter. That write is shielded from cancellation, because tokens already spent must be
  recorded.
- At 80% of a cap, the run emits `budget.warning` once per kind (not repeated after a
  restart). At 100%, the next call raises `BudgetExhaustedError`. Sibling tasks are
  cancelled (`gather_bounded` now uses a `TaskGroup`). The worker writes
  `budget.exhausted`, `run.error` and `run.status → budget_exhausted` in one transaction.
  Emitting `budget.exhausted` from inside the budget lost the event: a sibling's raise
  cancelled the task mid-insert.
- Parallel calls that pass the check together can overshoot a cap by at most
  `AGENT_CONCURRENCY` calls.

**Search cache:** the `search_cache` table, keyed by `(run_id, normalised query,
max_results)`, so steps re-run after a crash don't pay for their searches again.

## Consequences
- A killed worker's run resumes within about one lease TTL plus the sweep interval. The
  integration test kills a worker mid-Analyst and checks that the Scout step is not re-run.
- The re-run step's events (`agent.*`) appear twice in the event log, with new ids.
- arq may still re-deliver the original job after its in-progress timeout. The lease turns
  that delivery into `skipped`.
- The runs table has two lease columns that only workers write. Phase 4's resume
  (`awaiting_human → running`) must claim the lease the same way.

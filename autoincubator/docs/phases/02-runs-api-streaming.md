# Phase 2 — Runs, persistence, worker & live streaming

## Goal
A run can be started over HTTP, executes in the worker, persists its ideas, and streams live events over SSE, including replay after reconnecting.

## Scope
- **DB models + migration:** `runs`, `ideas`, `idea_versions`, `agent_events` (bigserial id), `search_cache`, `run_costs`, `founder_profile`. Each has `user_id`, indexes, enums and JSONB where appropriate. Repositories in `db/`.
- **Event layer:** a typed event union (SPEC §6), a publisher that inserts into `agent_events` and then `NOTIFY`s, and agent nodes emitting `agent.started/thought/tool_call/completed`.
- **Worker:** an arq task `start_run(run_id)` that builds the graph, runs it to the interrupt, and writes ideas plus version 1 to the app tables. Run status lifecycle: `queued → running → awaiting_human → …`, plus `failed` with the error stored.
- **API:**
  - `POST /runs` (Mode A/B + constraints) → `202 {run_id}`
  - `GET /runs` (list)
  - `GET /runs/{id}` (state + ideas)
  - `GET /runs/{id}/stream` (SSE; supports `Last-Event-ID`, heartbeats, closes on terminal status)
  - `GET/PUT /profile`
  - Consistent error model.
- **Budget:** per-run token and search caps checked before each LLM/search call. Emits `budget.warning` at 80%; at 100%, `budget.exhausted` and a graceful stop.
- **Search cache:** per run, keyed by normalized query.

## Out of scope
Co-working endpoints, Phase 2 agents, UI beyond what already exists.

## Acceptance criteria
- [ ] `POST /runs` returns in under 200 ms; the work happens in the worker.
- [ ] Integration test: start a run → events arrive over SSE in order → status reaches `awaiting_human` → ideas readable via `GET /runs/{id}`.
- [ ] Test: disconnect mid-stream, reconnect with `Last-Event-ID`, and no events are lost or duplicated.
- [ ] Test: killing the worker mid-run, then restarting it, resumes from the checkpoint (or marks the run `failed` cleanly, per an ADR you write).
- [ ] Test: budget exhaustion stops the run gracefully with a clear status.
- [ ] The OpenAPI schema is generated and committed (`backend/openapi.json`).
- [ ] All checks are green; PROGRESS.md is updated.

## Prompt to paste
```
Phase 2. Read CLAUDE.md, docs/SPEC.md, docs/PROGRESS.md and docs/phases/02-runs-api-streaming.md.
Propose: table definitions (columns, types, indexes), the event schema, the run status state machine, and how SSE gets notified (LISTEN/NOTIFY vs Redis pub/sub — pick one, justify). Wait for my OK, then implement, write ADRs, run all acceptance checks, update PROGRESS.md.
```

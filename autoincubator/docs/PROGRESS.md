# Progress log

Claude updates this file at the end of every phase. Newest entries go on top.

## Current phase
Phase 2 — done; Phase 3 (frontend: start screen & live discovery) next.
Still open from Phase 1: the real-Anthropic-key CLI check.

## Phase checklist
- [x] 0 — Skeleton & infrastructure
- [x] 1 — Phase-1 graph core (offline) — real-key CLI run pending
- [x] 2 — Runs, persistence, worker & streaming
- [ ] 3 — Frontend: start screen & live discovery
- [ ] 4 — Co-working checkpoint (HITL)
- [ ] 5 — Phase-2 agents, finance engine & export
- [ ] 6 — Real search, evals, cost & observability
- [ ] 7 — Deployment

---

### Phase 2 — Runs, persistence, worker & streaming (2026-10-23)
**Built:**
- **Tables** (migration `0002`, round-trips up/down): `runs` (status enum, `input` JSONB
  snapshot, `error` JSONB, budget caps + counters, lease columns), `ideas` (unique
  `(run_id, key)`), `idea_versions` (unique `(idea_id, version)`, opportunity/analysis/
  critique JSONB), `agent_events` (bigserial, `(run_id, id)` index, `type` varchar),
  `search_cache` (unique per run + normalised query + max_results), `run_costs` (one row per
  LLM attempt), `founder_profile` (one row per user). Every table has `user_id`, filled from
  `DEFAULT_USER_ID` until auth. Repositories in `app/db/repositories/`. The unique-constraint
  naming convention now includes every column.
- **Events:**
  - typed `Event` union (13 types, SPEC §6) in `app/events/schema.py`
  - `EventSink` protocol in `GraphDeps` (null and recording sinks for the CLI and tests)
  - `PostgresEventSink`
  - `insert_event`: per-run advisory lock, then insert, then `pg_notify`
  - `EventBroker`: one LISTEN connection per API process, wake-ups only
  
  Scout, Analyst, Skeptic and rank emit `agent.started/thought/tool_call/completed`.
- **Worker** (`app/worker/runs.py`): `start_run` takes a per-job lease, runs the graph
  with `durability="sync"`, and at the interrupt writes ideas + version 1, `idea.created`,
  `run.interrupted` and `awaiting_human` in one transaction. The lease is renewed in the
  background. The `recover_runs` cron (at startup and every 15 s) re-enqueues runs with an
  expired lease or a lost job; they resume from the checkpoint. Status machine in
  `services/runs.py`.
- **Budget** (`services/budget.py`): checked before every LLM attempt (new `before_call`
  hook in the retry loop) and every search-provider call. `budget.warning` at 80%; at 100%
  the run stops with `budget.exhausted`, `run.error` and status `budget_exhausted`.
  `gather_bounded` now cancels siblings on the first error (`TaskGroup`).
- **Search cache:** `CachedSearchProvider` takes a `SearchCache` (in-memory for the CLI,
  `PostgresSearchCache` in the worker) plus budget hooks. Only cache misses are counted.
- **API** under `/api/incubator`:
  - `POST /runs` → 202 `{run_id, status}`
  - `GET /runs?limit&offset`
  - `GET /runs/{id}` (run, budget usage, cost, ideas at their latest version)
  - `GET /runs/{id}/stream` (SSE: `Last-Event-ID` header or `?last_event_id=`, `retry`,
    keep-alive pings, closes on terminal statuses)
  - `GET/PUT /profile`
  
  One error shape, `{"error": {code, message, details}}`, covers app errors, 404/405, 422
  and 500.
- **OpenAPI:** `backend/openapi.json` is committed. It includes the SSE `Event` union under
  `components/schemas/Event`, referenced by the stream's `data` field.
  `scripts/export_openapi.py` (`make openapi`) regenerates it, and a unit test fails when
  the file is stale.
- `FAKE_LLM_LATENCY_MS` makes offline runs slow enough to watch live (and to kill a worker
  mid-run in tests).
- **Tests:**
  - 32 new unit tests: event union round-trip, budget thresholds/retries/shielding, status
    machine, node events, error model, OpenAPI drift, `gather_bounded` cancellation.
  - 10 new integration tests: real uvicorn + arq subprocesses on a private queue for the
    SSE, reconnect, kill and budget tests; DB-level tests for the state machine, leases and
    the two-jobs race.

**Deviations from spec (and why):**
- Routes are under `/api/incubator/...` (the SPEC §6 table), not bare `/runs` as written
  in the phase file. The profile route is `/api/incubator/profile`.
- `cowork_messages` and `business_plans` are not created yet (Phases 4 and 5).
- `budget_exhausted` is its own terminal status rather than `failed` + code (ADR 0004).
- Only ranked briefs (3–5) are persisted as ideas. Scored ideas below the threshold stay in
  the checkpoint only.
- `agent.thought` carries progress notes written by the nodes, not model reasoning.
- `agent.tool_call` has no `cached` flag: the node can't see whether the search cache
  answered.

**ADRs added:** 0003 — SSE via LISTEN/NOTIFY with per-run ordered ids. 0004 — run
execution: status machine, job leases, crash recovery (resume from checkpoint), budgets.

**Known issues / tech debt:**
- **Bugs found and fixed while verifying:**
  - Leases were first owned per worker process, so one worker could drive a run twice
    (arq retry + recovery job) and mark a finished run `failed`. They are now owned per job,
    and final writes require the lease. A regression test covers it.
  - `budget.exhausted` could be lost when a sibling task cancelled the emitting task. The
    worker now writes it, and usage accounting is shielded from cancellation.
- Steps re-run after a crash re-emit their `agent.*` events, with new ids.
- **Budget overshoot:** parallel calls can pass the cap by up to `AGENT_CONCURRENCY` calls.
  The cost of an LLM call isn't known before it is made.
- **LISTEN needs a direct Postgres connection.** It won't work through a
  transaction-pooling PgBouncer; note this for Phase 7.
- arq still re-delivers a killed job after `RUN_JOB_TIMEOUT_S + 10 s`. The lease turns
  that delivery into a `skipped` no-op.
- **Leftover row in the dev DB:** run `b2c746ef-…` (status `failed`), produced by the
  lease bug above before it was fixed. Harmless; delete it if you like.
- **Single-user mode:** `get_current_user_id` returns `DEFAULT_USER_ID`. The API scopes
  reads by user; worker-side reads do not.
- Integration tests leave their completed runs in the dev database (no active ones).

**Acceptance criteria:** all passed (verified by running commands):
- `POST /runs` under 200 ms: `test_start_run_streams_events_in_order_and_reaches_awaiting_human`
  times 5 POSTs (well under 200 ms; a manual `curl` measured 52 ms). The work runs in the
  worker.
- Start a run → ordered SSE events → `awaiting_human` → ideas via `GET /runs/{id}`: same test.
- Disconnect, reconnect with `Last-Event-ID`, nothing lost or duplicated:
  `test_reconnect_with_last_event_id_loses_and_duplicates_nothing`. It disconnects mid-run
  and compares against a full replay.
- SIGKILL the worker mid-Analyst, start a new one: the run resumes from the checkpoint
  (Scout not re-run) and reaches `awaiting_human`
  (`test_killed_worker_is_recovered_and_resumes_from_the_checkpoint`; ADR 0004).
- Budget exhaustion: `test_budget_exhaustion_stops_the_run_with_a_clear_status` checks
  warning → exhausted → `run.error` → status `budget_exhausted`, the stream closing, and
  `GET` showing the error.
- `backend/openapi.json` is generated and committed, with a drift test.
- `pytest` (93 passed), `pytest -m integration` (12 passed, repeated 3+ times without
  failures after the fixes), `mypy --strict` (app, scripts, tests, migrations), `ruff check`,
  `ruff format --check`, `alembic check`, the Phase-1 CLI, the ping smoke check, and
  `pnpm typecheck/lint/test` all pass.
- ADR 0001 follow-up: SSE through the Next rewrite (`pnpm dev` on :3000) streams
  incrementally and forwards `Last-Event-ID`.

**Next:** Phase 3 — frontend start screen & live discovery
(`docs/phases/03-frontend-discovery.md`). Types for events can be generated from
`openapi.json`.

---

### Phase 1 — Phase-1 graph core, offline (2026-10-23)
**Built:**
- Providers: `LLMProvider` protocol + `StructuredLLMProvider` retry loop (schema validation
  and optional semantic validator; the error is fed back to the model; `LLMOutputError`
  after `LLM_MAX_VALIDATION_RETRIES`), `UsageRecord` per attempt + async `UsageHook`,
  pricing table. `AnthropicLLM` (SDK 2.1.0, `beta.messages.create` with
  `output_config.format` JSON schema from `transform_schema`, `effort=medium`, server-side
  `fallbacks="default"`, refusal → `LLMRefusalError`). `FakeLLM` (scripted per agent, call
  log) + `offline_responder` (deterministic, schema-valid answers derived from the prompt).
  `SearchProvider` + `MockSearchProvider` (24 JSON fixtures incl. a prompt-injection page)
  + `CachedSearchProvider`. `Deduplicator` protocol + `JaccardDeduplicator`.
- Schemas: `RunInput`/`RunConstraints`/`FounderProfile`, `RawOpportunity` (+ signals with
  URLs), `SourcedFigure` (rejects figures with neither `source_url` nor `assumption`),
  `MarketAnalysis` (TAM/SAM/SOM with method, SOM ≤ SAM ≤ TAM), `RubricScore`,
  `CritiqueScorecard` (all 7 dimensions exactly once), `IdeaBrief`, `CheckpointPayload`,
  `ResumePayload`. URLs use `WebUrl` (HttpUrl-validated `str`).
- Agents (`agents/{scout,analyst,skeptic}`): versioned prompt constants (Scout has
  `MODE_A_PLAN_V1`, `MODE_B_PLAN_V1`, `EXTRACT_V1`), node functions. Scout: plan queries →
  search → extract → filter (generic / weak signal / low novelty / excluded industry) →
  dedup. Mode B plans must cover ≥ 4 signal categories with ≤ 3 queries per industry.
  Cited URLs (Scout signals, Analyst figures and competitors) must come from that call's
  search results, else retry. Web content is wrapped in `<untrusted_web_content>` with
  delimiter break-out neutralised. A per-idea Analyst/Skeptic failure skips the idea.
- Graph (`graph/`): `Phase1State` with reducers, `GraphDeps` runtime context, rank node
  (weighted composite in Python), `route_after_rank` (one loop back), `checkpoint` node
  (`interrupt()`, re-asks on invalid selection), Phase-2 stubs (3 parallel + editor),
  `postgres_checkpointer` (`AsyncPostgresSaver`). Alembic ignores the checkpoint tables.
- CLI `scripts/run_phase1.py --seed … | --auto | --thread-id … --resume-select …` (JSON on
  stdout, logs on stderr); `make phase1 ARGS=…`.
- Tests: 61 unit (schemas, retry loop, Anthropic request shape via stub client, search,
  dedup, untrusted wrapping, each node, ranking/routing, whole graph on `InMemorySaver`
  incl. loop-once/shortfall and invalid selection), 1 new integration (interrupt in one
  process, read back typed state in another, resume in a third, under
  `LANGGRAPH_STRICT_MSGPACK=true`).

**Deviations from spec (and why):**
- CLI has an extra `--thread-id/--resume-select` mode, needed for the cross-process resume.
- Default model per agent is `claude-sonnet-5-5` (configurable per agent), as agreed in the plan.
- Real search is not wired: with `LLM_PROVIDER=anthropic` the CLI still uses
  `MockSearchProvider` (real providers are Phase 6). `search_cache` is in-memory per run
  until the DB tables exist (Phase 2).
- No explicit msgpack allowlist: LangGraph 1.2 derives it from the state schema at
  `compile()` (verified: models come back typed without one). See ADR 0002.
- New deps (exact pins): langgraph 1.2.16, langgraph-checkpoint-postgres 3.2.0,
  psycopg[binary] 3.3.6, anthropic 2.1.0. langgraph-sdk pulls websockets down from 17.3 to 16.1.1.

**ADRs added:** 0002 — Phase-1 state schema, routing and checkpoint semantics.

**Known issues / tech debt:**
- **Not verified with a real Anthropic key** — no key was available in the session. To
  check: `LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=… make phase1 ARGS='--seed "…"'`
  (about 20 calls). Watch for schema features the structured-output API rejects; the SDK's
  `transform_schema` accepts all four output schemas offline.
- Cost is computed locally from `response.model` + `usage` and a price table. When a
  server-side fallback serves the request, billing may differ (`usage.iterations` is not
  parsed yet); unknown models log `llm.unpriced_model` and cost 0. Cache-write and Haiku
  cache-read prices are derived, not quoted. Revisit with budgets in Phase 6.
- `briefs` in the interrupt payload is a snapshot; reloading latest idea versions from
  the DB on resume (SPEC §6) waits for the app tables (Phase 3/4).
- Ideas that fail analysis are retried on a loop-back pass (extra cost, by design).
- `docs/CLAUDE.md` is a tracked copy of the root `CLAUDE.md`; kept in sync manually.
  Consider deleting one.

**Acceptance criteria:** all passed except the real-key CLI run (verified by running commands):
- Unit tests per node with `FakeLLM` + `MockSearchProvider`: `tests/unit/test_{scout,analyst,skeptic}_node.py`, `test_ranking.py`.
- Integration: `pytest -m integration` → `test_interrupt_then_resume_from_a_new_process`
  passes (interrupt → new process `Command(resume=…)` from Postgres → Phase-2 stubs).
- Loop runs exactly once then reports "fewer than 3" honestly:
  `test_quality_loop_runs_exactly_once_then_reports_shortfall_honestly`.
- `SourcedFigure` validation: `test_schemas.py` (every figure path in an analysis).
- CLI offline: `--seed`, `--auto` and `--resume-select` against Postgres. ⚠ Real-key run pending (above).
- `pytest` (61 passed), `pytest -m integration` (2 passed), `mypy --strict` on
  app/scripts/tests/migrations, `ruff check`, `ruff format --check`, `alembic check` all clean.

**Next:** Phase 2 — runs, persistence, worker & streaming.

---

### Phase 0 — Skeleton & infrastructure (2026-10-23)
**Built:**
- `docker-compose.yml`: Postgres 16 + Redis 7 with healthchecks and named volumes.
- Backend (`uv`, Python 3.12, exact pins + `uv.lock`): FastAPI app with lifespan-managed async
  engine and Redis client; `GET /api/health` returns `{"db","redis"}` with `ok`/`error` (503 if
  either fails); pydantic-settings config reading the repo-root `.env`; structlog JSON logging
  (uvicorn and arq routed through it); `DeclarativeBase` with naming conventions; async Alembic
  with empty baseline revision `0001`; arq `WorkerSettings` with a `ping` task;
  `scripts/enqueue_ping.py` smoke check. Empty packages for agents/graph/services/providers/events.
- Tests: unit (health 200/503 via dependency overrides, worker ping), integration (live health,
  `-m integration`, excluded by default). ruff + `mypy --strict` clean on app, tests, scripts, migrations.
- Frontend (pnpm 12.15 via corepack): Next.js 16.4 App Router, TS strict (+ `noUncheckedIndexedAccess`),
  Tailwind 4 (Turbopack loader), shadcn/ui (base-nova; button, card, badge), lucide-react,
  TanStack Query provider, home page health card (loading / ok / degraded / unreachable states),
  `/api/*` rewrite to the backend. ESLint + Prettier, Vitest + Testing Library (3 tests).
- Root `Makefile` wrapping the CLAUDE.md commands; `.env.example`; CLAUDE.md commands updated.

**Deviations from spec (and why):**
- Pinned redis 5.3.1, TypeScript 6.0.3, SQLAlchemy 2.0.55 instead of latest — compatibility (ADR 0001).
- Makefile instead of justfile (`just` not installed).
- `pnpm typecheck` runs `next typegen && tsc --noEmit` — Next 16 generates global route types
  (`LayoutProps`) that `tsc` needs.
- LangGraph not installed yet; it arrives in Phase 1 with the graph.

**ADRs added:** 0001 — version pins and same-origin API proxy.

**Known issues / tech debt:**
- The arq worker exits if Redis drops after startup (arq does not reconnect in its poll loop).
  Needs a supervisor / `restart: unless-stopped` when the worker is containerised (Phase 7), or a
  retry wrapper in Phase 6 hardening.
- arq prints its first two startup lines before our JSON logging is configured, so they are plain text.
- shadcn init wrote a self-referencing `--font-sans`; fixed to `var(--font-geist-sans)`. Re-check
  after future `shadcn init`/theme updates.
- SSE through the Next rewrite proxy is unverified (ADR 0001, Phase 2/3).

**Acceptance criteria:** all passed (verified by running commands):
- `docker compose up -d` → postgres and redis `healthy`.
- `alembic upgrade head` on a fresh volume (`docker compose down -v` first) → `0001 (head)`.
- `curl :8000/api/health` → `{"db":"ok","redis":"ok"}`; same through `:3000/api/health`.
- Worker started; enqueued `ping` → `pong` in the worker log.
- Home page rendered in headless Chrome shows Database ok / Redis ok; with Redis stopped it shows
  `error` and the API returns 503.
- `pytest` (5 passed), `mypy app`, `ruff check`, `pnpm typecheck`, `pnpm lint`, `pnpm test`
  (3 passed), `pnpm build`, `prettier --check` all pass.
- CLAUDE.md commands executed as written.

**Next:** Phase 1 — Phase-1 graph core (offline), `docs/phases/01-phase1-graph-core.md`.

---

## Entry template
### Phase N — <name> (YYYY-MM-DD)
**Built:**
**Deviations from spec (and why):**
**ADRs added:**
**Known issues / tech debt:**
**Acceptance criteria:** all passed / exceptions:
**Next:**

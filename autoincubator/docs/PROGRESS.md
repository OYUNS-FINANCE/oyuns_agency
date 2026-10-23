# Progress log

Claude updates this file at the end of every phase. Newest entries go on top.

## Current phase
Phase 1 — done except the real-Anthropic-key CLI check (see Phase 1 entry); Phase 2 next

## Phase checklist
- [x] 0 — Skeleton & infrastructure
- [x] 1 — Phase-1 graph core (offline) — real-key CLI run pending
- [ ] 2 — Runs, persistence, worker & streaming
- [ ] 3 — Frontend: start screen & live discovery
- [ ] 4 — Co-working checkpoint (HITL)
- [ ] 5 — Phase-2 agents, finance engine & export
- [ ] 6 — Real search, evals, cost & observability
- [ ] 7 — Deployment

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

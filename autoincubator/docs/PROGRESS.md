# Progress log

Claude updates this file at the end of every phase. Newest entries go on top.

## Current phase
Phase 4 — done; Phase 5 (Phase-2 agents, finance engine & export) next.
Still open from Phase 1: the real-Anthropic-key CLI check (now also covers streamed chat).

## Phase checklist
- [x] 0 — Skeleton & infrastructure
- [x] 1 — Phase-1 graph core (offline) — real-key CLI run pending
- [x] 2 — Runs, persistence, worker & streaming
- [x] 3 — Frontend: start screen & live discovery
- [x] 4 — Co-working checkpoint (HITL)
- [ ] 5 — Phase-2 agents, finance engine & export
- [ ] 6 — Real search, evals, cost & observability
- [ ] 7 — Deployment

---

### Phase 4 — Co-working checkpoint, HITL (2026-10-23)
**Built:**
- **ADR 0006:** co-working runs outside the paused graph; versions live in the DB. Select
  resumes with `Command(resume={idea_id, brief})`: the worker loads the latest version, and
  the graph stores it as `selected_brief` (Phase 5 reads that). The CLI's
  `--resume-select` builds the brief from the interrupt snapshot.
- **Migration `0003`:** `cowork_messages` (agent, role, `pending/complete/failed`, content,
  `proposed_patch`, `based_on_version`), `runs.selected_idea_id`, `ideas.merged_from` and
  `ideas.reject_reason`, and `idea_versions.patch` / `message_id` (unique, so a proposal
  applies once).
- **Agent** (`agents/cowork`): Scout, Analyst and Skeptic personas share rules and return
  `{reply, edits}`. Edits are JSON Patch operations whose values travel JSON-encoded, so the
  output schema stays plain. The patch is applied and validated inside the retry loop. The
  brief is wrapped in `<idea_brief>` delimiters and treated as untrusted.
- **Patches** (`services/brief_patch.py`): RFC 6902 `add`/`replace`/`remove`, on
  `/opportunity` and `/analysis` only (ids are read-only, and the critique changes only
  through a re-score). The result must re-validate (`SourcedFigure`, SOM ≤ SAM ≤ TAM), may
  cite only URLs the idea already cites, and must change something.
- **Streaming:** `LLMRequest.on_delta`. Anthropic uses `beta.messages.stream`; `FakeLLM`
  sends its output in chunks. `ReplyStreamReader` pulls the `reply` string out of the
  partial JSON, and a validation retry sends `reset`.
- **API** (`api/cowork.py`), all under `/api/incubator/runs/{run_id}`:
  - Reads: `GET ideas/{id}` (all versions) and `GET ideas/{id}/cowork` (messages).
  - `POST ideas/{id}/cowork`: SSE `started`/`delta`/`reset`/`completed`/`error`.
  - `POST ideas/{id}/versions`: 201, or 200 when the proposal was already applied.
  - `POST ideas/{id}/rescore` and `POST ideas/merge`: 202, run as worker jobs.
  - `POST ideas/{id}/reject`.
  - `POST select`: 202, idempotent.
  - Every mutation row-locks the run, then the idea, and returns 409 `run_not_paused` unless
    the run is `awaiting_human`. The other 409 codes are `idea_not_active`,
    `reply_in_progress`, `patch_conflict` and `budget_exhausted`.
- **Chat:** the user message and a `pending` reply are stored first. The reply is generated
  in a task that isn't bound to the request, so a disconnect or reload still stores it. A
  pending reply older than `COWORK_REPLY_TIMEOUT_S` is reported as failed.
- **Worker jobs** (`worker/cowork.py`):
  - `rescore_idea`: the Skeptic scores the latest version, and a `rescore` version is written.
    It is dropped if the idea changed meanwhile.
  - `merge_ideas`: Scout synthesis (signals only from the source ideas), then Analyst (with
    searches) and Skeptic, then a `merge` idea `mrg-NN` with `merged_from`.
  - Both stream `agent.*` and `idea.*` events, re-check `awaiting_human` under the run lock
    before writing, and recompute ranks in Python.
  - `start_run` resumes a selected run. Crash recovery covers the resume as well.
- **Reject:** `"<title>: <reason>"` is appended to `founder_profile.rejected_idea_reasons`
  (newest `REJECTED_REASONS_MAX`). Mode B snapshots it into the Scout context.
- **Budget:** co-working calls are charged to the run budget through the shared
  `services/run_deps.py`.
- **Events:** `idea.updated` gains `status` and `source`; `agent.started` and
  `agent.completed` gain an optional `idea_id`. The chat-stream payloads are published in
  `openapi.json`.
- **Frontend:**
  - **Drawer** (base-ui Dialog as a side sheet; Tabs, AlertDialog, Checkbox): Chat (agent
    picker, streamed reply, "Apply change"), Versions (side-by-side field diff with
    word-level highlights) and Scorecard (rubric with justifications, every figure with its
    source or assumption, signals).
  - **Drawer state** lives in the URL (`?idea&tab&agent`), and the content is re-read from
    the server.
  - **Cards:** a Co-work button and badges (score out of date, re-scoring, rejected,
    selected, hybrid).
  - **Merge:** a selection mode with a confirm dialog.
  - **Develop Full Business Plan:** asks for confirmation; double clicks send one request.
  - **In-flight state:** re-score and merge progress is derived from the event log, so it
    survives a reload.
- **Tests:**
  - Backend: 120 unit (was 93) and 21 integration (was 12). New coverage: patch rules,
    stream reader, chat retry/reset, Anthropic streaming, in-process double select racing
    resume and recovery jobs, edited brief reaching the graph, reject → Mode B Scout prompt,
    409s, budget, and a live HTTP suite.
  - Frontend: 65 Vitest tests (was 49).

**Deviations from spec (and why):**
- **Resume reads the latest version in the worker, not in the graph** (revises SPEC §6).
  The graph then never touches application tables, and its replayed resume value is stable.
- **Resume payload:** `{idea_id, brief}` (DB UUID plus the full brief), not
  `{"idea_id": key}`.
- **Chat runs in the API process**, which is allowed because it isn't a graph. Re-score and
  merge run in the worker, as the phase file asks for merge.
- **Merge keeps the sources** active and selectable (agreed in the plan).
- **Re-score and merge jobs aren't retried** (`max_tries=1`): a partial retry would pay
  twice. A double-clicked merge creates two hybrids. The UI prevents it, but the API doesn't.
- **Chat has no search tool.** That's why patches may only cite existing sources (ADR 0006).

**ADRs added:** 0006 — co-working outside the paused graph; DB versions; resume with the
selected brief.

**Known issues / tech debt:**
- **One reply task per API process.** A reply in flight when the API stops shows as failed
  once `COWORK_REPLY_TIMEOUT_S` has passed, not immediately.
- **Lost co-working jobs:** a re-score or merge whose worker dies leaves no result. The UI
  stops showing "working" after 20 minutes.
- **Recovery notice:** after a select, the recovery sweep can occasionally claim the run
  before the `resume:` job does. It then emits the "Recovered…" notice. That's cosmetic;
  the run still resumes once.
- **Chat history** sent to the model is capped at 40 messages.
- **E2E script still outside the repo:** the Phase-4 Playwright-core script lives in the
  session scratchpad, like Phase 3's. This belongs in Phase 6.
- **Test data in the dev DB:** more test runs from verification, and the dev profile now
  holds e2e rejection reasons (clear them in `/settings/profile`).

**Acceptance criteria:** all passed (verified by running commands):
- **Setup:** a Playwright-core script drove headless Chrome against the real stack (uvicorn
  + arq worker with `FAKE_LLM_LATENCY_MS=150`, `pnpm dev`): **18/18 checks** on the final
  run.
- **Chat → apply patch → v2 with a diff → re-score updates the card:**
  - E2E: partial reply text appears before completion, "Applied as v2", the stale badge
    shows, and the Versions diff shows the edited one-liner. After re-score the card shows
    v3 with the new score and no stale badge.
  - `test_chat_apply_patch_then_rescore_updates_the_card` (live HTTP) covers the same flow.
- **Merge creates a new scored idea, streamed live:**
  - E2E: the "Merging ideas…" banner, then a "Hybrid of 2" card with a score.
  - `test_merge_creates_a_new_scored_idea_streamed_live`: `agent.started` (scout), Analyst
    tool calls, `idea.created` `mrg-01`, 7 rubric scores, and ranks re-computed.
- **Rejected reasons reach the next Mode B Scout context:**
  `test_rejected_reasons_reach_the_next_mode_b_scout` checks reject → profile → Mode B
  `RunInput` → the `scout.plan` prompt. E2E: the reason is in the profile.
- **Double-clicking Select resumes exactly once:**
  - `test_double_select_resumes_exactly_once`: 5 concurrent selects give one resume; the
    resume and recovery jobs race, outcomes `[completed, skipped]`; one `run.resumed`; the
    graph's `selected_brief` and Phase-2 stubs are done.
  - Live HTTP: 4 parallel POSTs give one `run.resumed`.
  - Vitest and e2e `dblclick`: one POST.
- **Co-working on a non-paused run returns 409:** the service test (running run) and the
  live test (queued and completed runs, all 6 endpoints → `run_not_paused`); e2e on a
  completed run.
- **Reloading mid-co-working restores the drawer from the server:**
  - E2E: a reload reopens the same idea and the Versions tab with its diff.
  - A reload while a reply is streaming keeps the agent choice, and the reply completes and
    shows.
  - Vitest restores from the URL.
- **At 375 px:** no horizontal overflow with the drawer open. The screenshots were
  reviewed, and the close-button overlap and positional diff labels they showed were fixed.
  There were no console errors.
- **Checks:** `pytest` (120), `pytest -m integration` (21), `mypy --strict`, `ruff check`,
  `ruff format --check`, `alembic check` (0003 round-trips), the OpenAPI drift test, and the
  CLI `--auto` / `--resume-select` all pass. So do `pnpm typecheck`, `lint`, `test` (65),
  `format:check` and `build`.

**Next:** Phase 5 — Phase-2 agents, finance engine & export
(`docs/phases/05-phase2-business-plan.md`). Agents read `selected_brief` from the state.

---

### Phase 3 — Frontend: start screen & live discovery (2026-10-23)
**Built:**
- **API types and client:**
  - `openapi-typescript` 7.13.0 generates `src/lib/api/schema.d.ts` from `backend/openapi.json`
    (`pnpm gen:api`); a Vitest test fails when the file is stale.
  - `src/lib/api/client.ts` is a thin fetch wrapper with an `ApiError {status, code, message,
    details}` that reads the backend error shape; `describeError` lists 422 field errors.
  - Query hooks and keys live in `src/lib/api/queries.ts`.
- **`useRunStream(runId)`** (`src/lib/sse/`; ADR 0005): `fetch` + streamed body + our own SSE
  parser, not `EventSource`.
  - Sends a real `Last-Event-ID` header on every connect.
  - Backoff: 0.5 s doubling to a 15 s cap, with jitter.
  - Statuses: `connecting | live | reconnecting | closed | error`. A 404 stops the stream;
    a 5xx or network error retries.
  - Cache: `["runs","events",id]` dedups by id; `["runs","detail",id]` is patched in place,
    then refetched (debounced) on idea or lifecycle events and after every reconnect.
  - Resumes from the cached cursor when remounted, including when Next shows a hidden
    `<Activity>` page again.
- **Routes:**
  - `/`: mode cards, seed with counter, collapsible constraints, "Discover & Incubate", and
    recent runs.
  - `/runs`: paged history with status badges.
  - `/runs/[runId]`, header: status badge, connection indicator, budget meter (tokens,
    searches, cost; the detail is polled every 5 s while the run is working).
  - `/runs/[runId]`, banners: reconnecting, stream error, budget warning, budget exhausted,
    failed, awaiting review/shortfall.
  - `/runs/[runId]`, body: the activity panel and the ranked cards side by side; below `lg`,
    Activity/Ideas tabs that switch to Ideas once ideas exist.
  - `/settings/profile`: founder profile form (chip inputs, risk segmented control, validation).
- **Activity panel:** one collapsible pass per `agent.started` (agent hue, pass number, ideas,
  search count, duration, summary). Tool calls show the query, idea key and result count;
  notes (`agent.thought`) can be toggled. Run markers (status, interrupt, error, budget) appear
  between passes. It follows new events while you are scrolled to the bottom.
- **Idea card:** rank, title, one-liner, composite score, 7-bar rubric (fixed order, coloured
  by score), most likely failure, distinct source count. An expandable "Market" section shows
  TAM/SAM/SOM (linked to the source, or marked `*` with the assumption as a tooltip), the
  analysis summary and the attack summary. A placeholder card (from `idea.created`) shows
  until the refetch lands.
- **States:** loading skeletons, empty (no runs; no ranked ideas, with the shortfall), error
  with retry, not found, reconnecting, stream error, budget exhausted, failed.
- **Look:** warm paper and ink palette, one teal signal colour, muted per-agent hues,
  Instrument Serif for titles, Geist Mono for numbers and queries. Dark tokens are kept. A
  header health dot replaces the Phase-0 health card.
- **Tests:** 49 Vitest tests (was 3):
  - SSE parser
  - stream loop: backoff, `Last-Event-ID`, 404, malformed data, clean close
  - `useRunStream` hook: replay dedup across reconnects, reconnecting → live, detail
    patch/refetch, resume on remount, 404, disabled
  - reducers, timeline grouping, idea card / source count, start form, run view states,
    profile mapping, OpenAPI drift

**Deviations from spec (and why):**
- **Backend change:** the SSE response now sends `Cache-Control: no-cache, no-transform` (via
  a route dependency, so it lands before the streaming body runs).
  - Why: the Next server gzips proxied responses for browsers (`Accept-Encoding`), and that
    buffered the whole stream until the run ended. Phase 2 verified the proxy with curl, which
    sends no `Accept-Encoding`, so ADR 0001's "streams incrementally" was only true for curl.
    `no-transform` is honoured by Next's `compression`, nginx and CDNs.
  - The live integration tests now assert it on every stream. The API contract
    (`openapi.json`) is unchanged.
- **Hydration timing:** the run page's params resolve on the client (`use(params)` behind
  `Suspense`), as `cacheComponents` requires for request-time params. The nav's `usePathname`
  likewise has a static Suspense fallback.
- **Budget form:** per-run budget caps are not in the start form (agreed in the plan); runs
  use the server limits.
- **Co-working ADR:** the SPEC §6 note about confirming the co-working state model "in
  Phase 3" is deferred to the start of Phase 4 (agreed).
- **Generated types:** openapi-typescript's `defaultNonNullable` makes fields with defaults
  required in the generated types (e.g. `RunConstraints.business_model`). The forms always
  send complete bodies, so this only affects test fixtures.

**ADRs added:** 0005 — client SSE transport (fetch + Last-Event-ID + backoff) and the event →
Query cache mapping.

**Known issues / tech debt:**
- **E2E harness not committed:** the end-to-end verification script (Playwright-core driving
  installed Chrome) lives outside the repo. Adding Playwright as a dev dependency with a CI
  job fits Phase 6.
- **Activity panel scale:** it renders every event without virtualisation. That's fine for
  runs of ~50–100 events; revisit if real runs produce thousands.
- **Budget polling:** budget counters move through 5 s polling of `GET /runs/{id}`, not
  events. A `budget.usage` event would remove the polling.
- **Agent re-runs after a crash:** re-run steps re-emit `agent.*` events (Phase 2 known
  issue); the panel shows them as an extra pass.
- **Test data in the dev DB:** verification left ~200 test runs there (all `awaiting_human`).
- `src/components/ui/card.tsx` and `badge.tsx` (Phase 0) are no longer used.

**Acceptance criteria:** all passed (verified by running commands):
- **Setup:** the real stack (uvicorn + arq worker with `FAKE_LLM_LATENCY_MS=700`, `pnpm dev`
  on :3000) driven in headless Chrome by a Playwright script. The final two runs passed
  20/20 checks; earlier runs failed only the console-error check (explained below).
- **Mode A and Mode B from the UI render live to the ranked cards:** both reach 5 cards, and
  the UI event log equals a fresh server replay (51 and 57 events, same last id).
- **Kill and restart the API mid-run:** `pkill -9` uvicorn → the UI shows "Reconnecting" and
  the "Connection lost — reconnecting…" banner. After a restart 6 s later it goes live,
  catches up, and the UI log equals a server replay (51 = 51, no duplicates).
- **Hard reload during and after a run:**
  - During: activity is restored and keeps streaming.
  - After: the same 5 cards, and the event log equals a server replay.
- **Usable at 375 px:** home (constraints open), runs, profile, and the run page (Ideas and
  Activity tabs) all have `scrollWidth == clientWidth == 375`. Screenshots were reviewed and
  the layout fixed (history wrapping, budget meter).
- **No console errors before the deliberate outage.** An earlier hydration warning came from
  Playwright's own caret-hiding screenshot style, not the app.
- **Checks:** `pnpm typecheck`, `lint`, `test` (49 passed, hook tests included),
  `format:check` and `build` are green. Backend: `pytest` (93), `pytest -m integration` (12),
  `mypy --strict`, `ruff check` and `ruff format --check` pass; `openapi.json` is unchanged.

**Next:** Phase 4 — co-working checkpoint (`docs/phases/04-cowork-hitl.md`). Start with the
ADR on the co-working state model (SPEC §6).

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

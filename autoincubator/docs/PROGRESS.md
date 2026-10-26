# Progress log

Claude updates this file at the end of every phase. Newest entries go on top.

## Current phase
Phase 6 — code complete and verified offline; **not done**: the real runs and the grounding
and quality evals are waiting for API keys (none in `.env` or the environment). Commands to
finish it are under Phase 6 → "To finish". Still open from Phase 1: the real-Anthropic-key
CLI check, which the Phase 6 real runs cover.

## Phase checklist
- [x] 0 — Skeleton & infrastructure
- [x] 1 — Phase-1 graph core (offline) — real-key CLI run pending
- [x] 2 — Runs, persistence, worker & streaming
- [x] 3 — Frontend: start screen & live discovery
- [x] 4 — Co-working checkpoint (HITL)
- [x] 5 — Phase-2 agents, finance engine & export
- [ ] 6 — Real search, evals, cost & observability — code done; real runs + evals pending keys
- [ ] 7 — Deployment

---

### Phase 7 — Deployment (2026-10-26)
**Built:**
- Dockerfiles (multi-stage): `backend/` (one image for API, worker and migrations; Pango for
  PDF export; non-root) and `frontend/` (Next standalone). `deploy/backup.Dockerfile`.
- `docker-compose.prod.yml` for a Dokploy Compose service: postgres, redis (AOF), one-shot
  `migrate`, api, worker, frontend, nightly `backup`. Traefik labels route `/api` to the API,
  the rest to the frontend, with basic auth on both. `.env.production.example`.
- Backups: `pg_dump -Fc` nightly, 14 days, optional off-box copy via rclone;
  `restore-test.sh` restores into a scratch DB.
- Optional Sentry in API and worker (`SENTRY_DSN`).
- `.github/workflows/ci.yml` (repo root): backend lint/types/unit+integration tests, frontend
  lint/types/format/tests/build, image builds, then a Dokploy deploy call on main.
- `docs/RUNBOOK.md`: deploy, rollback, restore, key rotation. ADR 0009.

**Deviations from spec (and why):**
- Auth is Traefik basic auth, not magic links (no code, single user; ADR 0009).
- The ADR was written and accepted without a separate sign-off round: the target (Dokploy on a
  VPS) was already chosen. Monthly costs are rough, not re-verified.

**ADRs added:** 0009.

**Known issues / tech debt:**
- Not yet exercised on a real Dokploy/VPS: Traefik label names, `compose.deploy` API call,
  Let's Encrypt, `TRUSTED_PROXY_HOPS=1`. Real Anthropic/search runs and the evals are still
  pending keys (Phase 6).
- Backups are on the same box unless `RCLONE_REMOTE` is set.
- No uptime monitor is provisioned; point an external check at `/api/health` (needs basic auth).

**Acceptance criteria:**
- Verified locally with the production compose (fake LLM, Traefik absent): all services
  healthy, migrations applied, a run reaches `awaiting_human`, SSE streams directly and via the
  Next proxy, `Last-Event-ID` replay resumes at the next event, PDF renders in the image,
  worker survives a Redis restart, backup → restore into a scratch DB succeeds.
- Pending a real VPS: "fresh deploy from main", "full run on the public URL".

**Next:** deploy to the VPS following `docs/RUNBOOK.md`, tick the two pending criteria, then run
the Phase 6 evals with real keys.

---

### Phase 6 — Real search, evals, cost & observability (2026-10-24)
**Built:**
- **Search** (`providers/search/`, ADR 0008):
  - `TavilySearch` (default for real runs) and `SerperSearch` behind `SEARCH_PROVIDER`. A
    missing key fails at start-up with the variable's name.
  - The shared HTTP base:
    - retries timeouts, connection errors and 408/425/429/5xx with jittered backoff,
      honouring `Retry-After`;
    - a token bucket and one pooled client per provider, per process.
  - A cross-run Postgres cache (`search_result_cache`, migration 0005, TTL
    `SEARCH_CACHE_TTL_S`). It sits under the per-run cache and its budget hooks.
- **Injection hygiene** (`sanitize.py`):
  - Strips markup, control and invisible characters (zero-width, bidi, tag block).
  - Redacts instruction-like sentences with a visible marker and logs each one.
  - **Drops results that are nothing but instructions.**
  - Caps lengths. It runs before the `<untrusted_web_content>` wrapping.
- **Models and cost:**
  - Per-agent defaults: Haiku for the Scout; Sonnet for the Analyst and the Phase-2
    builders; Opus for the Skeptic and Editor.
  - Anthropic prompt caching on the system prompts (`LLM_PROMPT_CACHING`).
  - Cost per agent and model on the run detail, and a "Cost breakdown" disclosure on the run
    page. It shows model, calls, tokens, cached tokens and cost per agent, plus a daily-spend
    meter.
  - **Global daily cap** `DAILY_COST_CAP_USD`: new runs are refused (429
    `daily_cap_reached`), and a running run stops at its next LLM call as
    `budget_exhausted` with kind `daily_cost` (amounts in cents on the event).
- **Rate limits:**
  - Redis fixed windows per client: run creation per hour, LLM-starting endpoints per
    minute, the rest per minute. SSE and health are exempt.
  - `TRUSTED_PROXY_HOPS` reads the real client IP behind Traefik. A Redis outage fails open.
- **Observability:**
  - OpenTelemetry over OTLP/HTTP, off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. **A run's
    trace id is its UUID.**
  - Every request on a run, the enqueue in `POST /runs`, and both worker jobs are roots in
    that trace. Nodes, LLM attempts and searches nest under the jobs.
  - structlog lines carry `run_id`, `node`, `request_id` and the trace/span ids.
  - A local Jaeger runs under a compose profile: `docker compose --profile tracing up -d
    jaeger`.
- **Evals** (`backend/tests/evals/`, manual, not in CI; `make evals-collect`, `make evals`):
  - `collect`: runs Phase 1 in-process for 10 fixed seeds (`seeds.json`) plus 3 autonomous
    runs, under `--max-cost`. It saves each checkpoint, cost per agent and search count to
    `evals/results/runs/<stamp>/`. It refuses the fakes unless `--allow-offline` is passed.
  - `grounding`: samples sourced figures (TAM/SAM/SOM, competitor and benchmark prices,
    segment sizes; default 40, seeded) and fetches each page.
    - Unreadable pages count as failures with their cause: `dead_link`, `blocked`,
      `timeout`, `http_error`, `unreadable` (PDFs among them).
    - A judge (Sonnet by default) returns supported, partial or unsupported, plus a cause
      (`wrong_number`, `different_metric`, `derived`, `not_on_page`).
    - It must quote the page verbatim, or the answer is rejected and retried.
    - Headline: supported / sampled. Also reported: supported / readable.
  - `quality`: Opus grades the top 3 briefs per run, 1–5 against anchored rubrics.
    - Dimensions: specificity, evidence, solo-founder fit, differentiation, risk honesty.
    - Plus "worth a week of validation?", means by mode, and the correlation with the
      pipeline's own composite score.
  - `diversity`: local embeddings (fastembed, bge-small; `uv sync --group evals`) of the
    Mode B ideas. It reports the mean cosine distance within and across runs, and
    near-duplicates across runs.
  - Every result file records git SHA, prompt version, judge model, providers and an
    `offline` flag, and appends to `evals/results/history.jsonl`.

**Deviations from spec (and why):**
- **One ADR (0008) instead of two.** Search, cost, rate limits and tracing share one
  context (deploying on a single VPS) and are cross-referenced from the code as 0008.
- **Tracing links processes by trace id, not by propagated context.** Context propagation
  breaks across the checkpoint pause and worker recovery. The `POST /runs` HTTP span stays
  in its own trace; the enqueue span in the run's trace records its id.
- **Evals run the graph in-process** (in-memory checkpointer), not through the API, so they
  don't need the stack. That means they bypass the DB daily cap, so `collect` has its own
  `--max-cost` (default $30).
- **Injection test:** the acceptance check runs offline on `FakeLLM` (see below). With a real
  model, the same page is redacted before any prompt sees it, so the model never receives
  the instructions. A behavioural test against a real model was not run.

**ADRs added:** 0008 — real search chain, sanitising, per-agent models and prompt caching,
daily cap, rate limits, OpenTelemetry with run-id trace ids.

**Known issues / tech debt:**
- **No real-key run yet.** Every prompt, the Haiku Scout's extraction quality, the Phase-2
  number rule and prompt-cache hit rates are unproven against real models and real search.
- **Injection detection is heuristic** (regexes). Novel phrasings get through to the
  delimited block, where only the prompt rules defend. Redactions are logged
  (`search.injection_suspected` / `search.injection_dropped`) for auditing.
- **Found while writing the injection test:** a result whose title and snippet were wholly
  redacted still reached the prompt with its URL, and the offline Scout built opportunity
  `opp-07` citing `spam.example`. Such results are now dropped.
- **Grounding can't read PDFs.** Market reports are often PDFs, so they count as
  `unreadable` failures. That depresses the headline number honestly rather than skipping
  them. A PDF text extractor is the obvious next step if this dominates.
- **Fixed-window rate limits** allow up to 2× the limit across a window edge. That's fine
  for one user; revisit with auth.
- **The daily cap can overshoot** by at most one in-flight call per concurrent agent
  (`AGENT_CONCURRENCY`).
- **Diversity downloads** a ~70 MB embedding model from Hugging Face on first use.
- **Still outside the repo:** the e2e browser script from Phases 3–5 (it lives in the
  session scratchpad). Carried to Phase 7.

**Acceptance criteria:**
- [ ] **3 real Mode A + 2 real Mode B runs end-to-end, cost per run reported** — *pending
  keys*. Cost per run is reported by `collect` (per run and per agent) and on the run page.
  Offline: `collect --allow-offline` ran 2 Mode A + 2 Mode B runs to the checkpoint, and
  `test_full_run_with_fakes_completes_with_a_traceable_exported_plan` covers completion.
- [ ] **Grounding ≥ 80% supported, failures listed with causes** — *pending keys*. The
  harness is built and unit-tested (`tests/unit/test_evals.py`): fetch classification,
  excerpting long pages around the number, the verbatim-quote rule, and unreadable pages
  counted as failures.
- [x] **The prompt-injection page in mock search doesn't change agent behaviour** —
  `tests/unit/test_injection_run.py`.
  - Whole offline runs in both modes retrieve the page; no prompt contains its URL or its
    phrases.
  - The briefs (titles, scores, cited sources) are identical to the same runs with that one
    result removed.
  - Plus the sanitiser unit tests in `test_search_sanitize.py`.
- [x] **One trace shows a full run across API → worker → nodes.** Verified in Jaeger 2.20
  with the API and worker on the fakes and `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`.
  - Run `903842aa-46f2-4a0c-a516-edf91051e08c` (Mode B, selected, completed): trace
    `903842aa46f24a0ca516edf91051e08c`, 102 spans, services `autoincubator-api` and
    `autoincubator-worker`.
  - Roots: `api.enqueue_run` → `worker.start_run` (Phase 1) → the `HTTP POST …/select` →
    `worker.start_run` (Phase 2), plus the run's `HTTP GET`s.
  - Every `node.*` sits under its job and every `llm.call` under its node.
- [ ] **PROGRESS.md has the eval results and a cost table** — *pending keys*. No numbers are
  given here, because none were measured.
- Checks: backend 262 unit + 27 integration tests pass; `mypy --strict` and ruff are clean.
  Frontend typecheck, lint and 79 tests pass.

**To finish (needs `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`):**
```
# .env: LLM_PROVIDER=anthropic SEARCH_PROVIDER=tavily + the two keys
make evals-collect ARGS="--max-cost 30"            # 10 Mode A + 3 Mode B (covers 3 A + 2 B)
make evals                                         # grounding, quality, diversity
make api; make worker; make web                    # separate terminals
```
In the UI, start 3 Mode A + 2 Mode B runs and select an idea on each, so that Phase 2
completes. Cost per run is on each run page.
Then fill in here: the grounding % with its failure table, the quality means, the diversity
numbers, and a cost table (run, mode, cost, tokens, searches).

**Next:** finish the real runs above, then Phase 7 — deployment (Dokploy on a VPS:
`TRUSTED_PROXY_HOPS=1`, Pango in the image, an OTLP endpoint or tracing off).

---

### Phase 5 — Phase-2 agents, finance engine & dossier export (2026-10-23)
**Built:**
- **Finance engine** (`services/finance.py`, pure Python):
  - The `AssumptionSet` (`agents/financial_modeler/schemas.py`) holds the inputs: price tiers
    and mix, paid channels (CAC, spend), organic signups and growth, free→paid, churn, the
    payment fee, variable and fixed costs, starting cash, and the launch month. Every input is
    a `SourcedFigure`, and the ranges are validated.
  - The engine computes ARPA, gross margin, blended CAC, LTV, LTV:CAC and payback, plus a
    12-month table (signups, new customers, customers, MRR, COGS, gross profit, opex, net cash
    flow, cash). It also finds the break-even month, the cash-out month and the runway after
    month 12.
  - Scenarios: base, plus fixed bear/bull multipliers (`SCENARIOS`).
  - The formulas are written out in the module docstring. Each output declares its
    `DEPENDENCIES` and `FORMULAS`; the appendix and the UI show both.
- **Agents:**
  - `product_architect`, `gtm_strategist` and `financial_modeler` fan out from the
    checkpoint; the `editor` fans in. Each has a versioned prompt, Pydantic I/O, and per-agent
    model settings (`*_MODEL`).
  - They read `selected_brief`, wrapped in `<idea_brief>` as untrusted data.
  - They don't search: a `source_url` must be one the brief cites, and everything else is an
    assumption.
  - The Financial Modeler's validator runs the engine, so a degenerate `AssumptionSet` (no
    revenue, no margin) is fed back to the model.
- **Number tracing** (`services/trace.py`, `services/plan_trace.py`):
  - A figure registry holds every source, assumption, estimate, engine output and score.
  - A scanner checks the numbers in prose by value, at the precision they're written in.
  - It runs in every agent's retry loop, on the brief (`untraced_number`), and on the final
    Markdown.
- **Editor checks** (`services/plan_checks.py`):
  - GTM channels vs Finance channels: one-to-one, with CAC equal to the cent.
  - The "now" features vs the build estimate, within ±20%.
  - The launch month vs calendar build weeks (build weeks × 40 / founder weekly hours).
  - Untraced numbers in the brief.
  - The Editor LLM adds qualitative contradictions, the executive summary, risks and the
    30/60/90 checklist. It can't change numbers.
  - Contradictions are listed in the plan and the dossier, never hidden.
- **Persistence and API:**
  - Migration `0004` adds `business_plans` (plan JSONB, Markdown, version; unique per
    run/version).
  - The worker writes v1 and `run.completed {plan_version}`, then moves the status, in one
    transaction.
  - `GET /runs/{id}/plan` returns the plan plus the engine formulas.
    `GET /runs/{id}/plan/export?format=md|pdf` returns an attachment. Both return 404
    `plan_not_found` until the run completes.
- **Export** (`services/export/`):
  - A Jinja Markdown dossier: summary, opportunity, product, GTM, financials (three
    12-month tables), contradictions, risks, the 30/60/90 checklist, and an appendix with
    sources, assumptions, scenario definitions and engine formulas.
  - The PDF goes Markdown → HTML (markdown-it, raw HTML off) → WeasyPrint 70 with print CSS
    (page breaks, repeated table headers, page counters) and bundled Noto Sans (OFL).
  - The URL fetcher serves only the font files.
  - A missing Pango gives `503 pdf_unavailable`.
- **Frontend** `/runs/[runId]/plan`:
  - Sticky section navigation with the active section highlighted; a select below `lg`.
  - A base/bear/bull toggle drives the KPI tiles, the 12-month table, and two inline-SVG
    charts (MRR, cash).
    - The scenario palette passed the dataviz validator in both themes.
    - The charts have a legend, direct end labels, and a crosshair readout on hover or
      keyboard.
  - Contradiction callouts inline in their sections and in a full list. Appendix tables and
    export links.
  - States: loading, not ready (by run status), not found and error.
  - The run page links completed runs to the plan. The activity panel has labels and hues
    for the Phase-2 agents.
- **Tests:**
  - Backend: 188 unit (was 120) and 23 integration (was 21). New coverage:
    - the finance reference case, scenarios, edge cases and the perturbation test
    - the trace scanner
    - each Phase-2 agent's retry paths
    - the Editor checks
    - Markdown safety, number traceability, PDF fonts and fetch blocking
    - a live select → completed → export run over HTTP
  - Frontend: 77 Vitest tests (was 65).

**Deviations from spec (and why):**
- **Shared channel vocabulary** (`ChannelType`). GTM and Finance run in parallel, so free-text
  channel names would rarely match and the CAC check would be noise.
- **The proposed fourth check ("solo feasibility")** is folded into launch timing via the
  founder's weekly hours.
- **Agents may restate numbers that appear in the brief's text.** Whether such a number is
  sourced is reported once, by the Editor's `untraced_number` check. Bare years (1900–2099)
  count as dates. This was found in the live test: a "$12M" headline made every Phase-2 agent
  fail.
- **An extra endpoint:** `GET /runs/{id}/plan` (structured JSON for the UI), next to the
  export.
- **The plan is persisted by the worker at completion**, not by the Editor node. The graph
  stays DB-free (ADR 0006).

**ADRs added:** 0007 — plan assembled in the graph and persisted at completion, number
traceability, PDF via WeasyPrint.

**Known issues / tech debt:**
- **Not run with a real model.** The Phase-2 prompts and output schemas (notably
  `AssumptionSet` and the number rule) need the pending real-key run. Real models estimating
  CAC in parallel will often produce `channel_cac_mismatch` contradictions. That's by design,
  but worth watching.
- **A Phase-2 section that never validates fails the run** (`run_failed`). There's no
  "retry Phase 2" action; the checkpoint keeps the completed sections.
- **Only plan v1 is written.** There's no regenerate or edit flow.
- **Scanner limits:** a number that coincides with some registered figure passes, and so does
  a bare four-digit count in the year range.
- **Pango:**
  - On macOS: `brew install pango`, and run the API, the worker and pytest with
    `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`. The make targets set it inline because SIP
    strips `DYLD_*` from `/bin/sh`.
  - PDF tests skip on macOS without it.
  - The Phase-7 image must install Pango.
- **Cyrillic in the web UI:** Geist and Instrument Serif are loaded with the `latin` subset,
  so Cyrillic titles fall back to system fonts. The PDF uses Noto Sans. Traditional Mongolian
  script isn't covered by either.
- **Offline fixtures:** the fake Scout's `industry` is the headline's first word ("funding:"),
  which is cosmetic. Its signal evidence now includes the headline.
- **The e2e script is still outside the repo**, in the session scratchpad, as in Phases 3–4.
  This belongs in Phase 6.

**Acceptance criteria:** all passed (verified by running commands):
- **Finance engine vs a hand-calculated reference case:** `tests/unit/test_finance.py`.
  - Unit economics and months 1–3 match by hand.
  - Month 12 matches an independent closed form.
  - Bear/bull multipliers, the fraction cap, cash-out and runway are covered.
- **Changing one assumption updates every dependent number:**
  `test_changing_one_assumption_updates_exactly_its_dependents`, parametrised over all 13
  input groups.
  - The declared dependents change and nothing else does; the dependency map is checked to be
    complete.
  - Plus a churn walk-through, and a dossier-level change of starting cash.
- **The full run with fakes reaches `completed` with a plan:**
  - `test_full_run_with_fakes_completes_with_a_traceable_exported_plan` (live uvicorn + arq):
    the four `agent.started` events, with the Editor last; `run.completed {plan_version: 1}`;
    `GET /plan`; MD and PDF exports.
  - The CLI `--auto` then `--resume-select` prints the plan.
  - Reading the checkpoint back in another process under strict msgpack returns a typed
    `BusinessPlan`.
- **Every number in the dossier traces (automated check):**
  `test_every_number_in_the_dossier_traces_to_a_source_assumption_or_engine`. It finds zero
  untraced numbers across about 100 money figures, and an injected "$987,654" is caught.
  - Unsourced brief numbers are disclosed rather than hidden
    (`test_untraced_brief_numbers_are_disclosed_in_the_dossier`).
  - The live test runs the same check on the HTTP export.
- **The PDF renders correctly:** rasterised with poppler and reviewed page by page.
  - 12 A4 pages: the summary on the cover, then one section per page, with repeated table
    headers and page counters.
  - Cyrillic/Mongolian titles and text (Ш, Ө, Ү) render.
  - Only Noto Sans is embedded (`pdffonts`). A wrapped "Section" column and a DejaVu fallback
    for "≥" were found and fixed.
  - The PDF exported from the real HTTP run checks out the same way.
- **Browser check:** Playwright-core with headless Chrome against the real stack (worker at
  `FAKE_LLM_LATENCY_MS=150`, `pnpm dev`): **15/15**.
  - The plan page before the run completes.
  - Phase-2 agents live in the activity panel, then "View business plan".
  - All nine sections render.
  - The scenario toggle, with the bear table equal to the engine's numbers.
  - The chart readout lists all three scenarios.
  - PDF and MD downloads.
  - 375 px: no overflow, and the section select jumps to the section.
  - No console errors.
  - Desktop, mobile and dark-mode screenshots were reviewed.
- **Checks:**
  - Backend: `make check-backend` (pytest 188, `mypy --strict`, ruff), `make test-integration`
    (23), `ruff format --check`, `alembic check` (0004 round-trips), and the OpenAPI drift
    test.
  - Frontend: `make check-frontend` (typecheck, lint, 77 tests), `format:check` and `build`.

**Next:** Phase 6 — real search, evals, cost & observability
(`docs/phases/06-hardening-real-search.md`). Real search would let the Phase-2 agents cite
benchmarks.

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

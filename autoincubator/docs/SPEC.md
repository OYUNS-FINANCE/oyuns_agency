# AutoIncubator — Product & Technical Spec

This file describes *what* we are building. It changes rarely. *How* and *when* are in `docs/phases/`.

## 1. Product
AutoIncubator is an AI venture studio that discovers, stress-tests and develops business ideas **together with** a human founder. It is not a one-shot report generator. Its core value is the **co-working checkpoint**, where the founder interrogates, reshapes, merges or kills ideas before the system invests effort in a full plan.

### Design priorities (in order)
1. **Trustworthy output.** Every market number is sourced, or labeled as an estimate with stated assumptions.
2. **Resumability.** A run can pause for days, survive restarts and resume exactly where it stopped.
3. **Transparency.** The founder watches agents work live and sees why each score was given.
4. **Cost control.** Each run has a token/search budget and stops gracefully when it is exhausted.
5. **Separation of concerns.** Agents, orchestration, persistence, transport and UI are independently testable.

## 2. Input modes
- **Mode A — Directed.** A seed (topic, niche, trend or pain point) plus optional constraints: region, budget ceiling, B2B/B2C, solo-founder feasibility, excluded industries.
- **Mode B — Autonomous ("Discover & Incubate").** No prompt. The system mines current signals itself and respects the saved founder profile (skills, region, capital, risk tolerance).

## 3. Phase 1 — Ideation & stress-testing
| # | Agent | Job | Output |
|---|---|---|---|
| 1 | Trend Scout | 8–12 raw candidates, deduplicated and diverse | `RawOpportunity[]` with signal sources + URLs |
| 2 | Market Analyst | TAM/SAM/SOM (with method), competitors, pricing benchmarks, segments | `MarketAnalysis` per idea; each figure has `source_url` or `assumption` |
| 3 | Devil's Advocate | Attacks each idea on a fixed rubric; names the single most likely cause of failure | `CritiqueScorecard` per idea |

**Skeptic rubric** (each scored 1–10 with a one-sentence justification): CAC risk, platform/channel dependency, churn risk, defensibility, regulatory risk, time-to-first-revenue, solo-founder feasibility. The composite score uses configurable weights.

**Output:** 3–5 ranked, differentiated briefs. If fewer than 3 pass the quality threshold, loop back to the Scout once (max-iteration guard). If still fewer than 3, report that honestly rather than padding the list.

### Autonomous signal mining (Mode B)
Signal categories: rising search queries, recent funding rounds, new regulations, complaint threads (forums, review sites, app stores), job postings that reveal manual work, marketplace gaps.

Queries are generated per category and diversified across industries. Results are deduplicated (semantic similarity) and filtered for novelty and feasibility. Generic ideas ("AI chatbot for X") are rejected by an explicit high-signal score.

## 4. Checkpoint — co-working (HITL)
The graph pauses via `interrupt()`. The founder can:
- **Chat** with a named agent (Scout / Analyst / Skeptic) about one idea. Agreed changes become a new **idea version**, with history and diffs.
- **Re-score** an edited idea.
- **Reject** an idea, with an optional reason that feeds future Mode B runs.
- **Merge** 2+ ideas into a hybrid, which is re-analyzed and re-scored.
- **Select** one idea and run "Develop Full Business Plan", which resumes the graph.

## 5. Phase 2 — Deep development
| # | Agent | Job |
|---|---|---|
| 4 | Product Architect | MVP scope (now vs. later), features, architecture, data model, stack, solo build estimate |
| 5 | GTM Strategist | Positioning, ICP, channels ranked by expected CAC, zero-budget tactics, viral loops, first-100-customers plan |
| 6 | Financial Modeler | Pricing tiers, LTV/CAC/payback/margin, 12-month base/bear/bull projections. **The LLM proposes assumptions; Python computes.** |
| 7 | Editor | Reconciles 4–6, flags contradictions, assembles the dossier |

Agents 4–6 run in parallel; the Editor runs after them.

**Output:** a Markdown + PDF dossier with a 30/60/90-day launch checklist and a "Sources & Assumptions" appendix.

## 6. Architecture
- **API (FastAPI):** enqueues runs, resumes runs, reads state, streams events. It never executes graphs.
- **Worker (arq):** runs and resumes LangGraph graphs. It publishes events to Postgres (`agent_events`) and notifies via Postgres `LISTEN/NOTIFY` (or Redis pub/sub).
- **LangGraph:** `AsyncPostgresSaver` checkpoints keyed by `thread_id = run_id`. Application tables are the source of truth for ideas and plans; checkpoints hold execution state only.
- **Co-working while paused:** handled by `services/cowork` outside the main graph. Chat runs as a lightweight agent call. Accepted edits write a new `idea_version`. On resume, the `Command(resume=...)` payload carries the selected `idea_id`, and the graph reloads the latest versions from the DB. (Confirm or revise in Phase 3 with an ADR.)
- **LLM layer:** a `LLMProvider` protocol with Anthropic / OpenAI / local implementations plus `FakeLLM`. Each agent can use a different model.
- **Search layer:** a `SearchProvider` protocol with Tavily / Serper / `MockSearchProvider`. Results are cached per run.

### SSE event types
`run.status`, `agent.started`, `agent.thought`, `agent.tool_call`, `agent.completed`, `idea.created`, `idea.updated`, `run.interrupted`, `run.resumed`, `run.completed`, `run.error`, `budget.warning`, `budget.exhausted`.

### Tables (minimum)
`runs`, `ideas`, `idea_versions`, `agent_events`, `cowork_messages`, `business_plans`, `search_cache`, `run_costs`, `founder_profile`. Every table has `user_id`, so the app is auth-ready.

### API
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/incubator/runs` | Start a run (Mode A/B) |
| GET | `/api/incubator/runs/{run_id}` | Run state, ideas, status |
| GET | `/api/incubator/runs/{run_id}/stream` | SSE + `Last-Event-ID` replay |
| POST | `/api/incubator/runs/{run_id}/ideas/{idea_id}/cowork` | Chat with an agent (streamed) |
| POST | `/api/incubator/runs/{run_id}/ideas/{idea_id}/rescore` | Skeptic re-score |
| POST | `/api/incubator/runs/{run_id}/ideas/{idea_id}/reject` | Reject idea |
| POST | `/api/incubator/runs/{run_id}/ideas/merge` | Merge ideas |
| POST | `/api/incubator/runs/{run_id}/select` | Resume → Phase 2 (idempotent) |
| GET | `/api/incubator/runs/{run_id}/plan/export?format=md\|pdf` | Export dossier |

## 7. Frontend
- `/` — start screen: seed input with constraints, plus the "Discover & Incubate" button.
- `/runs` — run history.
- `/runs/[runId]` — live activity panel + idea cards. When interrupted, it shows the co-working view: drawer with per-agent chat, version history with diffs, scorecard; merge flow; select button.
- `/runs/[runId]/plan` — dossier viewer + export.
- `/settings/profile` — founder profile.
- Required states: loading, empty, error, budget-exhausted, reconnecting.

## 8. Out of scope (for now)
Multi-user auth, billing, team sharing, mobile app.

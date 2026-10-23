# Role

You are a Principal AI Systems Architect and Lead Full-Stack Engineer with deep, current experience shipping LangGraph-based multi-agent systems, FastAPI services, and Next.js App Router frontends to production. You write strictly typed, tested, runnable code, and you state your assumptions instead of hiding them behind TODOs.

# What we are building

**AutoIncubator** (working name; alt. "AgencyOS"): an AI venture studio that discovers, stress-tests, and develops business ideas *together with* a human founder (me). It is not a one-shot report generator. The product's core value is the **co-working checkpoint**, where I can interrogate, reshape, merge, or kill ideas before the system invests effort in a full plan.

Design priorities, in order:
1. **Trustworthiness of output** — every market number is sourced or explicitly labeled as an estimate with stated assumptions. No invented statistics.
2. **Resumability** — any run can pause for hours or days, survive a server restart, and resume exactly where it left off.
3. **Transparency** — I can watch each agent work in real time and see why an idea scored the way it did.
4. **Cost control** — every run has a token/search budget and stops gracefully when it is exhausted.
5. **Clean separation of concerns** — agents, orchestration, persistence, transport, and UI are independently testable.

---

# Product behavior

## Input modes
- **Mode A — Directed:** I provide a seed (topic, niche, trend, or pain point), e.g. "AI tools for local supply chains in Central Asia" or "solopreneur invoice reconciliation". Optional constraints: target region, budget ceiling, B2B/B2C, solo-founder feasibility, excluded industries.
- **Mode B — Autonomous ("Discover & Incubate"):** one click, no prompt. The system mines current signals itself and generates candidate niches. It must still respect any saved founder profile (skills, region, capital, risk tolerance) if one exists.

## Phase 1 — Ideation & stress-testing
| Agent | Responsibility | Required output (structured) |
|---|---|---|
| 1. Trend Scout | Gather raw opportunities from search/APIs (Mode A) or autonomous signal mining (Mode B). Produce 8–12 raw candidates, deduplicated and diverse across industries and business models. | `RawOpportunity[]` with signal sources and URLs |
| 2. Market Analyst | For each surviving candidate: TAM/SAM/SOM (with method: top-down or bottom-up), competitors, pricing benchmarks, target segments. | `MarketAnalysis` per idea, every figure carrying `source_url` or `assumption` |
| 3. Devil's Advocate | Attack each idea on a fixed rubric (below). Must name the single most likely cause of failure. | `CritiqueScorecard` per idea |

**Skeptic rubric (each 1–10, with a one-sentence justification):** CAC risk, platform/channel dependency, churn risk, defensibility/moat, regulatory risk, time-to-first-revenue, solo-founder feasibility. Composite score uses explicit, configurable weights.

**Phase 1 output:** 3–5 ranked, clearly differentiated business briefs. If fewer than 3 survive a minimum quality threshold, say so rather than padding the list.

## Checkpoint — Human-in-the-loop co-working
The graph pauses. The UI shows each idea as an interactive dossier. I can:
- **Chat with a specific agent** (Analyst, Skeptic, or Scout) about a specific idea to tweak hypotheses, pivot the model, or add constraints. Agreed changes are written back to the idea as a new **version** (keep history; show diffs).
- **Request a re-score** of an edited idea by the Skeptic.
- **Reject** ideas (with an optional reason that feeds future autonomous runs).
- **Combine** two or more ideas into a new hybrid, which is then re-analyzed and re-scored.
- **Select** one idea and click **"Develop Full Business Plan"**, which resumes the graph.

## Phase 2 — Deep development
| Agent | Responsibility |
|---|---|
| 4. Product Architect | MVP scope (must-have vs. later), feature breakdown, system architecture, data model, tech stack, rough build estimate for a solo developer. |
| 5. GTM & Growth Strategist | Positioning, ICP, channels ranked by expected CAC, zero-budget launch tactics, viral/referral loops, first-100-customers plan. |
| 6. Financial Modeler | Pricing tiers, unit economics (LTV, CAC, payback, gross margin), 12-month revenue and runway projection under base/bear/bull scenarios. **All calculations are done in Python code, not by the LLM.** The LLM only proposes assumptions. |
| 7. Editor (new) | Reconciles the three outputs (e.g., GTM channel costs must match the Financial Modeler's CAC), flags contradictions, and assembles the final dossier. |

Agents 4–6 should run in parallel where their inputs allow; the Editor runs after them.

**Phase 2 output:** a business dossier exportable as Markdown and PDF, ending with a concrete 30/60/90-day launch checklist. The dossier includes a "Sources & Assumptions" appendix.

---

# Technical requirements

- **Backend:** Python 3.12, FastAPI, fully async. Pydantic v2 models for all agent I/O; agents return validated structured output, with retry on validation failure.
- **Orchestration:** LangGraph `StateGraph` using the current recommended APIs: the dynamic `interrupt()` function for the HITL pause and `Command(resume=...)` to continue, with `AsyncPostgresSaver` as the checkpointer. If you choose static `interrupt_before` instead anywhere, justify it. Check that every API you use exists in current LangGraph; do not use deprecated patterns.
- **Execution model:** graph runs execute in a background worker (e.g., arq or a dedicated asyncio task manager), never inside the HTTP request. The API only enqueues, resumes, and reads.
- **LLM layer:** provider-agnostic interface (Anthropic, OpenAI, local), with per-agent model selection (cheap model for the Scout's breadth, strong model for the Skeptic and Editor).
- **Persistence:** PostgreSQL with SQLAlchemy 2.0 async + asyncpg, Alembic migrations. LangGraph checkpoint tables are separate from application tables; explain how they relate.
- **Real-time:** Server-Sent Events. Events are persisted to an `agent_events` table with monotonically increasing IDs so clients can reconnect with `Last-Event-ID` and replay missed events. Define a typed event schema (e.g., `run.status`, `agent.started`, `agent.thought`, `agent.tool_call`, `agent.completed`, `idea.updated`, `run.interrupted`, `run.error`, `budget.warning`).
- **Search:** a `SearchProvider` protocol with Tavily and Serper implementations plus a deterministic mock for tests and offline dev. Cache search results per run.
- **Frontend:** Next.js (App Router), TypeScript strict mode, Tailwind, shadcn/ui, Lucide icons. Server state via TanStack Query; SSE consumed through a typed hook.
- **Cross-cutting:** auth-ready (single-user now, `user_id` on every table for multi-tenancy later), structured logging, tracing (LangSmith or OpenTelemetry), per-run token and cost accounting, rate limiting, idempotent resume/select endpoints, prompt-injection hygiene for fetched web content.

---

# Your task

Deliver the following. Where I ask for code, give complete, runnable files, not fragments, unless a fragment is explicitly enough.

### 1. Architecture overview
- A diagram (Mermaid) of the full system: frontend, API, worker, LangGraph, Postgres, search providers, LLM providers.
- The key architectural decisions and the trade-offs you considered (e.g., SSE vs. WebSockets; how co-working chat interacts with a paused graph).

### 2. State and graph design
- The complete LangGraph state schema (`TypedDict` with reducers where needed) covering Phase 1, the checkpoint, and Phase 2, plus the Pydantic models for every agent's input and output.
- Graph topology: nodes, edges, conditional routing (e.g., quality threshold not met → loop back to the Scout once, with a max-iterations guard), parallel fan-out/fan-in for Phase 2, and exactly where and how `interrupt()` is called.
- **How co-working works while the graph is paused:** does agent chat run as a separate lightweight graph/subgraph, or via `update_state`? How are idea edits, rejections, and merges written back so the resumed graph sees them? Pick one approach and justify it.

### 3. Autonomous "no-prompt" strategy (Mode B)
- The exact system prompt for the Trend Scout in autonomous mode.
- The query-generation strategy: signal categories to mine (e.g., rising search queries, recent funding rounds, new regulations, complaint threads on forums/review sites, job postings revealing manual work, marketplace gaps), how queries are generated and diversified, and how results are deduplicated and filtered for novelty and feasibility.
- Guardrails against generic ideas ("AI chatbot for X") — define what counts as "high-signal" and how it is scored.

### 4. Prompts for all agents
System prompts for all seven agents, each specifying role, inputs, output schema, rules on citing sources vs. labeling assumptions, and what to do when evidence is missing.

### 5. Database schema
SQLAlchemy models and the initial Alembic migration for at least: `runs`, `ideas`, `idea_versions`, `agent_events`, `cowork_messages`, `business_plans`, `search_cache`, `run_costs`. Include indexes, foreign keys, enums, and JSONB where appropriate, with a short rationale for each table.

### 6. Backend implementation
Endpoints (with request/response Pydantic models, status codes, and error cases):
- `POST /api/incubator/runs` — start a run (Mode A or B), returns `run_id`.
- `GET /api/incubator/runs/{run_id}` — current run state, ideas, and status.
- `GET /api/incubator/runs/{run_id}/stream` — SSE with replay via `Last-Event-ID`.
- `POST /api/incubator/runs/{run_id}/ideas/{idea_id}/cowork` — chat with a named agent about an idea (streamed response).
- `POST /api/incubator/runs/{run_id}/ideas/{idea_id}/reject`
- `POST /api/incubator/runs/{run_id}/ideas/merge`
- `POST /api/incubator/runs/{run_id}/select` — resume the graph for Phase 2 (idempotent).
- `GET /api/incubator/runs/{run_id}/plan/export?format=md|pdf`

Plus: the graph builder, every node implementation, the worker, the event publisher, and the search and LLM provider interfaces.

### 7. Frontend architecture
- Route map and component tree.
- Layout: idea discovery cards, live agent activity panel, co-working drawer (per-agent chat, idea version history with diffs, scorecard view), merge flow, and the plan viewer.
- Code for the key pieces: the typed SSE hook with reconnection, the run page that correctly restores an interrupted run on reload, the idea card, the co-working drawer, and the API client types (generated from or kept in sync with the backend's OpenAPI schema).
- Loading, empty, error, and budget-exhausted states.

### 8. Quality, testing and evaluation
- Unit tests for nodes using the mock search and a fake LLM; an integration test that runs the full graph through the interrupt and resume.
- An evaluation approach for idea quality and for factual grounding of market claims.

### 9. Implementation roadmap
Phased plan from local MVP to production deployment, with concrete deliverables and acceptance criteria per phase: (0) skeleton and infra, (1) Phase 1 end-to-end with mock search, (2) HITL checkpoint and co-working, (3) Phase 2 and export, (4) real search, cost controls, observability, (5) deployment (Docker Compose locally; a recommended production target with reasoning).

---

# Output format and process

- Start with a project **file tree**, then a short **assumptions** list.
- Then deliver sections 1–9 in order. If everything does not fit in one response, finish complete sections, stop at a clean boundary, and end with "Continue with section N" so I can prompt you to continue. Never truncate a file mid-way.
- Every code block begins with its file path as a comment.
- No placeholders like `# TODO: implement` or `...` inside delivered files. If something is deliberately out of scope, say so in prose.
- Pin dependency versions in `pyproject.toml` and `package.json`.
- If any requirement above is contradictory or a worse choice than an alternative, say so and propose the better option before implementing.

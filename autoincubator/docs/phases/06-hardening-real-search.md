# Phase 6 — Real search, quality evals, cost & observability

## Goal
Move from fakes to real-world runs that are grounded, measurable and affordable.

## Scope
- **Search:** Tavily and Serper providers with retries, timeouts, rate limiting and cache. Fetched pages are sanitized (prompt-injection hygiene) and length-capped.
- **Per-agent model routing** via config (cheap model for the Scout, strong model for the Skeptic/Editor). Use prompt caching where the provider supports it.
- **Cost:** `run_costs` populated per call. The run page shows cost so far and the budget. Global daily cap.
- **Observability:** structured logs with `run_id`, plus tracing (LangSmith or OpenTelemetry — pick one in an ADR).
- **Evals** (`tests/evals/`, run manually, not in CI):
  - **Grounding:** sample sourced figures, fetch each source, and LLM-judge whether it supports the claim. Report a % supported.
  - **Idea quality:** a rubric judged by a strong model over a fixed set of 10 seeds + 3 autonomous runs. Track scores over time in `evals/results/`.
  - **Diversity:** semantic spread of Mode B outputs across runs.
- Rate limiting on public endpoints.

## Acceptance criteria
- [ ] 3 real Mode A and 2 real Mode B runs complete end-to-end. Cost per run is reported.
- [ ] Grounding eval ≥ 80% supported; failures are listed with causes.
- [ ] A prompt-injection test page in mock search does not change agent behavior.
- [ ] One trace shows a full run across API → worker → nodes.
- [ ] PROGRESS.md includes the eval results and a cost table.

## Prompt to paste
```
Phase 6. Read CLAUDE.md, docs/PROGRESS.md and docs/phases/06-hardening-real-search.md.
Propose the eval design (datasets, judge prompts, metrics) and the tracing choice. Wait for my OK, then implement, run the evals, and report results honestly in PROGRESS.md — including what's weak.
```

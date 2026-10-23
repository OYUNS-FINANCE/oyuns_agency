# Phase 1 — Phase-1 graph core (offline, testable)

## Goal
The Scout → Analyst → Skeptic pipeline works as a LangGraph graph, runs fully offline with fakes, and stops at the `interrupt()` checkpoint. No API or UI yet; it is driven by tests and a CLI script.

## Scope
- **Providers:** the `LLMProvider` protocol (structured output via Pydantic, with retry on validation failure, plus token/cost accounting hooks), an Anthropic implementation and `FakeLLM` (scripted responses). The `SearchProvider` protocol and `MockSearchProvider` (deterministic fixtures).
- **Schemas** (`agents/*/schemas.py`): `RunInput`, `FounderProfile`, `RawOpportunity`, `SourcedFigure` (value, unit, `source_url | assumption`), `MarketAnalysis`, `RubricScore`, `CritiqueScorecard`, `IdeaBrief`.
- **Agents 1–3:** each module holds its system prompt (as a versioned constant), its node function and its schemas. The Scout has two prompts: Mode A (seeded) and Mode B (autonomous signal mining per SPEC §3). Fetched web content is wrapped as untrusted data.
- **Graph** (`graph/`): a state `TypedDict` with reducers, the builder, and conditional routing: quality threshold → loop back to the Scout once, with a max-iteration guard. Ranking by composite score with configurable weights. A checkpoint node calls `interrupt()` with the ranked briefs. Phase 2 nodes exist as no-op stubs after the interrupt.
- **Checkpointer:** `AsyncPostgresSaver` (the in-memory saver is allowed only in unit tests).
- **Dedup:** embedding or simple similarity dedup of raw opportunities, behind an interface.
- **CLI:** `scripts/run_phase1.py --seed "..."` or `--auto`, which prints the ranked briefs as JSON.
- An ADR documenting the state schema and routing decisions.

## Out of scope
DB application tables, API, SSE, worker, UI.

## Acceptance criteria
- [ ] Unit tests for each node using `FakeLLM` + `MockSearchProvider`.
- [ ] Integration test: the graph runs to `interrupt()`, a new process resumes the same thread from Postgres with `Command(resume=...)`, and reaches the Phase-2 stubs.
- [ ] Test: the quality-threshold loop runs exactly once, then reports "fewer than 3 viable ideas" honestly.
- [ ] Test: every `SourcedFigure` has a source or an assumption (validation rejects otherwise).
- [ ] The CLI works offline (`LLM_PROVIDER=fake SEARCH_PROVIDER=mock`) and with a real Anthropic key.
- [ ] mypy/ruff/pytest are green; PROGRESS.md is updated.

## Prompt to paste
```
Phase 1. Read CLAUDE.md, docs/SPEC.md, docs/PROGRESS.md and docs/phases/01-phase1-graph-core.md.
Before coding, check the installed LangGraph version's docs for interrupt(), Command(resume=...) and AsyncPostgresSaver and tell me the exact APIs you'll use.
Then propose the state schema, node list and routing as a short plan + Mermaid diagram, and wait for my OK.
After approval: implement, write the ADR, run all acceptance checks, update PROGRESS.md.
```

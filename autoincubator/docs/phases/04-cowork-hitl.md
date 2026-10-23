# Phase 4 — Co-working checkpoint (HITL), backend + UI

## Goal
While a run is paused, I can chat with agents about an idea, accept changes as new versions, re-score, reject, merge, and finally select one idea, which resumes the graph.

## Scope
### Backend
- **ADR:** confirm or revise the SPEC §6 approach (co-working outside the graph; versions in the DB; the resume payload carries the selected `idea_id`).
- **Table:** `cowork_messages` (run, idea, agent, role, content, proposed_patch).
- **`POST /ideas/{id}/cowork`:** streams the agent's reply (SSE or chunked). The agent can return a structured `proposed_patch` (a JSON patch against the idea brief) alongside its text.
- **`POST /ideas/{id}/versions`:** accepts a proposed patch → creates a new `idea_version` and emits `idea.updated`.
- **`POST /ideas/{id}/rescore`:** the Skeptic re-scores the latest version.
- **`POST /ideas/{id}/reject`:** takes a reason; stores it for future Mode B runs as "avoid" context.
- **`POST /ideas/merge`:** takes ≥2 ids and creates a hybrid idea → Analyst + Skeptic run on it (in the worker; events streamed).
- **`POST /select`:** idempotent (an idempotency key, or status-guarded). Enqueues a resume with `Command(resume={"idea_id": ...})`. Repeated calls do not double-resume.
- All co-working endpoints return `409` unless the run is `awaiting_human`.

### Frontend
- **Co-working drawer** on an idea, with tabs:
  - **Chat:** pick an agent; streamed replies; "Apply change" button on proposed patches.
  - **Versions:** list with a side-by-side diff.
  - **Scorecard:** full rubric with justifications and sources.
- Reject (with a reason), multi-select → Merge flow, and a "Develop Full Business Plan" button with confirmation.

## Out of scope
Phase 2 agents. After select, the graph reaches the Phase 2 stubs and completes.

## Acceptance criteria
- [ ] Chat → apply patch → version 2 is visible with a diff → re-score updates the card.
- [ ] Merge creates a new scored idea, streamed live.
- [ ] Rejected-idea reasons appear in the next Mode B run's Scout context (test).
- [ ] Double-clicking Select resumes exactly once (test).
- [ ] Co-working calls on a non-paused run return 409.
- [ ] Reloading the page mid-co-working restores the drawer state from the server.
- [ ] All checks are green; PROGRESS.md is updated.

## Prompt to paste
```
Phase 4. Read CLAUDE.md, docs/SPEC.md §4 and §6, docs/PROGRESS.md and docs/phases/04-cowork-hitl.md.
First write the ADR for how co-working interacts with the paused graph (compare: external service + DB versions vs. update_state on the checkpoint vs. a cowork subgraph) and recommend one. Wait for my OK, then implement backend first, then UI, and verify every acceptance criterion.
```

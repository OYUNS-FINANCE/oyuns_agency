# Phase 3 — Frontend: start screen & live discovery view

## Goal
From the browser I can start a run (seeded or autonomous), watch agents work live, and see ranked idea cards. This is the first usable vertical slice.

## Scope
- **API client:** types generated from `backend/openapi.json` (e.g., `openapi-typescript`), plus a thin fetch wrapper with an error model. Add a `pnpm gen:api` script.
- **`useRunStream(runId)` hook:** typed SSE consumption with auto-reconnect using `Last-Event-ID`, exponential backoff, a connection-status flag, and events merged into the TanStack Query cache.
- **Routes:**
  - `/` — seed input, collapsible constraints, "Discover & Incubate" button.
  - `/runs` — history list with status badges.
  - `/runs/[runId]` — two-column layout: live activity panel (grouped by agent, collapsible thoughts, tool calls showing queries) and ranked idea cards.
  - `/settings/profile` — founder profile form.
- **Idea card:** title, one-line pitch, composite score, a rubric mini-chart, "most likely failure", and a source count.
- **Page restore:** reloading `/runs/[runId]` at any status restores the correct view from `GET /runs/{id}` + replay.
- **States:** loading, empty, error, reconnecting, budget-exhausted, failed.
- Load the `frontend-design` skill (if available) for visual direction before building UI. Aim for a distinctive, calm, data-dense look, not a template.

## Out of scope
The co-working drawer, merge, select, plan viewer.

## Acceptance criteria
- [ ] A Mode A run and a Mode B run can each be started from the UI against the fake/mock backend, and render live to the ranked cards.
- [ ] Killing and restarting the API mid-run: the UI shows "reconnecting", then catches up with no duplicated events.
- [ ] Hard reload during and after a run restores the correct state.
- [ ] Usable at 375px width.
- [ ] `pnpm typecheck`, `lint`, `test` are green (hook unit tests included); PROGRESS.md is updated.

## Prompt to paste
```
Phase 3. Read CLAUDE.md, docs/SPEC.md §7, docs/PROGRESS.md and docs/phases/03-frontend-discovery.md.
Propose the route map, component tree and the useRunStream design (how events map into the Query cache). Include a rough ASCII wireframe of /runs/[runId]. Wait for my OK, then implement and verify every acceptance criterion by actually running the app.
```

# Phase 0 — Skeleton & infrastructure

## Goal
An empty but fully wired monorepo: both apps boot, the database migrates, CI-style checks pass. No product features yet.

## Scope
- Monorepo layout exactly as in `CLAUDE.md`.
- `docker-compose.yml`: Postgres 16 and Redis 7 with healthchecks and named volumes.
- **Backend:** `uv` project with pinned deps. Includes `app/main.py` with a `GET /api/health` route that checks DB and Redis, `core/config.py` (pydantic-settings), `core/logging.py` (structlog JSON), async SQLAlchemy session, Alembic configured for async, and an empty initial migration.
- **Worker:** an arq `WorkerSettings` with a `ping` task.
- **Frontend:** Next.js App Router, TS strict, Tailwind, shadcn/ui initialized, TanStack Query provider, and a placeholder home page that calls `/api/health`.
- **Tooling:** ruff, mypy --strict, pytest + pytest-asyncio; ESLint, Prettier, Vitest.
- **Files:** `.env.example`, root `Makefile` (or `justfile`) with the commands listed in `CLAUDE.md`, `docs/PROGRESS.md`.

## Out of scope
Agents, the graph, real tables.

## Acceptance criteria
- [ ] `docker compose up -d` brings Postgres and Redis to healthy.
- [ ] `alembic upgrade head` succeeds on a fresh DB.
- [ ] `GET /api/health` returns `{"db":"ok","redis":"ok"}`.
- [ ] The worker starts and runs the `ping` task when enqueued.
- [ ] The frontend home page shows health status.
- [ ] `pytest`, `mypy app`, `ruff check`, `pnpm typecheck`, `pnpm lint` all pass.
- [ ] The commands in `CLAUDE.md` match reality.

## Prompt to paste
```
We're starting Phase 0. Read CLAUDE.md, docs/SPEC.md and docs/phases/00-skeleton.md.
Propose your plan (file list + pinned versions you intend to use, verified against current releases) and wait for my OK.
After I approve, implement it, run every acceptance check, and update docs/PROGRESS.md.
```

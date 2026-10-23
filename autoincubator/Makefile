.PHONY: up down migrate api worker ping phase1 openapi web check check-backend check-frontend test-integration install

# WeasyPrint (PDF export) loads Pango at runtime. On macOS the uv-managed Python does not
# search Homebrew's lib directory, so point dyld at it (brew install pango). It is set inline
# in each recipe: SIP strips DYLD_* variables from the environment of /bin/sh.
ifeq ($(shell uname -s),Darwin)
PANGO := DYLD_FALLBACK_LIBRARY_PATH=$(shell brew --prefix 2>/dev/null || echo /opt/homebrew)/lib
endif

install:
	cd backend && uv sync
	cd frontend && pnpm install

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
	cd backend && uv run alembic upgrade head

api:
	cd backend && $(PANGO) uv run uvicorn app.main:app --reload

worker:
	cd backend && $(PANGO) uv run arq app.worker.main.WorkerSettings

ping:
	cd backend && PYTHONPATH=. uv run python scripts/enqueue_ping.py

phase1:
	cd backend && PYTHONPATH=. uv run python scripts/run_phase1.py $(ARGS)

openapi:
	cd backend && PYTHONPATH=. uv run python scripts/export_openapi.py

web:
	cd frontend && pnpm dev

check: check-backend check-frontend

check-backend:
	cd backend && $(PANGO) uv run pytest && uv run mypy app scripts tests migrations && uv run ruff check .

check-frontend:
	cd frontend && pnpm typecheck && pnpm lint && pnpm test

test-integration:
	cd backend && $(PANGO) uv run pytest -m integration

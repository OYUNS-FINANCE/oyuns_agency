.PHONY: up down migrate api worker ping phase1 web check check-backend check-frontend test-integration install

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
	cd backend && uv run uvicorn app.main:app --reload

worker:
	cd backend && uv run arq app.worker.main.WorkerSettings

ping:
	cd backend && PYTHONPATH=. uv run python scripts/enqueue_ping.py

phase1:
	cd backend && PYTHONPATH=. uv run python scripts/run_phase1.py $(ARGS)

web:
	cd frontend && pnpm dev

check: check-backend check-frontend

check-backend:
	cd backend && uv run pytest && uv run mypy app scripts tests migrations && uv run ruff check .

check-frontend:
	cd frontend && pnpm typecheck && pnpm lint && pnpm test

test-integration:
	cd backend && uv run pytest -m integration

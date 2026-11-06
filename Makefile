.DEFAULT_GOAL := help
.PHONY: help setup up down logs ps dev-api dev-worker dev-beat dev-web migrate seed run-pol skill test test-pg lint format check secrets clean

# `uv` can mark the editable-install .pth as hidden on macOS, which Python then skips; PYTHONPATH makes it moot.
BACKEND := cd backend && PYTHONPATH=src

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend + frontend deps and git hooks
	cd backend && uv sync
	cd frontend && npm ci
	@git rev-parse --git-dir >/dev/null 2>&1 && uvx pre-commit install || echo "Skipping git hooks: run 'git init' first, then 'uvx pre-commit install'"

secrets: ## Print fresh values for LS_JWT_SECRET and LS_FIELD_ENCRYPTION_KEYS
	@$(BACKEND) uv run python -c "import secrets; from cryptography.fernet import Fernet; print('LS_JWT_SECRET=' + secrets.token_urlsafe(48)); print('LS_FIELD_ENCRYPTION_KEYS=' + Fernet.generate_key().decode())"

up: ## Run the full stack in Docker, seeded (demo mode without keys) -> http://localhost:8080
	docker compose up --build -d
	@echo "Lodestar is starting: http://localhost:8080  (docker compose logs -f migrate api worker)"

down: ## Stop the stack (data volumes are kept; `docker compose down -v` wipes them)
	docker compose down

logs: ## Tail API + worker logs
	docker compose logs -f api worker beat

ps: ## Show service status
	docker compose ps

migrate: ## Apply database migrations (local dev)
	$(BACKEND) uv run alembic upgrade head

seed: ## First-run data: owner, watchlist, holdings, POL report, scan, trade plans, paper replay (idempotent)
	$(BACKEND) uv run python -m lodestar.interfaces.cli seed

run-pol: ## Run the full pipeline for Polygon (POL) inline and print the step outcomes
	$(BACKEND) uv run python -m lodestar.interfaces.cli run polygon-ecosystem-token

skill: ## Run one trader skill as JSON, e.g. `make skill S=trade-plan ARGS="--coin solana"` (no DB needed)
	$(BACKEND) uv run python -m lodestar.interfaces.skills $(S) $(ARGS)

dev-api: ## API with reload (needs db + redis: `docker compose up -d db redis`)
	$(BACKEND) uv run uvicorn lodestar.interfaces.http.app:app --reload --port 8000

dev-worker: ## Celery worker (runs pipelines)
	$(BACKEND) uv run celery -A lodestar.interfaces.workers.tasks worker --pool=solo --loglevel=INFO

dev-beat: ## Celery beat (daily reports, hourly paper-trading tick)
	$(BACKEND) uv run celery -A lodestar.interfaces.workers.tasks beat --loglevel=INFO --schedule /tmp/lodestar-celerybeat

dev-web: ## Frontend dev server -> http://localhost:5173 (LS_API_URL overrides the API target)
	cd frontend && npm run dev

test: ## All tests (backend + frontend)
	$(BACKEND) uv run pytest --cov
	cd frontend && npm test

test-pg: ## Repository tests against a real Postgres (set LS_TEST_DATABASE_URL to a migrated database)
	$(BACKEND) uv run pytest tests/integration/test_postgres_repositories.py

lint: ## Lint + typecheck everything
	$(BACKEND) uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src
	cd frontend && npm run lint && npm run typecheck

format: ## Auto-format
	$(BACKEND) uv run ruff check --fix src tests && uv run ruff format src tests
	cd frontend && npm run format

check: lint test ## Everything CI runs (except Docker)

clean: ## Remove caches and build output
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache backend/.coverage frontend/dist

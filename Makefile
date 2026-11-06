# Pramana developer commands. Requires uv and a native PostgreSQL (scripts/dev_db.py).
.PHONY: setup dev dev-web db-up db-down migrate sim core lint typecheck test e2e contracts openapi check run-text preflight

ifeq ($(OS),Windows_NT)
DEV_PYTHON := .venv/Scripts/python.exe
else
DEV_PYTHON := uv run python
endif

setup:            ## install the workspace and create .env with fresh keys
	uv sync
	uv run python scripts/dev_env.py

dev:              ## database + migrations + simulator + core in one command (Ctrl+C stops all)
	$(DEV_PYTHON) scripts/dev.py

dev-web:          ## same as dev, plus the Next.js console on :3002
	$(DEV_PYTHON) scripts/dev.py --web

db-up:            ## start the local PostgreSQL cluster (port 5433)
	uv run python scripts/dev_db.py start

db-down:
	uv run python scripts/dev_db.py stop

migrate:          ## apply database migrations
	cd services/core && uv run alembic upgrade head

sim:              ## simulator on :8100
	uv run python -m pramana_sim

core:             ## core API on :8000
	uv run python -m pramana_core

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy packages/contracts/src packages/domain/src packages/engine/src services/sim/src services/core/src
	uv run lint-imports

contracts:        ## regenerate the JSON Schema bundle from the Pydantic contracts
	uv run python -m pramana_contracts.export

openapi:          ## regenerate services/core/openapi.json from the app
	uv run python -m pramana_core.openapi_export

test:
	uv run pytest

e2e:              ## M1 acceptance against real sim + core processes (ports 8030/8130)
	uv run pytest tests/e2e -m e2e

check: lint typecheck test

run-text:         ## one live sealed investigation against running sim + core
	uv run python scripts/run_text_investigation.py

preflight:        ## check demo prerequisites; pass PREFLIGHT_ARGS="--url <core-url>"
	uv run python scripts/preflight.py $(PREFLIGHT_ARGS)

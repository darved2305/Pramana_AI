# Pramana developer commands. Requires uv and a native PostgreSQL (scripts/dev_db.py).
.PHONY: setup db-up db-down migrate sim core lint typecheck test contracts check run-text

setup:            ## install the workspace and create .env with fresh keys
	uv sync
	uv run python scripts/dev_env.py

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

test:
	uv run pytest

check: lint typecheck test

run-text:         ## one live sealed investigation against running sim + core
	uv run python scripts/run_text_investigation.py

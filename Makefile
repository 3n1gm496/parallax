UV_CACHE_DIR ?= /tmp/uv-cache
UV = UV_CACHE_DIR=$(UV_CACHE_DIR) uv

.PHONY: install up down migrate test test-integration lint pipeline api dev ui-install ui-check ui-build verify clean help

help:
	@echo "Parallax HFT Commands:"
	@echo "  make install     Install deps and build Rust core"
	@echo "  make up          Start infrastructure (Postgres, Neo4j)"
	@echo "  make migrate     Run DB migrations"
	@echo "  make api         Start FastAPI server"
	@echo "  make pipeline    Run a dry-run arbitrage scan"
	@echo "  make docs        Generate documentation with MkDocs"
	@echo "  make verify      Run all checks (lint, test, ui)"
	@echo "  make clean       Remove temporary files"

docs:
	$(UV) run mkdocs build

install:
	$(UV) sync --extra dev
	$(UV) pip install -e src/parallax_core

up:
	docker compose up -d

down:
	docker compose down

migrate:
	$(UV) run alembic upgrade head

test:
	APP_ENV=test API_AUTH_TOKEN=test_token DATABASE_URL=postgresql://parallax:placeholder@localhost:5433/parallax_test $(UV) run pytest tests/unit/ -v

test-integration:
	APP_ENV=test API_AUTH_TOKEN=test_token $(UV) run pytest tests/integration/ -v -m integration

lint:
	$(UV) run ruff check src/ tests/
	cd src/parallax_core && cargo clippy

pipeline:
	$(UV) run python -m parallax.pipeline.runner

api:
	$(UV) run uvicorn parallax.api.app:app --reload --port 8000

benchmark:
	$(UV) run python3 scripts/generate_mock_data.py
	PYTHONPATH=src $(UV) run python3 scripts/benchmark_replay.py

dev:
	docker compose up -d && $(UV) run uvicorn parallax.api.app:app --reload --port 8000

ui-install:
	cd ui && npm install

ui-check:
	cd ui && npm run check

ui-build:
	cd ui && npm run build

verify: lint test ui-check ui-build

clean:
	rm -rf `find . -name __pycache__`
	rm -rf .pytest_cache
	rm -rf src/parallax_core/target
	rm -f .env.test
	@echo "Repository cleaned."

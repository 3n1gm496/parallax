UV_CACHE_DIR ?= /tmp/uv-cache
UV = UV_CACHE_DIR=$(UV_CACHE_DIR) uv

.PHONY: install up down migrate test test-integration lint pipeline oddpool-dist api dev ui-install ui-check ui-build verify verify-integration
install:
	$(UV) sync --extra dev
up:
	docker compose up -d
down:
	docker compose down
migrate:
	$(UV) run alembic upgrade head
test:
	$(UV) run pytest tests/unit/ -v
test-integration:
	$(UV) run pytest tests/integration/ -v -m integration
lint:
	$(UV) run ruff check src/ tests/
pipeline:
	$(UV) run python -m parallax.pipeline.runner
oddpool-dist:
	$(UV) run python -m parallax.ingestion.oddpool_dist_consumer
api:
	$(UV) run uvicorn parallax.api.app:app --reload --port 8000
dev:
	docker compose up -d && $(UV) run uvicorn parallax.api.app:app --reload --port 8000
ui-install:
	cd ui && npm install
ui-check:
	cd ui && npm run check
ui-build:
	cd ui && npm run build
verify: lint test ui-check ui-build
verify-integration:
	$(UV) run pytest tests/integration/test_pipeline_integration.py -v -m integration

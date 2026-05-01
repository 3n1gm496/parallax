.PHONY: install up down migrate test test-integration lint pipeline api dev
install:
	uv sync --extra dev
up:
	docker compose up -d
down:
	docker compose down
migrate:
	uv run alembic upgrade head
test:
	uv run pytest tests/unit/ -v
test-integration:
	uv run pytest tests/integration/ -v -m integration
lint:
	uv run ruff check src/ tests/
pipeline:
	uv run python -m parallax.pipeline.runner
api:
	uv run uvicorn parallax.api.app:app --reload --port 8000
dev:
	docker compose up -d && uv run uvicorn parallax.api.app:app --reload --port 8000

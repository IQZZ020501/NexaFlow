.PHONY: dev migrate worker coverage

HOST ?= 127.0.0.1
PORT ?= 8000
COMPOSE ?= docker compose --env-file ../.env -f ../deploy/docker-compose.yml -f ../deploy/docker-compose.dev.yml

dev:
	$(COMPOSE) up -d --wait db redis qdrant
	$(MAKE) migrate
	uv run python scripts/dev.py --host $(HOST) --port $(PORT)

migrate:
	uv run python -m alembic upgrade head

worker:
	uv sync --project ../sandbox --no-install-project --frozen
	uv run python scripts/worker.py

coverage:
	uv run python scripts/coverage.py

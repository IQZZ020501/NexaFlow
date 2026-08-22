.PHONY: dev migrate worker worker-compose coverage

HOST ?= 127.0.0.1
PORT ?= 8000
COMPOSE ?= docker compose --env-file ../.env -f ../deploy/docker-compose.yml -f ../deploy/docker-compose.dev.yml
WORKER_LOG_TAIL ?= 20

dev:
	$(COMPOSE) up -d --wait db redis qdrant
	$(MAKE) migrate
	uv run python scripts/dev.py --host $(HOST) --port $(PORT) --worker-log-tail $(WORKER_LOG_TAIL) --compose $(COMPOSE)

migrate:
	uv run python -m alembic upgrade head

worker:
	uv run celery -A app.infrastructure.celery:celery_app worker --beat --queues=celery,agents-legacy,agents-v2 --loglevel=INFO

worker-compose:
	$(COMPOSE) up --build sandbox worker

coverage:
	uv run python scripts/coverage.py

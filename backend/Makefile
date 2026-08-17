.PHONY: dev migrate worker worker-compose coverage

HOST ?= 127.0.0.1
PORT ?= 8000
COMPOSE ?= docker compose -f ../deploy/docker-compose.yml -f ../deploy/docker-compose.dev.yml
WORKER_LOG_TAIL ?= 20

dev: migrate
	@logs_pid=""; \
	if $(COMPOSE) ps --status running --quiet worker 2>/dev/null | grep -q .; then \
		$(COMPOSE) logs -f --tail=$(WORKER_LOG_TAIL) worker & \
		logs_pid=$$!; \
	fi; \
	trap 'if [ -n "$$logs_pid" ]; then kill "$$logs_pid" 2>/dev/null || true; wait "$$logs_pid" 2>/dev/null || true; fi' EXIT INT TERM; \
	uv run python -m uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

migrate:
	uv run python -m alembic upgrade head

worker:
	uv run celery -A app.infrastructure.celery:celery_app worker --beat --queues=celery,agents-legacy,agents-v2 --loglevel=INFO

worker-compose:
	$(COMPOSE) up --build sandbox worker

coverage:
	scripts/coverage.sh

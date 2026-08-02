.PHONY: dev migrate worker

HOST ?= 127.0.0.1
PORT ?= 8000

dev: migrate
	uv run python -m uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

migrate:
	uv run python -m alembic upgrade head

worker:
	uv run celery -A app.core.celery:celery_app worker --loglevel=INFO

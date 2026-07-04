.PHONY: dev migrate

HOST ?= 127.0.0.1
PORT ?= 8000

dev: migrate
	uv run python -m uvicorn nexaflow.main:app --reload --host $(HOST) --port $(PORT)

migrate:
	uv run python -m alembic upgrade head

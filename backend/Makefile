.PHONY: dev migrate worker coverage

HOST ?= 127.0.0.1
PORT ?= 8000

dev:
	uv run python ../scripts/dev.py --infrastructure-only
	$(MAKE) migrate
	uv run python scripts/dev.py --host $(HOST) --port $(PORT)

migrate:
	uv run python -m alembic upgrade head

worker:
	uv run python scripts/worker.py

coverage:
	uv run python scripts/coverage.py

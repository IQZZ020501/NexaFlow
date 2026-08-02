# Backend image: FastAPI API, Celery worker, and beat share this image;
# the container command selects the process (see deploy/docker-compose.yml).
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

FROM base
COPY --from=builder /app/.venv /app/.venv
COPY nexaflow ./nexaflow
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY main.py ./main.py
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "nexaflow.main:app", "--host", "0.0.0.0", "--port", "8000"]

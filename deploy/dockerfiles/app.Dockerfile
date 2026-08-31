# Unified application image. API, worker, and frontend run as separate
# containers; the worker supervises the isolated sandbox broker.

FROM ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 AS uv

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS sandbox-builder
WORKDIR /opt/sandbox
COPY --from=uv /uv /usr/local/bin/uv
COPY sandbox/pyproject.toml sandbox/uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS sandbox-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/sandbox/.venv/bin:$PATH
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 65532 sandbox \
    && addgroup --system --gid 65533 sandbox-socket \
    && adduser --system --uid 65532 --gid 65532 --no-create-home \
       --shell /usr/sbin/nologin sandbox \
    && mkdir -p /run/sandbox \
    && chown root:sandbox-socket /run/sandbox \
    && chmod 0750 /run/sandbox
WORKDIR /opt/sandbox
COPY --from=sandbox-builder /opt/sandbox/.venv ./.venv
COPY sandbox ./sandbox
RUN chown root:sandbox /opt/sandbox \
    && chmod 0750 /opt/sandbox \
    && chown -R root:sandbox /opt/sandbox/.venv /opt/sandbox/sandbox \
    && chmod -R g+rX,o-rwx /opt/sandbox/.venv /opt/sandbox/sandbox

FROM sandbox-base AS sandbox-runtime
COPY backend/scripts/worker.py /opt/sandbox/worker.py
ENTRYPOINT ["/opt/sandbox/.venv/bin/python", "-m", "sandbox.server"]
HEALTHCHECK --interval=5s --timeout=2s --retries=10 \
    CMD ["/opt/sandbox/.venv/bin/python", "-m", "sandbox.healthcheck"]

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS backend-builder
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --no-dev --frozen

FROM oven/bun:1.3.14@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS frontend-deps
WORKDIR /app
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

FROM oven/bun:1.3.14@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS frontend-builder
WORKDIR /app
COPY --from=frontend-deps /app/node_modules ./node_modules
ARG NEXAFLOW_API_PROXY=http://api:8000
ENV NEXAFLOW_API_PROXY=$NEXAFLOW_API_PROXY \
    NEXT_TELEMETRY_DISABLED=1
COPY frontend/ ./
RUN bun run build

FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS node-runtime

FROM sandbox-base AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    PATH=/app/.venv/bin:$PATH
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libatomic1 \
        libcap2 \
        libstdc++6 \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-chi-tra \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-builder /app/.venv /app/.venv
COPY backend/app /app/app
COPY backend/alembic /app/alembic
COPY backend/scripts/worker.py /app/scripts/worker.py
COPY backend/alembic.ini backend/main.py /app/

COPY --from=frontend-builder /app/.next/standalone /opt/frontend
COPY --from=frontend-builder /app/.next/static /opt/frontend/.next/static
COPY --from=frontend-builder /app/public /opt/frontend/public
COPY --from=node-runtime /usr/local/bin/node /opt/node/bin/node

# The sandbox child runs as UID/GID 65532. Keep application runtimes outside
# that identity's readable or executable paths even though they share an image.
RUN chmod 0750 /opt/node/bin/node \
    && chmod -R o-rwx /app /opt/frontend /opt/node

WORKDIR /app
EXPOSE 3000 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

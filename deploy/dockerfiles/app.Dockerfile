# Application containers do not contain the untrusted execution runtime.
FROM ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 AS uv

FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS node-runtime

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS execution-builder
WORKDIR /opt/nexaflow
COPY --from=uv /uv /usr/local/bin/uv
COPY sandbox/pyproject.toml sandbox/uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS sandbox-runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/nexaflow/.venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates fontconfig fonts-noto-cjk libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 nexaflow && useradd --uid 65532 --gid 65532 --no-create-home nexaflow
WORKDIR /opt/nexaflow
COPY --from=execution-builder /opt/nexaflow/.venv ./.venv
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY sandbox/job.py sandbox/self_check.py ./
COPY sandbox/renderer_checks ./renderer_checks
COPY sandbox/skills ./skills
RUN chmod -R a+rX,a-w /opt/nexaflow
ENTRYPOINT ["tail", "-f", "/dev/null"]

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

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PATH=/app/.venv/bin:$PATH
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libatomic1 \
        libstdc++6 \
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

RUN chmod -R o-rwx /app /opt/frontend /opt/node

WORKDIR /app
EXPOSE 3000 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

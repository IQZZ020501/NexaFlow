# Standalone OpenSandbox guest image. It is built and published separately from the
# NexaFlow API/Worker/frontend image; OpenSandbox creates short-lived guests from it.
FROM ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 AS uv

FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS node-runtime

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS dependency-builder
WORKDIR /opt/nexaflow
COPY --from=uv /uv /usr/local/bin/uv
COPY sandbox/pyproject.toml sandbox/uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/nexaflow/.venv/bin:$PATH
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        fontconfig \
        fonts-noto-cjk \
        libstdc++6 \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 nexaflow \
    && useradd --uid 65532 --gid 65532 --no-create-home nexaflow
WORKDIR /opt/nexaflow
COPY --from=dependency-builder /opt/nexaflow/.venv ./.venv
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY sandbox/job.py sandbox/command.py sandbox/mcp_bridge.py sandbox/self_check.py ./
COPY sandbox/renderer_checks ./renderer_checks
COPY sandbox/skills ./skills
RUN chmod -R a+rX,a-w /opt/nexaflow
RUN mkdir -p /skills /tmp/nexaflow-skill /tmp/nexaflow-protocol /tmp/nexaflow-exports \
    && chmod 755 /skills /tmp/nexaflow-skill \
    && chmod 700 /tmp/nexaflow-protocol /tmp/nexaflow-exports
ENTRYPOINT ["tail", "-f", "/dev/null"]

# The sandbox has no third-party dependencies; the builder stage only copies
# the small source tree so the runtime image contains no repository metadata.
FROM python:3.11-slim AS builder
WORKDIR /build
COPY sandbox ./sandbox

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN addgroup --system --gid 65532 sandbox \
    && adduser --system --uid 65532 --gid 65532 --no-create-home \
       --shell /usr/sbin/nologin sandbox \
    && mkdir -p /run/sandbox \
    && chmod 0750 /run/sandbox
WORKDIR /opt/app
COPY --from=builder --chown=root:root /build/sandbox ./sandbox
ENTRYPOINT ["python", "-m", "sandbox.server"]
HEALTHCHECK --interval=5s --timeout=2s --retries=10 \
    CMD ["python", "-c", "import os, stat, sys; p='/run/sandbox/sandbox.sock'; sys.exit(0 if os.path.exists(p) and stat.S_ISSOCK(os.stat(p).st_mode) else 1)"]

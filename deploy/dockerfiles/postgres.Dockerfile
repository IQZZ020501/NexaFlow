FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS pg-search-package

ARG PG_SEARCH_VERSION=0.25.2

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    architecture="$(dpkg --print-architecture)"; \
    case "$architecture" in \
        amd64) checksum="f9f4cccbd5c19b8181c04bfb410bf64f76cac621fff62ca2e9086f220de1020a" ;; \
        arm64) checksum="117278b146bb9e068b8a07ff62315f70ce28465c0b3fa360397bd3f086e9cac4" ;; \
        *) echo "Unsupported architecture: $architecture" >&2; exit 1 ;; \
    esac; \
    curl -fsSL \
        "https://github.com/paradedb/paradedb/releases/download/v${PG_SEARCH_VERSION}/postgresql-17-pg-search_${PG_SEARCH_VERSION}-1PARADEDB-bookworm_${architecture}.deb" \
        -o /tmp/pg_search.deb; \
    echo "$checksum  /tmp/pg_search.deb" | sha256sum -c -

FROM postgres:17-bookworm@sha256:84560e3b9c6874893fc4e2854f5dc3e7c1a37bc9d1dfd7a8c641310ae22ba5ad

COPY --from=pg-search-package /tmp/pg_search.deb /tmp/pg_search.deb

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-17-pgvector=0.8.6-1.pgdg12+1 \
        /tmp/pg_search.deb; \
    rm -f /tmp/pg_search.deb; \
    rm -rf /var/lib/apt/lists/*

CMD ["postgres", "-c", "shared_preload_libraries=pg_search", "-c", "log_line_prefix=%m [%p] [%a] [%u@%d] [%r] [%i] ", "-c", "log_min_duration_statement=1000", "-c", "log_parameter_max_length=0", "-c", "log_parameter_max_length_on_error=0"]

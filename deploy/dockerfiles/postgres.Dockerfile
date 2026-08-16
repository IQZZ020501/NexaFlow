FROM debian:bookworm-slim AS pg-search-package

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

FROM postgres:17-bookworm

COPY --from=pg-search-package /tmp/pg_search.deb /tmp/pg_search.deb

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-17-pgvector \
        /tmp/pg_search.deb; \
    rm -f /tmp/pg_search.deb; \
    rm -rf /var/lib/apt/lists/*

CMD ["postgres", "-c", "shared_preload_libraries=pg_search"]

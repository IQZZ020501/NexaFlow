# NexaFlow container deployment

Runs the full stack with Docker Compose: PostgreSQL, Redis, Qdrant, FastAPI
(`api`), a Celery worker with embedded Beat, the isolated Python sandbox, and
the Next.js frontend.

## Quick start

```bash
cp .env.example .env   # then edit secrets
docker compose --env-file .env -f deploy/docker-compose.yml build db api
docker compose --env-file .env -f deploy/docker-compose.yml up -d db redis qdrant sandbox
docker compose --env-file .env -f deploy/docker-compose.yml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/docker-compose.yml up -d
```

- Public entrypoint: http://localhost:8000
- API routes: http://localhost:8000/api/v1/...
- Health/OpenAPI: http://localhost:8000/health and http://localhost:8000/docs

The production Compose file publishes only host port `8000` from the Next.js
frontend (`8000:3000`). Next.js rewrites API, health, and OpenAPI requests to
the internal `api:8000` service. PostgreSQL, Redis, Qdrant, and the worker remain
reachable only on the Compose network; the sandbox has no network namespace or
host port.

API, worker, frontend, and sandbox are four containers created from the same
application image. This preserves independent commands, scaling, network
namespaces, filesystems, and security options while requiring only one
application artifact in the image registry.

## Local development (infrastructure only)

To run only PostgreSQL, Redis, and Qdrant (while running the backend and
frontend directly on the host, e.g. `make dev` + `bun dev`), use the dev
override. It publishes PostgreSQL on `POSTGRES_PORT` (default `5432`) plus
Redis/Qdrant on `6379`/`6333`, and pins readable container names
(`nexaflow-db`, `nexaflow-redis`, `nexaflow-qdrant`):

```bash
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d db redis qdrant
```

The host backend and Compose use the same root `.env`. `POSTGRES_*` configures
both the published PostgreSQL service and the backend connection; the backend
safely constructs the URL, so credentials are not duplicated inside a
hand-written `DATABASE_URL`. Run migrations with
`cd backend && uv run python -m alembic upgrade head`.
When the API runs on the host and the Compose worker is enabled, the dev
override mounts `backend/storage` at the worker's `/data`; keep
`KNOWLEDGE_STORAGE_DIR=./storage/knowledge` so both processes read the same
uploaded files.

## Services

| Service | Image / build | Command |
|---|---|---|
| `db` | `${NEXAFLOW_POSTGRES_IMAGE}` / `deploy/dockerfiles/postgres.Dockerfile` | PostgreSQL 17 + `pg_search` 0.25.2 + `pgvector` |
| `redis` | redis:7-alpine | — |
| `qdrant` | qdrant/qdrant:v1.19.0 | vector database |
| `api` | `${NEXAFLOW_APP_IMAGE}` / `deploy/dockerfiles/app.Dockerfile` | uvicorn |
| `worker` | same application image | celery worker with embedded Beat |
| `sandbox` | same application image | isolated Python runner over a Unix socket |
| `frontend` | same application image | Next.js standalone |

The unified application image includes the backend virtual environment,
Next.js standalone output, the Node.js runtime, the sandbox source, and
Tesseract Chinese and English language data for PyMuPDF PDF/image OCR fallback.
The complete topology has four unique images: the unified application image,
the custom PostgreSQL image, official Redis, and official Qdrant.

Persistent volumes: `db-data` (PostgreSQL), `redis-data`, `qdrant-data`, and
`uploads` (shared `KNOWLEDGE_STORAGE_DIR` for the API and worker).

## Configuration

All runtime configuration comes from the repository-root `.env` (see
`.env.example`). The base compose file forces `ENVIRONMENT=production`, clears
the optional host `DATABASE_URL`, and overrides `POSTGRES_HOST`, Redis, Qdrant,
and upload-storage locations for the container network. The development
override sets the worker back to `ENVIRONMENT=development`.

`NEXAFLOW_APP_IMAGE` selects the image shared by API, worker, frontend, and
sandbox. `NEXAFLOW_POSTGRES_IMAGE` selects the PostgreSQL image containing the
required extensions. Keep the local defaults when building on the deployment
host; set both to registry tags before running a pull-only server deployment.

Leave `DATABASE_URL` empty for the normal setup. The backend safely constructs
it from `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and
`POSTGRES_PORT`. If a host deployment needs a full `DATABASE_URL`, its user,
password, and database must match any configured `POSTGRES_*` components or
startup fails instead of silently using drifted credentials. Existing
PostgreSQL data directories are not rewritten when these values change.
The bundled Compose topology always uses its `db` service; an external database
requires a deployment-specific Compose override.

For production, replace every example secret and set `CORS_ORIGINS` to the
actual frontend origins. The base compose file already supplies the production
environment mode; host-managed production processes must set
`ENVIRONMENT=production` themselves.
`JWT_EXPIRES_MINUTES` controls access token lifetime;
`REFRESH_TOKEN_EXPIRES_DAYS` controls persisted refresh sessions.
`AGENT_EXECUTOR_LEASE_SECONDS` and `AGENT_EXECUTOR_HEARTBEAT_SECONDS` control
Agent worker takeover; keep the heartbeat below half the lease. The Compose
worker embeds Beat, so keep that combined worker at one instance and do not run
a separate Beat process. It redispatches queued and expired Knowledge tasks and
Agent runs.
Celery uses `solo` automatically on macOS (HTTPS trust evaluation is unsafe
after a multithreaded process fork) and Windows (`prefork` needs `os.fork()`,
which Windows lacks); Linux containers keep `prefork`.
The Compose worker keeps zero prefork children while idle, grows to at most ten
for queued work, and removes idle children after five seconds. Beat groups the
30-second and 60-second recovery scans so maintenance alone does not fan out
the full worker pool.

### Migrating from split environment files

1. Copy `.env.example` to the repository-root `.env`.
2. Merge the existing secrets and shared application values from
   `backend/.env` and `deploy/.env` into that file.
3. Copy the old database name, user, and password into `POSTGRES_*`; normally
   leave `DATABASE_URL` empty so the backend constructs it for each runtime.
   Wrap literal values containing spaces, `#`, or `$` in single quotes, and do
   not use `${VAR}` expansion in the shared file.
4. Validate both Compose modes with the commands below, then remove the two old
   local files. They are no longer read.

```bash
docker compose --env-file .env -f deploy/docker-compose.yml config --quiet
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml config --quiet
```

### Python code sandbox

Workflow Python nodes run in the separate `sandbox` container. The container
has no network namespace, a read-only root filesystem, a size-limited `/tmp`,
drops all default capabilities and restores only `CHOWN`, `KILL`, `SETGID`, and
`SETUID` for child isolation and cleanup. It also has explicit container CPU,
memory, and PID limits. Both the sandbox and Celery worker mount the
`sandbox-socket` volume at `/run/sandbox`; the worker joins the dedicated socket
group. These container limits are separate from the per-request limits below.

The sandbox accepts one JSON object per Unix-socket line at
`/run/sandbox/sandbox.sock`:

```json
{"code":"print(input())","stdin":"hello","limits":{"timeout_ms":1000}}
```

The response is one JSON line with `ok`, `stdout`, `stderr`, `exit_code`, and
`error`. Requests are limited to 768 KiB; code and stdin are each limited to
256 KiB. The optional `limits` object accepts `timeout_ms`, `cpu_seconds`,
`memory_bytes`, `max_output_bytes`, `max_file_bytes`, `max_processes`, and
`max_open_files`; unknown keys are rejected. Requested limits may only reduce
the hard defaults: 5 seconds wall time, 5 CPU seconds, 256 MiB address space,
16 processes, 64 open files, 1 MiB per file, and 64 KiB each for stdout and
stderr. Child Python processes run as UID/GID 65532 with isolated imports and a
minimal environment.

Run the standalone self-check locally or in the built image:

```bash
python3 -m sandbox.self_check
docker build -f deploy/dockerfiles/app.Dockerfile --target sandbox-runtime -t nexaflow-sandbox .
docker run --rm --network none --entrypoint python nexaflow-sandbox -m sandbox.self_check
```

### MCP stdio Servers

Workspace admins enter stdio commands, arguments, working directories, and
environment values when registering an MCP Server. The full configuration is
encrypted in PostgreSQL and is not returned by the API. Install and pin each
server executable in a derived application image; the API performs discovery
and the worker performs Agent calls, so both must expose the same absolute
command and working-directory paths. Avoid shells and runtime downloaders such
as `npx`/`uvx` in production.

stdio commands run with the backend container's filesystem and network access,
so deployments must treat workspace admins as trusted code-execution
operators. Compose enables an init process for API and worker containers so
stdio children receive shutdown and are reaped.

## Split hosting with Nginx

The default Compose deployment already uses the frontend as the single public
entrypoint on port `8000`. `deploy/nginx/default.conf` remains an optional
alternative for deployments that need a separate edge proxy: it routes
`/api/` and `/health` to the API and everything else to the frontend. Keep all
application services on an internal network and publish only the proxy when
using that topology.

## Building images manually

```bash
docker build -f deploy/dockerfiles/app.Dockerfile \
  --build-arg NEXAFLOW_API_PROXY=http://api:8000 \
  -t nexaflow/app:local .
docker build -f deploy/dockerfiles/postgres.Dockerfile \
  -t nexaflow/postgres-pg-search:0.25.2 .
```

`NEXAFLOW_API_PROXY` is baked into the Next.js routes manifest at build time,
so a runtime environment variable cannot change it. The default
`http://api:8000` is portable across Compose deployments because `api` is the
internal service name.

## Publishing to Docker Hub

Only the unified application image and custom PostgreSQL image need to be
published by the project. Redis and Qdrant are pulled from their official
repositories.

```bash
docker login

export DOCKERHUB_NAMESPACE=your-dockerhub-name
export NEXAFLOW_RELEASE=v0.1.0

docker buildx build --platform linux/amd64,linux/arm64 \
  -f deploy/dockerfiles/app.Dockerfile \
  --build-arg NEXAFLOW_API_PROXY=http://api:8000 \
  -t "$DOCKERHUB_NAMESPACE/nexaflow-app:$NEXAFLOW_RELEASE" \
  --push .

docker buildx build --platform linux/amd64,linux/arm64 \
  -f deploy/dockerfiles/postgres.Dockerfile \
  -t "$DOCKERHUB_NAMESPACE/nexaflow-postgres:0.25.2" \
  --push .
```

Use immutable release tags rather than replacing an existing tag; rollback is
then an `.env` image-tag change followed by `docker compose up -d --no-build`.

## Pull-only server deployment

For the images under `registry.cn-shanghai.aliyuncs.com/ai-studios`, keep the
repository layout on the server, create the root `.env`, and use the dedicated
Compose file. Its one-shot `migrate` service runs Alembic before the API and
worker start:

```bash
docker login registry.cn-shanghai.aliyuncs.com
docker compose --env-file .env -f deploy/docker-compose.server.yml pull
docker compose --env-file .env -f deploy/docker-compose.server.yml up -d
```

Only frontend port `8000` is published. Override it with `NEXAFLOW_PORT`.

Copy the repository's `deploy/docker-compose.yml` and `.env.example` to the
server, create `.env`, replace all secrets, and set the published image tags:

```dotenv
NEXAFLOW_APP_IMAGE=your-dockerhub-name/nexaflow-app:v0.1.0
NEXAFLOW_POSTGRES_IMAGE=your-dockerhub-name/nexaflow-postgres:0.25.2
```

Then pull and start the four-image topology without building source code on
the server:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml pull
docker compose --env-file .env -f deploy/docker-compose.yml up -d db redis qdrant sandbox
docker compose --env-file .env -f deploy/docker-compose.yml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/docker-compose.yml up -d --no-build
```

Run `docker login` on the server first only when either Docker Hub repository is
private.

## Migrations

Run migrations before first start or after upgrading:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml run --rm api alembic upgrade head
```

Knowledge BM25 migrations require `pg_search` 0.25.2. The bundled database
image installs the pinned PostgreSQL 17 `pg_search` packages for amd64 and arm64,
verifies their release checksums, and installs the required `pgvector` package.
External PostgreSQL deployments must install both extensions and allow the
migration user to run `CREATE EXTENSION vector` and `CREATE EXTENSION pg_search`.
They must also add `pg_search` to `shared_preload_libraries` and restart
PostgreSQL before running Alembic; the bundled image applies that startup option.
Back up the database before replacing an existing `postgres:17-alpine`
container, rebuild and start `db`, then run Alembic. Building the first BM25
index can block writes to the chunk table, so schedule this migration in a
maintenance window for large knowledge bases. To roll back, restore the prior
application version and downgrade Alembic so its native GIN query path and index
match again; the installed extension may remain unused. `pg_search` Community is
distributed under AGPLv3, so deployments must account for its license.

For this migration, upgrade PostgreSQL first, roll all API and worker instances
to the new image, and only then create SSE/stdio registrations. Existing stdio
Profile registrations are preserved but disabled and must be recreated in the
inline JSON form. Downgrading disables inline stdio registrations and discards
their encrypted configuration, so they must also be recreated after re-upgrade.

## Notes

- Bootstrap admin credentials come from env values, never code defaults.
- Keep `JWT_SECRET_KEY` / `MODEL_SECRET_KEY` stable across restarts;
  rotating them invalidates sessions and encrypted model credentials.
- Agent HTTP streams are observers, not executors: disconnecting a client does
  not cancel the database-backed run. The API and worker must share PostgreSQL
  and Redis for checkpoint, approval, lease recovery, and short-lived answer
  delta delivery. Redis live-stream failure degrades to the durable terminal
  answer rather than failing the Run.
- Newly discovered MCP tools default to per-call approval. Workspace admins can
  explicitly set each tool to read-only, per-call approval, or disabled; server
  annotations such as `readOnlyHint=true` do not bypass approval on their own.
  A changed tool definition invalidates an existing policy and falls back to
  approval.
- Restrict backend filesystem/network access and process counts at the container
  or service-manager boundary, including process namespaces/cgroups that limit
  child processes and resource usage. Cooperative stdio cleanup handles normal
  child-process teardown but cannot isolate host-level crashes; host crashes
  require separate host-level isolation.
- Kubernetes/Helm deployment is not included yet; the compose topology is the
  reference for a future chart.

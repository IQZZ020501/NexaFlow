# NexaFlow container deployment

Runs the full stack with Docker Compose: PostgreSQL, Redis, Qdrant, FastAPI
(`api`), Celery worker and beat, and the Next.js frontend.

## Quick start

```bash
cp deploy/.env.example deploy/.env   # then edit secrets
docker compose -f deploy/docker-compose.yml up --build
```

- API: http://localhost:8000 (`/health`, `/api/v1/...`)
- Frontend: http://localhost:3000

## Services

| Service | Image / build | Command |
|---|---|---|
| `db` | postgres:17-alpine | — |
| `redis` | redis:7-alpine | — |
| `qdrant` | qdrant/qdrant:v1.19.0 | vector database |
| `api` | `deploy/dockerfiles/backend.Dockerfile` | uvicorn |
| `worker` | same backend image | celery worker |
| `beat` | same backend image | celery beat |
| `frontend` | `deploy/dockerfiles/frontend.Dockerfile` | Next.js standalone |

Persistent volumes: `db-data` (PostgreSQL), `redis-data`, `qdrant-data`, and
`uploads` (shared `KNOWLEDGE_STORAGE_DIR` for the API and worker).

## Configuration

All runtime configuration comes from `deploy/.env` (see `.env.example`).
The compose file overrides `DATABASE_URL` and `CELERY_BROKER_URL` to point at
the bundled services, connects the API and worker to the bundled Qdrant through
`QDRANT_URL`, and mounts the uploads volume for `KNOWLEDGE_STORAGE_DIR`.
`JWT_EXPIRES_MINUTES` controls access token lifetime;
`REFRESH_TOKEN_EXPIRES_DAYS` controls persisted refresh sessions.
`AGENT_EXECUTOR_LEASE_SECONDS` and `AGENT_EXECUTOR_HEARTBEAT_SECONDS` control
Agent worker takeover; keep the heartbeat below half the lease. Keep exactly
one `beat` instance running so queued and expired Agent runs are redispatched.
Celery uses `solo` automatically on macOS because HTTPS trust evaluation is
unsafe after a multithreaded process fork; Linux containers keep `prefork`.

### MCP stdio Servers

Workspace admins enter stdio commands, arguments, working directories, and
environment values when registering an MCP Server. The full configuration is
encrypted in PostgreSQL and is not returned by the API. Install and pin each
server executable in a derived backend image; the API performs discovery and
the worker performs Agent calls, so both must expose the same absolute command
and working-directory paths. Avoid shells and runtime downloaders such as
`npx`/`uvx` in production.

stdio commands run with the backend container's filesystem and network access,
so deployments must treat workspace admins as trusted code-execution
operators. Compose enables an init process for API and worker containers so
stdio children receive shutdown and are reaped.

## Split hosting with Nginx

`deploy/nginx/default.conf` routes `/api/` and `/health` to the API and
everything else to the frontend. With compose, either publish the ports and
point the proxy at `api:8000` / `frontend:3000`, or run the stack on an
internal network and expose only the proxy.

## Building images manually

```bash
docker build -f deploy/dockerfiles/backend.Dockerfile -t app/backend .
docker build -f deploy/dockerfiles/frontend.Dockerfile -t app/frontend .
```

`NEXAFLOW_API_PROXY` is baked into the Next.js routes manifest at build time,
so a custom API origin must be passed as a build arg (a runtime env var has no
effect):

```bash
docker build -f deploy/dockerfiles/frontend.Dockerfile \
  --build-arg NEXAFLOW_API_PROXY=https://api.example.com -t app/frontend .
```

## Migrations

Run migrations before first start or after upgrading:

```bash
docker compose -f deploy/docker-compose.yml run --rm api alembic upgrade head
```

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
- Newly discovered MCP tools auto-run as `read_only` only when they declare
  `readOnlyHint=true` without a destructive hint. Unknown or potentially
  destructive tools default to per-call approval. Workspace admins can override
  each tool to read-only, per-call approval, or disabled; a changed tool
  definition invalidates an existing policy and falls back to approval.
- Restrict backend filesystem/network access and process counts at the container
  or service-manager boundary. A hard host/process crash is outside cooperative
  stdio cleanup and must be contained by the runtime's process namespace/cgroup.
- Kubernetes/Helm deployment is not included yet; the compose topology is the
  reference for a future chart.

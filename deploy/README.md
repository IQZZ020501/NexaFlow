# NexaFlow container deployment

Runs the full stack with Docker Compose: PostgreSQL, Redis, FastAPI (`api`),
Celery worker and beat, and the Next.js frontend.

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
| `api` | `deploy/dockerfiles/backend.Dockerfile` | uvicorn |
| `worker` | same backend image | celery worker |
| `beat` | same backend image | celery beat |
| `frontend` | `deploy/dockerfiles/frontend.Dockerfile` | Next.js standalone |

Persistent volumes: `db-data` (PostgreSQL), `redis-data`, and `uploads`
(shared `KNOWLEDGE_STORAGE_DIR` / `CHROMA_PERSIST_DIR` for the API and
worker).

## Configuration

All runtime configuration comes from `deploy/.env` (see `.env.example`).
The compose file overrides `DATABASE_URL` and `CELERY_BROKER_URL` to point at
the bundled services, and mounts the uploads volume for
`KNOWLEDGE_STORAGE_DIR` / `CHROMA_PERSIST_DIR` — the API and worker must
share both directories. `JWT_EXPIRES_MINUTES` controls access token lifetime;
`REFRESH_TOKEN_EXPIRES_DAYS` controls persisted refresh sessions.

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

## Migrations

Run migrations before first start or after upgrading:

```bash
docker compose -f deploy/docker-compose.yml run --rm api alembic upgrade head
```

## Notes

- Bootstrap admin credentials come from env values, never code defaults.
- Keep `JWT_SECRET_KEY` / `MODEL_SECRET_KEY` stable across restarts;
  rotating them invalidates sessions and encrypted model credentials.
- Kubernetes/Helm deployment is not included yet; the compose topology is the
  reference for a future chart.

# NexaFlow

AI-native team workspace platform. Teams get workspace-scoped knowledge bases
with RAG, LLM-powered agents, and MCP tool integration — with a trilingual UI
(Simplified Chinese / Traditional Chinese / English).

## Features

- **Workspaces & teams** — multi-tenant resource isolation, three-tier admin
  hierarchy, role-based access control on every resource
- **Knowledge base with RAG** — upload → parse → chunk → embed into Qdrant;
  retrieval ranking with parent-context windows; durable deletion cleanup
  through Celery
- **LLM agents** — durable queued execution, checkpoints, replayable events,
  explicit knowledge retrieval policy, MCP approval, and conversation memory
- **MCP integration** — workspace-scoped Streamable HTTP server registrations
  with encrypted bearer tokens and private-network controls
- **Admin audit logs** — admin actions tracked through a system log
- **Trilingual UI** — zh-Hans / zh-Hant / en dictionaries kept in sync by
  type-checked keys

## Tech stack

- **Backend**: FastAPI (Python ≥3.11), SQLAlchemy async, PostgreSQL, Celery +
  Redis, Qdrant
- **Frontend**: Next.js 15 (App Router), React 19, TypeScript, Bun,
  shadcn/ui, Tailwind CSS
- **Deploy**: Docker Compose, Nginx

## Repository layout

```text
backend/   FastAPI application (api → application → shareddomain/capabilities → infrastructure)
frontend/  Next.js application (app routes, components, i18n, lib/api)
deploy/    Docker Compose topology, Dockerfiles, Nginx examples
docs/      module documentation — start at docs/INDEX.md
```

## Background worker

Knowledge processing and Agent runs are published to Redis through Celery.

```bash
uv run celery -A app.infrastructure.celery:celery_app worker --loglevel=INFO
```

The app selects Celery's `solo` pool on macOS to avoid unsafe HTTPS work after
process forks; Linux workers keep the production `prefork` pool.

Set `CELERY_BROKER_URL` for Redis. The API process and every worker must share
the configured `KNOWLEDGE_STORAGE_DIR` and connect to the same `QDRANT_URL`;
otherwise workers can miss uploaded files or write vectors to a different
Qdrant instance.

Run one Celery Beat process for storage-cleanup and Agent lease recovery. Agent
workers, the API, and Beat must use the same PostgreSQL database and Redis
broker. Agent answer and reasoning deltas use bounded, short-lived Redis
Streams while checkpoints, process events, and terminal answers stay in
PostgreSQL. Closing an Agent event stream only stops observation; it does not
cancel the durable run. If Redis live reads fail, the client still receives the
durable terminal answer.

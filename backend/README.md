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
- **LLM agents** — provider-agnostic model registry, run orchestration with
  error classification, conversation memory, and built-in tools
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

Knowledge document preview and indexing are published to Redis through Celery.

```bash
uv run celery -A app.infrastructure.celery:celery_app worker --loglevel=INFO
```

Set `CELERY_BROKER_URL` for Redis. The API process and every worker must share
the configured `KNOWLEDGE_STORAGE_DIR` and connect to the same `QDRANT_URL`;
otherwise workers can miss uploaded files or write vectors to a different
Qdrant instance.

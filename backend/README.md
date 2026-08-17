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
- **MCP integration** — workspace-scoped Streamable HTTP, legacy SSE, and
  operator-managed stdio registrations with transport-specific safety controls
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
uv run celery -A app.infrastructure.celery:celery_app worker --beat --loglevel=INFO
```

The app selects Celery's `solo` pool on macOS (unsafe HTTPS work after process
forks) and Windows (the `prefork` pool needs `os.fork()`, which Windows lacks);
Linux workers keep the production `prefork` pool.

On Windows the API and worker also install the `WindowsSelectorEventLoopPolicy`
so psycopg async connections work (Windows defaults to the Proactor loop,
which psycopg rejects).

Set `CELERY_BROKER_URL` for Redis. The API process and every worker must share
the configured `KNOWLEDGE_STORAGE_DIR` and connect to the same `QDRANT_URL`;
otherwise workers can miss uploaded files or write vectors to a different
Qdrant instance.

The worker embeds the single Celery Beat scheduler for storage-cleanup,
Knowledge task, and Agent lease recovery. Do not run another Beat process or
scale this combined worker command above one instance. The worker and API must
use the same PostgreSQL database and Redis broker. Agent answer and reasoning
deltas use bounded, short-lived Redis Streams while checkpoints, process
events, and terminal answers stay in PostgreSQL. Closing an Agent event stream
only stops observation; it does not cancel the durable run. If Redis live reads
fail, the client still receives the durable terminal answer.

Python Tools and Workflow code nodes require the network-disabled sandbox Unix
socket, which is mounted only into the Compose worker. For local development,
start the sandbox-capable worker from `backend/`:

```bash
make worker-compose
```

The host-only `make worker` command remains useful for tasks that do not execute
Python code, but it cannot run Python Tools or Workflow code nodes because the
sandbox socket is intentionally unavailable on the host.

## MCP transports

Streamable HTTP and legacy SSE registrations accept an HTTP(S) URL and an
optional encrypted Bearer token. Private and loopback addresses are rejected by
default and require `MCP_ALLOW_PRIVATE_NETWORKS=true`. HTTP clients ignore proxy
environment variables and redirects. Prefer HTTPS when credentials or sensitive
data cross an untrusted network.

Workspace admins enter each stdio Server's absolute command, arguments,
optional absolute working directory, and environment variables in the MCP
registration form. NexaFlow validates the executable before discovery and
encrypts the full configuration at rest; list responses expose only the command
path. The SDK starts the executable directly without a shell. Install the same
pinned executable at the same path in every API and worker image. Because stdio
commands run with the backend process's filesystem and network access, only
trusted workspace admins should be allowed to manage MCP Servers.

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
- **Frontend**: Next.js 16 (App Router), React 19, TypeScript, Bun,
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

Backend entry points, Alembic, and Celery load the repository-root `.env`.
Create it from `.env.example`; do not create a second file under `backend/`.
When `DATABASE_URL` is empty, the backend safely constructs it from the shared
`POSTGRES_*` components.

```bash
uv run celery -A app.infrastructure.celery:celery_app worker --beat --loglevel=INFO
```

The app selects Celery's `solo` pool on macOS (unsafe HTTPS work after process
forks) and Windows (the `prefork` pool needs `os.fork()`, which Windows lacks);
Linux workers keep the production `prefork` pool.

On Windows the API and worker also install the `WindowsSelectorEventLoopPolicy`
so psycopg async connections work (Windows defaults to the Proactor loop,
which psycopg rejects).

The `dev` target starts and waits for the Compose PostgreSQL, Redis, and Qdrant
services, applies Alembic migrations, and then starts the API through a Python
standard-library script. It does not start the Worker. The `coverage` target also delegates process
orchestration to Python, so GNU Make can run both targets from Windows
PowerShell or Command Prompt without Bash. GNU Make itself must still be
installed separately on Windows. Run the API and Worker inside WSL2 when code
execution is required; the native Windows Worker fails closed.

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

Python artifact Tools and Workflow code nodes use a private Unix socket owned by
the Worker-supervised sandbox Broker. Start the source Worker from `backend/`:

```bash
make worker
```

`make worker` syncs the separate `sandbox/` runtime and starts both the Broker
and Celery. Linux uses namespace/chroot isolation and requires root startup;
macOS uses Seatbelt per child. Native Windows is unsupported; use WSL2.

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

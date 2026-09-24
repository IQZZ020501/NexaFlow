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
  adaptive knowledge retrieval, tool approval modes, and conversation memory
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
backend/   FastAPI application (api → application → domain/adapters + ports → infra)
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
make worker
```

`make worker` runs `scripts/worker.py`, which execs
`python -m celery -A app.infra.queue.celery:celery_app worker --beat
--queues=celery,agents-legacy,agents-v2 --pool <platform pool>`. It requires
`OPENSANDBOX_API_KEY` and exits otherwise: there is no host execution fallback.
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

Python artifact Tools, Skill scripts, stdio MCP and Workflow code nodes run in
the external OpenSandbox execution plane through `app/ports/execution.py`
(`app/adapters/execution/opensandbox.py`); the business Worker keeps
`cap_drop: ALL` plus default AppArmor/seccomp and `no-new-privileges`, holds no
Docker socket, and has no local execution fallback. Program egress is denied by
default (`dns+nft`); only deployment-approved stdio-MCP domains and temporary
package-registry domains are allowed.

The app selects Celery's `threads` pool on macOS so Agent runs can overlap
without prefork inheriting live HTTPS clients. Windows keeps the `solo` pool
because `prefork` needs `os.fork()`; Linux workers use production `prefork`.
On Windows the API and worker also install the `WindowsSelectorEventLoopPolicy`
so psycopg async connections work.

The `dev` target starts and waits for the Compose PostgreSQL, Redis, and Qdrant
services, applies Alembic migrations, and then starts the API through a Python
standard-library script. It does not start the Worker. The `coverage` target
also delegates process orchestration to Python, so GNU Make can run both targets
from Windows PowerShell or Command Prompt without Bash; GNU Make itself must
still be installed separately on Windows. The Worker requires
`OPENSANDBOX_API_KEY` on every platform, and native Windows is not a supported
development target — use WSL2.

## MCP transports

Streamable HTTP and legacy SSE registrations accept an HTTP(S) URL and an
optional encrypted Bearer token. Private and loopback addresses are rejected by
default and require `MCP_ALLOW_PRIVATE_NETWORKS=true`. HTTP clients ignore proxy
environment variables and redirects. Prefer HTTPS when credentials or sensitive
data cross an untrusted network.

Workspace admins enter each stdio Server's absolute command, arguments,
optional absolute working directory, environment variables, and egress domains
in the MCP registration form. NexaFlow validates the stdio configuration shape
and bounds, then encrypts the full configuration at rest; list responses expose
only the command path. Command, working directory, and environment values are
execution-image paths, never business-host paths: discovery and calls run in
per-invocation OpenSandbox sessions with only that integration's environment and
approved egress, and there is no backend-process fallback. Only trusted
workspace admins should be allowed to manage stdio MCP Servers.

# NexaFlow

NexaFlow is a monorepo organized by runtime boundary, then by technical role
and business domain.

```text
frontend pages and components (Next.js)
        ↓
frontend API client modules (frontend/lib/api)
        ↓
backend HTTP layer (backend/app/api) — /api/v1
        ↓
backend business layer (backend/app/services)
        ↓
models / schemas / LLM providers / Celery tasks
        ↓
PostgreSQL + Redis + ChromaDB + local storage
```

## Repository layout

```text
.
├── backend/              FastAPI API, Celery worker, persistence, migrations
├── frontend/             Next.js application (App Router)
├── deploy/               Docker Compose, Dockerfiles, Nginx examples
├── docs/                 Product and engineering documentation
├── scripts/              Repository-level maintenance scripts
├── imgs/                 README and brand images
├── .github/workflows/    Repository CI
├── .githooks/            Git hooks (enable via scripts/setup-hooks.sh)
├── AGENTS.md             Repository contribution rules
├── LICENSE               Project license
└── README.md             Repository architecture and entry points
```

Generated directories such as `.git/`, `.codegraph/`, `backend/.venv/`,
`frontend/node_modules/`, `frontend/.next/`, `backend/storage/`,
`__pycache__/`, and local `.env` files are not source-code layers.

## Backend

```text
backend/
├── alembic/              Database migration environment and versions
├── app/             Importable FastAPI application package
│   ├── main.py           App factory, middleware, router registration
│   ├── api/              HTTP layer: auth dependencies (deps.py) and v1 routers
│   │   └── v1/
│   │       ├── api.py    /api/v1 router aggregation
│   │       ├── endpoints/  Platform-facing routers (auth, workspaces, teams,
│   │       │              knowledge, models, ...)
│   │       └── admin/    Global-admin routers (users, audit logs)
│   ├── application/      Use cases (identity, workspace management)
│   ├── domain/           Shared domain entities (User, Workspace, Team, permissions)
│   ├── shareddomain/     Module-owned business domains
│   │   ├── agents/       Agent definitions, permissions, and bounded loop
│   │   ├── knowledge/    Entities, services, processing, task runner
│   │   ├── tools/        Workspace MCP Server registry and bindings
│   │   ├── teams/        Team services
│   │   └── audit/        Audit services
│   ├── capabilities/      AI capabilities
│   │   ├── llm/          Provider catalogs, runtime, model registry
│   │   ├── mcp/          Streamable HTTP MCP client and safety checks
│   │   ├── rag/          Retrieval
│   │   └── embedding/    Chunking and vectorization
│   ├── infrastructure/   Config, security, DB session, data access, system log
│   │   └── repositories/ SQLAlchemy query implementations
│   ├── schemas/          Pydantic request and response contracts by domain
│   └── tasks/            Celery task entry points
├── tests/            Executable regression suites (python -m tests.<suite>)
│   └── support.py        Shared test database and application helpers
├── .env.example          Runtime configuration template
├── alembic.ini           Alembic configuration
├── main.py               Compatibility ASGI entry point
├── Makefile              Development, migration, and worker commands
├── pyproject.toml        Python metadata and dependencies
└── uv.lock               Locked Python dependency graph
```

Backend code mixes technical layers with module-owned business domains:

| Layer | Responsibility |
|---|---|
| `api/v1/` | Async FastAPI routes and HTTP-level validation |
| `application/` | Cross-domain use cases (auth, workspace management) |
| `domain/` | Shared domain entities and rules |
| `shareddomain/<feature>/` | Self-contained business domain modules |
| `capabilities/` | Model runtime, retrieval, embedding capabilities |
| `infrastructure/` | Config, DB session, data access, external services |
| `schemas/` | Pydantic request and response contracts |
| `tasks/` | Celery task entry points |

The knowledge domain spans several modules because parsing and indexing cross
the API/worker runtime boundary:
`tasks/knowledge.py` is the Celery entry point,
`shareddomain/knowledge/task_runner.py` owns task execution and leases,
`capabilities/embedding/pipeline.py` parses and indexes documents, and the
`*_api.py` endpoint modules expose lifecycle, retrieval, and compatibility
routes. The LLM domain keeps provider catalogs under `capabilities/llm/providers/` so
provider-specific metadata stays out of the generic runtime.

## Frontend

```text
frontend/
├── app/                  Next.js App Router pages and layouts
│   ├── (auth)/login/     Authentication pages
│   ├── (platform)/app/   User workspace pages (apps, knowledge, models, tools)
│   └── (dashboard)/system/  Global-admin pages (workspaces, teams, users, audit)
├── components/           Shared components
│   ├── ui/               Domain-neutral shadcn/Radix primitives
│   ├── app/              Application-shell UI (top bar, session gate)
│   ├── auth/             Login screen and password dialogs
│   ├── knowledge/        Knowledge base pages and dialogs
│   ├── agents/           Agent configuration and live RAG/MCP test panel
│   ├── tools/            MCP Server management
│   ├── system/           System-admin panels and dialogs
│   ├── llm/              Model management page
│   └── pages/            Generic placeholder pages
├── contexts/             Language, theme, and session providers
├── hooks/                Shared hooks
├── i18n/                 Trilingual dictionaries (zh-Hans, zh-Hant, en)
├── lib/
│   ├── api-client.ts     Shared fetch wrapper
│   └── api/              Feature API modules (auth, system, knowledge, agents, MCP, llm)
├── public/               Files served without bundling, including provider icons
├── tests/                Bun tests
├── components.json       shadcn/ui configuration
├── next.config.ts        Next.js configuration and dev proxy
└── bun.lock              Locked frontend dependency graph
```

Every user-facing string goes through `t()` from `@/i18n` (type-checked
trilingual dictionaries). Feature API calls live in `lib/api/` and share
`lib/api-client.ts`. Session state (token, workspaces, teams, notifications)
lives in `contexts/session-context.tsx`.

## Runtime entry points

Run the API and the web app together for local development:

```bash
cd backend
make dev          # FastAPI on http://localhost:8000 (runs migrations first)
```

```bash
cd frontend
bun install
bun run dev       # Next.js on http://localhost:3000, proxies /api to :8000
```

Background workers:

```bash
cd backend
make worker       # Celery worker (knowledge parsing and indexing)
```

The API and worker processes must share `KNOWLEDGE_STORAGE_DIR` and
`CHROMA_PERSIST_DIR`. Containerized deployments (PostgreSQL, Redis, API,
worker, beat, frontend) are defined under `deploy/`; see `deploy/README.md`.

## Verification

Backend regression suites run from `backend/` with
`uv run python -m tests.<suite>` (identity, workspaces, teams, knowledge,
agents, llm, test_main). Frontend checks: `bun run typecheck`, `bun run lint`,
`bun test`, `bun run build`. CI runs the same gates on every pull request.

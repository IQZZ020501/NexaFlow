# NexaFlow

NexaFlow is a monorepo organized first by runtime boundary, then by technical
role and business domain.

```text
frontend feature UI
        ↓
frontend feature API modules
        ↓
shared HTTP client
        ↓
backend domain routers
        ↓
domain services and repositories
        ↓
PostgreSQL / Redis / ChromaDB / local storage
```

## Repository layout

```text
.
├── backend/              FastAPI API, Celery worker, persistence, migrations
├── frontend/             React/Vite single-page application
├── docs/                 Product and engineering documentation
├── .github/workflows/    Repository CI
├── AGENTS.md             Repository contribution rules
├── LICENSE               Project license
└── README.md             Repository architecture and entry points
```

Generated directories such as `.git/`, `.codegraph/`, `backend/.venv/`,
`frontend/node_modules/`, `frontend/dist/`, `backend/storage/`, `__pycache__/`,
and local `.env` files are not source-code layers.

## Backend

```text
backend/
├── alembic/              Database migration environment and versions
├── nexaflow/             Importable FastAPI application package
│   ├── main.py           App factory, middleware, router registration, SPA host
│   ├── testing.py        Shared test database and application helpers
│   ├── main_test.py      Application and SPA fallback smoke checks
│   ├── core/             Configuration, secrets, validation, seed data, Celery
│   ├── db/               SQLAlchemy base, sessions, and model helpers
│   ├── audit/            Audit-log domain
│   ├── identity/         Authentication, users, authorization dependencies
│   ├── workspaces/       Workspace tenancy domain
│   ├── teams/            Team and membership domain
│   ├── knowledge/        Knowledge bases, documents, retrieval, processing jobs
│   ├── llm/              Model registry, runtime, and provider catalogs
│   ├── resource_permissions/  Cross-resource permission persistence
│   └── system_logs/      Operational error-log persistence
├── .env.example          Runtime configuration template
├── alembic.ini           Alembic configuration
├── main.py               Compatibility ASGI entry point
├── Makefile              Development, migration, and worker commands
├── pyproject.toml        Python metadata and dependencies
└── uv.lock               Locked Python dependency graph
```

Business domains use a vertical slice. A typical domain contains:

| File | Responsibility |
|---|---|
| `api.py` | Async FastAPI routes and HTTP-level validation |
| `schemas.py` | Pydantic request and response contracts |
| `services.py` | Business workflows, authorization, and transactions |
| `repositories.py` | Reusable SQLAlchemy queries |
| `models.py` | SQLAlchemy persistence models |
| `test.py` | Executable domain regression checks |

The knowledge domain has additional modules because parsing and indexing cross
the API/worker runtime boundary: `tasks.py` is the Celery entry point,
`task_runner.py` owns task execution and leases, `pipeline.py` parses and
indexes documents, and the `*_api.py` modules expose lifecycle, retrieval, and
compatibility routes. The LLM domain keeps provider catalogs under
`llm/providers/` so provider-specific metadata stays out of the generic runtime.

## Frontend

```text
frontend/
├── public/               Files served without bundling, including provider icons
├── src/
│   ├── main.tsx          Browser entry point
│   ├── app/              Root composition, routing, session, notifications
│   ├── components/
│   │   ├── app/          Cross-feature application-shell UI
│   │   └── ui/           Domain-neutral shadcn/Radix primitives
│   ├── features/         Feature-owned UI, API calls, types, and local helpers
│   ├── lib/              Shared HTTP client, i18n, DOM, and small utilities
│   └── styles/           Tailwind theme tokens and global styles
├── tests/                Cross-feature Bun tests
├── components.json       shadcn/ui configuration
├── package.json          Bun scripts and JavaScript dependencies
├── vite.config.ts        Vite aliases, plugins, and development proxy
└── bun.lock              Locked frontend dependency graph
```

Feature modules currently cover `auth`, `knowledge`, `llm`, and `system`.
Feature-specific API calls remain next to their feature; all of them share
`src/lib/api-client.ts`. Route parsing and app-wide state stay in `src/app/`,
while reusable visual primitives stay in `src/components/ui/`.

## Runtime entry points

Run commands from the runtime directory they belong to:

```bash
cd backend
make dev
make worker
```

```bash
cd frontend
bun install
bun run dev
```

The production backend serves `frontend/dist/` when it exists. Override that
location with `WEB_DIST_DIR` for split or custom deployments. API and Celery
worker processes must share `KNOWLEDGE_STORAGE_DIR` and `CHROMA_PERSIST_DIR`.

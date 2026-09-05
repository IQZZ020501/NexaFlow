# AGENTS.md

Instructions for coding agents working in this repository. The applicable
global instructions remain in force; this file adds narrower repository rules
and overrides generic Skill guidance only where it explicitly describes the
current stack or workflow. It applies to the entire repository unless a more
specific `AGENTS.md` exists in a subdirectory.

Treat each rule as scoped to the files or workflow it names. A command example
or release procedure is not authorization to modify external state.

## 1. Required Skills

- Before implementing FastAPI routes, dependencies, request/response schemas,
  or streaming behavior, read and follow `fastapi` where it is compatible with
  this repository.
- Before implementing or reorganizing React/Next.js components, routes, or
  frontend directory structure, read and follow `react-templates` where it is
  compatible with this repository.
- Documentation-only changes, read-only investigation, and work outside those
  surfaces do not trigger these Skills unless their guidance is directly
  relevant.
- Repository rules and inspected local patterns override generic Skill
  defaults. In particular, keep the existing Next.js deployment, SQLAlchemy
  `AsyncSession`, async route, and project-tooling conventions; do not introduce
  FastAPI static frontend serving, SQLModel, synchronous database paths, or new
  tooling merely because a Skill recommends them generically.
- If an applicable Skill is unavailable, state that before coding and proceed
  from repository evidence when the task remains unambiguous; stop only when
  the missing guidance leaves a material implementation or safety decision.

## 2. Project Notes

These facts and constraints apply only when a change touches the named area.
Existing exceptions in the codebase are not precedents for new code and should
not trigger unrelated cleanup.

- `backend/` is a Python project using `pyproject.toml`, Python `>=3.11`, and
  `uv.lock`. `backend/app/` contains the FastAPI backend package.
- Backend routes are async FastAPI with SQLAlchemy `AsyncSession`; do not add
  new synchronous database access paths.
- Backend code follows a hybrid layer + domain layout: technical layers
  (`api/` HTTP, `application/` use cases, `capabilities/` model/rag/embedding
  capabilities, `infrastructure/` config, DB session, data access, storage)
  cross-cut module-owned business domains under `shareddomain/` and shared
  domain entities under `shareddomain/platform/` (User, Workspace, Team, permissions).
  Schemas stay in `app/schemas/` and Celery task entry points in `app/tasks/`.
  When adding a new business domain, add a self-contained module directory
  under `app/shareddomain/<feature>/` (entities plus services), expose use cases
  through `app/application/`, and keep HTTP routers thin in `app/api/v1/`.
- Apply this dependency direction to new or changed backend code:
  - `api/v1/` routers keep HTTP concerns thin and use `application/`,
    `schemas/`, and `api/deps.py`. Existing direct imports from `entities/` or
    `infrastructure/` are legacy exceptions: do not expand them, and do not
    refactor them unless the requested change requires it.
  - `application/` may import `entities/`, `shareddomain/`, `ports/`,
    `infrastructure/`, and `schemas/`. It accesses capabilities through
    `app/ports/`, except for pure capability algorithms or validation functions
    it deliberately composes directly (for example retrieval ranking math or
    credential normalization).
  - Business services under `shareddomain/` may import `entities/`, `ports/`,
    `infrastructure/`, `schemas/`, and other domain modules, but never
    `application/` or concrete capability implementations.
  - `capabilities/` may import `infrastructure/` and its own modules, but never
    `shareddomain/`, `schemas/`, or `application/`.
  Business rules and status constants live in `shareddomain/` (repositories
  import them from the domain models). Consume infrastructure through an
  interface where implementation swapping matters (for example
  `infrastructure/object_storage.py::ObjectStorage`); domain services must not
  import the concrete implementation.
- Capability contracts live in `app/ports/` (Protocols plus delegate functions
  for vector store, LLM providers, document parsing, MCP client, and model
  registry). Swapping an implementation (for example Qdrant to Milvus) should
  touch only the capability module and its port factory.
- Data isolation: pure domain entities live in `app/entities/` (dataclasses
  mirroring the database columns); `app/shareddomain/platform/` and other
  `app/shareddomain/*/models.py` hold the SQLAlchemy database models.
  Repositories (`app/infrastructure/repositories/`) map ORM ↔ entities via
  `mapping.py` helpers and own all `db.add/delete/refresh/flush`; business
  services in `shareddomain/` and `application/` use entities rather than ORM
  models and coordinate transactions via the `db` unit-of-work
  (`db.commit()`/`db.rollback()`). New models: add the entity to
  `app/entities/`, keep the ORM class in its current models module
  (`app/shareddomain/platform/` for cross-domain shared entities), and
  expose create/save/refresh/delete wrappers on the repository. ORM model
  modules and explicit model-registration imports are the narrow exceptions;
  they are not a pattern for business logic.
- Agent Run persistence separates identity/caller/lineage in `agent_runs`,
  mutable lease/checkpoint/result data in `agent_run_states`, immutable
  execution configuration in `agent_run_snapshots`, and append-only history
  in `agent_run_events`. All Agent, Workflow, and test Tool executions use
  `tool_invocations`; do not recreate an `agent_tool_calls` table or dual-write
  ledger.
- `backend/tests/unit.py` is a pure unit suite (no DB, no HTTP, no network)
  for business rules and services with mocked ports/repositories; run it like
  the other suites with `uv run python -m tests.unit`.
- Large domain modules are split by concern with a facade keeping the public
  API stable: `application/agents.py` re-exports `agent_tools.py` (tool
  construction, pure mappers) and `agent_runs.py` (run orchestration);
  `shareddomain/knowledge/services.py` re-exports `kb.py`, `documents.py`,
  and `permissions.py`. Keep this pattern when a domain module grows:
  implementation files per concern, facade module for importers.
- Hand-written SQL goes under `backend/app/infrastructure/sql/<feature>/` for
  explicit write workflows, seed data, and complex queries; keep parameter
  binding in Python services.
- Root `.env.example` is the only environment template; host backend commands
  and Compose both read root `.env`, while Compose explicitly overrides
  container-only endpoints. It also selects the unified application and custom
  PostgreSQL image tags for pull-only deployments. Real `.env` files are
  local-only and gitignored; bootstrap admin credentials and managed-user
  initial passwords must come from env values, not Python constants.
- `backend/alembic/` contains database migrations; production data is
  PostgreSQL-backed.
- The build-capable and pull-only Compose topologies both run Alembic through a
  one-shot `migrate` service. API and worker startup depends on its successful
  completion; the service reuses the application image rather than requiring a
  separate migration image.
- Knowledge keyword retrieval uses `pg_search` 0.25.2 BM25 over
  `knowledge_document_chunks.search_text` with the Jieba tokenizer. The bundled
  PostgreSQL 17 image installs that pinned extension plus its `pgvector`
  dependency; external PostgreSQL deployments must install both before running
  migrations and preload `pg_search` before PostgreSQL starts. Qdrant remains
  the application vector store. Do not silently fall back to `ts_rank_cd`,
  because that changes the declared ranking semantics.
- Evidence Graph entities, claims, evidence, reviews, schemas, revisions and
  relationships are authoritative in PostgreSQL. Qdrant's graph Profile
  collection is a derived, rebuildable index; never use it as the source of
  truth or delete PostgreSQL Graph history to repair it.
- Regression suites live in `backend/tests/` and run from `backend/` with
  `uv run python -m tests.<suite>`.
- Knowledge parsing, indexing, and durable deletion cleanup run through Celery
  with Redis; API and worker instances must share `KNOWLEDGE_STORAGE_DIR` and
  use the same `QDRANT_URL`. Deletion cleanup intent is persisted in
  `knowledge_storage_cleanups`; Celery Beat redispatches due records, so do not
  replace it with best-effort post-commit cleanup.
- Graph incremental and rebuild work uses the leased `KnowledgeTask` runner
  (`graph_sync` / `graph_rebuild`). Celery Beat's graph reconcile recovers
  expired work, orphaned revisions, and Profile repair intents; it must remain
  persistent and retryable rather than becoming best-effort post-commit work.
- Knowledge retrieval evaluation also runs through the leased Celery knowledge
  task runner and reuses the production retrieval path. Evaluation is mutually
  exclusive with parse/index/rebuild work for the same knowledge base; result
  and progress writes must remain in one lease-checked transaction.
- `cd backend && make dev` starts and waits for the development Compose PostgreSQL,
  Redis, and Qdrant services, applies Alembic migrations, then starts Uvicorn.
  It does not start the Worker. The API process orchestration lives in
  `backend/scripts/dev.py` so the Make target does not depend on a POSIX shell.
- `cd backend && make worker` syncs the separate `sandbox/` Python runtime and
  starts the Celery worker plus its supervised source sandbox Broker. Linux uses
  namespace/chroot isolation and requires root startup; macOS uses Seatbelt per
  child; native Windows fails closed and must use WSL2.
- Agent and workflow uploads are one-time and expire after 24 hours. Cleanup
  intent is persisted in `workflow_upload_storage_cleanups` and recovered by
  Celery Beat; user, Agent, and workspace deletion must queue cleanup first.
- Agent-generated files use safe filenames with arbitrary common extensions,
  are capped at 5 MiB, stored in PostgreSQL for at most 24 hours, and downloaded
  through scoped signed bearer URLs. Every response is an attachment with
  `nosniff`; HTML additionally receives a restrictive CSP.
- Identity email uses the global administrator SMTP settings and trusted site
  URL. Invitation, welcome, and password-change messages are persisted as
  encrypted `email_deliveries` and recovered by Celery Beat; password-reset
  links store only a token hash and expire after 30 minutes.
- Knowledge parsing uses MarkItDown for DOCX, PPTX, XLSX, and XLS; PDF Markdown
  conversion uses PyMuPDF4LLM/PyMuPDF with native text first and page-level OCR
  fallback. The upload UI and parser accept DOCX, PDF, Markdown, text, common
  UTF-8 source/configuration files, PPTX, XLSX, XLS, HTML, CSV, JSON, XML, IPYNB,
  EPUB, ZIP, PNG, JPG, JPEG, and WEBP. The unified application image must include
  Tesseract Chinese/English data for OCR fallback.
- QA-table import is opt-in (`import_mode=qa`) and uses read-only openpyxl for
  XLSX plus the Python CSV module for UTF-8 CSV. It requires question/answer
  headers, ignores document segmentation settings, and indexes question plus
  answer while returning the answer as chunk content.
- Workflow custom reply nodes render Jinja2 templates in a sandboxed environment;
  undefined variables fail the node, and reference-only replies stringify one
  selected upstream field.
- MCP tools use workspace-scoped Streamable HTTP, legacy SSE, or stdio Server
  registrations. Remote Bearer tokens and full stdio configurations are
  encrypted; remote endpoints may use HTTP or HTTPS, while private and loopback
  addresses require `MCP_ALLOW_PRIVATE_NETWORKS=true`. Workspace admins submit
  stdio commands, arguments, working directories, and environment values, so
  deployments must trust MCP-managing admins with backend process-level code
  execution.
- `frontend/` is a Next.js (App Router) + TypeScript app using Bun, shadcn/ui,
  and Tailwind CSS. Pages live under the `src/app/` route groups `(auth)`,
  `(platform)`, `(dashboard)`, and `(public)` (anonymous share pages for
  published agents and Agent API docs); shared components in `src/components/`,
  providers in `src/contexts/`, trilingual dictionaries in `src/i18n/`, and
  feature API modules in `src/lib/api/`.
- Every new user-navigable frontend page must have a stable App Router entry
  under `frontend/src/app/`; do not leave navigation-level views only in component
  state. Dialogs and responsive panels remain component states unless they are
  intentionally promoted to pages.
- `sandbox/` is an independent Python execution service for Workflow code nodes
  and Agent-generated downloadable files. It accepts bounded JSON-line requests
  over a private Unix socket and runs each program with CPU, memory, process,
  file, wall-clock, input, and output limits. Its Artifact runtime includes
  python-docx, PyMuPDF, openpyxl, python-pptx, Pillow, and the standard library.
  Optional `SANDBOX_NETWORK=public` uses a Worker-owned HTTP(S) egress proxy;
  direct sockets and private/loopback/metadata destinations remain blocked.
  NexaFlow-authored `documents`, `pdf`, `pptx`, and `spreadsheets` Skills live
  under `sandbox/skills`; each declares a read-only renderer entrypoint and
  artifact format in `SKILL.md` and is registered as a fixed selectable
  built-in Tool. Fixed Skill Tools accept content/data rather than
  caller-supplied Python.
  Selected `requirements.txt` files install into a temporary per-run directory
  through that proxy.
  Keep it independent from `backend/app/`; only the Worker supervisor may start
  or reach its socket.
- `docs/` stores project planning and product/engineering documentation.
- `deploy/` holds the Docker Compose topology, the unified application
  Dockerfile shared by API/worker/frontend containers, the custom PostgreSQL
  Dockerfile, and Nginx examples. The production Worker supervises the sandbox
  source inside its own container and creates a private network/mount/PID/IPC/UTS
  namespace plus chroot before starting Celery. `NET_ADMIN` is used only to
  bring up namespace-local loopback for the egress relay, then dropped. Its outer Docker AppArmor
  profile is unconfined so those mount operations are permitted; default seccomp
  and `no-new-privileges` remain enabled. There is no sandbox service or socket
  volume. `scripts/setup-hooks.sh` enables the repository Git hooks.
- Use `rg` / `rg --files` for code search. Do not invent project commands;
  inspect local scripts first.

## 3. Implementation

- Treat an end-to-end MVP feature as a production slice, not a throwaway demo:
  evaluate the data model, backend behavior, authorization and tenant isolation,
  frontend behavior, validation and error states, checks, and deployment impact
  that are actually affected. Do not implement unaffected layers merely to
  complete this checklist. If the requested slice cannot be production-safe
  without an unrequested foundation, surface that decision instead of shipping
  a knowingly unsafe workaround.
- Fix the root cause at the narrowest shared boundary; check callers before
  patching.
- Reuse existing helpers and patterns before adding new code or dependencies.
- File size is a soft signal, not a hard rule: prefer focused files, and
  split when a file grows long enough that a clear module or component
  boundary exists; avoid very large source files unless they are generated or
  mostly static data.
- Prefer pure functions for reusable transformations; keep side effects at
  workflow edges.

### Trilingual i18n

- Every user-facing string must go through `t()` from `@/i18n` — never
  hardcode Chinese text in components or utilities.
- New UI copy must be added to all three dictionaries (`zhHans`, `zhHant`,
  `en`) in the same change; the dictionaries are type-checked to stay in
  sync, so missing keys fail the build.
- Applies to components, hooks, utilities, labels, aria-labels, and
  notification messages.

## 4. Subagents

Subagents are optional. Use them only when broad work splits into independent,
non-overlapping objectives and delegation materially helps. Work directly when
the task is targeted or sequential. Keep delegated exploration read-only unless
implementation is explicitly assigned, never assign overlapping edits, and
verify material findings against the cited files and lines before relying on
them.

## 5. Planning

- Use a short plan before editing for multi-step, cross-module, uncertain, or
  high-risk work. Simple, low-risk changes do not need one.
- State the goal, scope, non-goals, acceptance criteria, and validation at the
  level needed for the task; include risks and a rollback path only when they
  are material.
- A plan is not an approval gate. Continue the authorized work after stating it
  unless missing information materially changes the result or the next step
  exceeds the user's authority grant.
- If implementation would materially change user-visible scope, public
  behavior, risk, or cost beyond the request, stop and request direction.

## 6. Workflow

- `main` is protected: every change lands via a pull request; direct pushes
  are rejected.
- When the user asks for a standalone branch or PR-ready delivery, start from an
  up-to-date `main` on a short-lived branch when doing so will not disturb
  existing work. For an in-place local task, keep the current branch and
  preserve uncommitted changes. Do not add Codex-specific branch prefixes or
  markers.
- Commit messages follow Conventional Commits (`<type>(<scope>): <summary>`),
  matching the PR title style, so history stays readable.
- When the user has requested the external delivery steps, push the branch,
  open a PR (title and description per Pull Request Guidelines), wait for CI,
  then merge with a merge commit and delete the branch. Pushing, opening or
  updating a PR, merging, tagging, and deleting remote branches remain external
  writes and require the confirmation or authority specified by the applicable
  global rules.
- Before an authorized merge, sync `main` into the branch and resolve conflicts.

## 7. Pull Request Guidelines

These guidelines apply when preparing or creating a PR; they do not require
every local task to create one.

### PR Title Format

Use a Conventional Commits style title in English:

```text
<type>(<scope>): <summary>
```

Use these types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
`build`, `ci`, `chore`, `revert`. Omit the `scope` when the affected area is
unclear.

Rules:

- Lowercase `type` and `scope`; keep the summary short, specific, and
  action-oriented.
- Do not end the title with a period.
- For breaking changes, add `!` after the type or scope.

Examples:

```text
feat(knowledge): support re-segment options
fix(web): keep dropdowns open on trigger click
docs(readme): update deployment steps
```

### PR Description Template

Use the template below. Fill every section with facts grounded in the actual
change: explain what changed and why the approach works based on your
understanding of the code, not by pasting unedited output. If verification was
not run, say so plainly; if risk is low, state the reason. For multi-commit
PRs, group the change log per commit or per module.

```markdown
## 背景

说明为什么需要这个改动，以及为什么这样改能生效（基于对代码逻辑的理解）。

## 变更类型

- [ ] 🐛 Bug 修复 (Bug fix) - 请关联对应 Issue，避免将设计取舍或预期不一致直接归类为 bug
- [ ] ✨ 新功能 (New feature)
- [ ] ⚡ 性能优化 / 重构 (Refactor)
- [ ] 📝 文档更新 (Documentation)

## 改动内容

- 逐项说明改了什么、为什么；跨模块改动按模块分条。

## 验证方式

- [ ] 本地测试通过（列出实际运行的套件/命令与结果）
- [ ] 相关页面/接口已验证（附截图、关键日志或测试报告）
- [ ] 无需验证，原因：
- [ ] 已知未过/未验证项：如实列出，不隐含为通过

## 风险与影响

说明可能影响的模块、兼容性、回滚方式；风险低时写明原因。

## 关联信息

关联 issue、需求、缺陷或上下游 PR。
```

### Release Tag Naming

For an authorized release, use Semantic Versioning:
`v<major>.<minor>.<patch>`, with `-alpha.N` /
`-beta.N` / `-rc.N` suffixes for prereleases. Prefer annotated tags:

```bash
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
```

## 8. Validation

For code or configuration changes, run the smallest relevant checks first and
broaden only when the affected surface or risk is broad. Documentation-only or
instruction-only changes normally need Markdown/diff inspection rather than
product test suites, unless they change documented commands or executable
examples.

- `frontend/` code or configuration changes: use the smallest relevant Bun
  script from `frontend/package.json` (typecheck, lint, test, build as
  applicable). The full test suite runs as
  `bun test --parallel` (per-file isolation is required: happy-dom state leaks
  between files in serial mode). DOM-level page tests use the happy-dom
  preload in `frontend/bunfig.toml` and helpers in `frontend/tests/helpers/dom.tsx`;
  new DOM test files keep the existing `/* @jsxImportSource react */` header;
  Next.js 16 configures `tsconfig.json` with the `react-jsx` runtime.
- `backend/` Python changes: use the project's Python tooling. Run `compileall`
  over the touched packages, then run the affected suite from `backend/` with
  `uv run python -m tests.<suite>` (unit, logger, smtp, email, system_governance,
  identity, workspaces, teams, knowledge, llm, agents, workflows, mcp_transports, test_main,
  agent_access, workflow_run_coverage, workflow_node_coverage,
  workspace_admin_coverage,
  knowledge_graph, knowledge_graph_edge_coverage, knowledge_domain_coverage,
  knowledge_api_coverage, resource_folders, agent_services_coverage,
  agent_runtime_coverage, infra_unit_coverage). For migration changes,
  run Alembic against the target database or a temporary explicit test
  database. For Celery wiring changes, verify the expected tasks register on
  `celery_app`.
- `deploy/` Compose changes: render the affected base, development, and
  pull-only server configurations and verify the image list. Build an image
  only when its build inputs or wiring changed. When the unified application
  image or sandbox wiring changes, also run the `sandbox-runtime` direct
  container checks and embedded-Worker hard-isolation self-check, including
  public egress mode when affected.
- Run full coverage only for coverage work, release/CI validation, or changes
  broad enough to put a repository gate at risk. Do not claim a percentage
  unless it was measured in the current task. The configured gates and commands
  are:
  - Backend: `make coverage` / `backend/scripts/coverage.sh` — both use the
    cross-platform `backend/scripts/coverage.py` runner to execute all suites
    in parallel (each with an isolated `KNOWLEDGE_STORAGE_DIR`), trace TestClient
    threads and SQLAlchemy greenlets, and merge with coverage.py; the gate is
    97%.
  - Sandbox: `sandbox/run_coverage.sh` — `sandbox/tests.py` extends
    `self_check.py`; `sandbox/child.py` and the Linux-only `sandbox/launcher.py`
    are excluded from measurement because their exec/chroot boundary cannot
    retain a coverage tracer. Their limits and namespace isolation are verified
    behaviorally by the CI Docker runs. Other root/Linux-gated lines carry
    `# pragma: no cover`.
  - Frontend: `frontend/scripts/coverage.sh` — runs `bun test --isolate
    --coverage` (serial + per-file fresh globals; bun's parallel-worker lcov
    aggregation under-reports and inflates the line denominator); the gate is
    99%.

## 9. Keeping This File Current

- Update this file in the same change only when repository structure,
  build/test commands, dependencies, or conventions change in a way that makes
  an instruction here stale.
- If a top-level directory is added, removed, or repurposed, update
  `Project Notes`.
- If scripts or tooling change, update `Validation`.

# AGENTS.md

Instructions for coding agents working in this repository. This file adds
repository-specific rules to the applicable global instructions. It applies to
the entire repository unless a more specific `AGENTS.md` exists in a
subdirectory.

Correctness, safety, evidence, and validation take priority over speed.

## 1. Required Skills

- Backend work must read and follow `fastapi` before implementation.
- Frontend work must read and follow `react-templates`,
  `vercel-react-best-practices` before implementation.
- If a required skill is unavailable, surface that before coding instead of
  silently proceeding.

## 2. Project Notes

- `backend/` is a Python project using `pyproject.toml`, Python `>=3.11`, and
  `uv.lock`. `backend/app/` contains the FastAPI backend package.
- Backend routes are async FastAPI with SQLAlchemy `AsyncSession`; do not add
  new synchronous database access paths.
- Backend code follows a hybrid layer + domain layout: technical layers
  (`api/` HTTP, `application/` use cases, `capabilities/` model/rag/embedding
  capabilities, `infrastructure/` config, DB session, data access, storage)
  cross-cut module-owned business domains under `shareddomain/` and shared
  domain entities under `domain/` (User, Workspace, Team, permissions).
  Schemas stay in `app/schemas/` and Celery task entry points in
  `app/tasks/`. New features: add a self-contained module directory under
  `app/shareddomain/<feature>/` (entities + services), expose use cases
  through `app/application/`, and keep HTTP routers thin in `app/api/v1/`.
- Hand-written SQL goes under `backend/app/infrastructure/sql/<feature>/` for
  explicit write workflows, seed data, and complex queries; keep parameter
  binding in Python services.
- `backend/.env.example` documents initialization env keys. Real `.env` files are
  local-only and gitignored; bootstrap admin credentials must come from env
  values, not Python constants.
- `backend/alembic/` contains database migrations; production data is
  PostgreSQL-backed.
- Regression suites live in `backend/tests/` and run from `backend/` with
  `uv run python -m tests.<suite>`.
- Knowledge parsing and indexing run through Celery with Redis; API and
  worker instances must share `KNOWLEDGE_STORAGE_DIR` and `CHROMA_PERSIST_DIR`.
- MCP tools use workspace-scoped Streamable HTTP Server registrations. Bearer
  tokens are encrypted, and private-network endpoints require
  `MCP_ALLOW_PRIVATE_NETWORKS=true`.
- Agent execution uses LangGraph with PostgreSQL checkpoints in production;
  `AgentRun` is the tenant-scoped read model, and SQLite tests use in-memory
  checkpoints.
- `frontend/` is a Next.js (App Router) + TypeScript app using Bun, shadcn/ui,
  and Tailwind CSS. Pages live under the `app/` route groups `(auth)`,
  `(platform)`, and `(dashboard)`; shared components in `components/`, providers
  in `contexts/`, trilingual dictionaries in `i18n/`, and feature API modules in
  `lib/api/`.
- `docs/` stores project planning and product/engineering documentation.
- `deploy/` holds the Docker Compose topology, Dockerfiles, and Nginx examples;
  `scripts/setup-hooks.sh` enables the repository Git hooks.
- Use `rg` / `rg --files` for code search. Do not invent project commands;
  inspect local scripts first.

## 3. Implementation

- Treat MVP tasks as production slices, not throwaway demos: identify data
  model, backend behavior, authorization and tenant isolation, frontend
  behavior, validation and error states, checks, and deployment impact. If
  production foundation is missing, stop and surface the decision instead of
  working around it.
- Fix the root cause at the narrowest shared boundary; check callers before
  patching.
- Reuse existing helpers and patterns before adding new code or dependencies.
- Keep diffs small and focused: no unrelated refactoring or reformatting;
  remove only code made obsolete by your own change.
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

Use subagents for broad exploration that splits into independent,
non-overlapping objectives. Work directly when the task is targeted or
sequential. Keep exploration read-only unless implementation is explicitly
delegated, never assign overlapping edits, and verify material findings
against the cited files and lines before relying on them.

## 5. Planning

- Use a short plan before editing for multi-step, cross-module, uncertain, or
  high-risk work. Simple, low-risk changes do not need one.
- Plans should state goal, scope, non-goals, steps, acceptance criteria, and
  validation; include risks and a rollback path when material.
- If implementation materially changes user-visible scope, public behavior,
  risk, or cost, stop and request direction.

## 6. Workflow

- `main` is protected: every change lands via a pull request; direct pushes
  are rejected.
- Start each change from an up-to-date `main` on a short-lived feature
  branch. Branch names are free-form; existing history uses
  `codex/<topic>`.
- Commit messages follow Conventional Commits (`<type>(<scope>): <summary>`),
  matching the PR title style, so history stays readable.
- Once ready: push the branch, open a PR (title and description per
  Pull Request Guidelines), wait for CI to pass, then merge; delete the
  branch after merging.
- Merges use merge commits, as in existing history; sync `main` into the
  branch and resolve conflicts before merging.

## 7. Pull Request Guidelines

All changes to `main` must go through a pull request (branch protection).

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

```markdown
## 背景

说明为什么需要这个改动。

## 改动内容

-

## 验证方式

- [ ] 本地测试通过
- [ ] 相关页面/接口已验证
- [ ] 无需验证，原因：

## 风险与影响

说明可能影响的模块、兼容性、回滚方式。

## 关联信息

关联 issue、需求、缺陷或上下游 PR。
```

Fill every section with facts; if verification was not run, say so plainly.
If risk is low, state the reason.

### Release Tag Naming

Use Semantic Versioning: `v<major>.<minor>.<patch>`, with `-alpha.N` /
`-beta.N` / `-rc.N` suffixes for prereleases. Prefer annotated tags:

```bash
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
```

## 8. Validation

Run the smallest relevant checks first, then broaden only when impact is
broad. Never claim a check passed unless it completed successfully.

- `frontend/` changes: use the smallest relevant Bun script from `frontend/package.json`
  (typecheck, lint, test, build as applicable).
- `backend/` changes: use the project's Python tooling. Run `compileall` over the
  touched packages, then run the affected suite from `backend/` with
  `uv run python -m tests.<suite>` (identity, workspaces, teams, knowledge, agents,
  llm, test_main). For migration changes, run Alembic against the target database or
  a temporary explicit test database. For Celery wiring changes, verify the
  expected tasks register on `celery_app`.
- If a check cannot be run, say exactly why in the final response.

## 9. Keeping This File Current

- Update this file in the same change when repository structure, build/test
  commands, dependencies, or conventions change.
- If a top-level directory is added, removed, or repurposed, update
  `Project Notes`.
- If scripts or tooling change, update `Validation`.
- Before finishing a task, check whether your changes made any instruction
  here stale.

# AGENTS.md

Instructions for coding agents working in this repository.

## Scope

This file applies to the whole repository unless a deeper `AGENTS.md` overrides it.

## Behavioral Guidelines

### Think Before Coding

- State assumptions explicitly before implementing.
- If multiple interpretations exist, surface them instead of picking silently.
- Ask when a requirement is unclear and a reasonable assumption would be risky.
- Prefer the simpler approach when it fully satisfies the request.

### Simplicity First

- Write the minimum code that solves the problem.
- Do not add speculative features, configurability, abstractions, or scaffolding.
- Reuse existing helpers, patterns, and dependencies before adding new code.
- Prefer standard library and platform features over new dependencies.

### Surgical Changes

- Touch only files required by the task.
- Match existing style, even if you would choose differently.
- Do not refactor adjacent code or reformat unrelated files.
- Remove only imports, variables, or functions made unused by your own changes.
- Mention unrelated dead code or issues instead of changing them.

### Goal-Driven Execution

- Convert each task into a verifiable goal before editing.
- For bug fixes, identify the root cause and check callers before patching.
- Add or update the smallest relevant test/check for non-trivial logic.
- Keep looping until the change is implemented and verified, or clearly explain the blocker.

### Production Implementation Expectations

- Treat MVP tasks as production slices, not throwaway demos or local-only prototypes.
- Before implementing a feature, identify every required completion point: data model and migrations, backend API/service behavior, authorization and tenant isolation, frontend/API client behavior, validation and error states, tests/checks, documentation updates, and deployment or operations impact.
- Do not default to temporary storage, in-memory state, SQLite, mock data, or local-only shortcuts for production features unless the user explicitly approves that tradeoff.
- If the repository is missing production foundation required by the task, stop and surface the decision instead of silently implementing around it.
- "Simplicity First" still applies: avoid speculative features, but do not omit required production behavior just to keep the diff small.

### File Size Guidelines

- Treat line counts as soft maintainability signals, not hard rules.
- Prefer files in the `100-250` line range when the responsibility is naturally small.
- Files in the `250-400` line range are acceptable when they still own one clear responsibility.
- Reconsider the structure around `400-600` lines, especially for React pages and backend services.
- Split files over `600` lines when a clear module, component, hook, service, or helper boundary exists.
- Avoid `1000+` line source files unless the file is generated, mostly static data, or there is no clean split yet.
- For React, prefer ordinary components around `50-200` lines, page containers around `200-500` lines, and hooks/utilities around `50-150` lines.
- For backend code, prefer FastAPI `api.py` files around `100-300` lines, `services.py` around `150-400` lines, and `schemas.py` / `models.py` around `100-300` lines.
- Test files may be longer when a workflow is easier to read together; `300-600` lines is acceptable if setup stays clear.
- Split by responsibility first, then by length. Do not create abstractions or tiny files just to satisfy a line-count target.

## Python Guidelines

- Keep Python features modular: put cohesive business logic in focused functions, classes, or modules that can be reused by callers.
- Avoid duplicating logic. When the same behavior appears in multiple places, reuse an existing helper or extract the smallest shared helper that fits the current need.
- Do not create abstractions only to appear modular. Prefer direct code until reuse, testing, or readability clearly benefits.
- Keep module boundaries clear: serializers, views, services, models, and utilities should not absorb responsibilities from each other.
- Prefer pure functions for reusable transformations and calculations when they do not need database, network, or framework state.
- Use explicit names and type hints for public functions, service methods, and non-obvious data structures.
- Keep side effects at the edges of a workflow. Separate validation, transformation, persistence, and external calls when practical.
- Prefer standard library features and existing project utilities before adding new helpers or dependencies.
- Add the narrowest relevant test/check for shared helpers, branching logic, parsers, and bug fixes.

## React Guidelines

- Keep React components focused and reusable: split a component when it owns a distinct responsibility, not just because it is long.
- Reuse existing components, hooks, utilities, shadcn/ui primitives, and Tailwind patterns before creating new ones.
- Avoid duplicating UI logic. Extract the smallest shared component or hook only when reuse is real or the current component becomes hard to read.
- Keep state as local as possible. Lift state only when multiple components need to coordinate around the same value.
- Derive values during render when possible instead of storing duplicate derived state in `useState`.
- Put side effects in `useEffect` only when they synchronize with something outside React, such as network, storage, subscriptions, timers, or browser APIs.
- Keep custom hooks focused on reusable behavior, not one-off component plumbing.
- Use TypeScript types for component props, API data, and non-obvious state. Avoid `any` unless the boundary is genuinely unknown and documented.
- Prefer semantic HTML and accessible shadcn/ui primitives. Preserve keyboard navigation, labels, focus states, and ARIA attributes when changing interactive UI.
- Avoid unnecessary memoization. Use `useMemo`, `useCallback`, and `React.memo` only for expensive work, stable dependencies, or measured render issues.
- Keep bundle size in mind: avoid large imports for small tasks and prefer direct imports when the package supports them.
- Add or update the smallest relevant check for shared components, custom hooks, complex conditional rendering, and bug fixes.

## Project Notes

- `apps/` is a Python project using `pyproject.toml`, Python `>=3.11`, and `uv.lock`.
- `apps/nexaflow/` contains the FastAPI backend package.
- Backend application code should use async FastAPI routes, async dependencies, and SQLAlchemy `AsyncSession`; avoid adding new synchronous database access paths.
- Backend business code follows a DRF-like app layout. Add new feature modules as their own package under `apps/nexaflow/<feature>/`, with local `api.py`, `models.py`, `schemas.py`, and `services.py` files when needed.
- Keep shared infrastructure in `apps/nexaflow/core/` and `apps/nexaflow/db/`; do not recreate global `api/`, `models/`, `schemas/`, or `services/` folders that collect every feature.
- Put hand-written SQL under `apps/nexaflow/sql/<feature>/`. Use SQL files for explicit database write workflows, seed/bootstrap data, complex queries, or any database operation that is clearer or not practical through the ORM; keep parameter binding in Python services and do not inline dynamic values into SQL strings.
- `apps/.env.example` documents initialization env keys. Real `apps/.env` files are local-only and ignored by git; bootstrap admin credentials must come from env values, not Python constants.
- `apps/alembic/` contains backend database migrations; production data is PostgreSQL-backed.
- `web/` is a React + TypeScript + Vite app using Bun, shadcn/ui, and Tailwind CSS.
- `docs/` stores project planning and product/engineering documentation.
- Use `rg` / `rg --files` for code search.
- Do not invent project commands; inspect local scripts first.

## Keeping This File Current

- Update this file in the same change when repository structure, build/test commands, dependencies, or conventions change.
- If a top-level directory is added, removed, or repurposed, update `Project Notes`.
- If scripts or tooling change, update `Verification`.
- Before finishing a task, check whether your changes made any instruction here stale.

## Verification

- For `web/` changes, use the smallest relevant Bun script from `web/package.json`:
  - `bun run typecheck`
  - `bun run lint`
  - `bun run build`
- For `apps/` changes, inspect the available Python tooling first and run the narrowest relevant check:
  - `apps/.venv/bin/python -m compileall apps/nexaflow apps/main.py`
  - From `apps/`: `.venv/bin/python -m nexaflow.identity.test`
  - From `apps/`: `.venv/bin/python -m nexaflow.workspaces.test`
  - From `apps/`: `.venv/bin/python -m nexaflow.teams.test`
  - From `apps/`: run Alembic against the target database, or a temporary explicit test database when only validating migration syntax.
- If a check cannot be run, say exactly why in the final response.

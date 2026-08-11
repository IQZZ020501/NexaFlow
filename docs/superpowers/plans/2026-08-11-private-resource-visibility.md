# Private Resource Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agents and knowledge bases owner-private by default, with explicit member grants and an Agent `view`-only authorization UI.

**Architecture:** Extend the existing `resource_permissions` relation with the `agent` resource type, centralize its CRUD repository, and enforce visibility both in SQL list queries and in service-layer direct-access checks. Keep Agent editing owner/admin-only, preserve knowledge-base `view/edit`, and leave published/API Agent paths unchanged.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, Alembic, PostgreSQL/SQLite tests, Next.js App Router, React 19, TypeScript, Bun, shadcn/ui, Tailwind CSS.

---

### Task 1: Define Agent permission rules with unit tests

**Files:**
- Create: `backend/app/shareddomain/agents/permissions.py`
- Modify: `backend/app/shareddomain/agents/services.py`
- Modify: `backend/tests/unit.py`

- [ ] **Step 1: Write failing permission matrix tests**

Add imports for `Agent`, `ResourcePermission`, `effective_agent_permission`, and `validate_agent_permission`, then add:

```python
def test_effective_agent_permission_matrix() -> None:
    agent = Agent(id="agent-1", workspace_id="ws-1", created_by_user_id="owner-1")
    owner = User(id="owner-1", username="owner")
    member = User(id="member-1", username="member")
    grant = ResourcePermission(
        workspace_id="ws-1",
        resource_type="agent",
        resource_id="agent-1",
        user_id="member-1",
        permission="view",
    )

    assert effective_agent_permission(agent, owner, "member") == "edit"
    assert effective_agent_permission(agent, member, "admin") == "edit"
    assert effective_agent_permission(agent, member, "member") == "none"
    assert effective_agent_permission(agent, member, "member", grant) == "view"


def test_validate_agent_permission_only_accepts_view() -> None:
    validate_agent_permission("view")
    expect_http_error(lambda: validate_agent_permission("edit"), 422)
```

- [ ] **Step 2: Run the unit suite and verify RED**

Run from `backend/`:

```powershell
uv run python -m tests.unit
```

Expected: import failure because `app.shareddomain.agents.permissions` does not exist.

- [ ] **Step 3: Implement the pure policy module**

Create constants and pure helpers in `permissions.py`:

```python
AGENT_RESOURCE_TYPE = "agent"
AGENT_VIEW_PERMISSION = "view"


def validate_agent_permission(permission: str) -> None:
    if permission != AGENT_VIEW_PERMISSION:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid Agent permission.",
        )


def effective_agent_permission(
    agent: Agent,
    actor: User,
    workspace_role: str | None,
    grant: ResourcePermission | None = None,
) -> str:
    if workspace_role == "admin" or agent.created_by_user_id == actor.id:
        return "edit"
    return "view" if grant is not None and grant.permission == "view" else "none"


def can_edit_agent(agent: Agent, actor: User, workspace_role: str | None) -> bool:
    return effective_agent_permission(agent, actor, workspace_role) == "edit"


def require_agent_edit(agent: Agent, actor: User, workspace_role: str | None) -> None:
    if not can_edit_agent(agent, actor, workspace_role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent owner required.")
```

Import and re-export `can_edit_agent` and `require_agent_edit` from `services.py`, removing their old definitions without changing callers.

- [ ] **Step 4: Run the unit suite and verify GREEN**

Run: `uv run python -m tests.unit`

Expected: all unit tests pass.

- [ ] **Step 5: Commit the policy slice**

```powershell
git add backend/app/shareddomain/agents/permissions.py backend/app/shareddomain/agents/services.py backend/tests/unit.py
git commit -m "feat(permissions): define agent view access"
```

### Task 2: Extend the permission store and filter knowledge-base lists

**Files:**
- Create: `backend/app/infrastructure/repositories/resource_permission.py`
- Create: `backend/alembic/versions/202608110001_private_resource_visibility.py`
- Modify: `backend/app/domain/resource_permission.py`
- Modify: `backend/app/infrastructure/repositories/knowledge.py`
- Modify: `backend/app/shareddomain/knowledge/permissions.py`
- Modify: `backend/app/shareddomain/knowledge/kb.py`
- Modify: `backend/tests/knowledge.py`

- [ ] **Step 1: Change knowledge-list expectations to private and verify RED**

Replace the pre-grant and post-revoke `permission == "none"` assertions with ID absence checks:

```python
assert knowledge_base_id not in {item["id"] for item in bob_list.json()}
```

After the existing `view` grant, assert the list contains the resource with `permission == "view"`. Add a page-boundary case where a newer inaccessible knowledge base precedes an accessible one, call `?limit=1&offset=0`, and assert the accessible row is returned.

Run from `backend/`:

```powershell
uv run python -m tests.knowledge
```

Expected: failure because ungranted rows are still returned and filtering currently happens nowhere.

- [ ] **Step 2: Add the migration and ORM constraint**

Update the model constraint to:

```python
"resource_type IN ('knowledge_base', 'agent')"
```

Create revision `202608110001` with `down_revision = "202608100003"`. In `upgrade()`, use `op.batch_alter_table("resource_permissions")` to drop and recreate `ck_resource_permissions_resource_type` for both resource types. In `downgrade()`, first delete `resource_type = 'agent'` rows, then restore the knowledge-base-only constraint.

- [ ] **Step 3: Extract generic permission persistence**

Create `resource_permission.py` with the generic entity/ORM mapping implementation:

```python
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.resource_permission import ResourcePermission as ResourcePermissionORM
from app.domain.user import User as UserORM
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipORM
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User
from app.infrastructure.repositories.mapping import save, to_entity


async def get_user_grant(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> ResourcePermission | None:
    row = await db.scalar(
        select(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
            ResourcePermissionORM.user_id == user_id,
        )
    )
    return to_entity(ResourcePermission, row) if row else None


async def create_resource_permission(
    db: AsyncSession,
    entity: ResourcePermission,
) -> ResourcePermission:
    row = await save(db, ResourcePermissionORM, entity)
    return to_entity(ResourcePermission, row)


async def save_resource_permission(
    db: AsyncSession,
    entity: ResourcePermission,
) -> None:
    await save(db, ResourcePermissionORM, entity)


async def list_resource_permission_rows(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[tuple[ResourcePermission, User]]:
    result = await db.execute(
        select(ResourcePermissionORM, UserORM)
        .join(UserORM, UserORM.id == ResourcePermissionORM.user_id)
        .where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
        )
        .order_by(UserORM.name, UserORM.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        (to_entity(ResourcePermission, permission), to_entity(User, user))
        for permission, user in result.all()
    ]


async def get_active_workspace_member(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> User | None:
    row = await db.scalar(
        select(UserORM)
        .join(WorkspaceMembershipORM, WorkspaceMembershipORM.user_id == UserORM.id)
        .where(
            WorkspaceMembershipORM.workspace_id == workspace_id,
            WorkspaceMembershipORM.user_id == user_id,
            UserORM.is_active.is_(True),
        )
    )
    return to_entity(User, row) if row else None


async def delete_resource_permission(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> int:
    result = await db.execute(
        delete(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
            ResourcePermissionORM.user_id == user_id,
        )
    )
    return result.rowcount


async def delete_resource_permissions(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
) -> None:
    await db.execute(
        delete(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
        )
    )
```

Change knowledge permission services to call this repository with explicit workspace/resource identifiers. Remove the moved CRUD functions from `knowledge.py`; keep its list query imports needed for the grant join.

- [ ] **Step 4: Filter the knowledge query before pagination**

Add `include_all: bool` to `list_knowledge_base_rows`. For non-admin calls append:

```python
statement = statement.where(
    or_(
        KnowledgeBaseORM.created_by_user_id == actor_id,
        grant.id.is_not(None),
    )
)
```

Pass `workspace_role == "admin"` from `list_knowledge_bases`, remove statistics masking, and always return the computed `document_count` / `char_count` for rows that passed visibility filtering.

- [ ] **Step 5: Run focused checks and verify GREEN**

Run:

```powershell
uv run python -m compileall app/domain app/infrastructure/repositories app/shareddomain/knowledge
uv run python -m tests.knowledge
```

Expected: compile succeeds and the knowledge suite passes with hidden ungranted rows.

- [ ] **Step 6: Commit the knowledge/private-store slice**

```powershell
git add backend/alembic/versions/202608110001_private_resource_visibility.py backend/app/domain/resource_permission.py backend/app/infrastructure/repositories/resource_permission.py backend/app/infrastructure/repositories/knowledge.py backend/app/shareddomain/knowledge/permissions.py backend/app/shareddomain/knowledge/kb.py backend/tests/knowledge.py
git commit -m "feat(knowledge): hide ungranted knowledge bases"
```

### Task 3: Enforce private Agent visibility at every console entry point

**Files:**
- Modify: `backend/app/infrastructure/repositories/agent.py`
- Modify: `backend/app/shareddomain/agents/permissions.py`
- Modify: `backend/app/shareddomain/agents/services.py`
- Modify: `backend/app/application/agent_runs.py`
- Modify: `backend/app/api/v1/endpoints/agents.py`
- Modify: `backend/tests/agents.py`

- [ ] **Step 1: Write failing owner/admin/ungranted tests**

Before any Agent grant exists, assert:

```python
assert agent_id not in {item["id"] for item in member_list.json()}
assert client.get(
    agents_url(workspace_id, f"/{agent_id}"),
    headers=auth_headers(member_token),
).status_code == 403
assert client.post(
    agents_url(workspace_id, f"/{agent_id}/runs"),
    headers=auth_headers(member_token),
    json={"goal": "Denied"},
).status_code == 403
```

Create a member-owned Agent and assert admin can list/read it. Add `limit=1` coverage with a newer inaccessible Agent preceding an accessible owner Agent to prove filtering occurs before pagination.

Run: `uv run python -m tests.agents`

Expected: failures because all workspace Agents are listed and console runs do not require Agent visibility.

- [ ] **Step 2: Filter Agent list SQL**

Join `ResourcePermission` for the requesting actor and resource type. For non-admin list calls filter:

```python
or_(
    Agent.created_by_user_id == actor_id,
    ResourcePermissionOrm.id.is_not(None),
)
```

Apply this before ordering and pagination. Pass actor ID and admin status from the domain service.

- [ ] **Step 3: Add async view enforcement**

Implement in `permissions.py`:

```python
async def require_agent_view(db, agent, actor, workspace_role) -> str:
    grant = await resource_permission_repository.get_user_grant(
        db,
        agent.workspace_id,
        AGENT_RESOURCE_TYPE,
        agent.id,
        actor.id,
    )
    permission = effective_agent_permission(agent, actor, workspace_role, grant)
    if permission == "none":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent access denied.")
    return permission
```

Call it from `get_agent_response`. In `prepare_agent_run`, call it only when `access_source == "console"`. Add `workspace_role` through `list_agent_runs`, `get_agent_run_response`, `get_agent_run_entity`, `list_agent_run_tool_calls`, and `resolve_agent_tool_approval`, and pass the route context role at every workspace-console caller.

- [ ] **Step 4: Run Agent tests and verify GREEN**

Run:

```powershell
uv run python -m compileall app/shareddomain/agents app/application/agent_runs.py app/api/v1/endpoints/agents.py app/infrastructure/repositories/agent.py
uv run python -m tests.agents
```

Expected: owner/admin tests pass, ungranted list/detail/run access is denied, and published/API flows remain green.

- [ ] **Step 5: Commit direct access enforcement**

```powershell
git add backend/app/infrastructure/repositories/agent.py backend/app/shareddomain/agents/permissions.py backend/app/shareddomain/agents/services.py backend/app/application/agent_runs.py backend/app/api/v1/endpoints/agents.py backend/tests/agents.py
git commit -m "feat(agents): enforce private console access"
```

### Task 4: Add Agent grant, revoke, and cleanup workflows

**Files:**
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/shareddomain/agents/permissions.py`
- Modify: `backend/app/shareddomain/agents/services.py`
- Modify: `backend/app/application/agents.py`
- Modify: `backend/app/api/v1/endpoints/agents.py`
- Modify: `backend/app/infrastructure/repositories/agent.py`
- Modify: `backend/tests/agents.py`
- Modify: `backend/tests/workspaces.py`

- [ ] **Step 1: Write failing grant lifecycle tests**

Exercise the API with these assertions:

```python
grant = client.put(
    agents_url(workspace_id, f"/{agent_id}/permissions/{member_id}"),
    headers=auth_headers(admin_token),
    json={"permission": "view"},
)
assert grant.status_code == 200
assert grant.json()["permission"] == "view"
assert agent_id in {item["id"] for item in client.get(
    agents_url(workspace_id), headers=auth_headers(member_token)
).json()}
assert client.patch(
    agents_url(workspace_id, f"/{agent_id}"),
    headers=auth_headers(member_token),
    json={"name": "Denied"},
).status_code == 403
```

Assert an authorized run succeeds, `permission="edit"` returns `422`, non-owner permission management returns `403`, permission listing returns the member, revoke returns `204`, and post-revoke list/detail/new-run access is denied. Add database assertions that Agent deletion and workspace-member removal clear `agent` permission rows.

Run: `uv run python -m tests.agents`

Expected: `404` for missing permission routes.

- [ ] **Step 2: Add Agent permission schemas and services**

Add:

```python
class AgentPermissionResponse(BaseModel):
    user: UserResponse
    permission: Literal["view"]


class AgentPermissionUpsertRequest(BaseModel):
    permission: Literal["view"]
```

Implement list/upsert/revoke in `permissions.py` using the generic repository, active workspace-member validation, audit events, commit/rollback behavior matching knowledge permissions, and owner/admin management checks. Re-export through `services.py` and `application/agents.py`.

- [ ] **Step 3: Add thin API routes**

Add the three approved routes under `/{agent_id}/permissions`, using `get_agent`, management checks, and the application facade. Return `204` for revoke.

- [ ] **Step 4: Delete Agent grants with the Agent graph**

In `delete_agent_graph`, delete `resource_type = "agent"` rows for the Agent before deleting the Agent. Keep workspace-level cleanup unchanged and verify the existing generic workspace cleanup covers Agent rows.

- [ ] **Step 5: Run affected backend suites and verify GREEN**

Run:

```powershell
uv run python -m compileall app
uv run python -m tests.unit
uv run python -m tests.workspaces
uv run python -m tests.agents
```

Expected: all listed checks pass.

- [ ] **Step 6: Commit the Agent authorization API**

```powershell
git add backend/app/schemas/agent.py backend/app/shareddomain/agents/permissions.py backend/app/shareddomain/agents/services.py backend/app/application/agents.py backend/app/api/v1/endpoints/agents.py backend/app/infrastructure/repositories/agent.py backend/tests/agents.py backend/tests/workspaces.py
git commit -m "feat(agents): add member view grants"
```

### Task 5: Add typed frontend permission API calls

**Files:**
- Modify: `frontend/lib/api/agents.ts`
- Create: `frontend/tests/agent-permissions.test.ts`

- [ ] **Step 1: Write failing request-shape tests**

Stub `globalThis.fetch`, call the three functions, and assert exact paths/method/body:

```typescript
expect(requests).toEqual([
  ["/api/v1/workspaces/ws-1/agents/agent-1/permissions", "GET", undefined],
  ["/api/v1/workspaces/ws-1/agents/agent-1/permissions/user-1", "PUT", '{"permission":"view"}'],
  ["/api/v1/workspaces/ws-1/agents/agent-1/permissions/user-1", "DELETE", undefined],
])
```

Run from `frontend/`: `bun test tests/agent-permissions.test.ts`

Expected: import failures because the permission API functions do not exist.

- [ ] **Step 2: Implement types and calls**

Add `AgentPermission` with the existing system `User` shape and implement `listAgentPermissions`, `grantAgentPermission`, and `revokeAgentPermission` using `agentsPath` and `request`.

- [ ] **Step 3: Verify GREEN and commit**

Run:

```powershell
bun test tests/agent-permissions.test.ts
bun run typecheck
```

Then commit:

```powershell
git add frontend/lib/api/agents.ts frontend/tests/agent-permissions.test.ts
git commit -m "feat(web): add agent permission client"
```

### Task 6: Add the Agent authorization dialog and trilingual UI

**Files:**
- Create: `frontend/components/agents/agent-permissions-dialog.tsx`
- Modify: `frontend/components/agents/agents-page.tsx`
- Modify: `frontend/tests/agent-permissions.test.ts`

- [ ] **Step 1: Add failing UI contract tests**

Test a pure exported target selector:

```typescript
expect(agentPermissionTargets(members, "owner-1", permissions)).toEqual([
  members[2],
])
```

It must exclude the owner and already-authorized members. Read `agents-page.tsx` as text and assert the owner/admin card menu includes an Agent permission dialog trigger using `t("资源授权")`.

Run: `bun test tests/agent-permissions.test.ts`

Expected: missing module/helper and missing trigger failures.

- [ ] **Step 2: Build the focused dialog component**

Create a controlled dialog using existing shadcn `Dialog`, `DropdownMenu`, `Button`, `Field`, `PermissionBadge`, and Lucide icons. Props include `agent`, `open`, `members`, `permissions`, `isLoading`, `isSaving`, `onOpenChange`, `onGrant(userId)`, and `onRevoke(userId)`. The dialog only shows `view`; it has no permission-level selector.

Export:

```typescript
export function agentPermissionTargets(
  members: WorkspaceMember[],
  ownerId: string,
  permissions: AgentPermission[]
) {
  const granted = new Set(permissions.map((item) => item.user.id))
  return members.filter(
    (member) => member.user.id !== ownerId && !granted.has(member.user.id)
  )
}
```

- [ ] **Step 3: Wire dialog state into AgentsPage**

On menu selection, load workspace members and Agent permissions in parallel. Keep loading/saving state local to the page, call grant/revoke functions, refresh permission state after successful mutation, and use existing `notify`/`reportError`. Render the menu only when `agent.can_edit`; authorized view-only users keep the existing view badge and no management action.

- [ ] **Step 4: Verify all dialog copy uses synchronized dictionary keys**

Use only existing synchronized keys: `资源授权`, `用户`, `选择用户`, `可查看`, `保存授权`, `撤销授权`, `暂无授权`, `授权已保存`, `授权已撤销`, and `正在加载`. Do not add hardcoded visible strings or change the dictionaries.

- [ ] **Step 5: Run frontend checks and verify GREEN**

Run:

```powershell
bun test tests/agent-permissions.test.ts tests/i18n.test.ts tests/dialog-dropdown-interaction.test.ts
bun run typecheck
bun run lint
```

Expected: all commands exit successfully with no missing dictionary keys or hook/lint errors.

- [ ] **Step 6: Commit the UI slice**

```powershell
git add frontend/components/agents/agent-permissions-dialog.tsx frontend/components/agents/agents-page.tsx frontend/tests/agent-permissions.test.ts
git commit -m "feat(web): manage agent view grants"
```

### Task 7: Verify migration, architecture, and end-to-end regression scope

**Files:**
- Modify only if checks expose defects in files already listed above.

- [ ] **Step 1: Validate Alembic upgrade and downgrade on an explicit temporary database**

Create an empty temporary SQLite database path, point the backend test configuration at it without reusing any local or production database, then run:

```powershell
uv run alembic upgrade head
uv run alembic downgrade 202608100003
uv run alembic upgrade head
```

Expected: all three commands exit successfully; downgrade removes Agent grants before restoring the old constraint.

- [ ] **Step 2: Run backend verification**

From `backend/`:

```powershell
uv run python -m compileall app
uv run python -m tests.unit
uv run python -m tests.workspaces
uv run python -m tests.knowledge
uv run python -m tests.agents
```

Expected: every command exits `0`.

- [ ] **Step 3: Run frontend verification**

From `frontend/`:

```powershell
bun test
bun run typecheck
bun run lint
bun run build
```

Expected: every command exits `0`.

- [ ] **Step 4: Check layer boundaries and instruction drift**

Verify API routers import Agent permission use cases only from `app.application.agents`; `shareddomain` imports ORM only through repositories; no capability layer imports were introduced; all new UI strings use `t()`; and `AGENTS.md` remains accurate because no structure, command, or dependency convention changed.

- [ ] **Step 5: Inspect final diff and commit any verification fixes**

Run:

```powershell
git diff --check
git status --short
git log --oneline origin/main..HEAD
```

If verification required a source fix, stage only the affected files and commit with a scoped Conventional Commit message describing that fix.

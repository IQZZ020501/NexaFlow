from dataclasses import fields
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.platform.models import ResourcePermission as ResourcePermissionOrm
from app.domain.platform.models import User as UserOrm
from app.domain.platform.models import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.entities.tools import (
    ApplicationToolBinding,
    Tool,
    ToolDraft,
    ToolInvocation,
    ToolPolicy,
    ToolRef,
    ToolSource,
    ToolVersion,
)
from app.entities.identity.user import User
from app.infra.db.mapping import save, to_entity
from app.domain.tools.models import (
    ApplicationToolBinding as ApplicationToolBindingOrm,
)
from app.domain.tools.models import Tool as ToolOrm
from app.domain.tools.models import ToolDraft as ToolDraftOrm
from app.domain.tools.models import ToolInvocation as ToolInvocationOrm
from app.domain.tools.models import ToolPolicy as ToolPolicyOrm
from app.domain.tools.models import ToolSource as ToolSourceOrm
from app.domain.tools.models import ToolVersion as ToolVersionOrm
from app.domain.tools.runtime import (
    TOOL_INVOCATION_APPROVED,
    TOOL_INVOCATION_AWAITING_APPROVAL,
    TOOL_INVOCATION_CLAIMABLE_STATUSES,
    TOOL_INVOCATION_QUEUED,
    TOOL_INVOCATION_RUNNING,
    TOOL_INVOCATION_TERMINAL_STATUSES,
    TOOL_INVOCATION_UNCERTAIN,
    exhausted_tool_invocation_terminal_state,
)

ToolCatalogRow = tuple[
    Tool,
    ToolSource,
    ToolVersion | None,
    ToolDraft | None,
    ResourcePermission | None,
]
ToolCatalogDetailRow = tuple[
    Tool,
    ToolSource,
    ToolVersion | None,
    ToolDraft | None,
    ToolPolicy | None,
    ResourcePermission | None,
]
McpCatalogRow = tuple[ToolSource, Tool, ToolVersion, ToolPolicy | None]
ApplicationToolSnapshotRow = tuple[
    str,
    ApplicationToolBinding,
    Tool | None,
    ToolSource | None,
    ToolVersion | None,
    ToolPolicy | None,
    User | None,
    str | None,
    ResourcePermission | None,
]



async def get_tool_source(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
) -> ToolSource | None:
    row = await db.scalar(
        select(ToolSourceOrm).where(
            ToolSourceOrm.workspace_id == workspace_id,
            ToolSourceOrm.id == source_id,
        )
    )
    return to_entity(ToolSource, row) if row is not None else None

async def lock_tool_source(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
) -> ToolSource | None:
    row = await db.scalar(
        select(ToolSourceOrm)
        .where(
            ToolSourceOrm.workspace_id == workspace_id,
            ToolSourceOrm.id == source_id,
        )
        .with_for_update()
    )
    return to_entity(ToolSource, row) if row is not None else None

async def list_tool_sources(
    db: AsyncSession,
    workspace_id: str,
) -> list[ToolSource]:
    rows = await db.scalars(
        select(ToolSourceOrm)
        .where(ToolSourceOrm.workspace_id == workspace_id)
        .order_by(ToolSourceOrm.kind, ToolSourceOrm.created_at, ToolSourceOrm.id)
    )
    return [to_entity(ToolSource, row) for row in rows.all()]

async def list_mcp_tool_sources(
    db: AsyncSession,
    workspace_id: str,
    mcp_server_id: str | None = None,
) -> list[ToolSource]:
    statement = select(ToolSourceOrm).where(
        ToolSourceOrm.workspace_id == workspace_id,
        ToolSourceOrm.kind == "mcp",
        ToolSourceOrm.mcp_server_id.is_not(None),
    )
    if mcp_server_id is not None:
        statement = statement.where(ToolSourceOrm.mcp_server_id == mcp_server_id)
    rows = await db.scalars(
        statement.order_by(ToolSourceOrm.created_at, ToolSourceOrm.id)
    )
    return [to_entity(ToolSource, row) for row in rows.all()]

async def list_mcp_catalog_rows(
    db: AsyncSession,
    workspace_id: str,
    mcp_server_id: str,
    *,
    available_only: bool = False,
) -> list[McpCatalogRow]:
    statement = (
        select(ToolSourceOrm, ToolOrm, ToolVersionOrm, ToolPolicyOrm)
        .join(
            ToolOrm,
            and_(
                ToolOrm.workspace_id == ToolSourceOrm.workspace_id,
                ToolOrm.source_id == ToolSourceOrm.id,
            ),
        )
        .join(
            ToolVersionOrm,
            and_(
                ToolVersionOrm.workspace_id == ToolOrm.workspace_id,
                ToolVersionOrm.tool_id == ToolOrm.id,
                ToolVersionOrm.id == ToolOrm.current_version_id,
            ),
        )
        .outerjoin(
            ToolPolicyOrm,
            and_(
                ToolPolicyOrm.workspace_id == ToolOrm.workspace_id,
                ToolPolicyOrm.tool_id == ToolOrm.id,
            ),
        )
        .where(
            ToolSourceOrm.workspace_id == workspace_id,
            ToolSourceOrm.kind == "mcp",
            ToolSourceOrm.mcp_server_id == mcp_server_id,
        )
        .order_by(ToolOrm.created_at, ToolOrm.id)
    )
    if available_only:
        statement = statement.where(ToolOrm.availability == "available")
    rows = await db.execute(statement)
    return [
        (
            to_entity(ToolSource, source),
            to_entity(Tool, tool),
            to_entity(ToolVersion, version),
            to_entity(ToolPolicy, policy) if policy is not None else None,
        )
        for source, tool, version, policy in rows.all()
    ]

async def save_tool_source(db: AsyncSession, entity: ToolSource) -> ToolSource:
    row = await save(db, ToolSourceOrm, entity)
    return to_entity(ToolSource, row)

async def get_tool(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
) -> Tool | None:
    row = await db.scalar(
        select(ToolOrm).where(
            ToolOrm.workspace_id == workspace_id,
            ToolOrm.id == tool_id,
        )
    )
    return to_entity(Tool, row) if row is not None else None

async def get_tool_by_function_name(
    db: AsyncSession,
    workspace_id: str,
    function_name: str,
) -> Tool | None:
    row = await db.scalar(
        select(ToolOrm).where(
            ToolOrm.workspace_id == workspace_id,
            ToolOrm.function_name == function_name,
        )
    )
    return to_entity(Tool, row) if row is not None else None

async def get_tool_by_source_key(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
    stable_key: str,
) -> Tool | None:
    row = await db.scalar(
        select(ToolOrm).where(
            ToolOrm.workspace_id == workspace_id,
            ToolOrm.source_id == source_id,
            ToolOrm.stable_key == stable_key,
        )
    )
    return to_entity(Tool, row) if row is not None else None

async def lock_tool(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
) -> Tool | None:
    row = await db.scalar(
        select(ToolOrm)
        .where(
            ToolOrm.workspace_id == workspace_id,
            ToolOrm.id == tool_id,
        )
        .with_for_update()
    )
    return to_entity(Tool, row) if row is not None else None

async def list_tools(db: AsyncSession, workspace_id: str) -> list[Tool]:
    rows = await db.scalars(
        select(ToolOrm)
        .where(ToolOrm.workspace_id == workspace_id)
        .order_by(ToolOrm.created_at, ToolOrm.id)
    )
    return [to_entity(Tool, row) for row in rows.all()]

async def list_tool_catalog_rows(
    db: AsyncSession,
    workspace_id: str,
    actor_id: str,
    include_all: bool = False,
    limit: int | None = None,
    offset: int = 0,
    excluded_builtin_function_names: tuple[str, ...] = (),
) -> list[ToolCatalogRow]:
    grant = ResourcePermissionOrm
    statement = (
        select(ToolOrm, ToolSourceOrm, ToolVersionOrm, ToolDraftOrm, grant)
        .join(
            ToolSourceOrm,
            and_(
                ToolSourceOrm.workspace_id == ToolOrm.workspace_id,
                ToolSourceOrm.id == ToolOrm.source_id,
            ),
        )
        .outerjoin(
            ToolVersionOrm,
            and_(
                ToolVersionOrm.workspace_id == ToolOrm.workspace_id,
                ToolVersionOrm.tool_id == ToolOrm.id,
                ToolVersionOrm.id == ToolOrm.current_version_id,
            ),
        )
        .outerjoin(
            ToolDraftOrm,
            and_(
                ToolDraftOrm.workspace_id == ToolOrm.workspace_id,
                ToolDraftOrm.tool_id == ToolOrm.id,
            ),
        )
        .outerjoin(
            grant,
            and_(
                grant.workspace_id == ToolOrm.workspace_id,
                grant.resource_type == "tool",
                grant.resource_id == ToolOrm.id,
                grant.user_id == actor_id,
            ),
        )
        .where(
            ToolOrm.workspace_id == workspace_id,
            ToolOrm.status != "archived",
        )
    )
    if not include_all:
        statement = statement.where(
            or_(
                ToolOrm.kind == "builtin",
                ToolOrm.created_by_user_id == actor_id,
                grant.id.is_not(None),
            )
        )
    if excluded_builtin_function_names:
        statement = statement.where(
            or_(
                ToolOrm.kind != "builtin",
                ToolOrm.function_name.not_in(excluded_builtin_function_names),
            )
        )
    statement = (
        statement.order_by(ToolOrm.created_at.desc(), ToolOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(statement)
    return [
        (
            to_entity(Tool, tool),
            to_entity(ToolSource, source),
            to_entity(ToolVersion, version) if version is not None else None,
            to_entity(ToolDraft, draft) if draft is not None else None,
            to_entity(ResourcePermission, permission)
            if permission is not None
            else None,
        )
        for tool, source, version, draft, permission in rows.all()
    ]

async def get_tool_catalog_detail_row(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor_id: str,
) -> ToolCatalogDetailRow | None:
    grant = ResourcePermissionOrm
    row = (
        await db.execute(
            select(
                ToolOrm,
                ToolSourceOrm,
                ToolVersionOrm,
                ToolDraftOrm,
                ToolPolicyOrm,
                grant,
            )
            .join(
                ToolSourceOrm,
                and_(
                    ToolSourceOrm.workspace_id == ToolOrm.workspace_id,
                    ToolSourceOrm.id == ToolOrm.source_id,
                ),
            )
            .outerjoin(
                ToolVersionOrm,
                and_(
                    ToolVersionOrm.workspace_id == ToolOrm.workspace_id,
                    ToolVersionOrm.tool_id == ToolOrm.id,
                    ToolVersionOrm.id == ToolOrm.current_version_id,
                ),
            )
            .outerjoin(
                ToolDraftOrm,
                and_(
                    ToolDraftOrm.workspace_id == ToolOrm.workspace_id,
                    ToolDraftOrm.tool_id == ToolOrm.id,
                ),
            )
            .outerjoin(
                ToolPolicyOrm,
                and_(
                    ToolPolicyOrm.workspace_id == ToolOrm.workspace_id,
                    ToolPolicyOrm.tool_id == ToolOrm.id,
                ),
            )
            .outerjoin(
                grant,
                and_(
                    grant.workspace_id == ToolOrm.workspace_id,
                    grant.resource_type == "tool",
                    grant.resource_id == ToolOrm.id,
                    grant.user_id == actor_id,
                ),
            )
            .where(
                ToolOrm.workspace_id == workspace_id,
                ToolOrm.id == tool_id,
                ToolOrm.status != "archived",
            )
        )
    ).one_or_none()
    if row is None:
        return None
    tool, source, version, draft, policy, permission = row
    return (
        to_entity(Tool, tool),
        to_entity(ToolSource, source),
        to_entity(ToolVersion, version) if version is not None else None,
        to_entity(ToolDraft, draft) if draft is not None else None,
        to_entity(ToolPolicy, policy) if policy is not None else None,
        to_entity(ResourcePermission, permission)
        if permission is not None
        else None,
    )

async def list_tools_by_source(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
) -> list[Tool]:
    rows = await db.scalars(
        select(ToolOrm)
        .where(
            ToolOrm.workspace_id == workspace_id,
            ToolOrm.source_id == source_id,
        )
        .order_by(ToolOrm.created_at, ToolOrm.id)
    )
    return [to_entity(Tool, row) for row in rows.all()]

async def save_tool(db: AsyncSession, entity: Tool) -> Tool:
    row = await save(db, ToolOrm, entity)
    return to_entity(Tool, row)

async def get_tool_version(
    db: AsyncSession,
    workspace_id: str,
    version_id: str,
) -> ToolVersion | None:
    row = await db.scalar(
        select(ToolVersionOrm).where(
            ToolVersionOrm.workspace_id == workspace_id,
            ToolVersionOrm.id == version_id,
        )
    )
    return to_entity(ToolVersion, row) if row is not None else None

async def get_tool_version_by_hash(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    definition_hash: str,
) -> ToolVersion | None:
    row = await db.scalar(
        select(ToolVersionOrm).where(
            ToolVersionOrm.workspace_id == workspace_id,
            ToolVersionOrm.tool_id == tool_id,
            ToolVersionOrm.definition_hash == definition_hash,
        )
    )
    return to_entity(ToolVersion, row) if row is not None else None

async def list_tool_versions(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
) -> list[ToolVersion]:
    rows = await db.scalars(
        select(ToolVersionOrm)
        .where(
            ToolVersionOrm.workspace_id == workspace_id,
            ToolVersionOrm.tool_id == tool_id,
        )
        .order_by(ToolVersionOrm.revision.desc(), ToolVersionOrm.id)
    )
    return [to_entity(ToolVersion, row) for row in rows.all()]

async def save_tool_version(
    db: AsyncSession,
    entity: ToolVersion,
) -> ToolVersion:
    if await db.get(ToolVersionOrm, entity.id) is not None:
        raise ValueError("ToolVersion records are immutable.")
    row = await save(db, ToolVersionOrm, entity)
    return to_entity(ToolVersion, row)

async def get_tool_policy(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
) -> ToolPolicy | None:
    row = await db.scalar(
        select(ToolPolicyOrm).where(
            ToolPolicyOrm.workspace_id == workspace_id,
            ToolPolicyOrm.tool_id == tool_id,
        )
    )
    return to_entity(ToolPolicy, row) if row is not None else None

async def list_tool_policies(
    db: AsyncSession,
    workspace_id: str,
) -> list[ToolPolicy]:
    rows = await db.scalars(
        select(ToolPolicyOrm)
        .where(ToolPolicyOrm.workspace_id == workspace_id)
        .order_by(ToolPolicyOrm.created_at, ToolPolicyOrm.id)
    )
    return [to_entity(ToolPolicy, row) for row in rows.all()]

async def save_tool_policy(db: AsyncSession, entity: ToolPolicy) -> ToolPolicy:
    row = await save(db, ToolPolicyOrm, entity)
    return to_entity(ToolPolicy, row)

async def update_tool_policy_if_revision(
    db: AsyncSession,
    entity: ToolPolicy,
    expected_revision: int,
) -> ToolPolicy | None:
    if entity.revision != expected_revision + 1:
        raise ValueError("ToolPolicy revision must advance exactly once.")
    result = await db.execute(
        update(ToolPolicyOrm)
        .where(
            ToolPolicyOrm.id == entity.id,
            ToolPolicyOrm.workspace_id == entity.workspace_id,
            ToolPolicyOrm.tool_id == entity.tool_id,
            ToolPolicyOrm.revision == expected_revision,
        )
        .values(
            tool_version_id=entity.tool_version_id,
            definition_hash=entity.definition_hash,
            revision=entity.revision,
            approval=entity.approval,
            effect=entity.effect,
            allowed_access_sources=entity.allowed_access_sources,
            workflow_callable=entity.workflow_callable,
            parallel_safe=entity.parallel_safe,
            reviewed_by_user_id=entity.reviewed_by_user_id,
            reviewed_at=entity.reviewed_at,
            updated_at=entity.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    return entity if result.rowcount == 1 else None

async def list_application_tool_snapshot_rows(
    db: AsyncSession,
    workspace_id: str,
    application_ids: list[str],
) -> list[ApplicationToolSnapshotRow]:
    if not application_ids:
        return []
    grant = ResourcePermissionOrm
    rows = await db.execute(
        select(
            ApplicationToolBindingOrm.application_id,
            ApplicationToolBindingOrm,
            ToolOrm,
            ToolSourceOrm,
            ToolVersionOrm,
            ToolPolicyOrm,
            UserOrm,
            WorkspaceMembershipOrm.role,
            grant,
        )
        .outerjoin(
            ToolOrm,
            and_(
                ToolOrm.workspace_id == ApplicationToolBindingOrm.workspace_id,
                ToolOrm.id == ApplicationToolBindingOrm.tool_id,
            ),
        )
        .outerjoin(
            ToolSourceOrm,
            and_(
                ToolSourceOrm.workspace_id == ApplicationToolBindingOrm.workspace_id,
                ToolSourceOrm.id == ToolOrm.source_id,
            ),
        )
        .outerjoin(
            ToolVersionOrm,
            and_(
                ToolVersionOrm.workspace_id
                == ApplicationToolBindingOrm.workspace_id,
                ToolVersionOrm.id == ApplicationToolBindingOrm.tool_version_id,
            ),
        )
        .outerjoin(
            ToolPolicyOrm,
            and_(
                ToolPolicyOrm.workspace_id
                == ApplicationToolBindingOrm.workspace_id,
                ToolPolicyOrm.tool_id == ApplicationToolBindingOrm.tool_id,
            ),
        )
        .outerjoin(UserOrm, UserOrm.id == ApplicationToolBindingOrm.bound_by_user_id)
        .outerjoin(
            WorkspaceMembershipOrm,
            and_(
                WorkspaceMembershipOrm.workspace_id
                == ApplicationToolBindingOrm.workspace_id,
                WorkspaceMembershipOrm.user_id
                == ApplicationToolBindingOrm.bound_by_user_id,
            ),
        )
        .outerjoin(
            grant,
            and_(
                grant.workspace_id == ApplicationToolBindingOrm.workspace_id,
                grant.resource_type == "tool",
                grant.resource_id == ApplicationToolBindingOrm.tool_id,
                grant.user_id == ApplicationToolBindingOrm.bound_by_user_id,
            ),
        )
        .where(
            ApplicationToolBindingOrm.workspace_id == workspace_id,
            ApplicationToolBindingOrm.application_id.in_(application_ids),
        )
        .order_by(
            ApplicationToolBindingOrm.created_at,
            ApplicationToolBindingOrm.id,
        )
    )
    return [
        (
            application_id,
            to_entity(ApplicationToolBinding, binding),
            to_entity(Tool, tool) if tool is not None else None,
            to_entity(ToolSource, source) if source is not None else None,
            to_entity(ToolVersion, version) if version is not None else None,
            to_entity(ToolPolicy, policy) if policy is not None else None,
            to_entity(User, binder) if binder is not None else None,
            membership_role,
            to_entity(ResourcePermission, permission)
            if permission is not None
            else None,
        )
        for (
            application_id,
            binding,
            tool,
            source,
            version,
            policy,
            binder,
            membership_role,
            permission,
        ) in rows.all()
    ]

async def has_retained_user_audit_references(
    db: AsyncSession,
    user_id: str,
) -> bool:
    binding_id = await db.scalar(
        select(ApplicationToolBindingOrm.id)
        .where(ApplicationToolBindingOrm.bound_by_user_id == user_id)
        .limit(1)
    )
    if binding_id is not None:
        return True
    invocation_id = await db.scalar(
        select(ToolInvocationOrm.id)
        .where(ToolInvocationOrm.execution_user_id == user_id)
        .limit(1)
    )
    if invocation_id is not None:
        return True
    snapshot_invocation_id = await db.scalar(
        select(ToolInvocationOrm.id)
        .where(
            ToolInvocationOrm.policy_snapshot["tool_snapshot"][
                "bound_by_user_id"
            ].as_string()
            == user_id
        )
        .limit(1)
    )
    if snapshot_invocation_id is not None:
        return True
    draft_id = await db.scalar(
        select(ToolDraftOrm.id)
        .where(ToolDraftOrm.updated_by_user_id == user_id)
        .limit(1)
    )
    return draft_id is not None


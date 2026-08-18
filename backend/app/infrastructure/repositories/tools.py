from dataclasses import fields
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.resource_permission import ResourcePermission as ResourcePermissionOrm
from app.domain.user import User as UserOrm
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.resource_permission import ResourcePermission
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
from app.entities.user import User
from app.infrastructure.repositories.mapping import save, to_entity
from app.shareddomain.tools.models import (
    ApplicationToolBinding as ApplicationToolBindingOrm,
)
from app.shareddomain.tools.models import Tool as ToolOrm
from app.shareddomain.tools.models import ToolDraft as ToolDraftOrm
from app.shareddomain.tools.models import ToolInvocation as ToolInvocationOrm
from app.shareddomain.tools.models import ToolPolicy as ToolPolicyOrm
from app.shareddomain.tools.models import ToolSource as ToolSourceOrm
from app.shareddomain.tools.models import ToolVersion as ToolVersionOrm
from app.shareddomain.tools.runtime import (
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
    limit: int | None = None,
    offset: int = 0,
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
            or_(
                ToolOrm.kind == "builtin",
                ToolOrm.created_by_user_id == actor_id,
                grant.id.is_not(None),
            ),
        )
        .order_by(ToolOrm.created_at.desc(), ToolOrm.id.desc())
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


async def get_tool_draft(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
) -> ToolDraft | None:
    row = await db.scalar(
        select(ToolDraftOrm).where(
            ToolDraftOrm.workspace_id == workspace_id,
            ToolDraftOrm.tool_id == tool_id,
        )
    )
    return to_entity(ToolDraft, row) if row is not None else None


async def list_tool_drafts(
    db: AsyncSession,
    workspace_id: str,
) -> list[ToolDraft]:
    rows = await db.scalars(
        select(ToolDraftOrm)
        .where(ToolDraftOrm.workspace_id == workspace_id)
        .order_by(ToolDraftOrm.updated_at.desc(), ToolDraftOrm.id)
    )
    return [to_entity(ToolDraft, row) for row in rows.all()]


async def save_tool_draft(db: AsyncSession, entity: ToolDraft) -> ToolDraft:
    row = await save(db, ToolDraftOrm, entity)
    return to_entity(ToolDraft, row)


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


async def get_application_tool_binding(
    db: AsyncSession,
    workspace_id: str,
    application_id: str,
    tool_id: str,
) -> ApplicationToolBinding | None:
    row = await db.scalar(
        select(ApplicationToolBindingOrm).where(
            ApplicationToolBindingOrm.workspace_id == workspace_id,
            ApplicationToolBindingOrm.application_id == application_id,
            ApplicationToolBindingOrm.tool_id == tool_id,
        )
    )
    return to_entity(ApplicationToolBinding, row) if row is not None else None


async def list_application_tool_bindings(
    db: AsyncSession,
    workspace_id: str,
    application_id: str,
) -> list[ApplicationToolBinding]:
    rows = await db.scalars(
        select(ApplicationToolBindingOrm)
        .where(
            ApplicationToolBindingOrm.workspace_id == workspace_id,
            ApplicationToolBindingOrm.application_id == application_id,
        )
        .order_by(ApplicationToolBindingOrm.created_at, ApplicationToolBindingOrm.id)
    )
    return [to_entity(ApplicationToolBinding, row) for row in rows.all()]


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


async def list_application_tool_reference_map(
    db: AsyncSession,
    application_ids: list[str],
) -> dict[str, list[ToolRef]]:
    references = {application_id: [] for application_id in application_ids}
    if not application_ids:
        return references
    rows = await db.execute(
        select(
            ApplicationToolBindingOrm.application_id,
            ApplicationToolBindingOrm.tool_id,
            ApplicationToolBindingOrm.tool_version_id,
        )
        .where(ApplicationToolBindingOrm.application_id.in_(application_ids))
        .order_by(
            ApplicationToolBindingOrm.created_at,
            ApplicationToolBindingOrm.id,
        )
    )
    for application_id, tool_id, version_id in rows.all():
        references[application_id].append(
            ToolRef(tool_id=tool_id, version_id=version_id)
        )
    return references


async def list_application_mcp_reference_map(
    db: AsyncSession,
    application_ids: list[str],
) -> dict[str, list[dict[str, str]]]:
    references = {application_id: [] for application_id in application_ids}
    if not application_ids:
        return references
    rows = await db.execute(
        select(
            ApplicationToolBindingOrm.application_id,
            ToolVersionOrm.execution_spec,
        )
        .join(
            ToolVersionOrm,
            and_(
                ToolVersionOrm.workspace_id
                == ApplicationToolBindingOrm.workspace_id,
                ToolVersionOrm.id == ApplicationToolBindingOrm.tool_version_id,
            ),
        )
        .join(
            ToolOrm,
            and_(
                ToolOrm.workspace_id == ApplicationToolBindingOrm.workspace_id,
                ToolOrm.id == ApplicationToolBindingOrm.tool_id,
                ToolOrm.kind == "mcp",
            ),
        )
        .where(ApplicationToolBindingOrm.application_id.in_(application_ids))
        .order_by(
            ApplicationToolBindingOrm.created_at,
            ApplicationToolBindingOrm.id,
        )
    )
    for application_id, execution_spec in rows.all():
        server_id = execution_spec.get("server_id") if execution_spec else None
        tool_name = execution_spec.get("tool_name") if execution_spec else None
        if isinstance(server_id, str) and isinstance(tool_name, str):
            references[application_id].append(
                {"server_id": server_id, "tool_name": tool_name}
            )
    return references


async def save_application_tool_binding(
    db: AsyncSession,
    entity: ApplicationToolBinding,
) -> ApplicationToolBinding:
    row = await save(db, ApplicationToolBindingOrm, entity)
    return to_entity(ApplicationToolBinding, row)


async def replace_application_tool_bindings(
    db: AsyncSession,
    workspace_id: str,
    application_id: str,
    bindings: list[ApplicationToolBinding],
) -> None:
    await db.execute(
        delete(ApplicationToolBindingOrm).where(
            ApplicationToolBindingOrm.workspace_id == workspace_id,
            ApplicationToolBindingOrm.application_id == application_id,
        )
    )
    for binding in bindings:
        await save_application_tool_binding(db, binding)


async def sync_application_tool_bindings(
    db: AsyncSession,
    workspace_id: str,
    application_id: str,
    bindings: list[ApplicationToolBinding],
) -> None:
    desired_tool_ids = {binding.tool_id for binding in bindings}
    statement = delete(ApplicationToolBindingOrm).where(
        ApplicationToolBindingOrm.workspace_id == workspace_id,
        ApplicationToolBindingOrm.application_id == application_id,
    )
    if desired_tool_ids:
        statement = statement.where(
            ApplicationToolBindingOrm.tool_id.not_in(desired_tool_ids)
        )
    await db.execute(statement)
    for binding in bindings:
        await save_application_tool_binding(db, binding)


async def get_tool_invocation(
    db: AsyncSession,
    workspace_id: str,
    invocation_id: str,
) -> ToolInvocation | None:
    row = await db.scalar(
        select(ToolInvocationOrm).where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.id == invocation_id,
        )
    )
    return to_entity(ToolInvocation, row) if row is not None else None


async def get_tool_invocation_by_id(
    db: AsyncSession,
    invocation_id: str,
) -> ToolInvocation | None:
    row = await db.get(ToolInvocationOrm, invocation_id)
    return to_entity(ToolInvocation, row) if row is not None else None


async def get_tool_invocation_by_idempotency_key(
    db: AsyncSession,
    workspace_id: str,
    idempotency_key: str,
) -> ToolInvocation | None:
    row = await db.scalar(
        select(ToolInvocationOrm).where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.idempotency_key == idempotency_key,
        )
    )
    return to_entity(ToolInvocation, row) if row is not None else None


async def create_or_get_tool_invocation(
    db: AsyncSession,
    entity: ToolInvocation,
) -> ToolInvocation:
    existing = await get_tool_invocation_by_idempotency_key(
        db,
        entity.workspace_id,
        entity.idempotency_key,
    )
    if existing is not None:
        return existing
    values = {
        field.name: getattr(entity, field.name) for field in fields(ToolInvocation)
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(ToolInvocationOrm)
    elif dialect == "sqlite":
        statement = sqlite_insert(ToolInvocationOrm)
    else:
        raise RuntimeError(f"Unsupported Tool invocation dialect: {dialect}")
    await db.execute(
        statement.values(**values).on_conflict_do_nothing(
            index_elements=("workspace_id", "idempotency_key")
        )
    )
    stored = await get_tool_invocation_by_idempotency_key(
        db,
        entity.workspace_id,
        entity.idempotency_key,
    )
    if stored is None:
        raise RuntimeError("Tool invocation could not be persisted.")
    return stored


async def refresh_tool_invocation_deadline(
    db: AsyncSession,
    workspace_id: str,
    invocation_id: str,
    deadline_at: datetime,
) -> ToolInvocation | None:
    row = await db.scalar(
        select(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.id == invocation_id,
        )
        .with_for_update()
    )
    if row is None:
        return None
    if row.status in TOOL_INVOCATION_CLAIMABLE_STATUSES:
        row.policy_snapshot = {
            **row.policy_snapshot,
            "deadline_at": deadline_at.isoformat(),
        }
        row.updated_at = datetime.now(deadline_at.tzinfo)
        await db.flush()
    return to_entity(ToolInvocation, row)


async def resolve_tool_invocation_approval(
    db: AsyncSession,
    workspace_id: str,
    invocation_id: str,
    actor_id: str,
    resolved_at: datetime,
    deadline_at: datetime,
    *,
    approve: bool,
) -> bool:
    row = await db.scalar(
        select(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.id == invocation_id,
        )
        .with_for_update()
    )
    allowed_statuses = (
        {TOOL_INVOCATION_AWAITING_APPROVAL}
        if approve
        else {TOOL_INVOCATION_AWAITING_APPROVAL, TOOL_INVOCATION_UNCERTAIN}
    )
    if row is None or row.status not in allowed_statuses:
        return False
    row.approved_by_user_id = actor_id
    row.approved_at = resolved_at
    row.worker_task_id = None
    row.lease_expires_at = None
    row.updated_at = resolved_at
    if approve:
        row.status = TOOL_INVOCATION_APPROVED
        row.policy_snapshot = {
            **row.policy_snapshot,
            "deadline_at": deadline_at.isoformat(),
        }
        row.error_code = None
        row.error_message = None
        row.finished_at = None
    else:
        row.status = "rejected"
        row.result_summary = "Tool call rejected by user."
        row.error_code = "tool_call_rejected"
        row.error_message = "Tool call rejected by user."
        row.outcome = row.outcome or "confirmed"
        row.finished_at = resolved_at
    await db.flush()
    return True


async def claim_tool_invocation(
    db: AsyncSession,
    workspace_id: str,
    invocation_id: str,
    worker_task_id: str,
    now: datetime,
    lease_expires_at: datetime,
) -> bool:
    result = await db.execute(
        update(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.id == invocation_id,
            ToolInvocationOrm.attempts < ToolInvocationOrm.max_attempts,
            or_(
                ToolInvocationOrm.status.in_(TOOL_INVOCATION_CLAIMABLE_STATUSES),
                and_(
                    ToolInvocationOrm.status == TOOL_INVOCATION_RUNNING,
                    or_(
                        ToolInvocationOrm.lease_expires_at.is_(None),
                        ToolInvocationOrm.lease_expires_at < now,
                    ),
                ),
            ),
        )
        .values(
            status=TOOL_INVOCATION_RUNNING,
            attempts=ToolInvocationOrm.attempts + 1,
            worker_task_id=worker_task_id,
            lease_expires_at=lease_expires_at,
            started_at=func.coalesce(ToolInvocationOrm.started_at, now),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def finalize_tool_invocation(
    db: AsyncSession,
    workspace_id: str,
    invocation_id: str,
    worker_task_id: str,
    result: ToolInvocation,
) -> bool:
    updated = await db.execute(
        update(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.id == invocation_id,
            ToolInvocationOrm.status == TOOL_INVOCATION_RUNNING,
            ToolInvocationOrm.worker_task_id == worker_task_id,
        )
        .values(
            status=result.status,
            result_data=result.result_data,
            result_summary=result.result_summary,
            outcome=result.outcome,
            error_code=result.error_code,
            error_message=result.error_message,
            usage=result.usage,
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=result.finished_at,
            updated_at=result.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    return updated.rowcount == 1


async def fail_pending_tool_invocation(
    db: AsyncSession,
    workspace_id: str,
    invocation_id: str,
    result: ToolInvocation,
    now: datetime,
) -> bool:
    updated = await db.execute(
        update(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.id == invocation_id,
            or_(
                ToolInvocationOrm.status.in_(TOOL_INVOCATION_CLAIMABLE_STATUSES),
                and_(
                    ToolInvocationOrm.status == TOOL_INVOCATION_RUNNING,
                    or_(
                        ToolInvocationOrm.lease_expires_at.is_(None),
                        ToolInvocationOrm.lease_expires_at < now,
                    ),
                ),
            ),
        )
        .values(
            status=result.status,
            result_data=result.result_data,
            result_summary=result.result_summary,
            outcome=result.outcome,
            error_code=result.error_code,
            error_message=result.error_message,
            usage=result.usage,
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=result.finished_at,
            updated_at=result.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    return updated.rowcount == 1


async def requeue_tool_invocation(
    db: AsyncSession,
    workspace_id: str,
    invocation_id: str,
    worker_task_id: str,
    error_code: str,
    error_message: str,
    now: datetime,
) -> bool:
    updated = await db.execute(
        update(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.id == invocation_id,
            ToolInvocationOrm.status == TOOL_INVOCATION_RUNNING,
            ToolInvocationOrm.worker_task_id == worker_task_id,
        )
        .values(
            status=TOOL_INVOCATION_QUEUED,
            worker_task_id=None,
            lease_expires_at=None,
            error_code=error_code,
            error_message=error_message,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return updated.rowcount == 1


async def list_tool_invocations(
    db: AsyncSession,
    workspace_id: str,
    run_id: str | None = None,
) -> list[ToolInvocation]:
    statement = select(ToolInvocationOrm).where(
        ToolInvocationOrm.workspace_id == workspace_id
    )
    if run_id is not None:
        statement = statement.where(ToolInvocationOrm.run_id == run_id)
    rows = await db.scalars(
        statement.order_by(ToolInvocationOrm.created_at.desc(), ToolInvocationOrm.id)
    )
    return [to_entity(ToolInvocation, row) for row in rows.all()]


async def settle_exhausted_agent_tool_invocations(
    db: AsyncSession,
    run_ids: list[str],
    now: datetime,
) -> int:
    if not run_ids:
        return 0
    rows = await db.scalars(
        select(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.run_id.in_(run_ids),
            ToolInvocationOrm.status.in_(
                ("queued", "awaiting_approval", "approved", "running")
            ),
        )
        .with_for_update()
    )
    invocations = list(rows.all())
    for invocation in invocations:
        snapshot = invocation.policy_snapshot.get("tool_snapshot", {})
        effect = snapshot.get("effect") if isinstance(snapshot, dict) else None
        status, outcome, summary, message = (
            exhausted_tool_invocation_terminal_state(invocation.status, effect)
        )
        invocation.status = status
        invocation.outcome = outcome
        invocation.result_summary = summary
        invocation.error_code = "agent_run_retry_exhausted"
        invocation.error_message = message
        invocation.worker_task_id = None
        invocation.lease_expires_at = None
        invocation.finished_at = now
        invocation.updated_at = now
    await db.flush()
    return len(invocations)


async def settle_cancelled_agent_tool_invocations(
    db: AsyncSession,
    run_ids: list[str],
    now: datetime,
) -> int:
    if not run_ids:
        return 0
    rows = await db.scalars(
        select(ToolInvocationOrm)
        .where(
            ToolInvocationOrm.run_id.in_(run_ids),
            ToolInvocationOrm.status.in_(
                ("queued", "awaiting_approval", "approved", "running")
            ),
        )
        .with_for_update()
    )
    invocations = list(rows.all())
    for invocation in invocations:
        snapshot = invocation.policy_snapshot.get("tool_snapshot", {})
        effect = snapshot.get("effect") if isinstance(snapshot, dict) else None
        status, outcome, summary, _message = exhausted_tool_invocation_terminal_state(
            invocation.status,
            effect,
        )
        invocation.status = status
        invocation.outcome = outcome
        invocation.result_summary = summary
        invocation.error_code = "agent_run_cancelled"
        invocation.error_message = (
            "Tool execution was interrupted by cancellation; confirm the external state."
            if outcome == "uncertain"
            else "Tool invocation was cancelled before completion."
        )
        invocation.worker_task_id = None
        invocation.lease_expires_at = None
        invocation.finished_at = now
        invocation.updated_at = now
    await db.flush()
    return len(invocations)


async def has_unsettled_agent_tool_invocations(
    db: AsyncSession,
    workspace_id: str,
    run_ids: list[str],
) -> bool:
    if not run_ids:
        return False
    invocation_id = await db.scalar(
        select(ToolInvocationOrm.id)
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            ToolInvocationOrm.run_id.in_(run_ids),
            ToolInvocationOrm.status.not_in(
                tuple(TOOL_INVOCATION_TERMINAL_STATUSES)
            ),
        )
        .limit(1)
    )
    return invocation_id is not None


async def list_recoverable_tool_test_invocation_ids(
    db: AsyncSession,
    now: datetime,
    limit: int = 100,
) -> list[str]:
    rows = await db.scalars(
        select(ToolInvocationOrm.id)
        .where(
            ToolInvocationOrm.origin == "test",
            or_(
                and_(
                    ToolInvocationOrm.status == TOOL_INVOCATION_QUEUED,
                    ToolInvocationOrm.attempts < ToolInvocationOrm.max_attempts,
                ),
                and_(
                    ToolInvocationOrm.status == TOOL_INVOCATION_RUNNING,
                    or_(
                        ToolInvocationOrm.lease_expires_at.is_(None),
                        ToolInvocationOrm.lease_expires_at < now,
                    ),
                ),
            ),
        )
        .order_by(ToolInvocationOrm.created_at, ToolInvocationOrm.id)
        .limit(limit)
    )
    return list(rows.all())


async def save_tool_invocation(
    db: AsyncSession,
    entity: ToolInvocation,
) -> ToolInvocation:
    row = await save(db, ToolInvocationOrm, entity)
    return to_entity(ToolInvocation, row)


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

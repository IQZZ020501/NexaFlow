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


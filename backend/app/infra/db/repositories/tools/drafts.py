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


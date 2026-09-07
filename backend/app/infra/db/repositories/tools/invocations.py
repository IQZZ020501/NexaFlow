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



def _tool_invocation_effect(invocation: ToolInvocationOrm) -> str | None:
    snapshot = invocation.policy_snapshot.get("tool_snapshot", {})
    if isinstance(snapshot, dict) and snapshot.get("effect"):
        return str(snapshot["effect"])
    internal = invocation.policy_snapshot.get("internal_tool", {})
    if isinstance(internal, dict) and internal.get("effect"):
        return str(internal["effect"])
    return None

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
        effect = _tool_invocation_effect(invocation)
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
        effect = _tool_invocation_effect(invocation)
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


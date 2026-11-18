from datetime import timedelta

from sqlalchemy import and_, or_, select, update

from app.domain.tools.mcp.task_models import McpRemoteTask as TaskOrm
from app.domain.tools.models import ToolInvocation as InvocationOrm
from app.entities.defaults import utc_now
from app.entities.mcp_tasks import McpRemoteTask
from app.infra.db import mapping
from app.infra.db.repositories.tools.invocations import owned_tool_invocation


async def get(db, invocation_id, *, lock=False):
    query = select(TaskOrm).where(TaskOrm.invocation_id == invocation_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    return mapping.to_entity(McpRemoteTask, row) if row else None


async def save(db, task):
    return mapping.to_entity(McpRemoteTask, await mapping.save(db, TaskOrm, task))


async def owned_invocation(db, context, settings):
    now = utc_now()
    return await owned_tool_invocation(
        db, context, now,
        renew_until=now + timedelta(seconds=settings.agent_executor_lease_seconds),
    )


async def progress(db, invocation, task):
    row = await db.get(InvocationOrm, invocation.id)
    row.result_data = {
        "remote_task": {"id": task.id, "task_id": task.remote_id, "status": task.status}
    }
    row.updated_at = utc_now()
    await db.flush()


async def due_cancellations(db, now, limit=10):
    rows = await db.scalars(
        select(TaskOrm)
        .outerjoin(InvocationOrm, InvocationOrm.id == TaskOrm.invocation_id)
        .where(
            TaskOrm.status.in_(
                ("ready", "submitting", "queued", "running", "uncertain")
            ),
            TaskOrm.next_cancel_at <= now,
            or_(TaskOrm.cancel_lease_until.is_(None), TaskOrm.cancel_lease_until < now),
            or_(
                TaskOrm.cancel_requested.is_(True),
                TaskOrm.deadline_at <= now,
                InvocationOrm.id.is_(None),
                and_(
                    InvocationOrm.status.in_(
                        ("failed", "cancelled", "uncertain", "rejected")
                    )
                ),
            ),
        )
        .order_by(TaskOrm.next_cancel_at)
        .limit(limit)
        .with_for_update(of=TaskOrm, skip_locked=True)
    )
    return [mapping.to_entity(McpRemoteTask, row) for row in rows]


async def cancel_runs(db, run_ids):
    await db.execute(
        update(TaskOrm)
        .where(
            TaskOrm.invocation_id.in_(
                select(InvocationOrm.id).where(InvocationOrm.run_id.in_(run_ids))
            ),
            TaskOrm.status.in_(
                ("ready", "submitting", "queued", "running", "uncertain")
            ),
        )
        .values(cancel_requested=True, next_cancel_at=utc_now())
        .execution_options(synchronize_session=False)
    )


async def by_id(db, id, *, lock=False):
    query = select(TaskOrm).where(TaskOrm.id == id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    return mapping.to_entity(McpRemoteTask, row) if row else None

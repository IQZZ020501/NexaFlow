from sqlalchemy import delete, func, select

from app.domain.agents.models import (
    AGENT_RUN_RUNNING_STATUSES,
    AgentRunSnapshot,
    AgentRunState,
)
from app.domain.projects.models import AgentProject as ProjectRow
from app.domain.projects.models import ProjectFileVersion as VersionRow
from app.domain.projects.models import ProjectRunState as StateRow
from app.entities.projects import AgentProject, ProjectFileVersion, ProjectRunState
from app.infra.db import mapping


async def get_project(db, project_id, *, lock=False):
    query = select(ProjectRow).where(ProjectRow.id == project_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    return mapping.to_entity(AgentProject, row) if row else None


async def save_project(db, project):
    row = await mapping.save(db, ProjectRow, project)
    return mapping.to_entity(AgentProject, row)


async def latest_files(db, project_id):
    # Metadata only: do not read every historical file blob for each listing.
    ranked = (
        select(
            VersionRow.id,
            func.row_number()
            .over(partition_by=VersionRow.path, order_by=VersionRow.revision.desc())
            .label("rank"),
        )
        .where(VersionRow.project_id == project_id)
        .subquery()
    )
    fields = [
        getattr(VersionRow, name)
        for name in ProjectFileVersion.__dataclass_fields__
        if name != "content"
    ]
    rows = (
        (
            await db.execute(
                select(*fields)
                .join(ranked, ranked.c.id == VersionRow.id)
                .where(ranked.c.rank == 1)
                .order_by(VersionRow.path)
            )
        )
        .mappings()
        .all()
    )
    return [ProjectFileVersion(**dict(row)) for row in rows]


async def get_version(db, project_id, version_id):
    row = await db.scalar(
        select(VersionRow).where(
            VersionRow.project_id == project_id, VersionRow.id == version_id
        )
    )
    return mapping.to_entity(ProjectFileVersion, row) if row else None


async def history_bytes(db, project_id):
    return int(
        await db.scalar(
            select(func.coalesce(func.sum(VersionRow.size_bytes), 0)).where(
                VersionRow.project_id == project_id
            )
        )
        or 0
    )


async def create_version(db, version):
    # Immutable: this repository intentionally exposes no update wrapper.
    row = VersionRow(
        **{name: getattr(version, name) for name in version.__dataclass_fields__}
    )
    db.add(row)
    await db.flush()
    return mapping.to_entity(ProjectFileVersion, row)


async def get_run_state(db, run_id):
    row = await db.get(StateRow, run_id)
    return mapping.to_entity(ProjectRunState, row) if row else None


async def save_run_state(db, state):
    row = await db.get(StateRow, state.run_id)
    values = {name: getattr(state, name) for name in state.__dataclass_fields__}
    if row is None:
        row = StateRow(**values)
        db.add(row)
    else:
        for name, value in values.items():
            setattr(row, name, value)
    await db.flush()
    return mapping.to_entity(ProjectRunState, row)


async def lock_run_writer(db, run_id, worker_task_id, now):
    return (
        await db.scalar(
            select(AgentRunState.run_id)
            .where(
                AgentRunState.run_id == run_id,
                AgentRunState.worker_task_id == worker_task_id,
                AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
                AgentRunState.lease_expires_at > now,
                AgentRunState.execution_deadline_at > now,
            )
            .with_for_update()
        )
        is not None
    )


async def delete_conversation_files(db, run_ids):
    snapshots = await db.scalars(
        select(AgentRunSnapshot.application_snapshot).where(
            AgentRunSnapshot.run_id.in_(run_ids)
        )
    )
    ids = {
        payload["project"]["id"]
        for payload in snapshots
        if payload.get("project", {}).get("conversation_scope")
    }
    if ids:
        still_referenced = select(StateRow.project_id).where(
            StateRow.run_id.not_in(run_ids)
        )
        await db.execute(
            delete(ProjectRow).where(
                ProjectRow.id.in_(ids), ProjectRow.id.not_in(still_referenced)
            )
        )

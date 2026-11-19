"""Persistence and fencing for user memories and durable extraction jobs."""

from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.agents.models import AgentRun
from app.domain.memories import models as rows
from app.domain.projects.models import ChatProject as ChatProjectRow
from app.entities.defaults import new_id, utc_now
from app.entities.memories import MemoryJob, MemoryPreferences, UserMemory
from app.entities.projects import ChatProject
from app.infra.db import mapping


async def get_preferences(db, workspace_id, user_id, *, lock=False):
    statement = select(rows.MemoryPreferences).where(
        rows.MemoryPreferences.workspace_id == workspace_id,
        rows.MemoryPreferences.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement.execution_options(populate_existing=True))
    return mapping.to_entity(MemoryPreferences, row) if row else None


async def save_preferences(db, value):
    await mapping.save(db, rows.MemoryPreferences, value)
    return value


async def get_or_create_preferences(db, workspace_id, user_id, *, lock=False):
    profile = await get_preferences(db, workspace_id, user_id, lock=lock)
    if profile is not None:
        return profile
    profile = MemoryPreferences(workspace_id=workspace_id, user_id=user_id)
    try:
        async with db.begin_nested():
            await save_preferences(db, profile)
            await db.flush()
    except IntegrityError:
        pass
    return await get_preferences(db, workspace_id, user_id, lock=lock)


async def list_memories(db, profile_id):
    result = await db.scalars(
        select(rows.UserMemory)
        .where(rows.UserMemory.profile_id == profile_id)
        .order_by(rows.UserMemory.updated_at.desc(), rows.UserMemory.id)
    )
    return [mapping.to_entity(UserMemory, row) for row in result]


async def list_projects(db, workspace_id, owner_id):
    result = await db.scalars(
        select(ChatProjectRow)
        .where(
            ChatProjectRow.workspace_id == workspace_id,
            ChatProjectRow.owner_user_id == owner_id,
            ChatProjectRow.dissolved_at.is_(None),
        )
        .order_by(ChatProjectRow.updated_at.desc(), ChatProjectRow.id)
    )
    return [mapping.to_entity(ChatProject, row) for row in result]


async def save_memory(db, value):
    await mapping.save(db, rows.UserMemory, value)
    return value


async def delete_memory(db, profile_id, memory_id=None):
    statement = delete(rows.UserMemory).where(rows.UserMemory.profile_id == profile_id)
    if memory_id is not None:
        statement = statement.where(rows.UserMemory.id == memory_id)
    return (await db.execute(statement)).rowcount


async def delete_user_data(db, user_id):
    profiles = select(rows.MemoryPreferences.id).where(
        rows.MemoryPreferences.user_id == user_id
    )
    await db.execute(
        delete(rows.MemoryJob).where(rows.MemoryJob.profile_id.in_(profiles))
    )
    await db.execute(
        delete(rows.UserMemory).where(rows.UserMemory.profile_id.in_(profiles))
    )
    await db.execute(
        delete(rows.MemoryPreferences).where(rows.MemoryPreferences.user_id == user_id)
    )


async def delete_application_data(db, agent_id):
    run_ids = select(AgentRun.id).where(AgentRun.agent_id == agent_id)
    project_ids = select(ChatProjectRow.id).where(ChatProjectRow.agent_id == agent_id)
    affected_profiles = select(rows.UserMemory.profile_id).where(
        rows.UserMemory.project_id.in_(project_ids)
    )
    await db.execute(delete(rows.MemoryJob).where(rows.MemoryJob.run_id.in_(run_ids)))
    await db.execute(
        update(rows.MemoryPreferences)
        .where(rows.MemoryPreferences.id.in_(affected_profiles))
        .values(epoch=rows.MemoryPreferences.epoch + 1)
    )
    await db.execute(
        delete(rows.UserMemory).where(rows.UserMemory.project_id.in_(project_ids))
    )


async def queue_job(db, profile_id, run_id, epoch):
    if await db.scalar(
        select(rows.MemoryJob.id).where(rows.MemoryJob.run_id == run_id)
    ):
        return
    await mapping.save(
        db, rows.MemoryJob, MemoryJob(profile_id=profile_id, run_id=run_id, epoch=epoch)
    )


async def due_jobs(db):
    return list(
        await db.scalars(
            select(rows.MemoryJob.id)
            .where(
                rows.MemoryJob.status != "done",
                rows.MemoryJob.available_at <= utc_now(),
                rows.MemoryJob.attempts < 3,
            )
            .limit(50)
        )
    )


async def claim_job(db, job_id):
    token = new_id()
    result = await db.execute(
        update(rows.MemoryJob)
        .where(
            rows.MemoryJob.id == job_id,
            rows.MemoryJob.status != "done",
            rows.MemoryJob.available_at <= utc_now(),
            rows.MemoryJob.attempts < 3,
        )
        .values(
            status="running",
            lease_token=token,
            attempts=rows.MemoryJob.attempts + 1,
            available_at=utc_now() + timedelta(seconds=120),
        )
    )
    if not result.rowcount:
        return None
    row = await db.get(rows.MemoryJob, job_id, populate_existing=True)
    return mapping.to_entity(MemoryJob, row)


async def finish_job(db, job, *, retry=False):
    await db.execute(
        update(rows.MemoryJob)
        .where(
            rows.MemoryJob.id == job.id, rows.MemoryJob.lease_token == job.lease_token
        )
        .values(
            status="pending" if retry and job.attempts < 3 else "done",
            lease_token=None,
            available_at=utc_now() + timedelta(seconds=60),
        )
    )


async def owns_job(db, job):
    return (
        await db.scalar(
            select(rows.MemoryJob.id)
            .where(
                rows.MemoryJob.id == job.id,
                rows.MemoryJob.lease_token == job.lease_token,
                rows.MemoryJob.status == "running",
                rows.MemoryJob.available_at > utc_now(),
            )
            .with_for_update()
        )
        is not None
    )

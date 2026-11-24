from datetime import datetime

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.agents.models import (
    AGENT_RUN_CANCELLED_STATUS,
    AGENT_RUN_FAILED_STATUS,
    AGENT_RUN_SUCCEEDED_STATUS,
    AgentRunState,
)
from app.domain.agents.models import AgentRun as RunRow
from app.domain.artifacts.models import GeneratedArtifact as GeneratedArtifactOrm
from app.entities.artifacts import GeneratedArtifact
from app.entities.runs import AgentRun
from app.infra.db import mapping


async def create_artifact(
    db: AsyncSession,
    artifact: GeneratedArtifact,
) -> GeneratedArtifact:
    row = await mapping.save(db, GeneratedArtifactOrm, artifact)
    return mapping.to_entity(GeneratedArtifact, row)


async def get_artifact_by_idempotency_key(
    db: AsyncSession,
    workspace_id: str,
    idempotency_key: str,
) -> GeneratedArtifact | None:
    row = await db.scalar(
        select(GeneratedArtifactOrm).where(
            GeneratedArtifactOrm.workspace_id == workspace_id,
            GeneratedArtifactOrm.idempotency_key == idempotency_key,
        )
    )
    return mapping.to_entity(GeneratedArtifact, row) if row is not None else None


async def get_active_artifact(
    db: AsyncSession,
    artifact_id: str,
    now: datetime,
) -> GeneratedArtifact | None:
    row = await db.scalar(
        select(GeneratedArtifactOrm).where(
            GeneratedArtifactOrm.id == artifact_id,
            GeneratedArtifactOrm.expires_at > now,
        )
    )
    return mapping.to_entity(GeneratedArtifact, row) if row is not None else None


async def get_artifact(db: AsyncSession, artifact_id: str) -> GeneratedArtifact | None:
    row = await db.get(GeneratedArtifactOrm, artifact_id)
    return mapping.to_entity(GeneratedArtifact, row) if row is not None else None


async def delete_expired_artifacts(db: AsyncSession, now: datetime) -> None:
    await db.execute(
        delete(GeneratedArtifactOrm).where(
            GeneratedArtifactOrm.expires_at <= now,
            ~exists(
                select(RunRow.id).where(
                    RunRow.id == GeneratedArtifactOrm.run_id,
                    RunRow.workspace_id == GeneratedArtifactOrm.workspace_id,
                )
            ),
        )
    )


def _conversation_scope(run: AgentRun):
    return (
        GeneratedArtifactOrm.workspace_id == run.workspace_id,
        RunRow.workspace_id == run.workspace_id,
        RunRow.agent_id == run.agent_id,
        RunRow.access_source == run.access_source,
        RunRow.consumer_id == run.consumer_id,
        RunRow.execution_user_id == run.execution_user_id,
        RunRow.conversation_id == run.conversation_id,
    )


async def list_conversation_files(
    db: AsyncSession, run: AgentRun
) -> list[tuple[str, str, int]]:
    """Latest immutable version per path; metadata only, never load every blob."""
    successor = aliased(RunRow)
    successor_state = aliased(AgentRunState)
    path = func.coalesce(GeneratedArtifactOrm.relative_path, GeneratedArtifactOrm.filename)
    ranked = (
        select(
            GeneratedArtifactOrm.id,
            path.label("path"),
            GeneratedArtifactOrm.size_bytes,
            func.row_number().over(
                partition_by=path,
                order_by=(
                    RunRow.created_at.desc(),
                    GeneratedArtifactOrm.created_at.desc(),
                    GeneratedArtifactOrm.id.desc(),
                ),
            ).label("rank"),
        )
        .join(RunRow, RunRow.id == GeneratedArtifactOrm.run_id)
        .join(AgentRunState, AgentRunState.run_id == RunRow.id)
        .where(
            *_conversation_scope(run),
            or_(
                RunRow.id == run.id,
                and_(
                    AgentRunState.status == AGENT_RUN_SUCCEEDED_STATUS,
                    or_(
                        RunRow.created_at < run.created_at,
                        and_(RunRow.created_at == run.created_at, RunRow.id < run.id),
                    ),
                    ~exists(
                        select(successor.id)
                        .join(successor_state, successor_state.run_id == successor.id)
                        .where(
                            successor.regenerated_from_run_id == RunRow.id,
                            successor_state.status.notin_(
                                (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
                            ),
                        )
                    ),
                ),
            ),
        )
        .subquery()
    )
    rows = await db.execute(
        select(ranked.c.id, ranked.c.path, ranked.c.size_bytes)
        .where(ranked.c.rank == 1)
        .order_by(ranked.c.path)
    )
    return [tuple(row) for row in rows]


async def get_conversation_file(
    db: AsyncSession, run: AgentRun, artifact_id: str
) -> GeneratedArtifact | None:
    row = await db.scalar(
        select(GeneratedArtifactOrm)
        .join(RunRow, RunRow.id == GeneratedArtifactOrm.run_id)
        .where(*_conversation_scope(run), GeneratedArtifactOrm.id == artifact_id)
    )
    return mapping.to_entity(GeneratedArtifact, row) if row is not None else None


async def list_root_run_artifacts(
    db: AsyncSession,
    workspace_id: str,
    root_run_id: str,
) -> list[GeneratedArtifact]:
    """List artifact metadata for a root Run and any child Runs without reading blobs."""
    rows = await db.execute(
        select(
            GeneratedArtifactOrm.id,
            GeneratedArtifactOrm.workspace_id,
            GeneratedArtifactOrm.run_id,
            GeneratedArtifactOrm.idempotency_key,
            GeneratedArtifactOrm.format,
            GeneratedArtifactOrm.filename,
            GeneratedArtifactOrm.relative_path,
            GeneratedArtifactOrm.content_hash,
            GeneratedArtifactOrm.previous_artifact_id,
            GeneratedArtifactOrm.invocation_id,
            GeneratedArtifactOrm.inspection,
            GeneratedArtifactOrm.media_type,
            GeneratedArtifactOrm.size_bytes,
            GeneratedArtifactOrm.expires_at,
            GeneratedArtifactOrm.created_at,
        )
        .join(RunRow, RunRow.id == GeneratedArtifactOrm.run_id)
        .where(
            GeneratedArtifactOrm.workspace_id == workspace_id,
            RunRow.workspace_id == workspace_id,
            or_(RunRow.id == root_run_id, RunRow.root_run_id == root_run_id),
        )
        .order_by(
            GeneratedArtifactOrm.created_at.asc(),
            GeneratedArtifactOrm.id.asc(),
        )
    )
    return [
        GeneratedArtifact(
            id=row.id,
            workspace_id=row.workspace_id,
            run_id=row.run_id,
            idempotency_key=row.idempotency_key,
            format=row.format,
            filename=row.filename,
            relative_path=row.relative_path,
            content_hash=row.content_hash,
            previous_artifact_id=row.previous_artifact_id,
            invocation_id=row.invocation_id,
            inspection=dict(row.inspection or {}),
            media_type=row.media_type,
            content=b"",
            size_bytes=row.size_bytes,
            expires_at=row.expires_at,
            created_at=row.created_at,
        )
        for row in rows.all()
    ]

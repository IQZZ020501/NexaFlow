from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.artifacts import GeneratedArtifact
from app.infrastructure.repositories import mapping
from app.shareddomain.artifacts.models import GeneratedArtifact as GeneratedArtifactOrm


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


async def delete_expired_artifacts(db: AsyncSession, now: datetime) -> None:
    await db.execute(
        delete(GeneratedArtifactOrm).where(GeneratedArtifactOrm.expires_at <= now)
    )

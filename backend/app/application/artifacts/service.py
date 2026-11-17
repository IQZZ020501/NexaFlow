import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.artifacts.services import (
    artifact_workspace_path,
    validate_artifact_inspection,
    validate_generated_artifact,
)
from app.entities.artifacts import GeneratedArtifact
from app.entities.defaults import utc_now
from app.infra.config.settings import Settings
from app.infra.db.repositories.artifacts import repository
from app.infra.db.session import get_session_factory
from app.infra.security.auth import (
    create_artifact_download_token,
    decode_artifact_download_token,
)

ARTIFACT_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class GeneratedArtifactLink:
    artifact_id: str
    format: str
    filename: str
    media_type: str
    download_url: str
    expires_at: datetime
    size_bytes: int
    relative_path: str | None = None
    content_hash: str | None = None
    previous_artifact_id: str | None = None
    inspection: dict = field(default_factory=dict)


def _artifact_link(
    artifact: GeneratedArtifact,
    settings: Settings,
) -> GeneratedArtifactLink:
    # A random v4 UUID is the short-lived bearer for generated PNGs. Other
    # formats keep their signed tokens; existing signed image links still work.
    token = (
        artifact.id
        if artifact.format == "png" and artifact.media_type == "image/png"
        else create_artifact_download_token(artifact.id, artifact.expires_at, settings)
    )
    return GeneratedArtifactLink(
        artifact_id=artifact.id,
        format=artifact.format,
        filename=artifact.filename,
        media_type=artifact.media_type,
        download_url=f"/api/v1/artifacts/{token}",
        expires_at=artifact.expires_at,
        size_bytes=artifact.size_bytes,
        relative_path=artifact.relative_path,
        content_hash=artifact.content_hash,
        previous_artifact_id=artifact.previous_artifact_id,
        inspection=artifact.inspection,
    )


async def create_generated_artifact(
    db: AsyncSession,
    settings: Settings,
    *,
    workspace_id: str,
    run_id: str | None,
    idempotency_key: str,
    artifact_format: str,
    filename: str,
    content: bytes,
    relative_path: str | None = None,
    invocation_id: str | None = None,
    inspection: dict | None = None,
) -> GeneratedArtifactLink:
    if not workspace_id or not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("Artifact identity is invalid.")
    existing = await repository.get_artifact_by_idempotency_key(
        db,
        workspace_id,
        idempotency_key,
    )
    if existing is not None:
        return _artifact_link(existing, settings)

    media_type = await asyncio.to_thread(validate_generated_artifact, artifact_format, filename, content)
    report = validate_artifact_inspection(inspection, artifact_format, content)
    if relative_path is not None:
        artifact_workspace_path(relative_path)
        if relative_path.rsplit("/", 1)[-1] != filename:
            raise ValueError("Artifact path does not match its filename.")
    now = utc_now()
    previous_id = None
    if run_id:
        from app.infra.db.repositories.agents import repository as runs

        run = await runs.get_agent_run_by_id(db, run_id)
        if run is not None and run.workspace_id == workspace_id:
            files = await repository.list_conversation_files(db, run)
            previous_id = next(
                (
                    item_id
                    for item_id, path, _ in files
                    if path == (relative_path or filename)
                ),
                None,
            )
    artifact = await repository.create_artifact(
        db,
        GeneratedArtifact(
            workspace_id=workspace_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            format=artifact_format,
            filename=filename,
            relative_path=relative_path,
            content_hash=hashlib.sha256(content).hexdigest(),
            previous_artifact_id=previous_id,
            invocation_id=invocation_id,
            inspection=report,
            media_type=media_type,
            content=content,
            size_bytes=len(content),
            expires_at=now + ARTIFACT_TTL,
            created_at=now,
        ),
    )
    return _artifact_link(artifact, settings)


async def get_generated_artifact(
    db: AsyncSession,
    settings: Settings,
    token: str,
) -> GeneratedArtifact | None:
    try:
        image_id = UUID(token)
    except ValueError:
        image_id = None
    if image_id is not None and image_id.version == 4 and str(image_id) == token:
        artifact = await repository.get_active_artifact(db, token, utc_now())
        return (
            artifact
            if artifact is not None
            and artifact.format == "png"
            and artifact.media_type == "image/png"
            else None
        )
    artifact_id = decode_artifact_download_token(token, settings)
    if artifact_id is None:
        return None
    return await repository.get_active_artifact(db, artifact_id, utc_now())


async def cleanup_expired_generated_artifacts() -> None:
    async with get_session_factory()() as db:
        await repository.delete_expired_artifacts(db, utc_now())
        await db.commit()


async def get_authorized_artifact(db, artifact_id, actor):
    """Recheck current membership, publication and conversation ownership per read."""
    from fastapi import HTTPException

    from app.application.agents.access.service import (
        get_workspace_published_application_context,
    )
    from app.application.workspaces.service import build_workspace_context
    from app.domain.agents.access.permissions import require_agent_view
    from app.domain.agents.service import get_agent
    from app.infra.db.repositories.agents import repository as runs

    artifact = await repository.get_artifact(db, artifact_id)
    run = (
        await runs.get_agent_run_by_id(db, artifact.run_id)
        if artifact and artifact.run_id
        else None
    )
    if run is None or artifact.workspace_id != run.workspace_id:
        raise HTTPException(404, "Artifact not found.")
    if run.parent_run_id:
        root = await runs.get_agent_run_by_id(db, run.root_run_id)
        if root is None or root.workspace_id != run.workspace_id:
            raise HTTPException(404, "Artifact not found.")
        run = root
    agent = await get_agent(db, run.workspace_id, run.agent_id)
    if run.access_source == "console":
        if run.consumer_id != actor.id or run.requested_by_user_id != actor.id:
            raise HTTPException(404, "Artifact not found.")
        await build_workspace_context(db, actor, run.workspace_id)
        await require_agent_view(db, agent, actor)
    elif run.access_source == "public" and run.consumer_id == actor.id:
        await get_workspace_published_application_context(
            db, run.agent_id, actor, agent.app_type
        )
    else:
        raise HTTPException(404, "Artifact not found.")
    return artifact


async def get_run_artifact(db, artifact_id, run):
    """Caller must first authorize the Run with its current API credential."""
    from fastapi import HTTPException

    artifact = await repository.get_artifact(db, artifact_id)
    if artifact is None or artifact.workspace_id != run.workspace_id:
        raise HTTPException(404, "Artifact not found.")
    if artifact.run_id != run.id:
        from app.infra.db.repositories.agents import repository as runs

        source = await runs.get_agent_run_by_id(db, artifact.run_id)
        if (
            source is None
            or source.workspace_id != run.workspace_id
            or source.root_run_id != run.id
        ):
            raise HTTPException(404, "Artifact not found.")
    return artifact

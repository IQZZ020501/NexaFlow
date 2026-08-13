from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import Agent
from app.entities.user import User
from app.entities.workflows import WorkflowUpload
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id
from app.infrastructure.object_storage import (
    EmptyObjectError,
    create_object_storage,
)
from app.infrastructure.repositories import workflow as workflow_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.ports.parsing import KnowledgePipelineError, build_document_parser
from app.schemas.agent import AgentInteractionConfig, AgentUploadResponse
from app.schemas.workflow import WorkflowUploadResponse
from app.shareddomain.agents.permissions import require_agent_view
from app.shareddomain.agents.services import get_agent
from app.shareddomain.workflows.uploads import queue_upload_cleanups

if TYPE_CHECKING:
    from app.application.agent_access import PublishedAgentContext

UPLOAD_CHUNK_BYTES = 1024 * 1024
UPLOAD_EXTENSIONS = {
    "document": {
        ".csv", ".docx", ".epub", ".html", ".ipynb", ".json", ".md",
        ".pdf", ".pptx", ".txt", ".xls", ".xlsx", ".xml", ".zip",
    },
    "image": {".jpeg", ".jpg", ".png", ".webp"},
    "audio": {".m4a", ".mp3", ".ogg", ".wav", ".webm"},
}
AGENT_ATTACHMENT_TYPES = {"document", "image"}
AGENT_ATTACHMENT_CONFIG = AgentInteractionConfig(file_upload=True)
AGENT_FILE_TEXT_LIMIT = 20_000
AGENT_ATTACHMENT_CONTEXT_LIMIT = 50_000


def published_interaction_config(
    context: PublishedAgentContext,
) -> AgentInteractionConfig:
    value = (
        context.publication.interaction_config
        if context.publication is not None
        else context.agent.interaction_config
    )
    return AgentInteractionConfig.model_validate(value)


def _upload_category(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower()
    return next(
        (category for category, suffixes in UPLOAD_EXTENSIONS.items() if suffix in suffixes),
        None,
    )


async def upload_public_workflow_files(
    db: AsyncSession,
    context: PublishedAgentContext,
    user_id: str,
    uploads: list[UploadFile],
    settings: Settings,
) -> list[WorkflowUploadResponse]:
    config = published_interaction_config(context)
    stored = await _upload_files(
        db,
        context.agent,
        user_id,
        uploads,
        settings,
        config,
        "workflow",
    )
    return [
        WorkflowUploadResponse(
            id=item.id,
            filename=item.filename,
            content_type=item.content_type,
            size_bytes=item.size_bytes,
            category=item.category,
        )
        for item in stored
    ]


async def upload_public_agent_files(
    db: AsyncSession,
    context: PublishedAgentContext,
    user_id: str,
    uploads: list[UploadFile],
    settings: Settings,
) -> list[AgentUploadResponse]:
    config = published_interaction_config(context)
    stored = await _upload_files(
        db,
        context.agent,
        user_id,
        uploads,
        settings,
        config,
        "agent",
    )
    return [
        AgentUploadResponse(
            id=item.id,
            filename=item.filename,
            content_type=item.content_type,
            size_bytes=item.size_bytes,
            category=item.category,
        )
        for item in stored
    ]


async def upload_workspace_agent_files(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    uploads: list[UploadFile],
    settings: Settings,
) -> list[AgentUploadResponse]:
    agent = await get_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor, workspace_role)
    stored = await _upload_files(
        db,
        agent,
        actor.id,
        uploads,
        settings,
        AgentInteractionConfig.model_validate(agent.interaction_config),
        "agent",
    )
    return [
        AgentUploadResponse(
            id=item.id,
            filename=item.filename,
            content_type=item.content_type,
            size_bytes=item.size_bytes,
            category=item.category,
        )
        for item in stored
    ]


async def _upload_files(
    db: AsyncSession,
    agent: Agent,
    user_id: str,
    uploads: list[UploadFile],
    settings: Settings,
    config: AgentInteractionConfig,
    application_type: str,
) -> list[WorkflowUpload]:
    if application_type == "agent":
        config = AGENT_ATTACHMENT_CONFIG
    if not config.file_upload:
        raise HTTPException(status.HTTP_409_CONFLICT, "File upload is disabled.")
    if not uploads:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload files.")
    upload_config = config.file_upload_setting

    if await workspace_repository.lock_workspace(db, agent.workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload workspace not found.")
    if await user_repository.lock_user(db, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload user not found.")
    if not await workflow_repository.lock_upload_application(
        db,
        agent.workspace_id,
        agent.id,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload application not found.")

    storage = create_object_storage(settings.knowledge_storage_dir)
    stored: list[WorkflowUpload] = []
    stored_keys: list[str] = []
    try:
        for upload in uploads:
            filename = Path(upload.filename or "").name.strip()[:255]
            category = _upload_category(filename)
            if (
                not filename
                or category not in upload_config.file_upload_type
                or (application_type == "agent" and category not in AGENT_ATTACHMENT_TYPES)
            ):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Unsupported {application_type} upload type.",
                )
            upload_id = new_id()
            object_key = (
                f"workflow-uploads/{agent.workspace_id}/"
                f"{agent.id}/{user_id}/{upload_id}"
            )

            async def chunks(current_upload: UploadFile = upload):
                while chunk := await current_upload.read(UPLOAD_CHUNK_BYTES):
                    yield chunk

            size_bytes = await storage.put_chunks(
                object_key,
                chunks(),
                None,
            )
            stored_keys.append(object_key)
            stored.append(
                await workflow_repository.create_upload(
                    db,
                    WorkflowUpload(
                        id=upload_id,
                        workspace_id=agent.workspace_id,
                        agent_id=agent.id,
                        uploaded_by_user_id=user_id,
                        filename=filename,
                        content_type=upload.content_type or "application/octet-stream",
                        size_bytes=size_bytes,
                        category=category,
                        object_key=object_key,
                    ),
                )
            )
        await db.commit()
    except EmptyObjectError as exc:
        await db.rollback()
        for object_key in stored_keys:
            storage.delete(object_key)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{application_type.title()} upload is empty.",
        ) from exc
    except Exception:
        await db.rollback()
        for object_key in stored_keys:
            storage.delete(object_key)
        raise

    return stored


def _validate_upload_policy(
    uploads: list[WorkflowUpload],
    config: AgentInteractionConfig,
    application_type: str,
) -> None:
    if application_type == "agent":
        config = AGENT_ATTACHMENT_CONFIG
    setting = config.file_upload_setting
    for upload in uploads:
        if (
            upload.category not in setting.file_upload_type
            or (
                application_type == "agent"
                and upload.category not in AGENT_ATTACHMENT_TYPES
            )
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{application_type.title()} upload no longer matches the published policy.",
            )


async def _consume_uploads(
    db: AsyncSession,
    uploads: list[WorkflowUpload],
) -> None:
    await queue_upload_cleanups(
        db,
        upload_ids=[upload.id for upload in uploads],
    )


async def resolve_public_workflow_files(
    db: AsyncSession,
    context: PublishedAgentContext,
    user_id: str,
    file_ids: list[str],
) -> list[dict[str, object]]:
    if not file_ids:
        return []
    config = published_interaction_config(context)
    if not config.file_upload:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid workflow files.")
    if len(file_ids) != len(set(file_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate workflow files.")
    uploads = await workflow_repository.list_uploads(
        db,
        context.agent.workspace_id,
        context.agent.id,
        user_id,
        file_ids,
    )
    by_id = {item.id: item for item in uploads}
    if any(file_id not in by_id for file_id in file_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow upload not found.")
    ordered = [by_id[file_id] for file_id in file_ids]
    _validate_upload_policy(ordered, config, "workflow")
    result = [
        {
            "id": item.id,
            "name": item.filename,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "category": item.category,
        }
        for item in ordered
    ]
    await _consume_uploads(db, ordered)
    return result


async def resolve_public_agent_files(
    db: AsyncSession,
    context: PublishedAgentContext,
    user_id: str,
    file_ids: list[str],
    settings: Settings,
) -> str:
    return await _resolve_agent_file_text(
        db,
        context.agent,
        user_id,
        file_ids,
        settings,
    )


async def resolve_workspace_agent_files(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    file_ids: list[str],
    settings: Settings,
) -> str:
    agent = await get_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor, workspace_role)
    return await _resolve_agent_file_text(
        db,
        agent,
        actor.id,
        file_ids,
        settings,
    )


async def _resolve_agent_file_text(
    db: AsyncSession,
    agent: Agent,
    user_id: str,
    file_ids: list[str],
    settings: Settings,
) -> str:
    if not file_ids:
        return ""
    config = AGENT_ATTACHMENT_CONFIG
    if len(file_ids) != len(set(file_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid agent files.")
    uploads = await workflow_repository.list_uploads(
        db,
        agent.workspace_id,
        agent.id,
        user_id,
        file_ids,
    )
    by_id = {item.id: item for item in uploads}
    if any(file_id not in by_id for file_id in file_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent upload not found.")

    ordered = [by_id[file_id] for file_id in file_ids]
    _validate_upload_policy(ordered, config, "agent")

    storage = create_object_storage(settings.knowledge_storage_dir)
    parser = build_document_parser()
    sections: list[str] = []
    remaining = AGENT_ATTACHMENT_CONTEXT_LIMIT
    try:
        for item in ordered:
            extracted, _assets = await asyncio.to_thread(
                parser.extract,
                item.filename,
                item.content_type,
                storage.path(item.object_key),
            )
            text = extracted[: min(AGENT_FILE_TEXT_LIMIT, remaining)]
            sections.append(f"--- {item.filename} ---\n{text}")
            remaining -= len(text)
            if remaining <= 0:
                break
    except KnowledgePipelineError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Agent attachment text could not be extracted.",
        ) from exc
    result = "\n\n".join(sections)
    await _consume_uploads(db, ordered)
    return result

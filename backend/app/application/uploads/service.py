from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agents.access.permissions import require_agent_view
from app.domain.agents.service import get_agent
from app.domain.artifacts.services import MAX_ARTIFACT_BYTES
from app.domain.knowledge.service import (
    MAX_DOCUMENT_UPLOAD_BYTES,
    get_default_knowledge_model,
)
from app.domain.projects.imports import import_file_tree, upload_file_path
from app.domain.projects.services import MAX_PROJECT_BYTES, MAX_PROJECT_FILES
from app.domain.uploads.service import queue_upload_cleanups
from app.domain.workflows.definitions.service import get_workflow_agent
from app.entities.agents import Agent
from app.entities.defaults import new_id
from app.entities.identity.user import User
from app.entities.workflows import WorkflowUpload
from app.infra.config.settings import Settings
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.repositories.workflows import repository as workflow_repository
from app.infra.db.repositories.workspaces import repository as workspace_repository
from app.infra.storage.object_storage import (
    EmptyObjectError,
    ObjectTooLargeError,
    create_object_storage,
    with_local_file,
)
from app.ports.llm import (
    VISION_MODEL_REQUIRED_MESSAGE,
    extract_image_text,
)
from app.schemas.agents.contracts import AgentInteractionConfig, AgentUploadResponse
from app.schemas.workflows.contracts import WorkflowUploadResponse

if TYPE_CHECKING:
    from app.application.publications.service import PublishedApplicationContext

UPLOAD_CHUNK_BYTES = 1024 * 1024
from app.domain.knowledge.documents.parsing import (
    EXTRACTABLE_DOCUMENT_EXTENSIONS,
    PLAIN_TEXT_DOCUMENT_EXTENSIONS,
    ImageTextExtractor,
    KnowledgePipelineError,
    extract_document,
)

MAX_WORKFLOW_UPLOAD_BYTES = MAX_DOCUMENT_UPLOAD_BYTES
MAX_WORKFLOW_UPLOAD_FILES = 10
UPLOAD_EXTENSIONS = {
    "document": {
        ".csv", ".docx", ".epub", ".html", ".ipynb", ".json", ".md",
        ".pdf", ".pptx", ".txt", ".xls", ".xlsx", ".xml", ".zip",
        *PLAIN_TEXT_DOCUMENT_EXTENSIONS,
    },
    "image": {".jpeg", ".jpg", ".png", ".webp"},
    "audio": {".m4a", ".mp3", ".ogg", ".wav", ".webm"},
}
SUPPORTED_ATTACHMENT_TYPES = {"document", "image"}
AGENT_ATTACHMENT_CONFIG = AgentInteractionConfig(file_upload=True)
AGENT_FILE_TEXT_LIMIT = 20_000
AGENT_ATTACHMENT_CONTEXT_LIMIT = 50_000


def published_interaction_config(
    context: PublishedApplicationContext,
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


async def _vision_text_extractor(
    db: AsyncSession,
    workspace_id: str,
    settings: Settings,
    user_id: str | None = None,
) -> ImageTextExtractor:
    model = await get_default_knowledge_model(
        db, workspace_id, "VISION", user_id=user_id
    )
    if model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            VISION_MODEL_REQUIRED_MESSAGE,
        )
    return partial(extract_image_text, settings, model)


async def upload_public_workflow_files(
    db: AsyncSession,
    context: PublishedApplicationContext,
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


async def upload_workspace_workflow_files(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    uploads: list[UploadFile],
    settings: Settings,
) -> list[WorkflowUploadResponse]:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor)
    stored = await _upload_files(
        db,
        agent,
        actor.id,
        uploads,
        settings,
        AgentInteractionConfig.model_validate(agent.interaction_config),
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
    context: PublishedApplicationContext,
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
    await require_agent_view(db, agent, actor)
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
    file_limit = (
        MAX_PROJECT_FILES if application_type == "agent" else MAX_WORKFLOW_UPLOAD_FILES
    )
    if len(uploads) > file_limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Upload at most {file_limit} files per request.",
        )
    upload_config = config.file_upload_setting
    prepared_uploads: list[tuple[UploadFile, str, str]] = []
    for upload in uploads:
        if application_type == "agent":
            try:
                filename = upload_file_path(upload.filename or "")
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            category = _upload_category(filename) or "document"
        else:
            filename = Path(upload.filename or "").name.strip()[:255]
            category = _upload_category(filename)
        if (
            not filename
            or category not in upload_config.file_upload_type
            or category not in SUPPORTED_ATTACHMENT_TYPES
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unsupported {application_type} upload type.",
            )
        prepared_uploads.append((upload, filename, category))

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
    if any(
        category == "image" and "/" not in filename
        for _upload, filename, category in prepared_uploads
    ):
        await _vision_text_extractor(db, agent.workspace_id, settings, user_id)

    storage = create_object_storage(settings.knowledge_storage_dir, settings=settings)
    stored: list[WorkflowUpload] = []
    stored_keys: list[str] = []
    total_size = 0
    try:
        for upload, filename, category in prepared_uploads:
            upload_id = new_id()
            object_key = (
                f"workflow-uploads/{agent.workspace_id}/"
                f"{agent.id}/{user_id}/{upload_id}"
            )

            async def chunks(current_upload: UploadFile = upload):
                while chunk := await current_upload.read(UPLOAD_CHUNK_BYTES):
                    yield chunk

            maximum = MAX_WORKFLOW_UPLOAD_BYTES
            if application_type == "agent":
                if "/" in filename:
                    maximum = MAX_ARTIFACT_BYTES
                elif filename.lower().endswith(".zip"):
                    maximum = MAX_PROJECT_BYTES
                elif (
                    Path(filename).suffix.lower() not in EXTRACTABLE_DOCUMENT_EXTENSIONS
                ):
                    maximum = MAX_ARTIFACT_BYTES
            size_bytes = await storage.put_chunks(
                object_key,
                chunks(),
                min(MAX_WORKFLOW_UPLOAD_BYTES - total_size, maximum),
                allow_empty=application_type == "agent",
            )
            total_size += size_bytes
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
    except ObjectTooLargeError as exc:
        await db.rollback()
        for object_key in stored_keys:
            await asyncio.to_thread(storage.delete, object_key)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"{application_type.title()} uploads are too large.",
        ) from exc
    except EmptyObjectError as exc:
        await db.rollback()
        for object_key in stored_keys:
            await asyncio.to_thread(storage.delete, object_key)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{application_type.title()} upload is empty.",
        ) from exc
    except Exception:
        await db.rollback()
        for object_key in stored_keys:
            await asyncio.to_thread(storage.delete, object_key)
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
            or upload.category not in SUPPORTED_ATTACHMENT_TYPES
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
    context: PublishedApplicationContext,
    user_id: str,
    file_ids: list[str],
    settings: Settings,
    *,
    extract_text: bool = False,
) -> list[dict[str, object]]:
    return await _resolve_workflow_files(
        db,
        context.agent,
        user_id,
        file_ids,
        published_interaction_config(context),
        settings,
        extract_text=extract_text,
    )


async def resolve_workspace_workflow_files(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    file_ids: list[str],
    settings: Settings,
    *,
    extract_text: bool = False,
) -> list[dict[str, object]]:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor)
    return await _resolve_workflow_files(
        db,
        agent,
        actor.id,
        file_ids,
        AgentInteractionConfig.model_validate(agent.interaction_config),
        settings,
        extract_text=extract_text,
    )


async def _resolve_workflow_files(
    db: AsyncSession,
    agent: Agent,
    user_id: str,
    file_ids: list[str],
    config: AgentInteractionConfig,
    settings: Settings,
    *,
    extract_text: bool,
) -> list[dict[str, object]]:
    if not file_ids:
        return []
    if not config.file_upload:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid workflow files.")
    if len(file_ids) != len(set(file_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate workflow files.")
    uploads = await workflow_repository.list_uploads(
        db,
        agent.workspace_id,
        agent.id,
        user_id,
        file_ids,
    )
    by_id = {item.id: item for item in uploads}
    if any(file_id not in by_id for file_id in file_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow upload not found.")
    ordered = [by_id[file_id] for file_id in file_ids]
    _validate_upload_policy(ordered, config, "workflow")
    contents: dict[str, str] = {}
    if extract_text:
        storage = create_object_storage(settings.knowledge_storage_dir, settings=settings)
        image_text_extractor = (
            await _vision_text_extractor(db, agent.workspace_id, settings, user_id)
            if any(item.category == "image" for item in ordered)
            else None
        )
        # ponytail: reuse the bounded attachment context; move document text to
        # storage if workflows need more than this existing 50k-character ceiling.
        remaining = AGENT_ATTACHMENT_CONTEXT_LIMIT
        try:
            for item in ordered:
                extracted, _assets = await asyncio.to_thread(
                    with_local_file, storage, item.object_key, extract_document,
                    item.filename,
                    item.content_type,
                    image_text_extractor=image_text_extractor,
                    supported_extensions=EXTRACTABLE_DOCUMENT_EXTENSIONS,
                )
                contents[item.id] = extracted[: min(AGENT_FILE_TEXT_LIMIT, remaining)]
                remaining -= len(contents[item.id])
                if remaining <= 0:
                    break
        except KnowledgePipelineError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Workflow document content could not be extracted.",
            ) from exc
        for item in ordered:
            contents.setdefault(item.id, "")
    result = [
        {
            "id": item.id,
            "name": item.filename,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "category": item.category,
            **(
                {"file_id": item.id, "content": contents[item.id]}
                if extract_text
                else {}
            ),
        }
        for item in ordered
    ]
    await _consume_uploads(db, ordered)
    return result


async def resolve_public_agent_files(
    db: AsyncSession,
    context: PublishedApplicationContext,
    user_id: str,
    file_ids: list[str],
    settings: Settings,
) -> tuple[str, list[dict[str, object]], list[dict]]:
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
) -> tuple[str, list[dict[str, object]], list[dict]]:
    agent = await get_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor)
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
) -> tuple[str, list[dict[str, object]], list[dict]]:
    if not file_ids:
        return "", [], []
    if len(file_ids) > MAX_PROJECT_FILES:
        raise HTTPException(413, "Upload at most 64 files per request.")
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
    if sum(item.size_bytes for item in ordered) > MAX_WORKFLOW_UPLOAD_BYTES:
        raise HTTPException(413, "Agent uploads are too large.")

    storage = create_object_storage(settings.knowledge_storage_dir, settings=settings)
    text_only = {
        item.id
        for item in ordered
        if "/" not in item.filename
        and Path(item.filename).suffix.lower()
        in EXTRACTABLE_DOCUMENT_EXTENSIONS - {".zip"}
        and item.size_bytes > MAX_ARTIFACT_BYTES
    }

    def read_inputs():
        inputs = []
        for item in ordered:
            if item.id in text_only:
                continue
            maximum = (
                MAX_PROJECT_BYTES
                if "/" not in item.filename and item.filename.lower().endswith(".zip")
                else MAX_ARTIFACT_BYTES
            )
            content = storage.read_bytes(item.object_key, maximum)
            if len(content) > maximum:
                raise ValueError("Conversation upload exceeds its size limit.")
            inputs.append((item.filename, content))
        return import_file_tree(inputs) if inputs else []

    try:
        input_files = await asyncio.to_thread(read_inputs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (OSError, ObjectTooLargeError) as exc:
        raise HTTPException(422, "Agent upload could not be read.") from exc
    image_text_extractor = (
        await _vision_text_extractor(db, agent.workspace_id, settings, user_id)
        if any(
            item.category == "image" and "/" not in item.filename for item in ordered
        )
        else None
    )
    sections: list[str] = []
    remaining = AGENT_ATTACHMENT_CONTEXT_LIMIT
    try:
        for item in ordered:
            if (
                not item.size_bytes
                or "/" in item.filename
                or Path(item.filename).suffix.lower() == ".zip"
                or Path(item.filename).suffix.lower()
                not in EXTRACTABLE_DOCUMENT_EXTENSIONS
            ):
                continue
            extracted, _assets = await asyncio.to_thread(
                with_local_file, storage, item.object_key, extract_document,
                item.filename,
                item.content_type,
                image_text_extractor=image_text_extractor,
                supported_extensions=EXTRACTABLE_DOCUMENT_EXTENSIONS,
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
    if input_files:
        sections.append(
            "Files available in /workspace/project/ (read them as needed with bash):\n"
            + "\n".join(item["path"] for item in input_files)
        )
    if text_only:
        sections.append(
            "Large standalone attachments provide text excerpts only; their originals are not in the file workspace:\n"
            + "\n".join(item.filename for item in ordered if item.id in text_only)
        )
    result = "\n\n".join(sections)
    attachments = [
        {
            "filename": item.filename,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "category": item.category,
        }
        for item in ordered
    ]
    await _consume_uploads(db, ordered)
    return result, attachments, input_files


__all__ = [
    "published_interaction_config",
    "resolve_public_agent_files",
    "resolve_public_workflow_files",
    "resolve_workspace_agent_files",
    "resolve_workspace_workflow_files",
    "upload_public_agent_files",
    "upload_public_workflow_files",
    "upload_workspace_agent_files",
    "upload_workspace_workflow_files",
]

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.session import get_db
from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
)
from app.api.v1.endpoints.knowledge import dispatch_knowledge_task
from app.services.knowledge_legacy import batch_create_knowledge_documents
from app.services.knowledge_processing import (
    enqueue_index_knowledge_document,
    get_knowledge_document,
    preview_knowledge_document,
)
from app.schemas.knowledge import (
    KnowledgeDocumentBatchCreateRequest,
    KnowledgeDocumentChunkResponse,
    KnowledgeDocumentParseRequest,
    KnowledgeDocumentResponse,
    KnowledgeDocumentSplitParagraphResponse,
    KnowledgeDocumentSplitResponse,
)
from app.services.knowledge import (
    document_to_response,
    get_knowledge_base,
    require_knowledge_base_permission,
    upload_knowledge_document,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases",
    tags=["knowledge"],
)
legacy_router = APIRouter(
    prefix="/workspace/{workspace_id}/knowledge",
    tags=["knowledge"],
)


def parse_security_levels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value: Any = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid security_levels.",
        ) from exc

    items = value.items() if isinstance(value, dict) else value
    if not isinstance(items, list) and not hasattr(items, "__iter__"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid security_levels.",
        )

    levels: dict[str, str] = {}
    for item in items:
        if isinstance(item, tuple):
            name, security_level = item
        elif isinstance(item, dict):
            name = item.get("name")
            security_level = item.get("security_level")
        else:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Invalid security_levels.",
            )
        if (
            isinstance(name, str)
            and isinstance(security_level, str)
            and name.strip()
            and security_level.strip()
        ):
            levels[name.strip()] = security_level.strip()
    return levels


def validate_split_patterns(patterns: str | None) -> None:
    if not patterns or not patterns.strip():
        return
    try:
        value = json.loads(patterns)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid split patterns.",
        ) from exc
    if value:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Advanced split patterns are not supported.",
        )


def split_response(
    document: KnowledgeDocumentResponse,
    chunks: list[KnowledgeDocumentChunkResponse],
) -> KnowledgeDocumentSplitResponse:
    return KnowledgeDocumentSplitResponse(
        name=document.filename,
        content=[
            KnowledgeDocumentSplitParagraphResponse(title="", content=chunk.content)
            for chunk in chunks
        ],
        source_file_id=document.id,
        preview_file_id=document.meta.get("preview_file_id"),
        security_level=str(document.meta.get("security_level") or "PUBLIC"),
    )


@router.post(
    "/{knowledge_base_id}/document/split",
    response_model=list[KnowledgeDocumentSplitResponse],
)
@legacy_router.post(
    "/{knowledge_base_id}/document/split",
    response_model=list[KnowledgeDocumentSplitResponse],
)
async def split_workspace_knowledge_base_documents(
    knowledge_base_id: str,
    files: Annotated[list[UploadFile], File(alias="file")],
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    security_levels: Annotated[str | None, Form()] = None,
    patterns: Annotated[str | None, Form()] = None,
    limit: Annotated[int | None, Form(ge=100, le=8000)] = None,
    with_filter: Annotated[bool, Form()] = False,
) -> list[KnowledgeDocumentSplitResponse]:
    validate_split_patterns(patterns)
    knowledge_base = await get_knowledge_base(
        db,
        context.workspace.id,
        knowledge_base_id,
    )
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    security_level_by_name = parse_security_levels(security_levels)
    cleaning_rules = (
        ["trim_lines", "remove_empty_lines", "collapse_spaces"]
        if with_filter
        else []
    )
    parse_payload = KnowledgeDocumentParseRequest(
        chunk_size=limit or 1000,
        chunk_overlap=0,
        split_separator="\n",
        cleaning_rules=cleaning_rules,
        auto_index=False,
    )

    responses: list[KnowledgeDocumentSplitResponse] = []
    for file in files:
        security_level = security_level_by_name.get(file.filename or "", "PUBLIC")
        uploaded = await upload_knowledge_document(
            db,
            knowledge_base,
            file,
            context.user,
            settings,
            {"security_level": security_level},
        )
        document = await get_knowledge_document(db, knowledge_base, uploaded.id)
        chunks = await preview_knowledge_document(
            db,
            knowledge_base,
            document,
            context.user,
            settings,
            parse_payload,
        )
        responses.append(split_response(document_to_response(document), chunks))
    return responses


@router.put(
    "/{knowledge_base_id}/document/batch_create",
    response_model=list[KnowledgeDocumentResponse],
)
@legacy_router.put(
    "/{knowledge_base_id}/document/batch_create",
    response_model=list[KnowledgeDocumentResponse],
)
async def batch_create_workspace_knowledge_base_documents(
    knowledge_base_id: str,
    payload: Annotated[list[KnowledgeDocumentBatchCreateRequest], Body()],
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeDocumentResponse]:
    knowledge_base = await get_knowledge_base(
        db,
        context.workspace.id,
        knowledge_base_id,
    )
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    documents = await batch_create_knowledge_documents(
        db,
        knowledge_base,
        payload,
        context.user,
        settings,
    )
    for document in documents:
        task = await enqueue_index_knowledge_document(
            db,
            knowledge_base,
            document,
            context.user,
        )
        await dispatch_knowledge_task(task.id, settings)
    return [document_to_response(document) for document in documents]

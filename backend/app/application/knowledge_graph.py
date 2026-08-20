import hashlib
import json
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    CHUNK_INDEXED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
)
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.ports.parsing import chunk_token_count
from app.schemas.knowledge import KnowledgeTaskResponse
from app.schemas.knowledge_graph import KnowledgeGraphImportRecord
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.knowledge.orchestration import (
    enqueue_graph_sync,
    task_to_response,
)
from app.shareddomain.knowledge.services import (
    DEFAULT_DOCUMENT_META,
    clean_upload_filename,
    knowledge_object_storage,
    require_knowledge_base_active,
)

MAX_GRAPH_IMPORT_BYTES = 10 * 1024 * 1024
MAX_GRAPH_IMPORT_RECORDS = 5_000


def parse_graph_import_records(
    filename: str,
    content: bytes,
) -> list[KnowledgeGraphImportRecord]:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".json", ".jsonl"}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Graph import must be a JSON or JSONL file.",
        )
    if len(content) > MAX_GRAPH_IMPORT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Graph import is too large.",
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Graph import must use UTF-8.",
        ) from exc
    try:
        if suffix == ".json":
            value = json.loads(text)
            values = value if isinstance(value, list) else [value]
        else:
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Graph import contains invalid JSON.",
        ) from exc
    if not values:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Graph import has no records.",
        )
    if len(values) > MAX_GRAPH_IMPORT_RECORDS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Graph import has too many records.",
        )
    records: list[KnowledgeGraphImportRecord] = []
    for index, value in enumerate(values, start=1):
        try:
            records.append(KnowledgeGraphImportRecord.model_validate(value))
        except ValidationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Graph import record {index} is invalid.",
            ) from exc
    return records


def _record_content(record: KnowledgeGraphImportRecord) -> str:
    return json.dumps(
        record.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _record_search_text(record: KnowledgeGraphImportRecord) -> str:
    object_text = (
        record.object.canonical_name
        if record.object is not None
        else json.dumps(record.value, ensure_ascii=False, sort_keys=True)
    )
    return "\n".join(
        part
        for part in (
            record.subject.canonical_name,
            record.predicate,
            object_text,
            record.evidence,
        )
        if part
    )


async def import_graph_records(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    upload: UploadFile,
    actor: User,
    settings: Settings,
) -> KnowledgeTaskResponse:
    require_knowledge_base_active(knowledge_base)
    if not knowledge_base.graph_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Graph RAG is disabled.")
    filename = clean_upload_filename(upload.filename)
    content = await upload.read(MAX_GRAPH_IMPORT_BYTES + 1)
    records = parse_graph_import_records(filename, content)

    attachment_id = new_id()
    document_id = new_id()
    object_key = (
        f"{knowledge_base.workspace_id}/{knowledge_base.id}/attachments/"
        f"{attachment_id}/{filename}"
    )
    storage = knowledge_object_storage(settings)
    try:
        storage.put_bytes(object_key, content)
        attachment = await knowledge_repository.create_knowledge_attachment(
            db,
            KnowledgeAttachment(
                id=attachment_id,
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename=filename,
                content_type=(
                    "application/json"
                    if Path(filename).suffix.lower() == ".json"
                    else "application/x-ndjson"
                ),
                size_bytes=len(content),
                object_key=object_key,
                status="consumed",
                created_by_user_id=actor.id,
            ),
        )
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id=document_id,
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                attachment_id=attachment.id,
                filename=filename,
                content_type=attachment.content_type,
                size_bytes=len(content),
                storage_path=object_key,
                meta={
                    **DEFAULT_DOCUMENT_META,
                    "import_mode": "graph",
                    "document_version": 1,
                    "normalized_content_hash": hashlib.sha256(content).hexdigest(),
                },
                status=DOCUMENT_INDEXED_STATUS,
                created_by_user_id=actor.id,
            ),
        )
        chunks = []
        for index, record in enumerate(records):
            normalized = _record_content(record)
            chunks.append(
                KnowledgeDocumentChunk(
                    id=new_id(),
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    document_id=document.id,
                    chunk_index=index,
                    content=normalized,
                    kind="graph_record",
                    search_text=_record_search_text(record),
                    meta={"record_index": index + 1},
                    char_count=len(normalized),
                    token_count=chunk_token_count(normalized),
                    status=CHUNK_INDEXED_STATUS,
                )
            )
        await knowledge_repository.replace_document_chunks(
            db,
            knowledge_base,
            document.id,
            [],
            chunks,
            [],
            [],
        )
        record_audit_log(
            db,
            actor,
            "knowledge_graph.import",
            "knowledge_document",
            document.id,
            document.filename,
            {
                "knowledge_base_id": knowledge_base.id,
                "record_count": len(records),
            },
            workspace_id=knowledge_base.workspace_id,
        )
        task = await enqueue_graph_sync(
            db,
            knowledge_base,
            actor,
            [document.id],
            options={
                "trusted_structured_import": True,
                "structured_document_ids": [document.id],
            },
        )
    except Exception:
        await db.rollback()
        storage.delete(object_key)
        raise
    return task_to_response(task)

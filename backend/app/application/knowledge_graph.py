import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import knowledge_graph_query
from app.entities.knowledge import (
    CHUNK_INDEXED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
)
from app.entities.knowledge_graph import (
    GRAPH_REVIEW_APPROVED,
    GRAPH_REVIEW_OPEN,
    GRAPH_REVIEW_REJECTED,
    GRAPH_REVIEW_RESOLVED,
    KnowledgeGraphClaim,
    KnowledgeGraphEntity,
    KnowledgeGraphRevision,
    KnowledgeGraphSchema,
)
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.ports.parsing import chunk_token_count
from app.schemas.knowledge import KnowledgeQueryRequest, KnowledgeTaskResponse
from app.schemas.knowledge_graph import (
    KnowledgeGraphClaimResponse,
    KnowledgeGraphEntityDetailResponse,
    KnowledgeGraphEntityListResponse,
    KnowledgeGraphEntityResponse,
    KnowledgeGraphEvidenceResponse,
    KnowledgeGraphImportRecord,
    KnowledgeGraphNeighborhoodRequest,
    KnowledgeGraphPathRequest,
    KnowledgeGraphQueryResultResponse,
    KnowledgeGraphReviewDecisionRequest,
    KnowledgeGraphReviewItemResponse,
    KnowledgeGraphReviewListResponse,
    KnowledgeGraphSchemaResponse,
    KnowledgeGraphSchemaUpdateRequest,
    KnowledgeGraphSettingsResponse,
    KnowledgeGraphSettingsUpdateRequest,
    KnowledgeGraphStatusResponse,
)
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.knowledge.orchestration import (
    enqueue_graph_rebuild,
    enqueue_graph_sync,
    task_to_response,
)
from app.shareddomain.knowledge.services import (
    DEFAULT_DOCUMENT_META,
    clean_upload_filename,
    get_knowledge_base,
    get_knowledge_model,
    knowledge_object_storage,
    require_knowledge_base_active,
    require_knowledge_base_permission,
)
from app.shareddomain.knowledge_graph.resolution import claim_fingerprint
from app.shareddomain.knowledge_graph.revisions import stage_revision_change
from app.shareddomain.knowledge_graph.schema import (
    GraphSchemaDefinition,
    normalize_graph_name,
)
from app.shareddomain.knowledge_graph.services import create_graph_schema

MAX_GRAPH_IMPORT_BYTES = 10 * 1024 * 1024
MAX_GRAPH_IMPORT_RECORDS = 5_000
logger = get_logger(__name__)


async def _dispatch_graph_task(task_id: str, settings: Settings) -> None:
    # Imported lazily because the Celery task module imports the graph runner.
    from app.application.knowledge import dispatch_knowledge_task

    await dispatch_knowledge_task(task_id, settings)


async def _enqueue_initial_graph_build(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    settings: Settings,
) -> None:
    try:
        task = await enqueue_graph_rebuild(db, knowledge_base, actor)
        await _dispatch_graph_task(task.id, settings)
    except Exception as exc:
        await db.rollback()
        # The persisted graph reconciler retries enabled knowledge bases whose
        # indexed sources have not been published yet.
        log_error(
            logger,
            "Initial knowledge graph build dispatch deferred.",
            exc,
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
        )


async def require_graph_knowledge_base(
    db: AsyncSession,
    workspace_id: str,
    knowledge_base_id: str,
    actor: User,
    workspace_role: str | None,
    permissions: set[str],
) -> KnowledgeBase:
    knowledge_base = await get_knowledge_base(
        db,
        workspace_id,
        knowledge_base_id,
    )
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        actor,
        workspace_role,
        permissions,
    )
    return knowledge_base


def _settings_response(
    knowledge_base: KnowledgeBase,
) -> KnowledgeGraphSettingsResponse:
    return KnowledgeGraphSettingsResponse(
        enabled=knowledge_base.graph_enabled,
        extraction_model_id=knowledge_base.graph_extraction_model_id,
        active_schema_id=knowledge_base.active_graph_schema_id,
        active_revision_id=knowledge_base.active_graph_revision_id,
    )


def _schema_response(
    schema: KnowledgeGraphSchema,
) -> KnowledgeGraphSchemaResponse:
    return KnowledgeGraphSchemaResponse(
        id=schema.id,
        version=schema.version,
        status=schema.status,
        graph_schema=schema.schema_json,
        schema_hash=schema.schema_hash,
    )


def _entity_response(
    entity: KnowledgeGraphEntity,
    aliases: list[str] | None = None,
) -> KnowledgeGraphEntityResponse:
    return KnowledgeGraphEntityResponse(
        id=entity.id,
        entity_type=entity.entity_type,
        canonical_name=entity.canonical_name,
        aliases=aliases or [],
        properties=entity.properties_json or {},
        profile_markdown=entity.profile_markdown,
        component_id=entity.component_id,
        degree=entity.degree,
    )


def _claim_response(
    claim: KnowledgeGraphClaim,
    evidence_ids: list[str],
) -> KnowledgeGraphClaimResponse:
    return KnowledgeGraphClaimResponse(
        id=claim.id,
        subject_entity_id=claim.subject_entity_id,
        predicate=claim.predicate,
        object_entity_id=claim.object_entity_id,
        object_value=claim.object_value_json,
        properties=claim.properties_json or {},
        quality_score=claim.quality_score,
        support_count=claim.support_count,
        evidence_ids=evidence_ids,
    )


async def _validate_graph_build_requirements(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    extraction_model_id: str | None,
) -> tuple[str, str]:
    require_knowledge_base_active(knowledge_base)
    extraction_model = await get_knowledge_model(
        db,
        knowledge_base.workspace_id,
        extraction_model_id,
        "LLM",
    )
    if extraction_model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Graph extraction model is required.",
        )
    embedding_model = await get_knowledge_model(
        db,
        knowledge_base.workspace_id,
        knowledge_base.embedding_model_id,
        "EMBEDDING",
        use_default=True,
    )
    if embedding_model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Embedding model is required.",
        )
    if not await knowledge_repository.has_indexed_knowledge_document(
        db,
        knowledge_base,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "At least one indexed document is required.",
        )
    return extraction_model.id, embedding_model.id


async def get_graph_settings(
    knowledge_base: KnowledgeBase,
) -> KnowledgeGraphSettingsResponse:
    return _settings_response(knowledge_base)


async def update_graph_settings(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeGraphSettingsUpdateRequest,
    actor: User,
    settings: Settings,
) -> KnowledgeGraphSettingsResponse:
    locked = await knowledge_repository.lock_knowledge_base(db, knowledge_base)
    if locked is None or locked.workspace_id != knowledge_base.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")

    was_enabled = locked.graph_enabled
    extraction_model_id = (
        locked.graph_extraction_model_id
        if payload.extraction_model_id is None
        else payload.extraction_model_id
    )
    embedding_model_id = locked.embedding_model_id
    if payload.enabled:
        extraction_model_id, embedding_model_id = (
            await _validate_graph_build_requirements(
                db,
                locked,
                extraction_model_id,
            )
        )
    elif payload.extraction_model_id is not None:
        extraction_model = await get_knowledge_model(
            db,
            locked.workspace_id,
            extraction_model_id,
            "LLM",
        )
        extraction_model_id = extraction_model.id if extraction_model else None

    locked.graph_enabled = payload.enabled
    locked.graph_extraction_model_id = extraction_model_id
    locked.embedding_model_id = embedding_model_id
    await knowledge_repository.save_knowledge_base(db, locked)
    record_audit_log(
        db,
        actor,
        "knowledge_graph.settings.update",
        "knowledge_base",
        locked.id,
        locked.name,
        {
            "knowledge_base_id": locked.id,
            "action": "enable" if locked.graph_enabled else "disable",
            "status": "enabled" if locked.graph_enabled else "disabled",
        },
        workspace_id=locked.workspace_id,
    )
    await db.commit()
    locked = await knowledge_repository.refresh_knowledge_base(db, locked)
    if locked.graph_enabled and not was_enabled:
        await _enqueue_initial_graph_build(db, locked, actor, settings)
    return _settings_response(locked)


async def get_graph_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeGraphSchemaResponse | None:
    schema = await graph_repository.get_latest_draft_or_active_schema(
        db,
        knowledge_base,
    )
    return _schema_response(schema) if schema is not None else None


async def update_graph_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeGraphSchemaUpdateRequest,
    actor: User,
) -> KnowledgeGraphSchemaResponse:
    require_knowledge_base_active(knowledge_base)
    try:
        definition = GraphSchemaDefinition.model_validate(payload.graph_schema)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Knowledge graph schema is invalid.",
        ) from exc
    schema = await create_graph_schema(db, knowledge_base, definition, actor)
    record_audit_log(
        db,
        actor,
        "knowledge_graph.schema.create",
        "knowledge_graph_schema",
        schema.id,
        str(schema.version),
        {
            "knowledge_base_id": knowledge_base.id,
            "schema_id": schema.id,
            "action": "create",
            "status": schema.status,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    return _schema_response(schema)


async def get_graph_status(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeGraphStatusResponse:
    revision = await graph_repository.get_latest_revision(db, knowledge_base)
    _, pending_review_count = await graph_repository.list_pending_review_page(
        db,
        knowledge_base,
        limit=1,
        offset=0,
    )
    return KnowledgeGraphStatusResponse(
        enabled=knowledge_base.graph_enabled,
        active_schema_id=knowledge_base.active_graph_schema_id,
        active_revision_id=knowledge_base.active_graph_revision_id,
        revision_no=revision.revision_no if revision else None,
        revision_status=revision.status if revision else None,
        source_watermark=revision.source_watermark if revision else None,
        stats=revision.stats_json if revision else {},
        model_usage=revision.model_usage_json if revision else {},
        pending_review_count=pending_review_count,
        last_error=revision.failure_reason if revision else None,
        published_at=revision.published_at if revision else None,
    )


async def rebuild_graph(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    settings: Settings,
) -> KnowledgeTaskResponse:
    if not knowledge_base.graph_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Graph RAG is disabled.")
    await _validate_graph_build_requirements(
        db,
        knowledge_base,
        knowledge_base.graph_extraction_model_id,
    )
    task = await enqueue_graph_rebuild(db, knowledge_base, actor)
    record_audit_log(
        db,
        actor,
        "knowledge_graph.rebuild.enqueue",
        "knowledge_task",
        task.id,
        task.task_type,
        {
            "knowledge_base_id": knowledge_base.id,
            "task_id": task.id,
            "action": "enqueue",
            "status": task.status,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    await _dispatch_graph_task(task.id, settings)
    return task_to_response(task)


async def list_graph_entities(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    query: str | None,
    entity_type: str | None,
    limit: int,
    offset: int,
) -> KnowledgeGraphEntityListResponse:
    entities, total = await graph_repository.list_active_entity_page(
        db,
        knowledge_base,
        query=query.strip() if query else None,
        entity_type=entity_type.strip() if entity_type else None,
        limit=limit,
        offset=offset,
    )
    aliases: dict[str, list[str]] = {}
    for alias in await graph_repository.list_active_aliases_for_entity_ids(
        db,
        knowledge_base,
        {entity.id for entity in entities},
    ):
        aliases.setdefault(alias.entity_id, []).append(alias.alias)
    return KnowledgeGraphEntityListResponse(
        items=[
            _entity_response(entity, aliases.get(entity.id))
            for entity in entities
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_graph_entity(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    entity_id: str,
) -> KnowledgeGraphEntityDetailResponse:
    entity = await graph_repository.get_active_entity(
        db,
        knowledge_base,
        entity_id,
    )
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Graph entity not found.")
    aliases = await graph_repository.list_active_aliases_for_entity_ids(
        db,
        knowledge_base,
        {entity.id},
    )
    claims = [
        claim
        for claim in await graph_repository.list_current_claims_for_entity_ids(
            db,
            knowledge_base,
            {entity.id},
        )
        if claim.status == "active"
    ]
    evidence_rows = await graph_repository.list_ranked_evidence_for_claim_ids(
        db,
        knowledge_base,
        {claim.id for claim in claims},
    )
    evidence_ids: dict[str, list[str]] = {}
    evidence_responses: list[KnowledgeGraphEvidenceResponse] = []
    for evidence, filename, source_kind, _, _ in evidence_rows:
        evidence_ids.setdefault(evidence.claim_id, []).append(evidence.id)
        evidence_responses.append(
            KnowledgeGraphEvidenceResponse(
                id=evidence.id,
                claim_id=evidence.claim_id,
                document_id=evidence.document_id,
                document_filename=filename,
                chunk_id=evidence.chunk_id,
                quote=evidence.quote,
                start_offset=evidence.start_offset,
                end_offset=evidence.end_offset,
                source_kind=source_kind,
            )
        )
    response = _entity_response(entity, [alias.alias for alias in aliases])
    return KnowledgeGraphEntityDetailResponse(
        **response.model_dump(),
        claims=[
            _claim_response(claim, evidence_ids.get(claim.id, []))
            for claim in claims
        ],
        evidence=evidence_responses,
    )


async def _execute_graph_query(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeQueryRequest,
    settings: Settings,
) -> KnowledgeGraphQueryResultResponse:
    result = await knowledge_graph_query.retrieve_graph_candidates(
        db,
        knowledge_base,
        payload,
        settings,
        1,
    )
    if result.operation == "off":
        raise HTTPException(status.HTTP_409_CONFLICT, "Graph RAG is disabled.")
    if result.traversal is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Knowledge graph has no active revision.",
        )
    response = knowledge_graph_query.graph_query_result_response(result.traversal)
    assert response is not None
    return response


async def query_graph_path(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeGraphPathRequest,
    settings: Settings,
) -> KnowledgeGraphQueryResultResponse:
    return await _execute_graph_query(
        db,
        knowledge_base,
        KnowledgeQueryRequest(
            query=f"{payload.source_entity} {payload.target_entity}",
            graph_mode="path",
            source_entity=payload.source_entity,
            target_entity=payload.target_entity,
            max_hops=payload.max_hops,
            relation_filters=payload.relation_filters,
        ),
        settings,
    )


async def query_graph_neighborhood(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeGraphNeighborhoodRequest,
    settings: Settings,
) -> KnowledgeGraphQueryResultResponse:
    return await _execute_graph_query(
        db,
        knowledge_base,
        KnowledgeQueryRequest(
            query=payload.entity,
            graph_mode="neighborhood",
            source_entity=payload.entity,
            max_hops=payload.max_hops,
            relation_filters=payload.relation_filters,
        ),
        settings,
    )


async def list_graph_reviews(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    limit: int,
    offset: int,
) -> KnowledgeGraphReviewListResponse:
    reviews, total = await graph_repository.list_pending_review_page(
        db,
        knowledge_base,
        limit=limit,
        offset=offset,
    )
    return KnowledgeGraphReviewListResponse(
        items=[
            KnowledgeGraphReviewItemResponse(
                id=review.id,
                kind=review.kind,
                payload=review.payload_json,
                status=review.status,
                revision_id=review.revision_id,
                created_at=review.created_at,
            )
            for review in reviews
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


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
            "knowledge_graph.records.import",
            "knowledge_document",
            document.id,
            document.filename,
            {
                "knowledge_base_id": knowledge_base.id,
                "action": "import",
                "record_count": len(records),
                "status": "queued",
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


async def import_and_dispatch_graph_records(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    upload: UploadFile,
    actor: User,
    settings: Settings,
) -> KnowledgeTaskResponse:
    task = await import_graph_records(
        db,
        knowledge_base,
        upload,
        actor,
        settings,
    )
    await _dispatch_graph_task(task.id, settings)
    return task


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _review_claim_ids(review_payload: dict[str, Any]) -> set[str]:
    values = {
        str(item)
        for item in review_payload.get("claim_ids", [])
        if str(item)
    }
    claim_id = str(review_payload.get("claim_id") or "")
    if claim_id:
        values.add(claim_id)
    return values


def _review_source_entity_id(review_payload: dict[str, Any]) -> str:
    return str(
        review_payload.get("new_entity_id")
        or review_payload.get("entity_id")
        or ""
    )


async def _normalize_review_decision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    review_id: str,
    review_kind: str,
    review_payload: dict[str, Any],
    payload: KnowledgeGraphReviewDecisionRequest,
    actor: User,
) -> dict[str, Any]:
    decision = {
        **payload.model_dump(mode="json"),
        "review_id": review_id,
        "reviewed_by_user_id": actor.id,
    }
    if payload.action in {"approve_claim", "reject_claim"}:
        allowed_claim_ids = _review_claim_ids(review_payload)
        selected_claim_ids = set(payload.claim_ids) or allowed_claim_ids
        if not selected_claim_ids or not selected_claim_ids <= allowed_claim_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Review decision is outside the review scope.",
            )
        claims = await graph_repository.list_current_claims_by_ids(
            db,
            knowledge_base,
            selected_claim_ids,
        )
        if len(claims) != len(selected_claim_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Graph claim not found.")
        decision["claim_ids"] = sorted(selected_claim_ids)
        decision["record_count"] = len(selected_claim_ids)
        return decision

    if review_kind not in {"ambiguous_entity", "possible_duplicate"}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Review action is incompatible with this review item.",
        )
    source_entity_id = _review_source_entity_id(review_payload)
    source = await graph_repository.get_active_entity(
        db,
        knowledge_base,
        source_entity_id,
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Graph entity not found.")
    decision["source_entity_id"] = source.id

    if payload.action == "merge_entities":
        assert payload.target_entity_id is not None
        allowed_targets = {
            str(item)
            for item in review_payload.get("candidate_entity_ids", [])
            if str(item)
        }
        if allowed_targets and payload.target_entity_id not in allowed_targets:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Review decision is outside the review scope.",
            )
        target = await graph_repository.get_active_entity(
            db,
            knowledge_base,
            payload.target_entity_id,
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Graph entity not found.")
        if target.id == source.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Merge source and target must differ.",
            )
        aliases = await graph_repository.list_active_aliases_for_entity_ids(
            db,
            knowledge_base,
            {source.id},
        )
        mentions = await graph_repository.list_active_mentions_for_entity_ids(
            db,
            knowledge_base,
            {source.id},
        )
        claims = await graph_repository.list_current_claims_for_entity_ids(
            db,
            knowledge_base,
            {source.id},
        )
        decision["record_count"] = len(aliases) + len(mentions) + len(claims)
        return decision

    mentions = await graph_repository.list_active_mentions_for_entity_ids(
        db,
        knowledge_base,
        {source.id},
    )
    claims = await graph_repository.list_current_claims_for_entity_ids(
        db,
        knowledge_base,
        {source.id},
    )
    if not set(payload.mention_ids) <= {item.id for item in mentions}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Graph mention not found.")
    if not set(payload.claim_ids) <= {item.id for item in claims}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Graph claim not found.")
    schema_entity = await graph_repository.get_active_schema(db, knowledge_base)
    if schema_entity is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Knowledge graph has no active schema.",
        )
    schema = GraphSchemaDefinition.model_validate(schema_entity.schema_json)
    if payload.entity_type not in {item.name for item in schema.entity_types}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Split entity type is not allowed by the active schema.",
        )
    decision["new_entity_id"] = str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    "kg-review-split",
                    knowledge_base.id,
                    review_id,
                    payload.entity_type or "",
                    normalize_graph_name(payload.canonical_name or ""),
                )
            ),
        )
    )
    decision["record_count"] = len(payload.mention_ids) + len(payload.claim_ids)
    return decision


async def resolve_graph_review(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    review_id: str,
    payload: KnowledgeGraphReviewDecisionRequest,
    actor: User,
    settings: Settings,
) -> KnowledgeTaskResponse:
    locked = await knowledge_repository.lock_knowledge_base(db, knowledge_base)
    if locked is None or locked.workspace_id != knowledge_base.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(locked)
    if not locked.graph_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Graph RAG is disabled.")
    if await graph_repository.get_active_revision(db, locked) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Knowledge graph has no active revision.",
        )
    if (
        await knowledge_repository.get_queued_graph_sync(db, locked) is not None
        or await knowledge_repository.get_queued_graph_rebuild(db, locked)
        is not None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A knowledge graph task is already queued.",
        )
    review = await graph_repository.lock_review_item(db, locked, review_id)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Graph review not found.")
    if review.status != GRAPH_REVIEW_OPEN:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Graph review has already been resolved.",
        )
    decision = await _normalize_review_decision(
        db,
        locked,
        review.id,
        review.kind,
        review.payload_json,
        payload,
        actor,
    )
    review.status = (
        GRAPH_REVIEW_REJECTED
        if payload.action == "reject_claim"
        else GRAPH_REVIEW_APPROVED
    )
    review.decision_json = decision
    review.reviewed_by_user_id = actor.id
    review.reviewed_at = utc_now()
    await graph_repository.save_review_item(db, review)
    audit_details = {
        "knowledge_base_id": locked.id,
        "review_id": review.id,
        "action": payload.action,
        "record_count": int(decision.get("record_count") or 0),
        "status": review.status,
    }
    source_entity_id = decision.get("source_entity_id")
    if source_entity_id:
        audit_details["source_entity_id"] = str(source_entity_id)
    target_entity_id = decision.get("target_entity_id") or decision.get(
        "new_entity_id"
    )
    if target_entity_id:
        audit_details["target_entity_id"] = str(target_entity_id)
    record_audit_log(
        db,
        actor,
        "knowledge_graph.review.resolve",
        "knowledge_graph_review",
        review.id,
        review.kind,
        audit_details,
        workspace_id=locked.workspace_id,
    )
    try:
        task = await enqueue_graph_sync(
            db,
            locked,
            actor,
            [],
            options={"review_decision": decision},
        )
    except Exception:
        await db.rollback()
        raise
    await _dispatch_graph_task(task.id, settings)
    return task_to_response(task)


async def _stage_existing_change(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_kind: str,
    record: Any,
    after_json: dict[str, Any] | None,
    *,
    operation: str = "upsert",
) -> None:
    await stage_revision_change(
        db,
        revision,
        record_kind=record_kind,
        record_key=record.id,
        operation=operation,
        before_json=_jsonable(asdict(record)),
        after_json=after_json,
    )


async def _stage_claim_rebindings(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    source_entity_id: str,
    target_entity_id: str,
    claim_ids: set[str] | None = None,
) -> set[str]:
    claims = await graph_repository.list_current_claims_for_entity_ids(
        db,
        knowledge_base,
        {source_entity_id},
    )
    if claim_ids is not None:
        claims = [claim for claim in claims if claim.id in claim_ids]
    current_claims = await graph_repository.list_current_claims(
        db,
        knowledge_base,
    )
    owners = {claim.fingerprint: claim for claim in current_claims}
    changes: list[
        tuple[KnowledgeGraphClaim, dict[str, Any], KnowledgeGraphClaim | None]
    ] = []
    affected = {source_entity_id, target_entity_id}
    for claim in claims:
        subject_entity_id = (
            target_entity_id
            if claim.subject_entity_id == source_entity_id
            else claim.subject_entity_id
        )
        object_entity_id = (
            target_entity_id
            if claim.object_entity_id == source_entity_id
            else claim.object_entity_id
        )
        fingerprint = claim_fingerprint(
            subject_entity_id,
            claim.predicate,
            object_entity_id,
            claim.object_value_json,
            claim.valid_from,
            claim.valid_to,
        )
        duplicate = owners.get(fingerprint)
        if duplicate is None:
            duplicate = await graph_repository.get_claim(
                db,
                revision,
                fingerprint,
            )
        if duplicate is not None and duplicate.id == claim.id:
            duplicate = None
        after = {
            "subject_entity_id": subject_entity_id,
            "object_entity_id": object_entity_id,
            "fingerprint": fingerprint,
            "source_kind": "human",
        }
        changes.append((claim, after, duplicate))
        owners.pop(claim.fingerprint, None)
        owners[fingerprint] = duplicate or claim
        affected.add(subject_entity_id)
        if object_entity_id:
            affected.add(object_entity_id)

    evidence_claim_ids = {
        claim.id
        for claim, _, duplicate in changes
        if duplicate is not None
    } | {
        duplicate.id
        for _, _, duplicate in changes
        if duplicate is not None
    }
    evidence_by_claim: dict[str, list[Any]] = {}
    for evidence in await graph_repository.list_current_evidence_for_claim_ids(
        db,
        knowledge_base,
        evidence_claim_ids,
    ):
        evidence_by_claim.setdefault(evidence.claim_id, []).append(evidence)

    status_rank = {"rejected": 0, "candidate": 1, "active": 2}
    for claim, after, duplicate in changes:
        if duplicate is None:
            await _stage_existing_change(
                db,
                revision,
                "claim",
                claim,
                after,
            )
            continue
        duplicate_status = max(
            (claim.status, duplicate.status),
            key=lambda item: status_rank.get(item, -1),
        )
        await _stage_existing_change(
            db,
            revision,
            "claim",
            duplicate,
            {"status": duplicate_status, "source_kind": "human"},
        )
        duplicate_positions = {
            (item.chunk_id, item.start_offset, item.end_offset)
            for item in evidence_by_claim.get(duplicate.id, [])
        }
        for evidence in evidence_by_claim.get(claim.id, []):
            position = (
                evidence.chunk_id,
                evidence.start_offset,
                evidence.end_offset,
            )
            await _stage_existing_change(
                db,
                revision,
                "evidence",
                evidence,
                None if position in duplicate_positions else {
                    "claim_id": duplicate.id
                },
                operation=(
                    "retire" if position in duplicate_positions else "upsert"
                ),
            )
        await _stage_existing_change(
            db,
            revision,
            "claim",
            claim,
            None,
            operation="retire",
        )
    return affected


async def _stage_merge_decision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    decision: dict[str, Any],
) -> set[str]:
    source_entity_id = str(decision["source_entity_id"])
    target_entity_id = str(decision["target_entity_id"])
    source = await graph_repository.get_active_entity(
        db,
        knowledge_base,
        source_entity_id,
    )
    target = await graph_repository.get_active_entity(
        db,
        knowledge_base,
        target_entity_id,
    )
    if source is None or target is None:
        raise ValueError("Graph review entity no longer exists.")

    aliases = await graph_repository.list_active_aliases_for_entity_ids(
        db,
        knowledge_base,
        {source.id, target.id},
    )
    target_aliases = {
        normalize_graph_name(target.canonical_name),
        *(
            alias.normalized_alias
            for alias in aliases
            if alias.entity_id == target.id
        ),
    }
    for alias in (item for item in aliases if item.entity_id == source.id):
        duplicate = alias.normalized_alias in target_aliases
        await _stage_existing_change(
            db,
            revision,
            "alias",
            alias,
            None if duplicate else {
                "entity_id": target.id,
                "source": "human",
            },
            operation="retire" if duplicate else "upsert",
        )
        target_aliases.add(alias.normalized_alias)
    source_name = normalize_graph_name(source.canonical_name)
    if source_name not in target_aliases:
        alias_id = str(
            uuid5(
                NAMESPACE_URL,
                "|".join(
                    (
                        "kg-human-alias",
                        knowledge_base.id,
                        target.id,
                        source_name,
                    )
                ),
            )
        )
        await stage_revision_change(
            db,
            revision,
            record_kind="alias",
            record_key=alias_id,
            operation="upsert",
            before_json=None,
            after_json={
                "id": alias_id,
                "entity_id": target.id,
                "alias": source.canonical_name,
                "normalized_alias": source_name,
                "source": "human",
            },
        )

    mentions = await graph_repository.list_active_mentions_for_entity_ids(
        db,
        knowledge_base,
        {source.id, target.id},
    )
    target_positions = {
        (item.chunk_id, item.start_offset, item.end_offset)
        for item in mentions
        if item.entity_id == target.id
    }
    for mention in (item for item in mentions if item.entity_id == source.id):
        position = (
            mention.chunk_id,
            mention.start_offset,
            mention.end_offset,
        )
        duplicate = position in target_positions
        await _stage_existing_change(
            db,
            revision,
            "mention",
            mention,
            None if duplicate else {
                "entity_id": target.id,
                "resolution_method": "human",
            },
            operation="retire" if duplicate else "upsert",
        )
        target_positions.add(position)

    affected = await _stage_claim_rebindings(
        db,
        knowledge_base,
        revision,
        source.id,
        target.id,
    )
    await _stage_existing_change(
        db,
        revision,
        "entity",
        source,
        {"state": "merged"},
        operation="retire",
    )
    return affected


async def _stage_split_decision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    decision: dict[str, Any],
) -> set[str]:
    source_entity_id = str(decision["source_entity_id"])
    source = await graph_repository.get_active_entity(
        db,
        knowledge_base,
        source_entity_id,
    )
    if source is None:
        raise ValueError("Graph review entity no longer exists.")
    entity_id = str(decision["new_entity_id"])
    canonical_name = str(decision["canonical_name"])
    entity_type = str(decision["entity_type"])
    await stage_revision_change(
        db,
        revision,
        record_kind="entity",
        record_key=entity_id,
        operation="upsert",
        before_json=None,
        after_json={
            "id": entity_id,
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "normalized_name": normalize_graph_name(canonical_name),
            "external_key": None,
            "properties_json": dict(source.properties_json or {}),
            "profile_markdown": "",
            "profile_hash": "",
            "profile_claim_ids": [],
            "search_text": canonical_name,
            "component_id": None,
            "degree": 0,
            "state": "active",
        },
    )
    selected_mentions = set(decision.get("mention_ids", []))
    for mention in await graph_repository.list_active_mentions_for_entity_ids(
        db,
        knowledge_base,
        {source.id},
    ):
        if mention.id in selected_mentions:
            await _stage_existing_change(
                db,
                revision,
                "mention",
                mention,
                {
                    "entity_id": entity_id,
                    "resolution_method": "human",
                },
            )
    affected = await _stage_claim_rebindings(
        db,
        knowledge_base,
        revision,
        source.id,
        entity_id,
        set(decision.get("claim_ids", [])),
    )
    return {source.id, entity_id, *affected}


async def stage_review_decision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    decision: dict[str, Any] | None,
) -> set[str]:
    if decision is None:
        return set()
    if not isinstance(decision, dict):
        raise ValueError("Graph review decision must be an object.")
    if not decision:
        return set()
    review_id = str(decision.get("review_id") or "")
    review = await graph_repository.get_review_item(db, revision, review_id)
    if review is None:
        raise ValueError("Graph review no longer exists.")
    if review.status == GRAPH_REVIEW_RESOLVED:
        return set()
    if review.status not in {GRAPH_REVIEW_APPROVED, GRAPH_REVIEW_REJECTED}:
        raise ValueError("Graph review is not ready for publication.")
    payload = KnowledgeGraphReviewDecisionRequest.model_validate(decision)
    affected: set[str] = set()
    if payload.action in {"approve_claim", "reject_claim"}:
        claim_ids = {str(item) for item in decision.get("claim_ids", [])}
        claims = await graph_repository.list_current_claims_by_ids(
            db,
            knowledge_base,
            claim_ids,
        )
        if len(claims) != len(claim_ids):
            raise ValueError("Graph review claim no longer exists.")
        for claim in claims:
            await _stage_existing_change(
                db,
                revision,
                "claim",
                claim,
                {
                    "status": (
                        "active"
                        if payload.action == "approve_claim"
                        else "rejected"
                    ),
                    "source_kind": "human",
                },
            )
            affected.add(claim.subject_entity_id)
            if claim.object_entity_id:
                affected.add(claim.object_entity_id)
    elif payload.action == "merge_entities":
        affected.update(
            await _stage_merge_decision(
                db,
                knowledge_base,
                revision,
                decision,
            )
        )
    else:
        affected.update(
            await _stage_split_decision(
                db,
                knowledge_base,
                revision,
                decision,
            )
        )
    await _stage_existing_change(
        db,
        revision,
        "review",
        review,
        {
            "status": GRAPH_REVIEW_RESOLVED,
            "decision_json": decision,
            "reviewed_by_user_id": decision.get("reviewed_by_user_id"),
            "reviewed_at": utc_now().isoformat(),
        },
    )
    return affected


async def reset_review_decision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    decision: dict[str, Any] | None,
) -> None:
    if not isinstance(decision, dict) or not decision:
        return
    locked = await knowledge_repository.lock_knowledge_base(db, knowledge_base)
    if locked is None:
        return
    review = await graph_repository.lock_review_item(
        db,
        locked,
        str(decision.get("review_id") or ""),
    )
    if review is None or review.status == GRAPH_REVIEW_RESOLVED:
        await db.rollback()
        return
    review.status = GRAPH_REVIEW_OPEN
    review.decision_json = {}
    review.reviewed_by_user_id = None
    review.reviewed_at = None
    await graph_repository.save_review_item(db, review)
    await db.commit()

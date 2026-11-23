"""Read models for knowledge document and task pages."""

from app.domain.knowledge.documents.service import document_to_response
from app.domain.knowledge.tasks.orchestration import task_to_response
from app.infra.db.repositories.knowledge import pagination as repository
from app.infra.db.repositories.knowledge.documents import count_document_chunks
from app.infra.db.repositories.knowledge.tasks import get_open_knowledge_task
from app.schemas.knowledge.contracts import (
    KnowledgeDocumentOptionResponse,
    KnowledgeDocumentPageResponse,
    KnowledgeDocumentSummaryResponse,
    KnowledgeTaskPageResponse,
)


async def get_knowledge_document_options(db, knowledge_base):
    return [
        KnowledgeDocumentOptionResponse(**row)
        for row in await repository.document_options(db, knowledge_base)
    ]


async def get_knowledge_document_page(db, knowledge_base, **options):
    documents, total, statuses = await repository.document_page(
        db, knowledge_base, **options
    )
    ids = [document.id for document in documents]
    counts = await count_document_chunks(db, knowledge_base, ids)
    tasks = await repository.document_tasks(db, knowledge_base, ids)
    rebuild = await get_open_knowledge_task(db, knowledge_base, "rebuild_index", None)
    indexed = statuses.get("indexed", 0)
    indexing = statuses.get("index_queued", 0) + statuses.get("indexing", 0)
    failed = sum(
        count for status, count in statuses.items() if status.endswith("_failed")
    )
    all_documents = sum(statuses.values())
    return KnowledgeDocumentPageResponse(
        items=[
            document_to_response(document, chunk_count=counts.get(document.id, 0))
            for document in documents
        ],
        total=total,
        summary=KnowledgeDocumentSummaryResponse(
            total=all_documents,
            indexed=indexed,
            indexing=indexing,
            failed=failed,
            pending=all_documents - indexed - indexing - failed,
            processing=indexing
            + statuses.get("parse_queued", 0)
            + statuses.get("parsing", 0),
        ),
        active_rebuild_task=task_to_response(rebuild) if rebuild else None,
        document_tasks=[task_to_response(task) for task in tasks],
    )


async def get_knowledge_task_page(db, knowledge_base, **options):
    rows, total, processing = await repository.task_page(db, knowledge_base, **options)
    return KnowledgeTaskPageResponse(
        items=[
            task_to_response(task).model_copy(update={"document_filename": filename})
            for task, filename in rows
        ],
        total=total,
        has_processing=processing,
    )

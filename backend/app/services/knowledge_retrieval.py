import asyncio

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services import knowledge_repositories as knowledge_base_repository
from app.models.knowledge import KnowledgeBase, KnowledgeDocument
from app.services.knowledge_pipeline import (
    KnowledgePipelineError,
    query_chroma_vectors,
)
from app.services.knowledge_processing import (
    CHUNK_INDEXED_STATUS,
    DOCUMENT_DELETED_STATUS,
    resolve_embedding_model,
)
from app.schemas.knowledge import (
    KnowledgeQueryHitResponse,
    KnowledgeQueryRequest,
)
from app.models.model import RegisteredModel
from app.llm.runtime import build_registered_model_provider

QUERY_OVERFETCH_FACTOR = 5


def embed_query(
    settings: Settings,
    embedding_model: RegisteredModel,
    query: str,
) -> list[float]:
    embeddings = build_registered_model_provider(embedding_model, settings).embed(
        [query]
    )
    if not embeddings:
        raise KnowledgePipelineError("Embedding provider returned no query embedding.")
    return embeddings[0]


async def query_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeQueryRequest,
    settings: Settings,
) -> list[KnowledgeQueryHitResponse]:
    embedding_model = await resolve_embedding_model(db, knowledge_base)
    if embedding_model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Embedding model is required.",
        )

    embedding = await asyncio.to_thread(
        embed_query,
        settings,
        embedding_model,
        payload.query,
    )
    vector_hits = await asyncio.to_thread(
        query_chroma_vectors,
        settings,
        knowledge_base.id,
        embedding,
        payload.limit * QUERY_OVERFETCH_FACTOR,
    )
    chunks = await knowledge_base_repository.list_chunks_by_ids(
        db,
        knowledge_base,
        [hit.chunk_id for hit in vector_hits],
    )
    chunks_by_id = {
        chunk.id: chunk for chunk in chunks if chunk.status == CHUNK_INDEXED_STATUS
    }

    documents: dict[str, KnowledgeDocument] = {}
    responses: list[KnowledgeQueryHitResponse] = []
    for hit in vector_hits:
        chunk = chunks_by_id.get(hit.chunk_id)
        if chunk is None:
            continue
        document = documents.get(chunk.document_id)
        if document is None:
            loaded = await db.get(KnowledgeDocument, chunk.document_id)
            if (
                loaded is None
                or loaded.status == DOCUMENT_DELETED_STATUS
                or not loaded.is_active
            ):
                continue
            documents[chunk.document_id] = loaded
            document = loaded
        responses.append(
            KnowledgeQueryHitResponse(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_filename=document.filename,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                distance=hit.distance,
            )
        )
        if len(responses) == payload.limit:
            break
    return responses

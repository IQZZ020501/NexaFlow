from dataclasses import dataclass
from typing import Any

from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from app.capabilities.llm.models import RegisteredModel
from app.capabilities.llm.runtime import build_registered_embeddings
from app.infrastructure.config import Settings
from app.shareddomain.knowledge.models import KnowledgeBase


@dataclass(frozen=True)
class VectorChunk:
    id: str
    document_id: str
    document_filename: str
    chunk_index: int
    content: str
    document_metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    distance: float | None


def vector_collection_name(knowledge_base_id: str) -> str:
    return f"kb_{knowledge_base_id.replace('-', '')}"


def _build_vector_store(
    settings: Settings,
    knowledge_base_id: str,
    embedding_model: RegisteredModel | None = None,
) -> Chroma:
    settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    embeddings = (
        build_registered_embeddings(embedding_model, settings)
        if embedding_model is not None
        else None
    )
    return Chroma(
        collection_name=vector_collection_name(knowledge_base_id),
        persist_directory=str(settings.chroma_persist_dir),
        embedding_function=embeddings,
    )


def delete_vector_collection(settings: Settings, knowledge_base_id: str) -> None:
    _build_vector_store(settings, knowledge_base_id).delete_collection()


def delete_vectors(
    settings: Settings,
    knowledge_base_id: str,
    vector_ids: list[str],
) -> None:
    if not vector_ids:
        return
    _build_vector_store(settings, knowledge_base_id).delete(ids=vector_ids)


def upsert_vectors(
    settings: Settings,
    knowledge_base: KnowledgeBase,
    embedding_model: RegisteredModel,
    chunks: list[VectorChunk],
) -> None:
    if not chunks:
        return
    documents = [
        Document(
            id=chunk.id,
            page_content=chunk.content,
            metadata={
                **{
                    key: value
                    for key, value in chunk.document_metadata.items()
                    if isinstance(value, (str, int, float, bool))
                },
                "chunk_id": chunk.id,
                "workspace_id": knowledge_base.workspace_id,
                "knowledge_base_id": knowledge_base.id,
                "document_id": chunk.document_id,
                "document_filename": chunk.document_filename,
                "chunk_index": chunk.chunk_index,
            },
        )
        for chunk in chunks
    ]
    _build_vector_store(settings, knowledge_base.id, embedding_model).add_documents(
        documents,
        ids=[chunk.id for chunk in chunks],
    )


def query_vectors(
    settings: Settings,
    knowledge_base_id: str,
    embedding_model: RegisteredModel,
    query: str,
    limit: int,
) -> list[VectorHit]:
    results = _build_vector_store(
        settings,
        knowledge_base_id,
        embedding_model,
    ).max_marginal_relevance_search(query, k=limit, fetch_k=limit * 2)
    return [
        VectorHit(chunk_id=chunk_id, distance=None)
        for document in results
        if isinstance(chunk_id := document.metadata.get("chunk_id"), str)
    ]

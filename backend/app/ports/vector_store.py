"""Vector store port.

Business code imports the functions and value types from here instead of
``app.capabilities.rag.vector_store``. The protocol documents the contract;
``build_vector_store`` is the single composition point for the concrete
backend (Qdrant today).
"""

from typing import Any, Protocol

from app.capabilities.rag.vector_store import (
    QdrantVectorStore,
    VectorChunk,
    VectorHit,
)
from app.infrastructure.config import Settings


class VectorStore(Protocol):
    def delete_vector_collection(self, knowledge_base_id: str) -> None: ...

    def delete_vectors(
        self,
        knowledge_base_id: str,
        vector_ids: list[str],
    ) -> None: ...

    def upsert_vectors(
        self,
        knowledge_base_id: str,
        workspace_id: str,
        embedding_model: object,
        chunks: list[VectorChunk],
    ) -> None: ...

    def query_vectors(
        self,
        knowledge_base_id: str,
        embedding_model: object,
        query: str,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[VectorHit]: ...


def build_vector_store(settings: Settings) -> VectorStore:
    return QdrantVectorStore(settings)


def delete_vector_collection(settings: Settings, knowledge_base_id: str) -> None:
    build_vector_store(settings).delete_vector_collection(knowledge_base_id)


def delete_vectors(
    settings: Settings,
    knowledge_base_id: str,
    vector_ids: list[str],
) -> None:
    build_vector_store(settings).delete_vectors(knowledge_base_id, vector_ids)


def upsert_vectors(
    settings: Settings,
    knowledge_base_id: str,
    workspace_id: str,
    embedding_model: object,
    chunks: list[VectorChunk],
) -> None:
    build_vector_store(settings).upsert_vectors(
        knowledge_base_id,
        workspace_id,
        embedding_model,
        chunks,
    )


def query_vectors(
    settings: Settings,
    knowledge_base_id: str,
    embedding_model: object,
    query: str,
    limit: int,
    score_threshold: float | None = None,
) -> list[VectorHit]:
    return build_vector_store(settings).query_vectors(
        knowledge_base_id,
        embedding_model,
        query,
        limit,
        score_threshold,
    )


__all__ = [
    "VectorChunk",
    "VectorHit",
    "VectorStore",
    "build_vector_store",
    "delete_vector_collection",
    "delete_vectors",
    "query_vectors",
    "upsert_vectors",
]

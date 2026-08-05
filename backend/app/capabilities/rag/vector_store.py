from dataclasses import dataclass
from functools import cache
from typing import Any

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

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


@cache
def _build_qdrant_client(qdrant_url: str, qdrant_api_key: str) -> QdrantClient:
    if qdrant_url == ":memory:":
        return QdrantClient(location=":memory:")
    return QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None)


def _client(settings: Settings) -> QdrantClient:
    return _build_qdrant_client(settings.qdrant_url, settings.qdrant_api_key)


def _ensure_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int,
) -> None:
    if not client.collection_exists(collection_name):
        try:
            created = client.create_collection(
                collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
        except UnexpectedResponse as exc:
            if exc.status_code != 409:
                raise
        else:
            if created:
                return

    vectors_config = client.get_collection(collection_name).config.params.vectors
    if (
        not isinstance(vectors_config, models.VectorParams)
        or vectors_config.size != vector_size
    ):
        raise ValueError(
            f"Qdrant collection {collection_name!r} uses a different vector size."
        )


def delete_vector_collection(settings: Settings, knowledge_base_id: str) -> None:
    client = _client(settings)
    collection_name = vector_collection_name(knowledge_base_id)
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)


def delete_vectors(
    settings: Settings,
    knowledge_base_id: str,
    vector_ids: list[str],
) -> None:
    if not vector_ids:
        return
    client = _client(settings)
    collection_name = vector_collection_name(knowledge_base_id)
    if client.collection_exists(collection_name):
        client.delete(collection_name, points_selector=vector_ids, wait=True)


def upsert_vectors(
    settings: Settings,
    knowledge_base: KnowledgeBase,
    embedding_model: RegisteredModel,
    chunks: list[VectorChunk],
) -> None:
    if not chunks:
        return
    embeddings = build_registered_embeddings(embedding_model, settings)
    vectors = embeddings.embed_documents([chunk.content for chunk in chunks])
    vector_size = len(vectors[0]) if vectors else 0
    if (
        len(vectors) != len(chunks)
        or vector_size == 0
        or any(len(vector) != vector_size for vector in vectors)
    ):
        raise ValueError("Embedding provider returned invalid document vectors.")

    client = _client(settings)
    collection_name = vector_collection_name(knowledge_base.id)
    _ensure_collection(client, collection_name, vector_size)
    client.upsert(
        collection_name,
        points=[
            models.PointStruct(
                id=chunk.id,
                vector=vector,
                payload={
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
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
        wait=True,
    )


def query_vectors(
    settings: Settings,
    knowledge_base_id: str,
    embedding_model: RegisteredModel,
    query: str,
    limit: int,
) -> list[VectorHit]:
    if limit <= 0:
        return []
    client = _client(settings)
    collection_name = vector_collection_name(knowledge_base_id)
    if not client.collection_exists(collection_name):
        return []

    query_embedding = build_registered_embeddings(
        embedding_model,
        settings,
    ).embed_query(query)
    results = client.query_points(
        collection_name,
        query=models.NearestQuery(
            nearest=query_embedding,
            mmr=models.Mmr(diversity=0.5, candidates_limit=limit * 2),
        ),
        limit=limit,
        with_payload=["chunk_id"],
    ).points
    return [
        VectorHit(chunk_id=chunk_id, distance=None)
        for point in results
        if isinstance(point.payload, dict)
        and isinstance(chunk_id := point.payload.get("chunk_id"), str)
    ]

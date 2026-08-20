import logging
import time
from dataclasses import dataclass
from functools import cache
from typing import Any

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.capabilities.llm.models import RegisteredModel
from app.capabilities.llm.runtime import build_registered_embeddings
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger, log_event

logger = get_logger(__name__)


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
        log_event(logger, logging.INFO, "Qdrant client created.", mode="memory")
        return QdrantClient(location=":memory:")
    log_event(logger, logging.INFO, "Qdrant client created.", url=qdrant_url)
    return QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None)


def _client(settings: Settings) -> QdrantClient:
    return _build_qdrant_client(settings.qdrant_url, settings.qdrant_api_key)


def check_vector_store_health(settings: Settings) -> None:
    """Verify that the configured Qdrant service accepts an API request."""
    _client(settings).get_collections()


def _ensure_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int,
) -> None:
    collection_created_concurrently = False
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
                log_error(
                    logger,
                    "Qdrant collection creation failed.",
                    exc,
                    collection_name=collection_name,
                    vector_size=vector_size,
                )
                raise
            log_event(
                logger,
                logging.INFO,
                "Qdrant collection created concurrently by another process.",
                collection_name=collection_name,
            )
            collection_created_concurrently = True
        else:
            if created:
                log_event(
                    logger,
                    logging.INFO,
                    "Qdrant collection created.",
                    collection_name=collection_name,
                    vector_size=vector_size,
                )
                return

    for attempt in range(3):
        try:
            vectors_config = client.get_collection(collection_name).config.params.vectors
            break
        except UnexpectedResponse as exc:
            if (
                not collection_created_concurrently
                or exc.status_code != 500
                or attempt == 2
            ):
                raise
            # ponytail: three short retries cover Qdrant's post-create metadata window.
            time.sleep(0.05)
    if (
        not isinstance(vectors_config, models.VectorParams)
        or vectors_config.size != vector_size
    ):
        log_error(
            logger,
            "Qdrant collection vector size mismatch.",
            None,
            collection_name=collection_name,
            expected_size=vector_size,
        )
        raise ValueError(
            f"Qdrant collection {collection_name!r} uses a different vector size."
        )


def delete_vector_collection(settings: Settings, knowledge_base_id: str) -> None:
    client = _client(settings)
    collection_name = vector_collection_name(knowledge_base_id)
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)
        log_event(
            logger,
            logging.INFO,
            "Qdrant collection deleted.",
            knowledge_base_id=knowledge_base_id,
            collection_name=collection_name,
        )
    else:
        log_event(
            logger,
            logging.INFO,
            "Qdrant collection absent, nothing to delete.",
            knowledge_base_id=knowledge_base_id,
            collection_name=collection_name,
        )


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
        log_event(
            logger,
            logging.INFO,
            "Qdrant vectors deleted.",
            knowledge_base_id=knowledge_base_id,
            collection_name=collection_name,
            vector_count=len(vector_ids),
        )
    else:
        log_event(
            logger,
            logging.INFO,
            "Qdrant collection absent, vectors already gone.",
            knowledge_base_id=knowledge_base_id,
            collection_name=collection_name,
            vector_count=len(vector_ids),
        )


def upsert_vectors(
    settings: Settings,
    knowledge_base_id: str,
    workspace_id: str,
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
        log_error(
            logger,
            "Embedding provider returned invalid document vectors.",
            None,
            source="external",
            expected_count=len(chunks),
            received_count=len(vectors),
            vector_size=vector_size,
        )
        raise ValueError("Embedding provider returned invalid document vectors.")

    client = _client(settings)
    collection_name = vector_collection_name(knowledge_base_id)
    _ensure_collection(client, collection_name, vector_size)
    started = time.monotonic()
    try:
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
                        "workspace_id": workspace_id,
                        "knowledge_base_id": knowledge_base_id,
                        "document_id": chunk.document_id,
                        "document_filename": chunk.document_filename,
                        "chunk_index": chunk.chunk_index,
                    },
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
            wait=True,
        )
    except Exception as exc:
        log_error(
            logger,
            "Qdrant vector upsert failed.",
            exc,
            collection_name=collection_name,
            knowledge_base_id=knowledge_base_id,
            vector_count=len(chunks),
        )
        raise
    log_event(
        logger,
        logging.INFO,
        "Qdrant vectors upserted.",
        collection_name=collection_name,
        knowledge_base_id=knowledge_base_id,
        vector_count=len(chunks),
        duration_ms=round((time.monotonic() - started) * 1000, 1),
    )


def query_vectors(
    settings: Settings,
    knowledge_base_id: str,
    embedding_model: RegisteredModel,
    query: str,
    limit: int,
    score_threshold: float | None = None,
    document_ids: set[str] | None = None,
) -> list[VectorHit]:
    if limit <= 0 or (document_ids is not None and not document_ids):
        return []
    client = _client(settings)
    collection_name = vector_collection_name(knowledge_base_id)
    if not client.collection_exists(collection_name):
        return []

    query_embedding = build_registered_embeddings(
        embedding_model,
        settings,
    ).embed_query(query)
    started = time.monotonic()
    try:
        query_kwargs: dict[str, Any] = {}
        if score_threshold is not None:
            query_kwargs["score_threshold"] = score_threshold
        if document_ids is not None:
            query_kwargs["query_filter"] = models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchAny(any=sorted(document_ids)),
                    )
                ]
            )
        results = client.query_points(
            collection_name,
            query=models.NearestQuery(
                nearest=query_embedding,
                mmr=models.Mmr(diversity=0.5, candidates_limit=limit * 2),
            ),
            limit=limit,
            with_payload=["chunk_id"],
            **query_kwargs,
        ).points
    except Exception as exc:
        log_error(
            logger,
            "Qdrant vector query failed.",
            exc,
            collection_name=collection_name,
            knowledge_base_id=knowledge_base_id,
            query_limit=limit,
            duration_ms=round((time.monotonic() - started) * 1000, 1),
        )
        raise
    return [
        # Qdrant COSINE reports cosine similarity (1 = identical); expose
        # cosine distance (1 - score, [0, 2]) so lower is more similar.
        VectorHit(chunk_id=chunk_id, distance=1.0 - point.score)
        for point in results
        if isinstance(point.payload, dict)
        and isinstance(chunk_id := point.payload.get("chunk_id"), str)
    ]


class QdrantVectorStore:
    """Adapter implementing the ``app.ports.vector_store.VectorStore`` contract."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check_health(self) -> None:
        check_vector_store_health(self._settings)

    def delete_vector_collection(self, knowledge_base_id: str) -> None:
        delete_vector_collection(self._settings, knowledge_base_id)

    def delete_vectors(
        self,
        knowledge_base_id: str,
        vector_ids: list[str],
    ) -> None:
        delete_vectors(self._settings, knowledge_base_id, vector_ids)

    def upsert_vectors(
        self,
        knowledge_base_id: str,
        workspace_id: str,
        embedding_model: RegisteredModel,
        chunks: list[VectorChunk],
    ) -> None:
        upsert_vectors(
            self._settings,
            knowledge_base_id,
            workspace_id,
            embedding_model,
            chunks,
        )

    def query_vectors(
        self,
        knowledge_base_id: str,
        embedding_model: RegisteredModel,
        query: str,
        limit: int,
        score_threshold: float | None = None,
        document_ids: set[str] | None = None,
    ) -> list[VectorHit]:
        return query_vectors(
            self._settings,
            knowledge_base_id,
            embedding_model,
            query,
            limit,
            score_threshold,
            document_ids,
        )

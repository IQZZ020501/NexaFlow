import asyncio
import json
from html import escape
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    create_active_user,
    settings as test_settings,
    test_client,
)

from app.infrastructure.session import get_session_factory
from app.domain.user import User
from app.shareddomain.knowledge.models import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeDocumentReference,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationExpectation,
    KnowledgeEvaluationResult,
    KnowledgeTask,
)
from app.api.v1.endpoints import knowledge as knowledge_api
from app.api.v1.endpoints import knowledge_evaluation as knowledge_evaluation_api
from app.application import knowledge as knowledge_application
from app.application import knowledge_evaluation as knowledge_evaluation_application
from app.application import knowledge_retrieval as knowledge_retrieval_application
from app.capabilities.rag import retrieval as knowledge_retrieval
from app.capabilities.rag import vector_store as knowledge_vector_store
from app.capabilities.embedding.pipeline import (
    KnowledgePipelineError,
    build_hierarchical_chunks,
    clean_text,
    split_text,
)
from app.capabilities.rag.vector_store import VectorChunk, VectorHit
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import (
    knowledge_evaluation as evaluation_repository,
)
from app.infrastructure.repositories import user as user_repository
from app.entities.knowledge import (
    DOCUMENT_DELETED_STATUS,
    KnowledgeEvaluationResult as KnowledgeEvaluationResultEntity,
)
from app.shareddomain.knowledge.orchestration import (
    enqueue_parse_knowledge_document,
    enqueue_rebuild_knowledge_index,
)
from app.shareddomain.knowledge.task_runner import (
    mark_knowledge_task_failed,
    recover_knowledge_tasks,
    run_knowledge_task,
    run_parse_task,
)
from app.tasks.knowledge import mark_task_dispatch_failed
from app.schemas.knowledge import (
    KnowledgeQueryHitResponse,
    KnowledgeQueryInspectResponse,
    KnowledgeQueryRequest,
    KnowledgeRetrievalTraceResponse,
)
from tests.llm import ModelTestHandler, model_payload, model_test_server, models_url
from app.domain.resource_permission import ResourcePermission


MEMBER_PASSWORD = "Member@12345."
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 120 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def docx_bytes(text: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:body>
</w:document>""",
        )
    return output.getvalue()


def knowledge_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge-bases{suffix}"


def create_workspace_user(client, token: str, workspace_id: str, username: str) -> tuple[str, str]:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members/users",
        headers=auth_headers(token),
        json={
            "username": username,
            "email": f"{username}@example.com",
            "name": username.replace("-", " ").title(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], response.json()["initial_password"]


async def assert_cross_workspace_permission_denied(
    default_workspace_id: str,
    knowledge_base_id: str,
) -> None:
    async with get_session_factory()() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        user = await db.scalar(select(User).where(User.username == "research-admin"))
        assert user is not None

        db.add(
            ResourcePermission(
                workspace_id=default_workspace_id,
                resource_type="knowledge_base",
                resource_id=knowledge_base_id,
                user_id=user.id,
                permission="view",
                created_by_user_id=user.id,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return

    raise AssertionError("Cross-workspace resource permission was allowed.")


async def assert_document_saved(document_id: str, expected_content: bytes) -> None:
    async with get_session_factory()() as db:
        document = await db.get(KnowledgeDocument, document_id)
        assert document is not None
        assert document.size_bytes == len(expected_content)
        path = test_settings().knowledge_storage_dir / document.storage_path
        assert path.read_bytes() == expected_content


async def set_document_chunk_search_text(
    document_id: str,
    search_text: str,
) -> None:
    async with get_session_factory()() as db:
        chunks = list(
            await db.scalars(
                select(KnowledgeDocumentChunk).where(
                    KnowledgeDocumentChunk.document_id == document_id
                )
            )
        )
        assert chunks
        for chunk in chunks:
            chunk.search_text = search_text
        await db.commit()


async def document_chunk_search_texts(document_id: str) -> list[str]:
    async with get_session_factory()() as db:
        return list(
            await db.scalars(
                select(KnowledgeDocumentChunk.search_text)
                .where(KnowledgeDocumentChunk.document_id == document_id)
                .order_by(KnowledgeDocumentChunk.chunk_index)
            )
        )


async def assert_document_reference_target(
    source_document_id: str,
    target_document_id: str | None,
    target_parent_title: str | None = None,
) -> None:
    async with get_session_factory()() as db:
        references = list(
            await db.scalars(
                select(KnowledgeDocumentReference)
                .where(
                    KnowledgeDocumentReference.source_document_id
                    == source_document_id
                )
                .order_by(KnowledgeDocumentReference.source_ordinal)
            )
        )
        assert len(references) == 1
        reference = references[0]
        assert reference.target_label == "rollback.md"
        assert reference.target_section == "rollback-procedure"
        assert reference.reference_type == "markdown"
        assert reference.source_ordinal == 0
        assert reference.target_document_id == target_document_id
        if target_parent_title is None:
            assert reference.target_parent_id is None
        else:
            parent = await db.get(
                KnowledgeDocumentParentChunk,
                reference.target_parent_id,
            )
            assert parent is not None
            assert parent.document_id == target_document_id
            assert parent.title == target_parent_title


async def assert_reference_parent_requires_document(
    source_document_id: str,
    target_document_id: str,
) -> None:
    async with get_session_factory()() as db:
        source_chunk = await db.scalar(
            select(KnowledgeDocumentChunk).where(
                KnowledgeDocumentChunk.document_id == source_document_id
            )
        )
        target_parent = await db.scalar(
            select(KnowledgeDocumentParentChunk).where(
                KnowledgeDocumentParentChunk.document_id == target_document_id
            )
        )
        assert source_chunk is not None
        assert target_parent is not None
        db.add(
            KnowledgeDocumentReference(
                id="invalid-parent-reference",
                workspace_id=source_chunk.workspace_id,
                knowledge_base_id=source_chunk.knowledge_base_id,
                source_document_id=source_document_id,
                source_chunk_id=source_chunk.id,
                target_document_id=None,
                target_parent_id=target_parent.id,
                target_label="invalid-parent.md",
                target_section="Invalid",
                reference_type="markdown",
                source_ordinal=99,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        else:
            raise AssertionError("Parent references must include their target document.")


async def clear_knowledge_base_embedding_model(knowledge_base_id: str) -> None:
    async with get_session_factory()() as db:
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        knowledge_base.embedding_model_id = None
        await db.commit()


async def assert_knowledge_base_embedding_model(knowledge_base_id: str, model_id: str) -> None:
    async with get_session_factory()() as db:
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        assert knowledge_base.embedding_model_id == model_id


async def assert_knowledge_base_deleted(knowledge_base_id: str, workspace_id: str) -> None:
    async with get_session_factory()() as db:
        assert await db.get(KnowledgeBase, knowledge_base_id) is None
        documents = await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == knowledge_base_id
            )
        )
        assert documents.scalars().all() == []
        for model in (
            KnowledgeEvaluationCase,
            KnowledgeEvaluationExpectation,
            KnowledgeEvaluationResult,
        ):
            rows = await db.scalars(
                select(model).where(model.knowledge_base_id == knowledge_base_id)
            )
            assert list(rows) == []
    assert not (test_settings().knowledge_storage_dir / workspace_id / knowledge_base_id).exists()


async def assert_document_deleted(document_id: str) -> None:
    async with get_session_factory()() as db:
        document = await db.get(KnowledgeDocument, document_id)
        assert document is not None
        assert document.status == "deleted"
        chunks = await db.execute(
            select(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.document_id == document_id)
        )
        assert chunks.scalars().all() == []
        parents = await db.execute(
            select(KnowledgeDocumentParentChunk).where(
                KnowledgeDocumentParentChunk.document_id == document_id
            )
        )
        assert parents.scalars().all() == []
        assert not (test_settings().knowledge_storage_dir / document.storage_path).exists()


async def assert_evaluation_success_resists_stale_error(
    workspace_id: str,
    knowledge_base_id: str,
    task_id: str,
    case_id: str,
    result_id: str,
) -> None:
    async with get_session_factory()() as db:
        persisted = await evaluation_repository.upsert_result(
            db,
            KnowledgeEvaluationResultEntity(
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                task_id=task_id,
                case_id=case_id,
                error="stale worker error",
            ),
        )
        await db.commit()
        assert persisted.id == result_id
        assert persisted.error is None

        row = await db.get(KnowledgeEvaluationResult, result_id)
        assert row is not None
        assert row.error is None
        assert row.hit_at_k == 1


async def assert_evaluation_run_deleted(task_id: str) -> None:
    async with get_session_factory()() as db:
        assert await db.get(KnowledgeTask, task_id) is None
        results = await db.scalars(
            select(KnowledgeEvaluationResult).where(
                KnowledgeEvaluationResult.task_id == task_id
            )
        )
        assert list(results) == []


async def enqueue_recoverable_parse_task(
    knowledge_base_id: str,
    document_id: str,
    actor_username: str,
) -> None:
    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            knowledge_base_id,
        )
        document = await knowledge_repository.get_knowledge_document_by_id(
            db,
            document_id,
        )
        actor = await user_repository.get_active_user_by_username(
            db,
            actor_username,
        )
        assert knowledge_base is not None
        assert document is not None
        assert actor is not None
        await enqueue_parse_knowledge_document(db, knowledge_base, document, actor)


async def assert_deleted_document_not_resurrected_by_parse_task(
    knowledge_base_id: str,
    document_id: str,
    task_id: str,
) -> None:
    # 模拟 worker 已领取任务（running），随后文档在导入会话中被删除
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
        document = await knowledge_repository.get_knowledge_document_by_id(
            db,
            document_id,
        )
        assert document is not None
        assert task is not None
        task.status = "running"
        document.status = DOCUMENT_DELETED_STATUS
        await knowledge_repository.save_knowledge_task(db, task)
        await knowledge_repository.save_knowledge_document(db, document)
        await db.commit()

        aborted = False
        caught: Exception | None = None
        async with get_session_factory()() as db:
            knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
                db,
                knowledge_base_id,
            )
            document = await knowledge_repository.get_knowledge_document_by_id(
                db,
                document_id,
            )
            task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
            assert knowledge_base is not None
            assert document is not None
            assert task is not None
            actor = await user_repository.get_user_by_id(
                db,
                task.created_by_user_id,
            )
            assert actor is not None
            try:
                await run_parse_task(
                    db,
                    task,
                    knowledge_base,
                    document,
                    actor,
                    test_settings(),
                    asyncio.Event(),
                )
            except KnowledgePipelineError as exc:
                aborted = True
                caught = exc
            except Exception as exc:  # noqa: BLE001 - surface unexpected failures
                caught = exc
            await db.rollback()

        assert caught is None or isinstance(
            caught, KnowledgePipelineError
        ), f"unexpected exception: {type(caught).__name__}: {caught}"
        assert aborted, "parse task must abort when its document was deleted"
        # run_knowledge_task 的收尾：任务标记失败（文档已删除时不改文档状态）
        await mark_knowledge_task_failed(
            db,
            task_id,
            "Knowledge document no longer exists.",
        )
    async with get_session_factory()() as db:
        document = await db.get(KnowledgeDocument, document_id)
        assert document is not None
        assert document.status == DOCUMENT_DELETED_STATUS
        task = await db.get(KnowledgeTask, task_id)
        assert task is not None
        assert task.status == "failed"


async def enqueue_recoverable_rebuild_task(
    knowledge_base_id: str,
    actor_username: str,
) -> None:
    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            knowledge_base_id,
        )
        actor = await user_repository.get_active_user_by_username(
            db,
            actor_username,
        )
        assert knowledge_base is not None
        assert actor is not None
        await enqueue_rebuild_knowledge_index(db, knowledge_base, actor)


async def assert_task_failed(task_id: str, document_id: str) -> None:
    async with get_session_factory()() as db:
        task = await db.get(KnowledgeTask, task_id)
        document = await db.get(KnowledgeDocument, document_id)
        assert task is not None
        assert task.status == "failed"
        assert task.attempts == 1
        assert task.total_items == 1
        assert task.processed_items == 0
        assert task.last_error
        assert document is not None
        assert document.status == "index_failed"
        assert document.last_error == task.last_error


async def assert_parse_task_failed(task_id: str, document_id: str) -> None:
    async with get_session_factory()() as db:
        task = await db.get(KnowledgeTask, task_id)
        document = await db.get(KnowledgeDocument, document_id)
        assert task is not None
        assert task.status == "failed"
        assert task.task_type == "parse"
        assert task.attempts == 1
        assert task.processed_items == 0
        assert task.last_error == "Document format is not supported."
        assert document is not None
        assert document.status == "parse_failed"
        assert document.last_error == task.last_error


async def assert_rebuild_task_failed_without_document_status_change(task_id: str, document_id: str) -> None:
    async with get_session_factory()() as db:
        task = await db.get(KnowledgeTask, task_id)
        document = await db.get(KnowledgeDocument, document_id)
        assert task is not None
        assert task.status == "failed"
        assert task.task_type == "rebuild_index"
        assert task.document_id is None
        assert task.last_error
        assert document is not None
        assert document.status == "indexed"
        assert document.last_error is None


async def assert_task_succeeded(task_id: str, document_id: str, attempts: int) -> None:
    async with get_session_factory()() as db:
        task = await db.get(KnowledgeTask, task_id)
        document = await db.get(KnowledgeDocument, document_id)
        assert task is not None
        assert task.status == "succeeded"
        assert task.attempts == attempts
        assert task.total_items == 1
        assert task.processed_items == 1
        assert task.last_error is None
        assert document is not None
        assert document.status in {"parsed", "indexed"}
        assert document.last_error is None


async def replace_document_file_with_text(
    document_id: str,
    content: bytes,
    filename: str,
) -> None:
    async with get_session_factory()() as db:
        document = await db.get(KnowledgeDocument, document_id)
        assert document is not None
        document.filename = filename
        document.content_type = "text/plain"
        document.size_bytes = len(content)
        path = test_settings().knowledge_storage_dir / document.storage_path
        path.write_bytes(content)
        await db.commit()


async def assert_query_skips_stale_vector(knowledge_base_id: str, indexed_chunk_id: str) -> None:
    original_query_vectors = knowledge_retrieval_application.query_vectors

    def fake_query_vectors(*_args) -> list[VectorHit]:
        assert _args[-2] == 5
        assert _args[-1] is None
        return [
            VectorHit(chunk_id="stale-chunk", distance=0.0),
            VectorHit(chunk_id=indexed_chunk_id, distance=0.1),
        ]

    knowledge_retrieval_application.query_vectors = fake_query_vectors
    try:
        async with get_session_factory()() as db:
            knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
            assert knowledge_base is not None
            hits = await knowledge_application.query_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="product docs", limit=1),
                test_settings(),
            )
            assert [hit.chunk_id for hit in hits] == [indexed_chunk_id]
    finally:
        knowledge_retrieval_application.query_vectors = original_query_vectors


def test_keyword_query_does_not_require_embedding_model() -> None:
    from unittest.mock import AsyncMock, Mock, patch

    async def run() -> None:
        keyword_query = AsyncMock(return_value=[])
        with patch.object(
            knowledge_retrieval_application,
            "resolve_embedding_model",
            new=AsyncMock(side_effect=AssertionError("embedding model was resolved")),
        ) as resolve_model, patch.object(
            knowledge_retrieval_application,
            "query_vectors",
            new=Mock(side_effect=AssertionError("vector search was called")),
        ) as vector_query, patch.object(
            knowledge_repository,
            "query_keyword_chunk_ids",
            new=keyword_query,
        ), patch.object(
            knowledge_repository,
            "list_chunks_by_ids",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            knowledge_repository,
            "list_active_documents_by_ids",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            knowledge_retrieval_application,
            "log_event",
        ) as completion_log:
            result = await knowledge_retrieval_application.retrieve_knowledge_base(
                object(),  # type: ignore[arg-type]
                SimpleNamespace(  # type: ignore[arg-type]
                    id="base-1",
                    reranker_model_id=None,
                ),
                KnowledgeQueryRequest(
                    query="private keyword only",
                    limit=1,
                    search_mode="keywords",
                ),
                SimpleNamespace(),  # type: ignore[arg-type]
            )

        assert result.hits == []
        assert result.trace.rerank_status == "not_configured"
        assert "private keyword only" not in str(completion_log.call_args)
        assert "query" not in completion_log.call_args.kwargs
        assert all("hash" not in key for key in completion_log.call_args.kwargs)
        resolve_model.assert_not_awaited()
        vector_query.assert_not_called()
        keyword_query.assert_awaited_once()
        assert keyword_query.await_args.args[2:] == ("private keyword only", 5)

    asyncio.run(run())


def assert_vector_store_mmr_and_metadata() -> None:
    chunk_id = "00000000-0000-0000-0000-000000000001"

    class FakeEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            assert texts == ["content"]
            return [[1.0, 0.0]]

        def embed_query(self, query: str) -> list[float]:
            assert query == "exact term"
            return [1.0, 0.0]

    original_build_embeddings = knowledge_vector_store.build_registered_embeddings
    knowledge_vector_store._build_qdrant_client.cache_clear()
    knowledge_vector_store.build_registered_embeddings = (
        lambda *_args: FakeEmbeddings()
    )
    client = None
    try:
        settings = test_settings()
        assert knowledge_vector_store.query_vectors(
            settings,
            "missing-knowledge",
            object(),
            "exact term",
            3,
        ) == []

        knowledge_vector_store.upsert_vectors(
            settings,
            "knowledge-1",
            "workspace-1",
            object(),
            [
                VectorChunk(
                    id=chunk_id,
                    document_id="document-1",
                    document_filename="guide.txt",
                    chunk_index=2,
                    content="content",
                    document_metadata={
                        "security_level": "INTERNAL",
                        "allow_download": False,
                        "content_type": "text/plain",
                        "nested": {"ignored": True},
                        "chunk_id": "untrusted",
                    },
                )
            ],
        )

        client = knowledge_vector_store._client(settings)
        collection_name = knowledge_vector_store.vector_collection_name("knowledge-1")
        assert client.get_collection(collection_name).config.params.vectors.size == 2
        stored = client.retrieve(collection_name, ids=[chunk_id], with_payload=True)
        assert len(stored) == 1
        assert stored[0].payload == {
            "security_level": "INTERNAL",
            "allow_download": False,
            "content_type": "text/plain",
            "chunk_id": chunk_id,
            "workspace_id": "workspace-1",
            "knowledge_base_id": "knowledge-1",
            "document_id": "document-1",
            "document_filename": "guide.txt",
            "chunk_index": 2,
        }

        client.upsert(
            collection_name,
            points=[
                knowledge_vector_store.models.PointStruct(
                    id="00000000-0000-0000-0000-000000000002",
                    vector=[1.0, 0.0],
                    payload={},
                )
            ],
        )
        assert knowledge_vector_store.query_vectors(
            settings,
            "knowledge-1",
            object(),
            "exact term",
            3,
        ) == [VectorHit(chunk_id=chunk_id, distance=0.0)]

        second_chunk_id = "00000000-0000-0000-0000-000000000003"
        client.upsert(
            collection_name,
            points=[
                knowledge_vector_store.models.PointStruct(
                    id=second_chunk_id,
                    vector=[1.0, 0.0],
                    payload={
                        "chunk_id": second_chunk_id,
                        "document_id": "document-2",
                    },
                )
            ],
        )
        assert knowledge_vector_store.query_vectors(
            settings,
            "knowledge-1",
            object(),
            "exact term",
            3,
            document_ids={"document-1"},
        ) == [VectorHit(chunk_id=chunk_id, distance=0.0)]
        assert knowledge_vector_store.query_vectors(
            settings,
            "knowledge-1",
            object(),
            "exact term",
            3,
            document_ids=set(),
        ) == []

        try:
            knowledge_vector_store._ensure_collection(client, collection_name, 3)
        except ValueError:
            pass
        else:
            raise AssertionError("Qdrant vector size mismatch was accepted.")

        class RacingClient:
            def __init__(self) -> None:
                self.get_collection_calls = 0

            def collection_exists(self, _collection_name: str) -> bool:
                return False

            def create_collection(self, *_args, **_kwargs) -> bool:
                raise knowledge_vector_store.UnexpectedResponse(
                    409,
                    "Conflict",
                    b"",
                    {},
                )

            def get_collection(self, _collection_name: str):
                self.get_collection_calls += 1
                if self.get_collection_calls == 1:
                    raise knowledge_vector_store.UnexpectedResponse(
                        500,
                        "Internal Server Error",
                        b'{"status":{"error":"Service internal error: 0 of 0 read operations failed"}}',
                        {},
                    )
                return SimpleNamespace(
                    config=SimpleNamespace(
                        params=SimpleNamespace(
                            vectors=knowledge_vector_store.models.VectorParams(
                                size=2,
                                distance=knowledge_vector_store.models.Distance.COSINE,
                            )
                        )
                    )
                )

        racing_client = RacingClient()
        knowledge_vector_store._ensure_collection(racing_client, "race", 2)
        assert racing_client.get_collection_calls == 2
        knowledge_vector_store.delete_vectors(settings, "knowledge-1", [chunk_id])
        assert client.retrieve(collection_name, ids=[chunk_id]) == []
        knowledge_vector_store.delete_vector_collection(settings, "knowledge-1")
        assert not client.collection_exists(collection_name)
    finally:
        knowledge_vector_store.build_registered_embeddings = original_build_embeddings
        if client is not None:
            client.close()
        knowledge_vector_store._build_qdrant_client.cache_clear()

    fused = knowledge_retrieval.reciprocal_rank_fusion(
        [
            VectorHit(chunk_id="vector-only", distance=0.1),
            VectorHit(chunk_id="shared", distance=0.2),
        ],
        ["shared", "keyword-only"],
    )
    assert [(hit.chunk_id, hit.distance) for hit in fused] == [
        ("shared", 0.2),
        ("vector-only", 0.1),
        ("keyword-only", None),
    ]


async def assert_query_aggregates_hybrid_hits(
    knowledge_base_id: str,
    product_document_id: str,
    product_chunk_id: str,
    configured_document_id: str,
    configured_chunks: list[dict],
) -> None:
    original_query_vectors = knowledge_retrieval_application.query_vectors
    original_query_keyword_chunk_ids = knowledge_repository.query_keyword_chunk_ids
    configured_by_index = {
        chunk["chunk_index"]: chunk for chunk in configured_chunks
    }

    def fake_query_vectors(*args) -> list[VectorHit]:
        assert args[-3:-1] == ("exact term", 10)
        assert args[-1] is None
        return [
            VectorHit(chunk_id=product_chunk_id, distance=0.05),
            VectorHit(chunk_id="stale-chunk", distance=0.1),
            VectorHit(chunk_id=configured_by_index[2]["id"], distance=0.15),
            VectorHit(chunk_id=configured_by_index[0]["id"], distance=0.2),
            VectorHit(chunk_id=configured_by_index[1]["id"], distance=0.25),
        ]

    async def fake_query_keyword_chunk_ids(
        _db,
        knowledge_base,
        query: str,
        candidate_limit: int,
    ) -> list[str]:
        assert knowledge_base.id == knowledge_base_id
        assert (query, candidate_limit) == ("exact term", 10)
        return [configured_by_index[0]["id"]]

    knowledge_retrieval_application.query_vectors = fake_query_vectors
    knowledge_repository.query_keyword_chunk_ids = fake_query_keyword_chunk_ids
    reranker_calls_before = sum(
        call["path"] == "/v1/rerank" for call in ModelTestHandler.calls
    )
    try:
        async with get_session_factory()() as db:
            knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
            assert knowledge_base is not None
            result = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="exact term", limit=2),
                test_settings(),
            )
            hits = result.hits
    finally:
        knowledge_retrieval_application.query_vectors = original_query_vectors
        knowledge_repository.query_keyword_chunk_ids = original_query_keyword_chunk_ids

    assert sum(call["path"] == "/v1/rerank" for call in ModelTestHandler.calls) == (
        reranker_calls_before + 1
    )
    assert result.trace.rerank_status == "applied"
    assert result.trace.vector_candidates == 5
    assert result.trace.keyword_candidates == 1
    assert result.trace.reference_candidates == 0
    assert result.trace.returned_hits == 2
    assert result.trace.duration_ms >= 0
    assert all(value >= 0 for value in result.trace.stage_duration_ms.values())
    assert [hit.document_id for hit in hits] == [
        configured_document_id,
        product_document_id,
    ]
    assert hits[0].chunk_id == configured_by_index[0]["id"]
    assert hits[0].chunk_index == 0
    assert hits[0].distance == 0.2
    assert hits[0].similarity == 0.9
    assert hits[0].sources == ["vector", "keywords"]
    assert hits[0].rerank_score == 1.0
    assert hits[0].content == "\n\n".join(
        configured_by_index[index]["content"] for index in range(3)
    )
    assert hits[1].chunk_id == product_chunk_id
    assert hits[1].distance == 0.05
    assert hits[1].similarity == 0.975


def upload_document(
    client,
    token,
    workspace_id,
    knowledge_base_id,
    filename,
    content,
    mime,
    staged=False,
    import_mode="document",
):
    """Two-step decoupled upload: attachment, then document creation."""
    attachment = client.post(
        knowledge_url(workspace_id, f"/{knowledge_base_id}/attachments"),
        headers=auth_headers(token),
        files={"file": (filename, content, mime)},
    )
    assert attachment.status_code == 201, attachment.text
    attachment_id = attachment.json()["id"]
    created = client.post(
        knowledge_url(workspace_id, f"/{knowledge_base_id}/documents"),
        headers=auth_headers(token),
        json={
            "attachment_ids": [attachment_id],
            "staged": staged,
            "import_mode": import_mode,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()[0]


async def assert_hierarchical_chunks_persisted(
    document_id: str,
) -> tuple[list[str], list[str], list[str]]:
    async with get_session_factory()() as db:
        chunks = list(
            await db.scalars(
                select(KnowledgeDocumentChunk)
                .where(KnowledgeDocumentChunk.document_id == document_id)
                .order_by(KnowledgeDocumentChunk.chunk_index)
            )
        )
        parents = list(
            await db.scalars(
                select(KnowledgeDocumentParentChunk)
                .where(KnowledgeDocumentParentChunk.document_id == document_id)
                .order_by(KnowledgeDocumentParentChunk.parent_index)
            )
        )
        parents_by_id = {parent.id: parent for parent in parents}
        assert [parent.title for parent in parents] == ["First", "Second"]
        assert [parent.meta["section_path"] for parent in parents] == [
            ["First"],
            ["First", "Second"],
        ]
        assert len(chunks) > len(parents)
        assert all(chunk.kind == "document" and chunk.meta == {} for chunk in chunks)
        assert all(chunk.parent_id in parents_by_id for chunk in chunks)
        assert all(
            parents_by_id[chunk.parent_id].content[
                chunk.start_offset : chunk.end_offset
            ]
            == chunk.content
            for chunk in chunks
        )
        search_texts = [
            "\n".join(
                [
                    "hierarchical-guide.md",
                    *parents_by_id[chunk.parent_id].meta["section_path"],
                    chunk.content,
                ]
            )
            for chunk in chunks
        ]
        assert [chunk.search_text for chunk in chunks] == search_texts
        return (
            [chunk.id for chunk in chunks],
            [parent.id for parent in parents],
            search_texts,
        )


async def assert_parent_scope_constraint(
    knowledge_base_id: str,
    document_id: str,
    foreign_document_id: str,
) -> None:
    parent_scope = next(
        constraint
        for constraint in KnowledgeDocumentChunk.__table__.foreign_key_constraints
        if constraint.name == "fk_knowledge_document_chunks_parent_scope"
    )
    assert tuple(parent_scope.column_keys) == (
        "workspace_id",
        "knowledge_base_id",
        "document_id",
        "parent_id",
    )

    async with get_session_factory()() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        document = await db.get(KnowledgeDocument, document_id)
        foreign_document = await db.get(KnowledgeDocument, foreign_document_id)
        assert knowledge_base is not None
        assert document is not None
        assert foreign_document is not None

        foreign_parent = KnowledgeDocumentParentChunk(
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
            document_id=foreign_document.id,
            parent_index=0,
            title="Foreign",
            content="foreign",
            char_count=7,
            meta={},
        )
        db.add(foreign_parent)
        await db.commit()
        await db.refresh(foreign_parent)

        db.add(
            KnowledgeDocumentChunk(
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                parent_id=foreign_parent.id,
                chunk_index=999999,
                start_offset=0,
                end_offset=7,
                content="foreign",
                char_count=7,
                token_count=1,
                status="preview",
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return
    raise AssertionError("Cross-document parent association was allowed.")


async def assert_hierarchical_retrieval(
    knowledge_base_id: str,
    document_id: str,
) -> None:
    original_query_vectors = knowledge_retrieval_application.query_vectors
    original_query_keyword_chunk_ids = knowledge_repository.query_keyword_chunk_ids
    original_build_reranker = knowledge_retrieval_application.build_reranker
    reranked_documents: list[str] = []
    reranker_calls = 0
    fallback_reranker_calls = 0
    invalid_reranker_calls = 0
    unexpected_reranker_calls = 0

    async with get_session_factory()() as db:
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        chunks = list(
            await db.scalars(
                select(KnowledgeDocumentChunk)
                .where(KnowledgeDocumentChunk.document_id == document_id)
                .order_by(KnowledgeDocumentChunk.chunk_index)
            )
        )
        parents = list(
            await db.scalars(
                select(KnowledgeDocumentParentChunk)
                .where(KnowledgeDocumentParentChunk.document_id == document_id)
                .order_by(KnowledgeDocumentParentChunk.parent_index)
            )
        )
        assert knowledge_base is not None
        first_children = [chunk for chunk in chunks if chunk.parent_id == parents[0].id]
        second_children = [chunk for chunk in chunks if chunk.parent_id == parents[1].id]
        assert len(first_children) >= 2
        assert second_children
        candidates = [first_children[0], first_children[1], second_children[0]]

        def fake_query_vectors(*args) -> list[VectorHit]:
            assert args[-3:-1] == ("hierarchical query", 10)
            assert args[-1] is None
            return [
                VectorHit(chunk_id=chunk.id, distance=index / 10)
                for index, chunk in enumerate(candidates, start=1)
            ]

        async def fake_query_keyword_chunk_ids(*_args) -> list[str]:
            return []

        class FakeReranker:
            def rerank(self, query: str, documents: list[str]) -> list[dict]:
                nonlocal reranker_calls
                reranker_calls += 1
                assert query == "hierarchical query"
                reranked_documents.extend(documents)
                return [
                    {"index": 2, "relevance_score": 1.0},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]

        knowledge_retrieval_application.query_vectors = fake_query_vectors
        knowledge_repository.query_keyword_chunk_ids = fake_query_keyword_chunk_ids
        knowledge_retrieval_application.build_reranker = (
            lambda *_args: FakeReranker()
        )
        try:
            result = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="hierarchical query", limit=2),
                test_settings(),
            )
            hits = result.hits

            class FailingReranker:
                def rerank(self, _query: str, _documents: list[str]) -> list[dict]:
                    nonlocal fallback_reranker_calls
                    fallback_reranker_calls += 1
                    raise knowledge_retrieval.ModelProviderError("reranker unavailable")

            knowledge_retrieval_application.build_reranker = (
                lambda *_args: FailingReranker()
            )
            fallback = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="hierarchical query", limit=2),
                test_settings(),
            )

            class InvalidReranker:
                def rerank(self, _query: str, _documents: list[str]) -> list[dict]:
                    nonlocal invalid_reranker_calls
                    invalid_reranker_calls += 1
                    return [
                        {"index": 2, "relevance_score": 1.0},
                        {"index": 0, "relevance_score": float("nan")},
                    ]

            knowledge_retrieval_application.build_reranker = (
                lambda *_args: InvalidReranker()
            )
            invalid = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="hierarchical query", limit=2),
                test_settings(),
            )

            class UnexpectedFailingReranker:
                def rerank(self, _query: str, _documents: list[str]) -> list[dict]:
                    nonlocal unexpected_reranker_calls
                    unexpected_reranker_calls += 1
                    raise RuntimeError("unexpected provider failure")

            knowledge_retrieval_application.build_reranker = (
                lambda *_args: UnexpectedFailingReranker()
            )
            unexpected = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="hierarchical query", limit=2),
                test_settings(),
            )
        finally:
            knowledge_retrieval_application.query_vectors = original_query_vectors
            knowledge_repository.query_keyword_chunk_ids = (
                original_query_keyword_chunk_ids
            )
            knowledge_retrieval_application.build_reranker = original_build_reranker

    assert reranker_calls == 1
    assert fallback_reranker_calls == 1
    assert invalid_reranker_calls == 1
    assert unexpected_reranker_calls == 1
    assert result.trace.rerank_status == "applied"
    assert hits[0].rerank_score == 1.0
    assert fallback.trace.rerank_status == "fallback"
    assert fallback.hits
    assert [hit.chunk_id for hit in fallback.hits] == [
        first_children[0].id,
        second_children[0].id,
    ]
    assert invalid.trace.rerank_status == "applied"
    assert [hit.chunk_id for hit in invalid.hits] == [
        second_children[0].id,
        first_children[0].id,
    ]
    assert unexpected.trace.rerank_status == "fallback"
    assert [hit.chunk_id for hit in unexpected.hits] == [
        first_children[0].id,
        second_children[0].id,
    ]
    assert reranked_documents == [
        chunk.search_text or chunk.content for chunk in candidates
    ]
    assert [hit.parent_id for hit in hits] == [parents[1].id, parents[0].id]
    assert hits[0].chunk_id == second_children[0].id
    assert hits[1].chunk_id == first_children[1].id
    assert len({hit.parent_id for hit in hits}) == len(hits)
    assert all(
        len(hit.content) <= knowledge_retrieval.MAX_EVIDENCE_CONTENT_CHARS
        for hit in hits
    )
    assert "SECOND" in hits[0].content and "FIRST" not in hits[0].content
    assert "FIRST" in hits[1].content and "SECOND" not in hits[1].content
    assert len(hits[1].content) > 2000


async def assert_one_hop_reference_retrieval(
    knowledge_base_id: str,
    source_document_id: str,
    target_document_id: str,
) -> None:
    async with get_session_factory()() as db:
        source_chunk = await db.scalar(
            select(KnowledgeDocumentChunk).where(
                KnowledgeDocumentChunk.document_id == source_document_id
            )
        )
        target_chunk = await db.scalar(
            select(KnowledgeDocumentChunk).where(
                KnowledgeDocumentChunk.document_id == target_document_id
            )
        )
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        assert source_chunk is not None
        assert target_chunk is not None
        assert knowledge_base is not None

        original_query_vectors = knowledge_retrieval_application.query_vectors
        original_list_references = (
            knowledge_retrieval_application.knowledge_reference_repository
            .list_resolved_references_for_chunks
        )
        reference_calls = 0

        def fake_query_vectors(
            _settings,
            selected_knowledge_base_id,
            _embedding_model,
            query,
            limit,
            _score_threshold=None,
            document_ids=None,
        ):
            assert selected_knowledge_base_id == knowledge_base_id
            assert query == "release overview"
            assert limit == 10
            if document_ids is None:
                return [VectorHit(chunk_id=source_chunk.id, distance=0.05)]
            assert document_ids == {target_document_id}
            return [VectorHit(chunk_id=target_chunk.id, distance=0.1)]

        knowledge_retrieval_application.query_vectors = fake_query_vectors
        try:
            enabled = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(
                    query="release overview",
                    limit=2,
                    search_mode="embedding",
                    include_references=True,
                ),
                test_settings(),
            )
            disabled = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(
                    query="release overview",
                    limit=2,
                    search_mode="embedding",
                    include_references=False,
                ),
                test_settings(),
            )

            async def capped_references(
                _db,
                _knowledge_base,
                source_chunk_ids,
                limit,
            ):
                nonlocal reference_calls
                reference_calls += 1
                assert source_chunk_ids == [source_chunk.id]
                assert limit == 100
                return [
                    SimpleNamespace(
                        target_document_id=f"unretrievable-{index}",
                        target_parent_id=None,
                    )
                    for index in range(8)
                ] + [
                    SimpleNamespace(
                        target_document_id=target_document_id,
                        target_parent_id=None,
                    )
                ]

            (
                knowledge_retrieval_application.knowledge_reference_repository
                .list_resolved_references_for_chunks
            ) = capped_references
            capped = await knowledge_retrieval_application.retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(
                    query="release overview",
                    limit=2,
                    search_mode="embedding",
                    include_references=True,
                ),
                test_settings(),
            )
        finally:
            knowledge_retrieval_application.query_vectors = original_query_vectors
            (
                knowledge_retrieval_application.knowledge_reference_repository
                .list_resolved_references_for_chunks
            ) = original_list_references

    assert [hit.document_filename for hit in enabled.hits] == [
        "overview.md",
        "rollback.md",
    ]
    assert enabled.hits[0].sources == ["vector"]
    assert enabled.hits[0].reference_hops == 0
    assert enabled.hits[1].sources == ["reference"]
    assert enabled.hits[1].reference_hops == 1
    assert enabled.hits[1].parent_title == "Rollback Procedure"
    assert enabled.trace.reference_candidates >= 1
    assert [hit.document_filename for hit in disabled.hits] == ["overview.md"]
    assert disabled.trace.reference_candidates == 0
    assert [hit.document_filename for hit in capped.hits] == [
        "overview.md",
        "rollback.md",
    ]
    assert reference_calls == 1


async def assert_document_open_tasks_failed(
    knowledge_base_id: str,
    document_id: str,
) -> None:
    async with get_session_factory()() as db:
        tasks = await db.scalars(
            select(KnowledgeTask).where(KnowledgeTask.document_id == document_id)
        )
        task_list = list(tasks)
        assert task_list, "expected open tasks to exist"
        open_tasks = [
            task
            for task in task_list
            if task.status in ("queued", "running")
        ]
        assert not open_tasks, [task.status for task in open_tasks]
        assert any(
            task.last_error == "Document deleted before task completed."
            for task in task_list
        )


def main() -> None:
    test_keyword_query_does_not_require_embedding_model()
    assert_vector_store_mmr_and_metadata()
    hierarchical_drafts = build_hierarchical_chunks(
        "# One\n\n```text\n# not a heading\n```\n\nBody\n\n# Two\n\nMore",
        chunk_size=20,
        overlap=5,
    )
    assert [parent.title for parent in hierarchical_drafts.parents] == ["One", "Two"]
    assert [parent.section_path for parent in hierarchical_drafts.parents] == [
        ["One"],
        ["Two"],
    ]
    assert all(
        hierarchical_drafts.parents[chunk.parent_index].content[
            chunk.start_offset : chunk.end_offset
        ]
        == chunk.content
        for chunk in hierarchical_drafts.children
    )
    assert split_text("甲。乙。丙。丁。", chunk_size=4, overlap=0, separator="。") == [
        "甲。乙。",
        "丙。丁。",
    ]
    paragraph_text = clean_text(
        "甲\n\n乙\n\n丙",
        ["remove_empty_lines"],
        preserve_empty_lines=True,
    )
    assert split_text(paragraph_text, chunk_size=3, overlap=0, separator="\n\n") == [
        "甲",
        "乙",
        "丙",
    ]

    with test_client() as client, model_test_server() as model_base_url:
        admin_token, default_workspace_id = activate_admin(client)

        alice_id, alice_temp_password = create_workspace_user(
            client,
            admin_token,
            default_workspace_id,
            "alice",
        )
        bob_id, bob_temp_password = create_workspace_user(
            client,
            admin_token,
            default_workspace_id,
            "bob",
        )
        alice_token = activate_user(client, "alice", alice_temp_password, MEMBER_PASSWORD)
        bob_token = activate_user(client, "bob", bob_temp_password, MEMBER_PASSWORD)

        research_admin_id, research_token = create_active_user(
            client,
            admin_token,
            "research-admin",
        )
        created_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "description": "研究工作空间",
                "admin_user_id": research_admin_id,
            },
        )
        assert created_workspace.status_code == 201, created_workspace.text
        research_workspace_id = created_workspace.json()["workspace"]["id"]

        embedding_model = client.post(
            models_url(default_workspace_id),
            headers=auth_headers(admin_token),
            json={
                **model_payload(model_base_url),
                "name": "Knowledge Embedding",
                "provider": "model_openai_provider",
                "provider_type": "openai_compatible",
                "model_type": "EMBEDDING",
                "model_name": "text-embedding-3-small",
            },
        )
        assert embedding_model.status_code == 201, embedding_model.text
        embedding_model_id = embedding_model.json()["id"]

        reranker_model = client.post(
            models_url(default_workspace_id),
            headers=auth_headers(admin_token),
            json={
                **model_payload(model_base_url),
                "name": "Knowledge Reranker",
                "provider": "model_custom_provider",
                "provider_type": "openai_compatible",
                "model_type": "RERANKER",
                "model_name": "custom-reranker",
            },
        )
        assert reranker_model.status_code == 201, reranker_model.text
        reranker_model_id = reranker_model.json()["id"]

        knowledge_base = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={
                "name": "Product Docs",
                "description": "Internal product answers",
                "embedding_model_id": None,
                "reranker_model_id": reranker_model_id,
            },
        )
        assert knowledge_base.status_code == 201, knowledge_base.text
        knowledge_base_id = knowledge_base.json()["id"]
        assert knowledge_base.json()["permission"] == "edit"
        assert knowledge_base.json()["created_by_user_id"] == alice_id
        assert knowledge_base.json()["embedding_model_id"] == embedding_model_id
        assert knowledge_base.json()["reranker_model_id"] == reranker_model_id
        asyncio.run(clear_knowledge_base_embedding_model(knowledge_base_id))

        bob_owned_knowledge_base = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(bob_token),
            json={"name": "Bob Notes", "description": "Bob private notes"},
        )
        assert bob_owned_knowledge_base.status_code == 201, bob_owned_knowledge_base.text
        alice_newer_knowledge_base = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={"name": "Alice Notes", "description": "Alice private notes"},
        )
        assert alice_newer_knowledge_base.status_code == 201, alice_newer_knowledge_base.text
        bob_first_page = client.get(
            knowledge_url(default_workspace_id) + "?limit=1&offset=0",
            headers=auth_headers(bob_token),
        )
        assert bob_first_page.status_code == 200, bob_first_page.text
        assert [item["id"] for item in bob_first_page.json()] == [
            bob_owned_knowledge_base.json()["id"]
        ]

        model_test = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/model-test"),
            headers=auth_headers(alice_token),
            json={"query": "Hello", "documents": ["Hello"]},
        )
        assert model_test.status_code == 200, model_test.text
        assert model_test.json() == {
            "embedding_model_id": embedding_model_id,
            "embedding_dimensions": 1,
            "reranker_model_id": reranker_model_id,
            "reranker_results": 1,
        }
        assert ModelTestHandler.calls[-2]["path"] == "/v1/embeddings"
        assert ModelTestHandler.calls[-1]["path"] == "/v1/rerank"

        bob_list = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(bob_token),
        )
        assert bob_list.status_code == 200, bob_list.text
        assert knowledge_base_id not in {item["id"] for item in bob_list.json()}

        denied_cross_workspace = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(research_token),
        )
        assert denied_cross_workspace.status_code == 404, denied_cross_workspace.text

        view_grant = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{bob_id}"),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert view_grant.status_code == 200, view_grant.text
        assert view_grant.json()["permission"] == "view"
        asyncio.run(assert_cross_workspace_permission_denied(default_workspace_id, knowledge_base_id))

        bob_list_after_grant = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(bob_token),
        )
        assert bob_list_after_grant.status_code == 200, bob_list_after_grant.text
        bob_visible_kb = next(
            item
            for item in bob_list_after_grant.json()
            if item["id"] == knowledge_base_id
        )
        assert bob_visible_kb["permission"] == "view"

        bob_get = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert bob_get.status_code == 200, bob_get.text
        assert bob_get.json()["permission"] == "view"

        bob_model_test_denied = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/model-test"),
            headers=auth_headers(bob_token),
            json={"query": "Hello", "documents": ["Hello"]},
        )
        assert bob_model_test_denied.status_code == 403, bob_model_test_denied.text

        bob_upload_denied = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(bob_token),
            files={"file": ("denied.txt", b"nope", "text/plain")},
        )
        assert bob_upload_denied.status_code == 403, bob_upload_denied.text

        document_content = b"Hello from product docs"
        uploaded_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "product-guide.txt",
            document_content,
            "text/plain",
        )
        document_payload = uploaded_document
        document_id = document_payload["id"]
        assert document_payload["filename"] == "product-guide.txt"
        assert document_payload["status"] == "uploaded"
        assert document_payload["size_bytes"] == len(document_content)
        asyncio.run(assert_document_saved(document_id, document_content))

        bob_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(bob_token),
        )
        assert bob_documents.status_code == 200, bob_documents.text
        assert [item["id"] for item in bob_documents.json()] == [document_id]

        parsed_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{document_id}/parse"),
            headers=auth_headers(alice_token),
            json={"auto_index": True},
        )
        assert parsed_document.status_code == 202, parsed_document.text

        document_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert document_chunks.status_code == 200, document_chunks.text
        assert [chunk["content"] for chunk in document_chunks.json()] == ["Hello from product docs"]
        assert "search_text" not in document_chunks.json()[0]
        assert document_chunks.json()[0]["status"] == "indexed"
        assert document_chunks.json()[0]["vector_id"] == document_chunks.json()[0]["id"]
        asyncio.run(assert_knowledge_base_embedding_model(knowledge_base_id, embedding_model_id))
        asyncio.run(assert_query_skips_stale_vector(knowledge_base_id, document_chunks.json()[0]["id"]))

        knowledge_query = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/query"),
            headers=auth_headers(bob_token),
            json={"query": "product docs", "limit": 1},
        )
        assert knowledge_query.status_code == 200, knowledge_query.text
        assert isinstance(knowledge_query.json(), list)
        assert knowledge_query.json()[0]["document_id"] == document_id
        assert knowledge_query.json()[0]["content"] == "Hello from product docs"
        inspected_query = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/query/inspect",
            ),
            headers=auth_headers(bob_token),
            json={"query": "product docs", "limit": 1},
        )
        assert inspected_query.status_code == 200, inspected_query.text
        inspected_payload = inspected_query.json()
        assert inspected_payload["hits"] == knowledge_query.json()
        assert inspected_payload["trace"]["returned_hits"] == 1
        assert inspected_payload["trace"]["rerank_status"] == "applied"
        assert "query" not in inspected_payload["trace"]
        assert all("hash" not in key for key in inspected_payload["trace"])

        configured_content = ("Alpha   beta " * 12 + "Gamma   delta " * 12).encode()
        configured_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "configured-guide.txt",
            configured_content,
            "text/plain",
        )
        configured_document_id = configured_document["id"]
        assert configured_document["status"] == "uploaded"
        configured_empty_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{configured_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert configured_empty_chunks.status_code == 200, configured_empty_chunks.text
        assert configured_empty_chunks.json() == []

        configured_parse = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{configured_document_id}/parse"),
            headers=auth_headers(alice_token),
            json={
                "chunk_size": 100,
                "chunk_overlap": 0,
                "cleaning_rules": ["collapse_spaces"],
                "auto_index": False,
            },
        )
        assert configured_parse.status_code == 202, configured_parse.text
        configured_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{configured_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert configured_chunks.status_code == 200, configured_chunks.text
        assert len(configured_chunks.json()) == 3
        assert all("  " not in chunk["content"] for chunk in configured_chunks.json())
        assert all(chunk["char_count"] <= 100 for chunk in configured_chunks.json())
        assert {chunk["status"] for chunk in configured_chunks.json()} == {"preview"}
        assert {chunk["vector_id"] for chunk in configured_chunks.json()} == {None}

        knowledge_card = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
        )
        assert knowledge_card.status_code == 200, knowledge_card.text
        knowledge_card_payload = next(
            item for item in knowledge_card.json() if item["id"] == knowledge_base_id
        )
        assert knowledge_card_payload["document_count"] == 2
        assert knowledge_card_payload["char_count"] == sum(
            chunk["char_count"]
            for chunk in document_chunks.json() + configured_chunks.json()
        )

        visible_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert visible_documents.status_code == 200, visible_documents.text
        assert configured_document_id in {
            item["id"] for item in visible_documents.json()
        }

        staged_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            params={"include_staged": True},
        )
        assert staged_documents.status_code == 200, staged_documents.text
        assert configured_document_id in {item["id"] for item in staged_documents.json()}

        bob_staged_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(bob_token),
            params={"include_staged": True},
        )
        assert bob_staged_documents.status_code == 403, bob_staged_documents.text

        configured_index = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{configured_document_id}/index"),
            headers=auth_headers(alice_token),
        )
        assert configured_index.status_code == 202, configured_index.text
        configured_indexed_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{configured_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert configured_indexed_chunks.status_code == 200, configured_indexed_chunks.text
        assert {chunk["status"] for chunk in configured_indexed_chunks.json()} == {"indexed"}
        asyncio.run(
            assert_query_aggregates_hybrid_hits(
                knowledge_base_id,
                document_id,
                document_chunks.json()[0]["id"],
                configured_document_id,
                configured_indexed_chunks.json(),
            )
        )
        visible_documents_after_index = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert (
            visible_documents_after_index.status_code == 200
        ), visible_documents_after_index.text
        assert configured_document_id in {
            item["id"] for item in visible_documents_after_index.json()
        }
        configured_deleted = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{configured_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert configured_deleted.status_code == 204, configured_deleted.text
        asyncio.run(assert_document_deleted(configured_document_id))

        qa_csv = b"question,answer,source\nWhat is SLA?,99.9%,runbook\n"
        csv_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "faq.csv",
            qa_csv,
            "text/csv",
        )
        assert csv_document["meta"]["import_mode"] == "document"
        csv_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{csv_document['id']}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"auto_index": False},
        )
        assert csv_parse.status_code == 202, csv_parse.text
        csv_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{csv_document['id']}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert csv_chunks.status_code == 200, csv_chunks.text
        assert {chunk["kind"] for chunk in csv_chunks.json()} == {"document"}

        qa_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "faq.csv",
            qa_csv,
            "text/csv",
            import_mode="qa",
        )
        assert qa_document["meta"]["import_mode"] == "qa"
        qa_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{qa_document['id']}/parse",
            ),
            headers=auth_headers(alice_token),
            json={
                "strategy": "hierarchical",
                "chunk_size": 100,
                "chunk_overlap": 99,
                "split_separator": ".",
                "cleaning_rules": ["collapse_spaces"],
                "auto_index": False,
            },
        )
        assert qa_parse.status_code == 202, qa_parse.text
        qa_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{qa_document['id']}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert qa_chunks.status_code == 200, qa_chunks.text
        assert qa_chunks.json() == [
            {
                **qa_chunks.json()[0],
                "content": "99.9%",
                "kind": "qa",
                "question": "What is SLA?",
                "source": "runbook",
                "row_number": 2,
                "parent_id": None,
                "parent_title": None,
                "parent_index": None,
            }
        ]
        assert qa_chunks.json()[0]["char_count"] == len("99.9%")

        for imported_document in (csv_document, qa_document):
            deleted_import = client.delete(
                knowledge_url(
                    default_workspace_id,
                    f"/{knowledge_base_id}/documents/{imported_document['id']}",
                ),
                headers=auth_headers(alice_token),
            )
            assert deleted_import.status_code == 204, deleted_import.text
            asyncio.run(assert_document_deleted(imported_document["id"]))

        asyncio.run(
            set_document_chunk_search_text(document_id, "Hello from product docs")
        )
        rebuild_embedding_calls_before = len(ModelTestHandler.calls)
        rebuild_task = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert rebuild_task.status_code == 202, rebuild_task.text
        assert rebuild_task.json()["task_type"] == "rebuild_index"
        assert rebuild_task.json()["total_items"] == 1
        assert rebuild_task.json()["processed_items"] == 0
        assert asyncio.run(document_chunk_search_texts(document_id)) == [
            "product-guide.txt\nHello from product docs"
        ]
        rebuild_embedding_calls = [
            call
            for call in ModelTestHandler.calls[rebuild_embedding_calls_before:]
            if call["path"] == "/v1/embeddings"
        ]
        assert rebuild_embedding_calls[-1]["body"]["input"] == [
            "product-guide.txt\nHello from product docs"
        ]

        ModelTestHandler.fail_next = True
        failed_rebuild_task = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert failed_rebuild_task.status_code == 202, failed_rebuild_task.text
        asyncio.run(
            assert_rebuild_task_failed_without_document_status_change(
                failed_rebuild_task.json()["id"],
                document_id,
            )
        )
        asyncio.run(enqueue_recoverable_rebuild_task(knowledge_base_id, "alice"))
        concurrent_parse = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{document_id}/parse"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_parse.status_code == 409, concurrent_parse.text
        asyncio.run(recover_knowledge_tasks(test_settings()))

        knowledge_tasks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/tasks"),
            headers=auth_headers(alice_token),
        )
        assert knowledge_tasks.status_code == 200, knowledge_tasks.text
        task_statuses = {(item["task_type"], item["status"]) for item in knowledge_tasks.json()}
        assert ("parse", "succeeded") in task_statuses
        assert ("index", "succeeded") in task_statuses
        assert ("rebuild_index", "succeeded") in task_statuses
        task_progress = {
            item["task_type"]: (item["total_items"], item["processed_items"])
            for item in knowledge_tasks.json()
        }
        assert task_progress["parse"] == (1, 1)
        assert task_progress["index"] == (1, 1)
        assert task_progress["rebuild_index"] == (1, 1)

        original_enqueue_knowledge_task = knowledge_application.enqueue_knowledge_task

        async def fail_knowledge_task_dispatch(task_id: str, _settings) -> None:
            await mark_task_dispatch_failed(task_id)
            raise RuntimeError("queue unavailable")

        knowledge_application.enqueue_knowledge_task = fail_knowledge_task_dispatch
        try:
            degraded_parse = client.post(
                knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{document_id}/parse"),
                headers=auth_headers(alice_token),
            )
        finally:
            knowledge_application.enqueue_knowledge_task = original_enqueue_knowledge_task

        assert degraded_parse.status_code == 503, degraded_parse.text

        queued_later_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "queued-later.txt",
            b"Stored before dispatch",
            "text/plain",
        )
        queued_later_document_id = queued_later_document["id"]

        pdf_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "pdf-guide.pdf",
            pdf_bytes("Hello from PDF docs"),
            "application/pdf",
        )
        pdf_document_id = pdf_document["id"]
        parsed_pdf = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{pdf_document_id}/parse"),
            headers=auth_headers(alice_token),
            json={"auto_index": True},
        )
        assert parsed_pdf.status_code == 202, parsed_pdf.text

        pdf_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{pdf_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert pdf_chunks.status_code == 200, pdf_chunks.text
        assert pdf_chunks.json()[0]["content"] == "# pdf-guide\n\nHello from PDF docs"

        docx_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "word-guide.docx",
            docx_bytes("Hello from DOCX docs"),
            DOCX_MIME,
        )
        docx_document_id = docx_document["id"]
        parsed_docx = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{docx_document_id}/parse"),
            headers=auth_headers(alice_token),
            json={"auto_index": True},
        )
        assert parsed_docx.status_code == 202, parsed_docx.text

        docx_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{docx_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert docx_chunks.status_code == 200, docx_chunks.text
        assert docx_chunks.json()[0]["content"] == "Hello from DOCX docs"

        pdf_query = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/query"),
            headers=auth_headers(alice_token),
            json={"query": "PDF docs", "limit": 5},
        )
        assert pdf_query.status_code == 200, pdf_query.text
        assert pdf_document_id in {item["document_id"] for item in pdf_query.json()}

        recovery_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "recovery-guide.txt",
            b"Recovered on startup",
            "text/plain",
        )
        recovery_document_id = recovery_document["id"]
        asyncio.run(
            enqueue_recoverable_parse_task(
                knowledge_base_id,
                recovery_document_id,
                "alice",
            )
        )
        asyncio.run(recover_knowledge_tasks(test_settings()))
        recovery_tasks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{recovery_document_id}/tasks"),
            headers=auth_headers(alice_token),
        )
        assert recovery_tasks.status_code == 200, recovery_tasks.text
        asyncio.run(assert_task_succeeded(recovery_tasks.json()[0]["id"], recovery_document_id, 1))
        recovery_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{recovery_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert recovery_chunks.status_code == 200, recovery_chunks.text
        assert recovery_chunks.json()[0]["content"] == "Recovered on startup"
        assert recovery_chunks.json()[0]["status"] == "indexed"

        rebuild_auto_indexed = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert rebuild_auto_indexed.status_code == 202, rebuild_auto_indexed.text
        assert rebuild_auto_indexed.json()["total_items"] == 4
        recovery_chunks_after_rebuild = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{recovery_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert recovery_chunks_after_rebuild.status_code == 200, recovery_chunks_after_rebuild.text
        assert recovery_chunks_after_rebuild.json()[0]["status"] == "indexed"

        split_content = b" Legacy split content\n\nSecond paragraph "
        split_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "split-guide.txt",
            split_content,
            "text/plain",
        )
        split_document_id = split_document["id"]
        assert split_document["filename"] == "split-guide.txt"
        asyncio.run(assert_document_saved(split_document_id, split_content))

        asyncio.run(
            enqueue_recoverable_parse_task(
                knowledge_base_id,
                recovery_document_id,
                "alice",
            )
        )
        concurrent_index = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{recovery_document_id}/index"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_index.status_code == 409, concurrent_index.text
        concurrent_rebuild = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_rebuild.status_code == 409, concurrent_rebuild.text
        concurrent_delete_knowledge_base = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_delete_knowledge_base.status_code == 409, concurrent_delete_knowledge_base.text
        concurrent_delete_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{recovery_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_delete_document.status_code == 204, concurrent_delete_document.text
        asyncio.run(
            assert_document_open_tasks_failed(
                knowledge_base_id,
                recovery_document_id,
            )
        )
        asyncio.run(recover_knowledge_tasks(test_settings()))

        failed_parse_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "unsupported.bin",
            b"\x00\x01\x02",
            "application/octet-stream",
        )
        failed_parse_document_id = failed_parse_document["id"]
        failed_parse_enqueue = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{failed_parse_document_id}/parse"),
            headers=auth_headers(alice_token),
        )
        assert failed_parse_enqueue.status_code == 202, failed_parse_enqueue.text
        failed_parse_tasks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{failed_parse_document_id}/tasks"),
            headers=auth_headers(alice_token),
        )
        assert failed_parse_tasks.status_code == 200, failed_parse_tasks.text
        failed_parse_task_id = failed_parse_tasks.json()[0]["id"]
        asyncio.run(assert_parse_task_failed(failed_parse_task_id, failed_parse_document_id))
        asyncio.run(
            replace_document_file_with_text(
                failed_parse_document_id,
                b"Retryable parse document",
                "retryable.txt",
            )
        )

        asyncio.run(enqueue_recoverable_rebuild_task(knowledge_base_id, "alice"))
        concurrent_retry_parse = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/tasks/{failed_parse_task_id}/retry"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_retry_parse.status_code == 409, concurrent_retry_parse.text
        asyncio.run(recover_knowledge_tasks(test_settings()))

        retried_parse_task = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/tasks/{failed_parse_task_id}/retry"),
            headers=auth_headers(alice_token),
        )
        assert retried_parse_task.status_code == 202, retried_parse_task.text
        assert retried_parse_task.json()["id"] == failed_parse_task_id
        asyncio.run(assert_task_succeeded(failed_parse_task_id, failed_parse_document_id, 2))

        retry_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "retry-guide.txt",
            b"Retryable embedding document",
            "text/plain",
        )
        retry_document_id = retry_document["id"]
        retry_parse = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{retry_document_id}/parse"),
            headers=auth_headers(alice_token),
            json={"auto_index": False},
        )
        assert retry_parse.status_code == 202, retry_parse.text

        ModelTestHandler.fail_next = True
        failed_index_task = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{retry_document_id}/index"),
            headers=auth_headers(alice_token),
        )
        assert failed_index_task.status_code == 202, failed_index_task.text
        failed_task_id = failed_index_task.json()["id"]
        asyncio.run(assert_task_failed(failed_task_id, retry_document_id))

        retried_index_task = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/tasks/{failed_task_id}/retry"),
            headers=auth_headers(alice_token),
        )
        assert retried_index_task.status_code == 202, retried_index_task.text
        assert retried_index_task.json()["id"] == failed_task_id
        asyncio.run(assert_task_succeeded(failed_task_id, retry_document_id, 2))

        bob_edit_denied = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"description": "Bob edit attempt"},
        )
        assert bob_edit_denied.status_code == 403, bob_edit_denied.text

        edit_grant = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{bob_id}"),
            headers=auth_headers(alice_token),
            json={"permission": "edit"},
        )
        assert edit_grant.status_code == 200, edit_grant.text

        bob_edit = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"description": "Bob can now edit"},
        )
        assert bob_edit.status_code == 200, bob_edit.text
        assert bob_edit.json()["description"] == "Bob can now edit"

        bob_delete_denied = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert bob_delete_denied.status_code == 403, bob_delete_denied.text

        permissions = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions"),
            headers=auth_headers(alice_token),
        )
        assert permissions.status_code == 200, permissions.text
        assert [(item["user"]["username"], item["permission"]) for item in permissions.json()] == [
            ("bob", "edit")
        ]

        revoked = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{bob_id}"),
            headers=auth_headers(alice_token),
        )
        assert revoked.status_code == 204, revoked.text
        bob_after_revoke = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(bob_token),
        )
        assert bob_after_revoke.status_code == 200, bob_after_revoke.text
        assert knowledge_base_id not in {
            item["id"] for item in bob_after_revoke.json()
        }

        bob_get_denied = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert bob_get_denied.status_code == 403, bob_get_denied.text

        deleted_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_document.status_code == 204, deleted_document.text
        asyncio.run(assert_document_deleted(document_id))

        deleted_retry_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{retry_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_retry_document.status_code == 204, deleted_retry_document.text
        asyncio.run(assert_document_deleted(retry_document_id))

        deleted_failed_parse_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{failed_parse_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_failed_parse_document.status_code == 204, deleted_failed_parse_document.text
        asyncio.run(assert_document_deleted(failed_parse_document_id))

        deleted_pdf_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{pdf_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_pdf_document.status_code == 204, deleted_pdf_document.text
        asyncio.run(assert_document_deleted(pdf_document_id))

        deleted_docx_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{docx_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_docx_document.status_code == 204, deleted_docx_document.text
        asyncio.run(assert_document_deleted(docx_document_id))

        deleted_split_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{split_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_split_document.status_code == 204, deleted_split_document.text
        asyncio.run(assert_document_deleted(split_document_id))

        deleted_queued_later_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{queued_later_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_queued_later_document.status_code == 204, deleted_queued_later_document.text
        asyncio.run(assert_document_deleted(queued_later_document_id))

        empty_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert empty_documents.status_code == 200, empty_documents.text
        assert empty_documents.json() == []

        cancel_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "cancel-guide.txt",
            b"Cancel flow document",
            "text/plain",
        )
        cancel_document_id = cancel_document["id"]
        asyncio.run(
            enqueue_recoverable_parse_task(
                knowledge_base_id,
                cancel_document_id,
                "alice",
            )
        )
        cancel_tasks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{cancel_document_id}/tasks"),
            headers=auth_headers(alice_token),
        )
        assert cancel_tasks.status_code == 200, cancel_tasks.text
        cancel_task_id = cancel_tasks.json()[0]["id"]
        asyncio.run(
            assert_deleted_document_not_resurrected_by_parse_task(
                knowledge_base_id,
                cancel_document_id,
                cancel_task_id,
            )
        )

        preview_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "preview-guide.txt",
            b"Preview synchronously",
            "text/plain",
            staged=True,
        )
        preview_document_id = preview_document["id"]
        assert preview_document["status"] == "uploaded"

        preview_parse = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{preview_document_id}/parse"),
            headers=auth_headers(alice_token),
            json={
                "chunk_size": 100,
                "chunk_overlap": 0,
                "split_separator": "\n",
                "cleaning_rules": [],
                "auto_index": False,
            },
        )
        assert preview_parse.status_code == 202, preview_parse.text

        preview_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{preview_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert preview_chunks.status_code == 200, preview_chunks.text
        assert [chunk["content"] for chunk in preview_chunks.json()] == [
            "Preview synchronously"
        ]

        preview_tasks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{preview_document_id}/tasks"),
            headers=auth_headers(alice_token),
        )
        assert preview_tasks.status_code == 200, preview_tasks.text
        assert preview_tasks.json()[0]["status"] == "succeeded"

        visible_preview_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert visible_preview_documents.status_code == 200, visible_preview_documents.text
        assert preview_document_id not in {
            item["id"] for item in visible_preview_documents.json()
        }

        staged_knowledge_card = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
        )
        assert staged_knowledge_card.status_code == 200, staged_knowledge_card.text
        staged_knowledge_card_payload = next(
            item
            for item in staged_knowledge_card.json()
            if item["id"] == knowledge_base_id
        )
        assert staged_knowledge_card_payload["document_count"] == 0
        assert staged_knowledge_card_payload["char_count"] == 0

        preview_document_list = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents?include_staged=true"),
            headers=auth_headers(alice_token),
        )
        assert preview_document_list.status_code == 200, preview_document_list.text
        preview_status = next(
            item["status"]
            for item in preview_document_list.json()
            if item["id"] == preview_document_id
        )
        assert preview_status == "parsed"

        preview_index = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{preview_document_id}/index",
            ),
            headers=auth_headers(alice_token),
        )
        assert preview_index.status_code == 202, preview_index.text
        visible_indexed_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert visible_indexed_documents.status_code == 200, visible_indexed_documents.text
        assert preview_document_id in {
            item["id"] for item in visible_indexed_documents.json()
        }
        imported_knowledge_card = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
        )
        assert imported_knowledge_card.status_code == 200, imported_knowledge_card.text
        imported_knowledge_card_payload = next(
            item
            for item in imported_knowledge_card.json()
            if item["id"] == knowledge_base_id
        )
        assert imported_knowledge_card_payload["document_count"] == 1
        assert imported_knowledge_card_payload["char_count"] == len(
            "Preview synchronously"
        )

        first_parent_body = "\n\n".join(
            f"FIRST paragraph {index} " + "alpha " * 40
            for index in range(15)
        )
        second_parent_body = "SECOND " * 80
        hierarchical_content = (
            f"# First\n\n{first_parent_body}\n\n## Second\n\n{second_parent_body}"
        ).encode()
        hierarchical_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "hierarchical-guide.md",
            hierarchical_content,
            "text/markdown",
        )
        hierarchical_document_id = hierarchical_document["id"]
        hierarchical_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{hierarchical_document_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={
                "strategy": "hierarchical",
                "chunk_size": 400,
                "chunk_overlap": 50,
                "split_separator": "\n\n",
                "cleaning_rules": [],
                "auto_index": False,
            },
        )
        assert hierarchical_parse.status_code == 202, hierarchical_parse.text

        hierarchical_preview = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{hierarchical_document_id}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert hierarchical_preview.status_code == 200, hierarchical_preview.text
        assert {chunk["parent_title"] for chunk in hierarchical_preview.json()} == {
            "First",
            "Second",
        }
        assert all(
            chunk["parent_id"]
            and chunk["start_offset"] is not None
            and chunk["end_offset"] is not None
            for chunk in hierarchical_preview.json()
        )
        (
            hierarchical_child_ids,
            hierarchical_parent_ids,
            hierarchical_search_texts,
        ) = asyncio.run(
            assert_hierarchical_chunks_persisted(hierarchical_document_id)
        )

        hierarchical_embedding_calls_before = len(ModelTestHandler.calls)
        hierarchical_index = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{hierarchical_document_id}/index",
            ),
            headers=auth_headers(alice_token),
        )
        assert hierarchical_index.status_code == 202, hierarchical_index.text
        hierarchical_embedding_calls = [
            call
            for call in ModelTestHandler.calls[hierarchical_embedding_calls_before:]
            if call["path"] == "/v1/embeddings"
        ]
        assert [
            value
            for call in hierarchical_embedding_calls
            for value in call["body"]["input"]
        ] == hierarchical_search_texts
        vector_client = knowledge_vector_store._client(test_settings())
        stored_hierarchical_ids = {
            str(point.id)
            for point in vector_client.retrieve(
                knowledge_vector_store.vector_collection_name(knowledge_base_id),
                ids=hierarchical_child_ids + hierarchical_parent_ids,
            )
        }
        assert stored_hierarchical_ids == set(hierarchical_child_ids)
        asyncio.run(
            assert_hierarchical_retrieval(
                knowledge_base_id,
                hierarchical_document_id,
            )
        )

        foreign_reference_target = upload_document(
            client,
            bob_token,
            default_workspace_id,
            bob_owned_knowledge_base.json()["id"],
            "rollback.md",
            b"# Rollback\n\nForeign knowledge base target.",
            "text/markdown",
        )
        foreign_reference_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{bob_owned_knowledge_base.json()['id']}/documents/"
                f"{foreign_reference_target['id']}/parse",
            ),
            headers=auth_headers(bob_token),
            json={"strategy": "hierarchical", "auto_index": False},
        )
        assert foreign_reference_parse.status_code == 202, foreign_reference_parse.text

        reference_source = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "overview.md",
            b"Release overview. [Rollback](rollback.md#rollback-procedure).",
            "text/markdown",
        )
        reference_source_id = reference_source["id"]
        reference_source_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{reference_source_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"auto_index": False},
        )
        assert reference_source_parse.status_code == 202, reference_source_parse.text
        asyncio.run(assert_document_reference_target(reference_source_id, None))

        reference_target = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "rollback.md",
            b"# Rollback Procedure\n\nUse the safe rollback procedure.",
            "text/markdown",
        )
        reference_target_id = reference_target["id"]
        reference_target_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{reference_target_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"strategy": "hierarchical", "auto_index": False},
        )
        assert reference_target_parse.status_code == 202, reference_target_parse.text
        asyncio.run(
            assert_document_reference_target(
                reference_source_id,
                reference_target_id,
                "Rollback Procedure",
            )
        )
        asyncio.run(
            assert_reference_parent_requires_document(
                reference_source_id,
                reference_target_id,
            )
        )

        duplicate_reference_target = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "rollback.md",
            b"# Rollback Procedure\n\nAmbiguous duplicate target.",
            "text/markdown",
        )
        duplicate_reference_target_id = duplicate_reference_target["id"]
        duplicate_reference_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/"
                f"{duplicate_reference_target_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"strategy": "hierarchical", "auto_index": False},
        )
        assert duplicate_reference_parse.status_code == 202, duplicate_reference_parse.text
        asyncio.run(assert_document_reference_target(reference_source_id, None))
        deleted_duplicate_reference_target = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{duplicate_reference_target_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert (
            deleted_duplicate_reference_target.status_code == 204
        ), deleted_duplicate_reference_target.text
        asyncio.run(
            assert_document_reference_target(
                reference_source_id,
                reference_target_id,
                "Rollback Procedure",
            )
        )

        for reference_document_id in (reference_source_id, reference_target_id):
            reference_index = client.post(
                knowledge_url(
                    default_workspace_id,
                    f"/{knowledge_base_id}/documents/{reference_document_id}/index",
                ),
                headers=auth_headers(alice_token),
            )
            assert reference_index.status_code == 202, reference_index.text
        asyncio.run(
            assert_one_hop_reference_retrieval(
                knowledge_base_id,
                reference_source_id,
                reference_target_id,
            )
        )

        evaluation_base = knowledge_url(
            default_workspace_id,
            f"/{knowledge_base_id}/evaluations",
        )
        missing_expected = client.post(
            f"{evaluation_base}/cases",
            headers=auth_headers(alice_token),
            json={"question": "missing expectation", "expected_document_ids": []},
        )
        assert missing_expected.status_code == 422, missing_expected.text
        cross_knowledge_expected = client.post(
            f"{evaluation_base}/cases",
            headers=auth_headers(alice_token),
            json={
                "question": "cross knowledge",
                "expected_document_ids": [foreign_reference_target["id"]],
            },
        )
        assert cross_knowledge_expected.status_code == 404, cross_knowledge_expected.text
        denied_case = client.post(
            f"{evaluation_base}/cases",
            headers=auth_headers(bob_token),
            json={
                "question": "viewers cannot write",
                "expected_document_ids": [reference_target_id],
            },
        )
        assert denied_case.status_code == 403, denied_case.text

        evaluation_view_grant = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert evaluation_view_grant.status_code == 200, evaluation_view_grant.text

        evaluation_case_ids: list[str] = []
        for question in ("successful evaluation", "retry evaluation"):
            created_case = client.post(
                f"{evaluation_base}/cases",
                headers=auth_headers(alice_token),
                json={
                    "question": question,
                    "expected_document_ids": [reference_target_id],
                },
            )
            assert created_case.status_code == 201, created_case.text
            evaluation_case_ids.append(created_case.json()["id"])
        visible_cases = client.get(
            f"{evaluation_base}/cases",
            headers=auth_headers(bob_token),
        )
        assert visible_cases.status_code == 200, visible_cases.text
        assert {item["id"] for item in visible_cases.json()} == set(
            evaluation_case_ids
        )

        original_evaluation_dispatch = (
            knowledge_evaluation_api.dispatch_knowledge_task
        )
        original_evaluation_retrieve = (
            knowledge_evaluation_application.retrieve_knowledge_base
        )
        evaluation_attempts: dict[str, int] = {}

        async def defer_evaluation_dispatch(_task_id, _settings) -> None:
            return None

        async def fake_evaluation_retrieve(
            _db,
            _knowledge_base,
            payload,
            _settings,
        ) -> KnowledgeQueryInspectResponse:
            evaluation_attempts[payload.query] = (
                evaluation_attempts.get(payload.query, 0) + 1
            )
            if (
                payload.query == "retry evaluation"
                and evaluation_attempts[payload.query] == 1
            ):
                raise RuntimeError("synthetic evaluation failure")
            return KnowledgeQueryInspectResponse(
                hits=[
                    KnowledgeQueryHitResponse(
                        chunk_id="evaluation-hit",
                        document_id=reference_target_id,
                        document_filename="rollback.md",
                        chunk_index=0,
                        content="safe rollback",
                    )
                ],
                trace=KnowledgeRetrievalTraceResponse(
                    trace_id=f"trace-{evaluation_attempts[payload.query]}",
                    search_mode=payload.search_mode,
                    limit=payload.limit,
                    min_similarity=payload.similarity,
                    max_distance=(
                        2 * (1 - payload.similarity)
                        if payload.similarity is not None
                        else None
                    ),
                    vector_candidates=1,
                    keyword_candidates=0,
                    reference_candidates=0,
                    fused_candidates=1,
                    rerank_status="not_configured",
                    returned_hits=1,
                    duration_ms=10.0,
                    stage_duration_ms={"retrieve": 10.0},
                ),
            )

        knowledge_evaluation_api.dispatch_knowledge_task = defer_evaluation_dispatch
        knowledge_evaluation_application.retrieve_knowledge_base = (
            fake_evaluation_retrieve
        )
        try:
            queued_run = client.post(
                f"{evaluation_base}/runs",
                headers=auth_headers(alice_token),
                json={
                    "case_ids": evaluation_case_ids,
                    "limit": 3,
                    "search_mode": "blend",
                    "include_references": True,
                },
            )
            assert queued_run.status_code == 202, queued_run.text
            evaluation_task_id = queued_run.json()["id"]

            delete_queued_run = client.delete(
                f"{evaluation_base}/runs/{evaluation_task_id}",
                headers=auth_headers(alice_token),
            )
            assert delete_queued_run.status_code == 409, delete_queued_run.text

            duplicate_run = client.post(
                f"{evaluation_base}/runs",
                headers=auth_headers(alice_token),
                json={"case_ids": evaluation_case_ids},
            )
            assert duplicate_run.status_code == 409, duplicate_run.text
            delete_during_run = client.delete(
                f"{evaluation_base}/cases/{evaluation_case_ids[0]}",
                headers=auth_headers(alice_token),
            )
            assert delete_during_run.status_code == 409, delete_during_run.text
            index_during_run = client.post(
                knowledge_url(
                    default_workspace_id,
                    f"/{knowledge_base_id}/documents/{reference_source_id}/index",
                ),
                headers=auth_headers(alice_token),
            )
            assert index_during_run.status_code == 409, index_during_run.text

            asyncio.run(
                run_knowledge_task(
                    evaluation_task_id,
                    test_settings(),
                    evaluation_runner=(
                        knowledge_evaluation_application.run_evaluation_task
                    ),
                )
            )
            failed_run = client.get(
                f"{evaluation_base}/runs/{evaluation_task_id}",
                headers=auth_headers(alice_token),
            )
            assert failed_run.status_code == 200, failed_run.text
            assert failed_run.json()["status"] == "failed"
            assert failed_run.json()["processed_items"] == 2
            failed_summary = client.get(
                f"{evaluation_base}/runs/{evaluation_task_id}/results",
                headers=auth_headers(bob_token),
            )
            assert failed_summary.status_code == 200, failed_summary.text
            assert failed_summary.json()["count"] == 1
            assert failed_summary.json()["failed_count"] == 1
            failed_result_ids = {
                item["case_id"]: item["id"]
                for item in failed_summary.json()["results"]
            }

            retry_run = client.post(
                knowledge_url(
                    default_workspace_id,
                    f"/{knowledge_base_id}/tasks/{evaluation_task_id}/retry",
                ),
                headers=auth_headers(alice_token),
            )
            assert retry_run.status_code == 202, retry_run.text
            succeeded_run = client.get(
                f"{evaluation_base}/runs/{evaluation_task_id}",
                headers=auth_headers(alice_token),
            )
            assert succeeded_run.status_code == 200, succeeded_run.text
            assert succeeded_run.json()["status"] == "succeeded"
            assert succeeded_run.json()["attempts"] == 2
            summary = client.get(
                f"{evaluation_base}/results/latest",
                headers=auth_headers(bob_token),
            )
            assert summary.status_code == 200, summary.text
            summary_payload = summary.json()
            assert summary_payload["count"] == 2
            assert summary_payload["failed_count"] == 0
            assert summary_payload["mean_hit_at_k"] == 1.0
            assert [item["case_id"] for item in summary_payload["results"]] == (
                evaluation_case_ids
            )
            assert {
                item["case_id"]: item["id"]
                for item in summary_payload["results"]
            } == failed_result_ids
            asyncio.run(
                assert_evaluation_success_resists_stale_error(
                    default_workspace_id,
                    knowledge_base_id,
                    evaluation_task_id,
                    evaluation_case_ids[0],
                    failed_result_ids[evaluation_case_ids[0]],
                )
            )
            assert evaluation_attempts == {
                "successful evaluation": 1,
                "retry evaluation": 2,
            }

            failed_write_run = client.post(
                f"{evaluation_base}/runs",
                headers=auth_headers(alice_token),
                json={"case_ids": [evaluation_case_ids[0]], "limit": 1},
            )
            assert failed_write_run.status_code == 202, failed_write_run.text
            original_upsert_result = evaluation_repository.upsert_result

            async def fail_result_write(*_args, **_kwargs):
                raise RuntimeError("synthetic result write failure")

            evaluation_repository.upsert_result = fail_result_write
            try:
                asyncio.run(
                    run_knowledge_task(
                        failed_write_run.json()["id"],
                        test_settings(),
                        evaluation_runner=(
                            knowledge_evaluation_application.run_evaluation_task
                        ),
                    )
                )
            finally:
                evaluation_repository.upsert_result = original_upsert_result
            failed_write_task = client.get(
                f"{evaluation_base}/runs/{failed_write_run.json()['id']}",
                headers=auth_headers(alice_token),
            )
            assert failed_write_task.status_code == 200, failed_write_task.text
            assert failed_write_task.json()["status"] == "failed"
            assert failed_write_task.json()["processed_items"] == 0
            failed_write_summary = client.get(
                f"{evaluation_base}/runs/{failed_write_run.json()['id']}/results",
                headers=auth_headers(alice_token),
            )
            assert failed_write_summary.status_code == 200, failed_write_summary.text
            assert failed_write_summary.json()["results"] == []

            recovery_run = client.post(
                f"{evaluation_base}/runs",
                headers=auth_headers(alice_token),
                json={"case_ids": [evaluation_case_ids[0]], "limit": 1},
            )
            assert recovery_run.status_code == 202, recovery_run.text
            asyncio.run(
                recover_knowledge_tasks(
                    test_settings(),
                    knowledge_evaluation_application.run_evaluation_task,
                )
            )
            recovered_run = client.get(
                f"{evaluation_base}/runs/{recovery_run.json()['id']}",
                headers=auth_headers(alice_token),
            )
            assert recovered_run.status_code == 200, recovered_run.text
            assert recovered_run.json()["status"] == "succeeded"
            recovery_task_id = recovery_run.json()["id"]
            denied_delete_run = client.delete(
                f"{evaluation_base}/runs/{recovery_task_id}",
                headers=auth_headers(bob_token),
            )
            assert denied_delete_run.status_code == 403, denied_delete_run.text
            deleted_run = client.delete(
                f"{evaluation_base}/runs/{recovery_task_id}",
                headers=auth_headers(alice_token),
            )
            assert deleted_run.status_code == 204, deleted_run.text
            missing_run = client.get(
                f"{evaluation_base}/runs/{recovery_task_id}",
                headers=auth_headers(alice_token),
            )
            assert missing_run.status_code == 404, missing_run.text
            asyncio.run(assert_evaluation_run_deleted(recovery_task_id))
        finally:
            knowledge_evaluation_api.dispatch_knowledge_task = (
                original_evaluation_dispatch
            )
            knowledge_evaluation_application.retrieve_knowledge_base = (
                original_evaluation_retrieve
            )

        deleted_reference_target = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{reference_target_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_reference_target.status_code == 204, deleted_reference_target.text
        asyncio.run(assert_document_reference_target(reference_source_id, None))
        deleted_reference_source = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{reference_source_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_reference_source.status_code == 204, deleted_reference_source.text
        deleted_foreign_reference_target = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{bob_owned_knowledge_base.json()['id']}/documents/"
                f"{foreign_reference_target['id']}",
            ),
            headers=auth_headers(bob_token),
        )
        assert (
            deleted_foreign_reference_target.status_code == 204
        ), deleted_foreign_reference_target.text

        asyncio.run(
            assert_parent_scope_constraint(
                knowledge_base_id,
                hierarchical_document_id,
                preview_document_id,
            )
        )

        deleted_hierarchical_document = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{hierarchical_document_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert (
            deleted_hierarchical_document.status_code == 204
        ), deleted_hierarchical_document.text
        asyncio.run(assert_document_deleted(hierarchical_document_id))

        deleted_preview_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{preview_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_preview_document.status_code == 204, deleted_preview_document.text
        asyncio.run(assert_document_deleted(preview_document_id))
        empty_query = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/query"),
            headers=auth_headers(alice_token),
            json={"query": "product docs", "limit": 5},
        )
        assert empty_query.status_code == 200, empty_query.text
        assert empty_query.json() == []

        # C: owner transfer requires admin or current owner.
        transfer_denied = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(bob_token),
            json={"user_id": alice_id},
        )
        assert transfer_denied.status_code == 403, transfer_denied.text

        transfer_missing_target = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(alice_token),
            json={"user_id": research_admin_id},
        )
        assert transfer_missing_target.status_code == 404, transfer_missing_target.text

        transferred = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(alice_token),
            json={"user_id": bob_id},
        )
        assert transferred.status_code == 200, transferred.text
        assert transferred.json()["created_by_user_id"] == bob_id
        assert transferred.json()["permission"] == "none"

        alice_patch_denied_after_transfer = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={"description": "Alice no longer owns"},
        )
        assert (
            alice_patch_denied_after_transfer.status_code == 403
        ), alice_patch_denied_after_transfer.text

        bob_patch_as_owner = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"description": "Bob owns now"},
        )
        assert bob_patch_as_owner.status_code == 200, bob_patch_as_owner.text

        # D: archived knowledge bases block writes but allow reads; only
        # admin/owner may restore.
        archived_kb = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"status": "archived"},
        )
        assert archived_kb.status_code == 200, archived_kb.text
        assert archived_kb.json()["status"] == "archived"

        archived_upload = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(bob_token),
            files={"file": ("archived.txt", b"nope", "text/plain")},
        )
        assert archived_upload.status_code == 403, archived_upload.text

        archived_rename = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"name": "Renamed while archived"},
        )
        assert archived_rename.status_code == 403, archived_rename.text

        archived_grant = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{alice_id}"),
            headers=auth_headers(bob_token),
            json={"permission": "view"},
        )
        assert archived_grant.status_code == 403, archived_grant.text

        archived_transfer = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(bob_token),
            json={"user_id": alice_id},
        )
        assert archived_transfer.status_code == 403, archived_transfer.text

        archived_delete = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert archived_delete.status_code == 403, archived_delete.text

        archived_get = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert archived_get.status_code == 200, archived_get.text
        assert archived_get.json()["status"] == "archived"

        archived_query = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/query"),
            headers=auth_headers(bob_token),
            json={"query": "product docs", "limit": 5},
        )
        assert archived_query.status_code == 200, archived_query.text

        restore_with_rename = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"status": "active", "name": "Restored and renamed"},
        )
        assert restore_with_rename.status_code == 403, restore_with_rename.text

        still_archived = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert still_archived.status_code == 200, still_archived.text
        assert still_archived.json()["status"] == "archived"

        restored = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"status": "active"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"

        restored_rename = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"description": "Writable again"},
        )
        assert restored_rename.status_code == 200, restored_rename.text

        # Transfer ownership back so the final delete runs as the owner.
        transferred_back = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(bob_token),
            json={"user_id": alice_id},
        )
        assert transferred_back.status_code == 200, transferred_back.text
        assert transferred_back.json()["created_by_user_id"] == alice_id

        deleted = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted.status_code == 204, deleted.text

        asyncio.run(assert_knowledge_base_deleted(knowledge_base_id, default_workspace_id))

        audit_logs = client.get("/api/v1/admin/audit-logs?limit=200", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "knowledge_base.create" in actions
        assert "knowledge_attachment.upload" in actions
        assert "knowledge_document.create_from_attachments" in actions
        assert "knowledge_document.parse" in actions
        assert "knowledge_document.index" in actions
        assert "knowledge_document.delete" in actions
        assert "knowledge_task.parse.fail" in actions
        assert "knowledge_task.index.fail" in actions
        assert "knowledge_task.rebuild_index.fail" in actions
        assert "knowledge_task.retry" in actions
        assert "resource_permission.grant" in actions
        assert "resource_permission.revoke" in actions
        assert "knowledge_base.owner_transfer" in actions
        assert "knowledge_base.delete" in actions


if __name__ == "__main__":
    main()

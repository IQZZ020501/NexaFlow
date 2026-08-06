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

from app.infrastructure.session import get_session_factory
from app.domain.user import User
from app.shareddomain.knowledge.models import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeTask,
)
from app.api.v1.endpoints import knowledge as knowledge_api
from app.application import knowledge as knowledge_application
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
from app.infrastructure.repositories import user as user_repository
from app.entities.knowledge import DOCUMENT_DELETED_STATUS
from app.shareddomain.knowledge.orchestration import (
    enqueue_parse_knowledge_document,
    enqueue_rebuild_knowledge_index,
)
from app.shareddomain.knowledge.task_runner import (
    mark_knowledge_task_failed,
    recover_knowledge_tasks,
    run_parse_task,
)
from app.tasks.knowledge import mark_task_dispatch_failed
from app.schemas.knowledge import KnowledgeQueryRequest
from tests.llm import ModelTestHandler, model_payload, model_test_server, models_url
from app.domain.resource_permission import ResourcePermission
from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    create_active_user,
    settings as test_settings,
    test_client,
)

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
    original_query_vectors = knowledge_application.query_vectors

    def fake_query_vectors(*_args) -> list[VectorHit]:
        assert _args[-1] == 5
        return [
            VectorHit(chunk_id="stale-chunk", distance=0.0),
            VectorHit(chunk_id=indexed_chunk_id, distance=0.1),
        ]

    knowledge_application.query_vectors = fake_query_vectors
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
        knowledge_application.query_vectors = original_query_vectors


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
        ) == [VectorHit(chunk_id=chunk_id, distance=None)]

        try:
            knowledge_vector_store._ensure_collection(client, collection_name, 3)
        except ValueError:
            pass
        else:
            raise AssertionError("Qdrant vector size mismatch was accepted.")

        class RacingClient:
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

        knowledge_vector_store._ensure_collection(RacingClient(), "race", 2)
        knowledge_vector_store.delete_vectors(settings, "knowledge-1", [chunk_id])
        assert client.retrieve(collection_name, ids=[chunk_id]) == []
        knowledge_vector_store.delete_vector_collection(settings, "knowledge-1")
        assert not client.collection_exists(collection_name)
    finally:
        knowledge_vector_store.build_registered_embeddings = original_build_embeddings
        if client is not None:
            client.close()
        knowledge_vector_store._build_qdrant_client.cache_clear()

    assert knowledge_retrieval.reciprocal_rank_fusion(
        [
            VectorHit(chunk_id="vector-only", distance=0.1),
            VectorHit(chunk_id="shared", distance=0.2),
        ],
        ["shared", "keyword-only"],
    ) == [
        VectorHit(chunk_id="shared", distance=0.2),
        VectorHit(chunk_id="vector-only", distance=0.1),
        VectorHit(chunk_id="keyword-only", distance=None),
    ]


async def assert_query_aggregates_hybrid_hits(
    knowledge_base_id: str,
    product_document_id: str,
    product_chunk_id: str,
    configured_document_id: str,
    configured_chunks: list[dict],
) -> None:
    original_query_vectors = knowledge_application.query_vectors
    original_query_keyword_chunk_ids = knowledge_repository.query_keyword_chunk_ids
    configured_by_index = {
        chunk["chunk_index"]: chunk for chunk in configured_chunks
    }

    def fake_query_vectors(*args) -> list[VectorHit]:
        assert args[-2:] == ("exact term", 10)
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

    knowledge_application.query_vectors = fake_query_vectors
    knowledge_repository.query_keyword_chunk_ids = fake_query_keyword_chunk_ids
    try:
        async with get_session_factory()() as db:
            knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
            assert knowledge_base is not None
            hits = await knowledge_application.query_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="exact term", limit=2),
                test_settings(),
            )
    finally:
        knowledge_application.query_vectors = original_query_vectors
        knowledge_repository.query_keyword_chunk_ids = original_query_keyword_chunk_ids

    assert [hit.document_id for hit in hits] == [
        configured_document_id,
        product_document_id,
    ]
    assert hits[0].chunk_id == configured_by_index[0]["id"]
    assert hits[0].chunk_index == 0
    assert hits[0].distance == 0.2
    assert hits[0].content == "\n\n".join(
        configured_by_index[index]["content"] for index in range(3)
    )
    assert hits[1].chunk_id == product_chunk_id
    assert hits[1].distance == 0.05


def upload_document(
    client,
    token,
    workspace_id,
    knowledge_base_id,
    filename,
    content,
    mime,
    staged=False,
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
        json={"attachment_ids": [attachment_id], "staged": staged},
    )
    assert created.status_code == 201, created.text
    return created.json()[0]


async def assert_hierarchical_chunks_persisted(
    document_id: str,
) -> tuple[list[str], list[str]]:
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
        assert len(chunks) > len(parents)
        assert all(chunk.parent_id in parents_by_id for chunk in chunks)
        assert all(
            parents_by_id[chunk.parent_id].content[
                chunk.start_offset : chunk.end_offset
            ]
            == chunk.content
            for chunk in chunks
        )
        return [chunk.id for chunk in chunks], [parent.id for parent in parents]


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
    original_query_vectors = knowledge_application.query_vectors
    original_query_keyword_chunk_ids = knowledge_repository.query_keyword_chunk_ids
    original_build_registered_reranker = (
        knowledge_retrieval.build_registered_reranker
    )
    reranked_documents: list[str] = []

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
            assert args[-2:] == ("hierarchical query", 10)
            return [
                VectorHit(chunk_id=chunk.id, distance=index / 10)
                for index, chunk in enumerate(candidates, start=1)
            ]

        async def fake_query_keyword_chunk_ids(*_args) -> list[str]:
            return []

        class FakeReranker:
            def rerank(self, query: str, documents: list[str]) -> list[dict]:
                assert query == "hierarchical query"
                reranked_documents.extend(documents)
                return [
                    {"index": 2, "relevance_score": 1.0},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]

        knowledge_application.query_vectors = fake_query_vectors
        knowledge_repository.query_keyword_chunk_ids = fake_query_keyword_chunk_ids
        knowledge_retrieval.build_registered_reranker = lambda *_args: FakeReranker()
        try:
            hits = await knowledge_application.query_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="hierarchical query", limit=2),
                test_settings(),
            )
        finally:
            knowledge_application.query_vectors = original_query_vectors
            knowledge_repository.query_keyword_chunk_ids = (
                original_query_keyword_chunk_ids
            )
            knowledge_retrieval.build_registered_reranker = (
                original_build_registered_reranker
            )

    assert reranked_documents == [chunk.content for chunk in candidates]
    assert [hit.parent_id for hit in hits] == [parents[1].id, parents[0].id]
    assert hits[0].chunk_id == second_children[0].id
    assert hits[1].chunk_id == first_children[1].id
    assert len({hit.parent_id for hit in hits}) == len(hits)
    assert all(len(hit.content) <= 2000 for hit in hits)
    assert "SECOND" in hits[0].content and "FIRST" not in hits[0].content
    assert "FIRST" in hits[1].content and "SECOND" not in hits[1].content
    assert len(hits[1].content) == 2000


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
    assert_vector_store_mmr_and_metadata()
    hierarchical_drafts = build_hierarchical_chunks(
        "# One\n\n```text\n# not a heading\n```\n\nBody\n\n# Two\n\nMore",
        chunk_size=20,
        overlap=5,
    )
    assert [parent.title for parent in hierarchical_drafts.parents] == ["One", "Two"]
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
        assert bob_list.json() == []

        denied_cross_workspace = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(research_token),
        )
        assert denied_cross_workspace.status_code == 403, denied_cross_workspace.text

        view_grant = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{bob_id}"),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert view_grant.status_code == 200, view_grant.text
        assert view_grant.json()["permission"] == "view"
        asyncio.run(assert_cross_workspace_permission_denied(default_workspace_id, knowledge_base_id))

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
        assert knowledge_query.json()[0]["document_id"] == document_id
        assert knowledge_query.json()[0]["content"] == "Hello from product docs"

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

        rebuild_task = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert rebuild_task.status_code == 202, rebuild_task.text
        assert rebuild_task.json()["task_type"] == "rebuild_index"
        assert rebuild_task.json()["total_items"] == 1
        assert rebuild_task.json()["processed_items"] == 0

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
        assert pdf_chunks.json()[0]["content"] == "Hello from PDF docs"

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

        first_parent_body = "\n\n".join(
            f"FIRST paragraph {index} " + "alpha " * 40
            for index in range(15)
        )
        second_parent_body = "SECOND " * 80
        hierarchical_content = (
            f"# First\n\n{first_parent_body}\n\n# Second\n\n{second_parent_body}"
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
        hierarchical_child_ids, hierarchical_parent_ids = asyncio.run(
            assert_hierarchical_chunks_persisted(hierarchical_document_id)
        )

        hierarchical_index = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{hierarchical_document_id}/index",
            ),
            headers=auth_headers(alice_token),
        )
        assert hierarchical_index.status_code == 202, hierarchical_index.text
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
        assert "knowledge_base.delete" in actions


if __name__ == "__main__":
    main()

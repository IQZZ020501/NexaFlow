import asyncio
import json
from html import escape
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from nexaflow.db.session import get_session_factory
from nexaflow.identity.models import User
from nexaflow.knowledge.models import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeTask,
)
from nexaflow.knowledge import api as knowledge_api
from nexaflow.knowledge import retrieval as knowledge_retrieval
from nexaflow.knowledge.pipeline import VectorHit, clean_text, split_text
from nexaflow.knowledge.processing import (
    enqueue_parse_knowledge_document,
    enqueue_rebuild_knowledge_index,
)
from nexaflow.knowledge.task_runner import recover_knowledge_tasks
from nexaflow.knowledge.tasks import mark_task_dispatch_failed
from nexaflow.knowledge.schemas import KnowledgeQueryRequest
from nexaflow.llm.test import ModelTestHandler, model_payload, model_test_server, models_url
from nexaflow.resource_permissions.models import ResourcePermission
from nexaflow.testing import (
    RESEARCH_PASSWORD,
    activate_admin,
    activate_user,
    auth_headers,
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
    return f"/workspaces/{workspace_id}/knowledge-bases{suffix}"


def create_workspace_user(client, token: str, workspace_id: str, username: str) -> tuple[str, str]:
    response = client.post(
        f"/workspaces/{workspace_id}/members/users",
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
        assert not (test_settings().knowledge_storage_dir / document.storage_path).exists()


async def enqueue_recoverable_parse_task(
    knowledge_base_id: str,
    document_id: str,
    actor_username: str,
) -> None:
    async with get_session_factory()() as db:
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        document = await db.get(KnowledgeDocument, document_id)
        actor = await db.scalar(select(User).where(User.username == actor_username))
        assert knowledge_base is not None
        assert document is not None
        assert actor is not None
        await enqueue_parse_knowledge_document(db, knowledge_base, document, actor)


async def enqueue_recoverable_rebuild_task(
    knowledge_base_id: str,
    actor_username: str,
) -> None:
    async with get_session_factory()() as db:
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        actor = await db.scalar(select(User).where(User.username == actor_username))
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
    original_embed_query = knowledge_retrieval.embed_query
    original_query_chroma_vectors = knowledge_retrieval.query_chroma_vectors

    def fake_embed_query(*_args) -> list[float]:
        return [1.0]

    def fake_query_chroma_vectors(*_args) -> list[VectorHit]:
        assert _args[-1] == 5
        return [
            VectorHit(chunk_id="stale-chunk", distance=0.0),
            VectorHit(chunk_id=indexed_chunk_id, distance=0.1),
        ]

    knowledge_retrieval.embed_query = fake_embed_query
    knowledge_retrieval.query_chroma_vectors = fake_query_chroma_vectors
    try:
        async with get_session_factory()() as db:
            knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
            assert knowledge_base is not None
            hits = await knowledge_retrieval.query_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(query="product docs", limit=1),
                test_settings(),
            )
            assert [hit.chunk_id for hit in hits] == [indexed_chunk_id]
    finally:
        knowledge_retrieval.embed_query = original_embed_query
        knowledge_retrieval.query_chroma_vectors = original_query_chroma_vectors


def main() -> None:
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

        created_workspace = client.post(
            "/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "description": "研究工作空间",
                "admin": {
                    "username": "research-admin",
                    "email": "research-admin@example.com",
                    "name": "Research Admin",
                },
            },
        )
        assert created_workspace.status_code == 201, created_workspace.text
        research_workspace_id = created_workspace.json()["workspace"]["id"]
        research_password = created_workspace.json()["admin_initial_password"]
        assert research_password
        research_token = activate_user(
            client,
            "research-admin",
            research_password,
            RESEARCH_PASSWORD,
        )

        embedding_model = client.post(
            models_url(default_workspace_id),
            headers=auth_headers(admin_token),
            json={
                **model_payload(model_base_url),
                "name": "Knowledge Embedding",
                "provider": "model_openai_provider",
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
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(bob_token),
            files={"file": ("denied.txt", b"nope", "text/plain")},
        )
        assert bob_upload_denied.status_code == 403, bob_upload_denied.text

        document_content = b"Hello from product docs"
        uploaded_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            files={"file": ("product-guide.txt", document_content, "text/plain")},
        )
        assert uploaded_document.status_code == 201, uploaded_document.text
        document_payload = uploaded_document.json()
        document_id = document_payload["id"]
        assert document_payload["filename"] == "product-guide.txt"
        assert document_payload["status"] == "parse_queued"
        assert document_payload["size_bytes"] == len(document_content)
        asyncio.run(assert_document_saved(document_id, document_content))

        bob_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(bob_token),
        )
        assert bob_documents.status_code == 200, bob_documents.text
        assert [item["id"] for item in bob_documents.json()] == [document_id]

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
        configured_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            files={
                "file": ("configured-guide.txt", configured_content, "text/plain"),
                "auto_parse": (None, "false"),
            },
        )
        assert configured_document.status_code == 201, configured_document.text
        configured_document_id = configured_document.json()["id"]
        assert configured_document.json()["status"] == "uploaded"
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
        assert configured_document_id not in {
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

        original_enqueue_knowledge_task = knowledge_api.enqueue_knowledge_task

        async def fail_knowledge_task_dispatch(task_id: str, _settings) -> None:
            await mark_task_dispatch_failed(task_id)
            raise RuntimeError("queue unavailable")

        knowledge_api.enqueue_knowledge_task = fail_knowledge_task_dispatch
        try:
            degraded_upload = client.post(
                knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
                headers=auth_headers(alice_token),
                files={"file": ("queued-later.txt", b"Stored before dispatch", "text/plain")},
            )
        finally:
            knowledge_api.enqueue_knowledge_task = original_enqueue_knowledge_task

        assert degraded_upload.status_code == 201, degraded_upload.text
        assert degraded_upload.json()["status"] == "parse_failed"

        pdf_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            files={"file": ("pdf-guide.pdf", pdf_bytes("Hello from PDF docs"), "application/pdf")},
        )
        assert pdf_document.status_code == 201, pdf_document.text
        pdf_document_id = pdf_document.json()["id"]

        pdf_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{pdf_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert pdf_chunks.status_code == 200, pdf_chunks.text
        assert pdf_chunks.json()[0]["content"] == "Hello from PDF docs"

        docx_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            files={"file": ("word-guide.docx", docx_bytes("Hello from DOCX docs"), DOCX_MIME)},
        )
        assert docx_document.status_code == 201, docx_document.text
        docx_document_id = docx_document.json()["id"]

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

        recovery_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            files={"file": ("recovery-guide.txt", b"Recovered on startup", "text/plain")},
        )
        assert recovery_document.status_code == 201, recovery_document.text
        recovery_document_id = recovery_document.json()["id"]
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
        split_document = client.post(
            f"/workspace/{default_workspace_id}/knowledge/{knowledge_base_id}/document/split",
            headers=auth_headers(alice_token),
            data={
                "security_levels": json.dumps(
                    [{"name": "split-guide.txt", "security_level": "INTERNAL"}]
                ),
                "limit": "1000",
                "with_filter": "true",
                "patterns": "[]",
            },
            files=[("file", ("split-guide.txt", split_content, "text/plain"))],
        )
        assert split_document.status_code == 200, split_document.text
        split_payload = split_document.json()[0]
        split_document_id = split_payload["source_file_id"]
        assert split_payload["name"] == "split-guide.txt"
        assert split_payload["security_level"] == "INTERNAL"
        assert split_payload["content"][0]["content"] == "Legacy split content\nSecond paragraph"
        asyncio.run(assert_document_saved(split_document_id, split_content))

        batch_created = client.put(
            f"/workspace/{default_workspace_id}/knowledge/{knowledge_base_id}/document/batch_create",
            headers=auth_headers(alice_token),
            json=[
                {
                    "name": "split-guide.txt",
                    "source_file_id": split_document_id,
                    "paragraphs": [{"title": "Intro", "content": "Edited split content"}],
                    "meta": {"security_level": "INTERNAL"},
                }
            ],
        )
        assert batch_created.status_code == 200, batch_created.text
        assert batch_created.json()[0]["id"] == split_document_id
        assert batch_created.json()[0]["meta"]["source_file_id"] == split_document_id
        assert batch_created.json()[0]["meta"]["security_level"] == "INTERNAL"
        split_chunks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{split_document_id}/chunks"),
            headers=auth_headers(alice_token),
        )
        assert split_chunks.status_code == 200, split_chunks.text
        assert split_chunks.json()[0]["content"] == "Intro\n\nEdited split content"
        assert split_chunks.json()[0]["status"] == "indexed"

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
        concurrent_delete_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{recovery_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_delete_document.status_code == 409, concurrent_delete_document.text
        concurrent_delete_knowledge_base = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_delete_knowledge_base.status_code == 409, concurrent_delete_knowledge_base.text
        asyncio.run(recover_knowledge_tasks(test_settings()))

        failed_parse_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            files={"file": ("unsupported.bin", b"\x00\x01\x02", "application/octet-stream")},
        )
        assert failed_parse_document.status_code == 201, failed_parse_document.text
        failed_parse_document_id = failed_parse_document.json()["id"]
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

        retry_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            files={"file": ("retry-guide.txt", b"Retryable embedding document", "text/plain")},
        )
        assert retry_document.status_code == 201, retry_document.text
        retry_document_id = retry_document.json()["id"]

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

        deleted_recovery_document = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents/{recovery_document_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted_recovery_document.status_code == 204, deleted_recovery_document.text
        asyncio.run(assert_document_deleted(recovery_document_id))

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

        empty_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert empty_documents.status_code == 200, empty_documents.text
        assert empty_documents.json() == []

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

        audit_logs = client.get("/audit-logs?limit=200", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "knowledge_base.create" in actions
        assert "knowledge_document.upload" in actions
        assert "knowledge_document.parse" in actions
        assert "knowledge_document.batch_create" in actions
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

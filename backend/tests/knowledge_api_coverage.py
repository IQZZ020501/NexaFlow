"""Knowledge API + RAG coverage suite.

Covers the baseline-missing lines of:
- app/api/v1/endpoints/knowledge.py (CRUD + task + permission endpoints)
- app/api/v1/endpoints/knowledge_lifecycle.py (download / asset / delete / status)
- app/api/v1/endpoints/knowledge_retrieval.py (query endpoint)
- app/application/knowledge.py (query aggregation, chunk-count responses, assets)
- app/capabilities/rag/retrieval.py (rerank edge paths)
- app/capabilities/rag/vector_store.py (in-memory error paths)
- app/capabilities/embedding/pipeline.py (split/clean/extract edge paths)

Run from backend/:  uv run python -m tests.knowledge_api_coverage
"""

import asyncio
import os
from contextlib import nullcontext
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, UploadFile

from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    create_active_user,
    test_client,
)
import tests.support as support_module
from tests.llm import model_payload, model_test_server, models_url

# The shared test storage dir is wiped (shutil.rmtree) by every suite's
# test_client() block; concurrent suites destroy each other's uploaded
# document files.  Isolate this suite's storage under a per-process dir:
# the eager knowledge tasks build Settings.from_env(), so the env var must
# point at the same isolated location as support.settings().
_UNIQUE_STORAGE_DIR = Path(f"/tmp/app-test-knowledge-storage-{os.getpid()}")
os.environ["KNOWLEDGE_STORAGE_DIR"] = str(_UNIQUE_STORAGE_DIR)

_ORIGINAL_SUPPORT_SETTINGS = support_module.settings


def _isolated_support_settings():
    return replace(
        _ORIGINAL_SUPPORT_SETTINGS(),
        knowledge_storage_dir=_UNIQUE_STORAGE_DIR,
    )


support_module.settings = _isolated_support_settings
test_settings = support_module.settings

from app.infrastructure.session import get_session_factory
from app.shareddomain.knowledge.models import (
    KnowledgeAsset,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
)
from app.api.v1.endpoints import knowledge as knowledge_api
from app.api.v1.endpoints import knowledge_lifecycle as knowledge_lifecycle_api
from app.api.v1.endpoints import knowledge_retrieval as knowledge_retrieval_api
from app.application import knowledge as knowledge_application
from app.capabilities.rag import retrieval as knowledge_retrieval
from app.capabilities.rag import vector_store as knowledge_vector_store
from app.capabilities.embedding import pipeline as knowledge_pipeline
from app.capabilities.llm.runtime import ModelProviderError
from app.capabilities.rag.vector_store import VectorChunk, VectorHit
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import user as user_repository
from app.schemas.knowledge import (
    KnowledgeBaseOwnerTransferRequest,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentStatusUpdateRequest,
    KnowledgeModelTestRequest,
    KnowledgeQueryRequest,
    ResourcePermissionUpsertRequest,
)
from app.shareddomain.knowledge.orchestration import (
    enqueue_parse_knowledge_document,
)
from app.shareddomain.knowledge.task_runner import recover_knowledge_tasks
from sqlalchemy import select, text

MEMBER_PASSWORD = "Member@12345."


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


def upload_document(
    client,
    token: str,
    workspace_id: str,
    knowledge_base_id: str,
    filename: str,
    content: bytes,
    mime: str,
    staged: bool = False,
) -> dict:
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


async def set_knowledge_base_reranker_model(knowledge_base_id: str, model_id: str) -> None:
    async with get_session_factory()() as db:
        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        knowledge_base.reranker_model_id = model_id
        await db.commit()


async def insert_asset(
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    asset_id: str,
    asset_index: int,
    object_key: str,
    filename: str,
    content_type: str,
) -> None:
    async with get_session_factory()() as db:
        db.add(
            KnowledgeAsset(
                id=asset_id,
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                asset_index=asset_index,
                kind="image",
                filename=filename,
                content_type=content_type,
                size_bytes=4,
                object_key=object_key,
                alt_text="asset",
                meta={},
            )
        )
        await db.commit()


async def delete_document_file(document_id: str) -> None:
    async with get_session_factory()() as db:
        document = await db.get(KnowledgeDocument, document_id)
        assert document is not None
        knowledge_application.knowledge_object_storage(test_settings()).delete(
            document.storage_path
        )


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


async def load_hierarchical_rows(
    knowledge_base_id: str,
    document_id: str,
    flat_document_id: str,
) -> tuple[KnowledgeBase, list[KnowledgeDocumentChunk], list[KnowledgeDocumentParentChunk], str]:
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
        flat_chunks = list(
            await db.scalars(
                select(KnowledgeDocumentChunk)
                .where(KnowledgeDocumentChunk.document_id == flat_document_id)
                .order_by(KnowledgeDocumentChunk.chunk_index)
            )
        )
        assert knowledge_base is not None
        assert len(parents) >= 2
        assert flat_chunks
        return knowledge_base, chunks, parents, flat_chunks[0].id


def exercise_direct_endpoint_calls(
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    missing_document_id: str,
    failed_task_id: str,
    alice_id: str,
    bob_id: str,
    reranker_model_id: str,
    asset_id: str,
    missing_file_asset_id: str,
    research_knowledge_base_id: str,
    research_admin_id: str,
) -> None:
    """Call endpoint functions directly so the whole body runs on the main
    thread (TestClient resumes endpoint coroutines on a portal thread, which
    the coverage tracer does not see). Task-dispatch endpoints patch out
    dispatch so the eager Celery worker does not re-enter asyncio.run from a
    running loop; the resulting queued tasks are settled afterwards by
    ``recover_knowledge_tasks``.
    """

    async def run() -> None:
        original_dispatch = knowledge_api.dispatch_knowledge_task
        knowledge_api.dispatch_knowledge_task = AsyncMock()
        settings = test_settings()

        async def settle_open_tasks(db) -> None:
            """Fail every queued/running task of the base so the next
            dispatch-style endpoint call is not blocked by a 409 conflict."""
            await db.execute(
                text(
                    "UPDATE knowledge_tasks SET status = 'failed' "
                    "WHERE knowledge_base_id = :knowledge_base_id "
                    "AND status IN ('queued', 'running')"
                ),
                {"knowledge_base_id": knowledge_base_id},
            )
            await db.commit()

        alice_ctx = SimpleNamespace(
            workspace=SimpleNamespace(id=workspace_id),
            user=SimpleNamespace(id=alice_id, username="alice", name="Alice"),
            membership_role=None,
        )
        bob_ctx = SimpleNamespace(
            workspace=SimpleNamespace(id=workspace_id),
            user=SimpleNamespace(id=bob_id, username="bob", name="Bob"),
            membership_role=None,
        )
        try:
            async with get_session_factory()() as db:
                knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
                assert knowledge_base is not None

                # GET "" — list knowledge bases.
                listed = await knowledge_api.list_workspace_knowledge_bases(
                    alice_ctx,
                    db,
                    100,
                    0,
                )
                assert any(item.id == knowledge_base_id for item in listed)

                # GET /{kb} — full response construction.
                fetched = await knowledge_api.get_workspace_knowledge_base(
                    knowledge_base_id,
                    alice_ctx,
                    db,
                )
                assert fetched.id == knowledge_base_id

                # PATCH /{kb} — update path.
                patched = await knowledge_api.patch_workspace_knowledge_base(
                    knowledge_base_id,
                    KnowledgeBaseUpdateRequest(description="direct patched"),
                    alice_ctx,
                    db,
                )
                assert patched.description == "direct patched"

                # GET /{kb}/documents — count aggregation.
                documents = await knowledge_api.list_workspace_knowledge_base_documents(
                    knowledge_base_id,
                    alice_ctx,
                    db,
                    False,
                    100,
                    0,
                )
                assert any(item.id == document_id for item in documents)

                # POST /{kb}/attachments — upload path.
                uploaded = await knowledge_api.upload_workspace_knowledge_attachment(
                    knowledge_base_id,
                    UploadFile(
                        file=BytesIO(b"direct attachment"),
                        filename="direct.txt",
                        headers={"content-type": "text/plain"},
                    ),
                    alice_ctx,
                    settings,
                    db,
                )
                assert uploaded.filename == "direct.txt"

                # DELETE /{kb}/attachments/{id}.
                deleted_attachment = (
                    await knowledge_api.delete_workspace_knowledge_attachment(
                        knowledge_base_id,
                        uploaded.id,
                        alice_ctx,
                        settings,
                        db,
                    )
                )
                assert deleted_attachment.status_code == 204

                # POST /{kb}/documents — create from a fresh attachment.
                second_upload = await knowledge_api.upload_workspace_knowledge_attachment(
                    knowledge_base_id,
                    UploadFile(
                        file=BytesIO(b"direct document"),
                        filename="direct-doc.txt",
                        headers={"content-type": "text/plain"},
                    ),
                    alice_ctx,
                    settings,
                    db,
                )
                created_documents = (
                    await knowledge_api.create_workspace_knowledge_base_documents(
                        knowledge_base_id,
                        KnowledgeDocumentCreateRequest(
                            attachment_ids=[second_upload.id],
                            staged=False,
                        ),
                        alice_ctx,
                        db,
                    )
                )
                direct_document_id = created_documents[0].id

                # GET /{kb}/documents/{id}/chunks — empty preview.
                chunks = await knowledge_api.list_workspace_knowledge_document_chunks(
                    knowledge_base_id,
                    direct_document_id,
                    alice_ctx,
                    db,
                    100,
                    0,
                )
                assert chunks == []

                # GET /{kb}/documents/{id}/tasks — no tasks yet.
                direct_document_tasks = (
                    await knowledge_api.list_workspace_knowledge_document_tasks(
                        knowledge_base_id,
                        direct_document_id,
                        alice_ctx,
                        db,
                        100,
                        0,
                    )
                )
                assert direct_document_tasks == []

                # POST /{kb}/model-test — provider round trip.
                model_test = await knowledge_api.test_workspace_knowledge_base_models(
                    knowledge_base_id,
                    KnowledgeModelTestRequest(query="Hello", documents=["Hello"]),
                    alice_ctx,
                    settings,
                    db,
                )
                assert model_test.embedding_dimensions == 1

                # GET /{kb}/tasks — base-level task listing.
                knowledge_tasks = await knowledge_api.list_workspace_knowledge_base_tasks(
                    knowledge_base_id,
                    alice_ctx,
                    db,
                    100,
                    0,
                )
                assert any(item.task_type == "parse" for item in knowledge_tasks)

                # POST /{kb}/rebuild-index — enqueue only (no dispatch).
                rebuild_task = await knowledge_api.rebuild_workspace_knowledge_base_index(
                    knowledge_base_id,
                    alice_ctx,
                    settings,
                    db,
                )
                assert rebuild_task.task_type == "rebuild_index"
                await settle_open_tasks(db)

                # POST /{kb}/documents/{id}/index — enqueue only.
                index_task = await knowledge_api.index_workspace_knowledge_base_document(
                    knowledge_base_id,
                    document_id,
                    alice_ctx,
                    settings,
                    db,
                )
                assert index_task.task_type == "index"
                await settle_open_tasks(db)

                # POST /{kb}/tasks/{id}/retry — enqueue only.
                retried = await knowledge_api.retry_workspace_knowledge_task(
                    knowledge_base_id,
                    failed_task_id,
                    alice_ctx,
                    settings,
                    db,
                )
                assert retried.id == failed_task_id
                await settle_open_tasks(db)

                # POST /{kb}/documents/{id}/parse — enqueue only.
                parse_task = await knowledge_api.parse_workspace_knowledge_base_document(
                    knowledge_base_id,
                    direct_document_id,
                    alice_ctx,
                    settings,
                    db,
                    None,
                )
                assert parse_task.task_type == "parse"
                await settle_open_tasks(db)

                # PUT /{kb}/owner — transfer away and back.
                transferred = await knowledge_api.transfer_workspace_knowledge_base_owner(
                    knowledge_base_id,
                    KnowledgeBaseOwnerTransferRequest(user_id=bob_id),
                    alice_ctx,
                    db,
                )
                assert transferred.created_by_user_id == bob_id
                transferred_back = (
                    await knowledge_api.transfer_workspace_knowledge_base_owner(
                        knowledge_base_id,
                        KnowledgeBaseOwnerTransferRequest(user_id=alice_id),
                        bob_ctx,
                        db,
                    )
                )
                assert transferred_back.created_by_user_id == alice_id

                # GET /{kb}/permissions.
                permissions = await knowledge_api.list_workspace_knowledge_base_permissions(
                    knowledge_base_id,
                    alice_ctx,
                    db,
                    100,
                    0,
                )
                assert permissions == []

                # PUT /{kb}/permissions/{user_id}.
                granted = await knowledge_api.grant_workspace_knowledge_base_permission(
                    knowledge_base_id,
                    bob_id,
                    ResourcePermissionUpsertRequest(permission="view"),
                    alice_ctx,
                    db,
                )
                assert granted.permission == "view"

                # DELETE /{kb}/permissions/{user_id}.
                revoked = await knowledge_api.revoke_workspace_knowledge_base_permission(
                    knowledge_base_id,
                    bob_id,
                    alice_ctx,
                    db,
                )
                assert revoked.status_code == 204

                # GET /{kb}/documents/{id}/download — present file.
                downloaded = await knowledge_lifecycle_api.download_workspace_knowledge_base_document(
                    knowledge_base_id,
                    document_id,
                    alice_ctx,
                    settings,
                    db,
                )
                assert downloaded.path.is_file()

                # GET /{kb}/documents/{id}/download — missing file -> 404.
                try:
                    await knowledge_lifecycle_api.download_workspace_knowledge_base_document(
                        knowledge_base_id,
                        missing_document_id,
                        alice_ctx,
                        settings,
                        db,
                    )
                except HTTPException as exc:
                    assert exc.status_code == 404
                else:
                    raise AssertionError("Download of a missing file was allowed.")

                # GET /{kb}/documents/{id}/assets/{asset_id}.
                asset_response = (
                    await knowledge_lifecycle_api.read_workspace_knowledge_document_asset(
                        knowledge_base_id,
                        document_id,
                        asset_id,
                        alice_ctx,
                        settings,
                        db,
                    )
                )
                assert asset_response.path.is_file()

                # Missing asset -> 404.
                try:
                    await knowledge_lifecycle_api.read_workspace_knowledge_document_asset(
                        knowledge_base_id,
                        document_id,
                        "00000000-0000-0000-0000-00000000deed",
                        alice_ctx,
                        settings,
                        db,
                    )
                except HTTPException as exc:
                    assert exc.status_code == 404
                else:
                    raise AssertionError("Missing asset was allowed.")

                # Asset row without an on-disk file -> 404.
                try:
                    await knowledge_lifecycle_api.read_workspace_knowledge_document_asset(
                        knowledge_base_id,
                        document_id,
                        missing_file_asset_id,
                        alice_ctx,
                        settings,
                        db,
                    )
                except HTTPException as exc:
                    assert exc.status_code == 404
                else:
                    raise AssertionError("Missing asset file was allowed.")

                # PATCH /{kb}/documents/{id} — status toggle.
                deactivated = (
                    await knowledge_lifecycle_api.update_workspace_knowledge_base_document_status(
                        knowledge_base_id,
                        document_id,
                        KnowledgeDocumentStatusUpdateRequest(is_active=False),
                        alice_ctx,
                        db,
                    )
                )
                assert deactivated.is_active is False
                reactivated = (
                    await knowledge_lifecycle_api.update_workspace_knowledge_base_document_status(
                        knowledge_base_id,
                        document_id,
                        KnowledgeDocumentStatusUpdateRequest(is_active=True),
                        alice_ctx,
                        db,
                    )
                )
                assert reactivated.is_active is True

                # DELETE /{kb}/documents/{id} — document lifecycle delete.
                deleted_document = (
                    await knowledge_lifecycle_api.delete_workspace_knowledge_base_document(
                        knowledge_base_id,
                        direct_document_id,
                        alice_ctx,
                        settings,
                        db,
                    )
                )
                assert deleted_document.status_code == 204

                # POST /{kb}/query — retrieval endpoint.
                queried = await knowledge_retrieval_api.query_workspace_knowledge_base(
                    knowledge_base_id,
                    KnowledgeQueryRequest(
                        query="direct query",
                        limit=2,
                        search_mode="keywords",
                    ),
                    alice_ctx,
                    settings,
                    db,
                )
                assert queried == []

                # -- Application-layer direct calls -------------------------
                # list_knowledge_documents_with_counts (chunk-count aggregation).
                with_counts = (
                    await knowledge_application.list_knowledge_documents_with_counts(
                        db,
                        knowledge_base,
                        include_staged=False,
                        limit=100,
                        offset=0,
                    )
                )
                assert any(item.id == document_id for item in with_counts)

                # document_response_with_chunk_count.
                source_document = await db.get(KnowledgeDocument, document_id)
                assert source_document is not None
                counted = (
                    await knowledge_application.document_response_with_chunk_count(
                        db,
                        knowledge_base,
                        source_document,
                    )
                )
                assert counted.id == document_id

                # get_knowledge_asset_file success + both 404 branches.
                resolved_asset, resolved_path = (
                    await knowledge_application.get_knowledge_asset_file(
                        db,
                        knowledge_base,
                        document_id,
                        asset_id,
                        settings,
                    )
                )
                assert resolved_path.is_file()
                assert resolved_asset.id == asset_id
                try:
                    await knowledge_application.get_knowledge_asset_file(
                        db,
                        knowledge_base,
                        document_id,
                        "00000000-0000-0000-0000-00000000deed",
                        settings,
                    )
                except HTTPException as exc:
                    assert exc.status_code == 404
                else:
                    raise AssertionError("Missing asset lookup was allowed.")
                try:
                    await knowledge_application.get_knowledge_asset_file(
                        db,
                        knowledge_base,
                        document_id,
                        missing_file_asset_id,
                        settings,
                    )
                except HTTPException as exc:
                    assert exc.status_code == 404
                else:
                    raise AssertionError("Missing asset file lookup was allowed.")

                # query_knowledge_base with embedding mode and no embedding
                # model -> 422.
                research_kb = await db.get(
                    KnowledgeBase,
                    research_knowledge_base_id,
                )
                assert research_kb is not None
                try:
                    await knowledge_application.query_knowledge_base(
                        db,
                        research_kb,
                        KnowledgeQueryRequest(
                            query="x",
                            limit=1,
                            search_mode="embedding",
                        ),
                        settings,
                    )
                except HTTPException as exc:
                    assert exc.status_code == 422
                else:
                    raise AssertionError(
                        "Embedding-model-required 422 was not raised."
                    )
        finally:
            knowledge_api.dispatch_knowledge_task = original_dispatch

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Unit-level edge paths (no API client required)
# ---------------------------------------------------------------------------


def test_rerank_child_hits_edge_paths() -> None:
    """retrieval.py: reranker-less, provider-error, and invalid-result branches."""
    hit_one = (
        SimpleNamespace(
            id="c1",
            document_id="d1",
            chunk_index=0,
            parent_id="p1",
            start_offset=0,
            end_offset=10,
            content="chunk one",
        ),
        VectorHit(chunk_id="c1", distance=0.1),
    )
    hit_two = (
        SimpleNamespace(
            id="c2",
            document_id="d1",
            chunk_index=1,
            parent_id="p1",
            start_offset=10,
            end_offset=20,
            content="chunk two",
        ),
        VectorHit(chunk_id="c2", distance=0.2),
    )
    hits = [hit_one, hit_two]

    async def run() -> None:
        # reranker_model None -> unchanged; empty hits -> unchanged
        assert (
            await knowledge_retrieval.rerank_child_hits(
                None,
                "q",
                hits,
                test_settings(),
            )
            == hits
        )
        assert (
            await knowledge_retrieval.rerank_child_hits(
                SimpleNamespace(id="m"),
                "q",
                [],
                test_settings(),
            )
            == []
        )

        # ModelProviderError from the reranker provider -> unchanged
        class ExplodingReranker:
            def rerank(self, query: str, documents: list[str]) -> list[dict]:
                raise ModelProviderError()

        with patch.object(
            knowledge_retrieval,
            "build_registered_reranker",
            return_value=ExplodingReranker(),
        ):
            assert (
                await knowledge_retrieval.rerank_child_hits(
                    SimpleNamespace(id="m"),
                    "q",
                    hits,
                    test_settings(),
                )
                == hits
            )

        # Non-dict results are skipped; valid dict entries reorder candidates
        class MixedReranker:
            def rerank(self, query: str, documents: list[str]) -> list[dict]:
                return [
                    None,
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.5},
                ]

        with patch.object(
            knowledge_retrieval,
            "build_registered_reranker",
            return_value=MixedReranker(),
        ):
            ordered = await knowledge_retrieval.rerank_child_hits(
                SimpleNamespace(id="m"),
                "q",
                hits,
                test_settings(),
            )
        assert [chunk.id for chunk, _ in ordered] == ["c2", "c1"]

        # No valid scored results -> unchanged
        class GarbageReranker:
            def rerank(self, query: str, documents: list[str]) -> list[dict]:
                return [
                    {"index": "nope", "relevance_score": 1.0},
                    {"index": 5, "relevance_score": "x"},
                ]

        with patch.object(
            knowledge_retrieval,
            "build_registered_reranker",
            return_value=GarbageReranker(),
        ):
            assert (
                await knowledge_retrieval.rerank_child_hits(
                    SimpleNamespace(id="m"),
                    "q",
                    hits,
                    test_settings(),
                )
                == hits
            )

    asyncio.run(run())


def test_query_application_vector_only_branch() -> None:
    """application/knowledge.py: embedding-only search must not touch keywords."""

    async def run() -> None:
        embedding_model = SimpleNamespace(id="model-1")
        vector_query = Mock(
            return_value=[VectorHit(chunk_id="c1", distance=0.5)]
        )
        keyword_query = Mock(
            side_effect=AssertionError("keyword search was called")
        )
        with patch.object(
            knowledge_application,
            "resolve_embedding_model",
            new=AsyncMock(return_value=embedding_model),
        ) as resolve_model, patch.object(
            knowledge_application,
            "query_vectors",
            new=vector_query,
        ), patch.object(
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
        ):
            hits = await knowledge_application.query_knowledge_base(
                object(),  # type: ignore[arg-type]
                SimpleNamespace(id="base-1"),  # type: ignore[arg-type]
                KnowledgeQueryRequest(
                    query="x",
                    limit=1,
                    search_mode="embedding",
                    similarity=0.5,
                ),
                test_settings(),
            )

        assert hits == []
        resolve_model.assert_awaited_once()
        vector_query.assert_called_once()
        assert vector_query.call_args.args[-2:] == (5, 0.5)
        keyword_query.assert_not_called()

    asyncio.run(run())


def test_vector_store_edge_paths() -> None:
    """vector_store.py: in-memory driver error paths + empty/batch boundaries."""
    settings = test_settings()
    original_build_embeddings = knowledge_vector_store.build_registered_embeddings
    original_client_builder = knowledge_vector_store._build_qdrant_client
    try:
        # Single-element batch round trip through the real in-memory driver.
        class OneDimEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.5, 0.5]] * len(texts)

            def embed_query(self, query: str) -> list[float]:
                return [0.5, 0.5]

        knowledge_vector_store.build_registered_embeddings = (
            lambda *_args: OneDimEmbeddings()
        )
        knowledge_vector_store.upsert_vectors(
            settings,
            "kb-single",
            "workspace-1",
            object(),  # type: ignore[arg-type]
            [
                VectorChunk(
                    id="00000000-0000-0000-0000-0000000000c1",
                    document_id="document-1",
                    document_filename="guide.txt",
                    chunk_index=0,
                    content="hello",
                    document_metadata={},
                )
            ],
        )
        query_hits = knowledge_vector_store.query_vectors(
            settings,
            "kb-single",
            object(),  # type: ignore[arg-type]
            "hello",
            3,
        )
        assert len(query_hits) == 1
        assert query_hits[0].chunk_id == "00000000-0000-0000-0000-0000000000c1"
        assert query_hits[0].distance < 0.001

        # Empty batches are no-ops.
        knowledge_vector_store.delete_vectors(settings, "kb-single", [])
        knowledge_vector_store.upsert_vectors(
            settings,
            "kb-single",
            "workspace-1",
            object(),  # type: ignore[arg-type]
            [],
        )

        # Non-positive limits return nothing without touching the store.
        assert (
            knowledge_vector_store.query_vectors(
                settings,
                "kb-single",
                object(),  # type: ignore[arg-type]
                "q",
                0,
            )
            == []
        )

        # Deleting a collection that does not exist logs and succeeds.
        knowledge_vector_store.delete_vector_collection(settings, "kb-absent")
        # Deleting vectors when the collection is absent logs and succeeds.
        knowledge_vector_store.delete_vectors(
            settings,
            "kb-absent-vectors",
            ["some-vector-id"],
        )

        # Embedding provider returning a wrong count -> ValueError.
        class WrongCountEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.5]]

        knowledge_vector_store.build_registered_embeddings = (
            lambda *_args: WrongCountEmbeddings()
        )
        try:
            knowledge_vector_store.upsert_vectors(
                settings,
                "kb-bad",
                "workspace-1",
                object(),  # type: ignore[arg-type]
                [
                    VectorChunk(
                        id="00000000-0000-0000-0000-0000000000d1",
                        document_id="document-1",
                        document_filename="a.txt",
                        chunk_index=0,
                        content="a",
                        document_metadata={},
                    ),
                    VectorChunk(
                        id="00000000-0000-0000-0000-0000000000d2",
                        document_id="document-1",
                        document_filename="b.txt",
                        chunk_index=1,
                        content="b",
                        document_metadata={},
                    ),
                ],
            )
        except ValueError as exc:
            assert "invalid document vectors" in str(exc)
        else:
            raise AssertionError("Invalid embedding vectors were accepted.")

        # Collection creation failing with a non-409 error propagates.
        class FailingCreateClient:
            def collection_exists(self, _collection_name: str) -> bool:
                return False

            def create_collection(self, *_args, **_kwargs) -> bool:
                raise knowledge_vector_store.UnexpectedResponse(
                    400,
                    "Bad Request",
                    b"",
                    {},
                )

        try:
            knowledge_vector_store._ensure_collection(
                FailingCreateClient(),
                "c-fail-create",
                2,
            )
        except knowledge_vector_store.UnexpectedResponse:
            pass
        else:
            raise AssertionError("Non-409 collection creation failure was swallowed.")

        # Collection metadata lookup failing after a silent create propagates.
        class FailingGetClient:
            def collection_exists(self, _collection_name: str) -> bool:
                return False

            def create_collection(self, *_args, **_kwargs) -> bool:
                return False

            def get_collection(self, _collection_name: str):
                raise knowledge_vector_store.UnexpectedResponse(
                    500,
                    "Internal Server Error",
                    b"{}",
                    {},
                )

        try:
            knowledge_vector_store._ensure_collection(
                FailingGetClient(),
                "c-fail-get",
                2,
            )
        except knowledge_vector_store.UnexpectedResponse:
            pass
        else:
            raise AssertionError("Collection metadata failure was swallowed.")

        # Upsert failing at the driver level propagates after logging.
        class FailingUpsertClient:
            def collection_exists(self, _collection_name: str) -> bool:
                return False

            def create_collection(self, *_args, **_kwargs) -> bool:
                return True

            def upsert(self, *_args, **_kwargs) -> None:
                raise RuntimeError("upsert boom")

        class ValidEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.5, 0.5]] * len(texts)

        knowledge_vector_store.build_registered_embeddings = (
            lambda *_args: ValidEmbeddings()
        )
        knowledge_vector_store._build_qdrant_client = (
            lambda *_args: FailingUpsertClient()
        )
        try:
            knowledge_vector_store.upsert_vectors(
                settings,
                "kb-upsert-fail",
                "workspace-1",
                object(),  # type: ignore[arg-type]
                [
                    VectorChunk(
                        id="00000000-0000-0000-0000-0000000000e1",
                        document_id="document-1",
                        document_filename="a.txt",
                        chunk_index=0,
                        content="a",
                        document_metadata={},
                    )
                ],
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Upsert failure was swallowed.")

        # Query failing at the driver level propagates after logging.
        class FailingQueryClient:
            def collection_exists(self, _collection_name: str) -> bool:
                return True

            def query_points(self, *_args, **_kwargs):
                raise RuntimeError("query boom")

        class QueryEmbeddings:
            def embed_query(self, query: str) -> list[float]:
                return [0.5, 0.5]

        knowledge_vector_store.build_registered_embeddings = (
            lambda *_args: QueryEmbeddings()
        )
        knowledge_vector_store._build_qdrant_client = (
            lambda *_args: FailingQueryClient()
        )
        try:
            knowledge_vector_store.query_vectors(
                settings,
                "kb-query-fail",
                object(),  # type: ignore[arg-type]
                "q",
                3,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Query failure was swallowed.")

        # URL branch of the cached client factory (no connection is opened).
        url_client = original_client_builder("http://127.0.0.1:9", "secret")
        url_client.close()
    finally:
        knowledge_vector_store.build_registered_embeddings = original_build_embeddings
        knowledge_vector_store._build_qdrant_client = original_client_builder
        knowledge_vector_store._build_qdrant_client.cache_clear()


def test_embedding_pipeline_edge_paths() -> None:
    """pipeline.py: split/clean/extract boundaries."""
    pipeline = knowledge_pipeline
    # asset_marker index overflow.
    try:
        pipeline.asset_marker(pipeline.ASSET_MARKER_LIMIT)
    except pipeline.KnowledgePipelineError:
        pass
    else:
        raise AssertionError("Asset marker overflow was accepted.")
    assert pipeline.asset_marker(0) == "\ue000"

    # clean_text rule branches.
    assert pipeline.clean_text("  a  \n b \n\n", ["trim_lines"]) == "a\nb"
    assert pipeline.clean_text("a\n\nb\n\n\n", ["remove_empty_lines"]) == "a\nb"
    assert (
        pipeline.clean_text(
            "a\n\nb\n\n\n",
            ["remove_empty_lines"],
            preserve_empty_lines=True,
        )
        == "a\n\nb"
    )

    # extract_with_pymupdf returning a non-string result.
    original_to_markdown = pipeline.pymupdf4llm.to_markdown
    pipeline.pymupdf4llm.to_markdown = lambda *_args, **_kwargs: 42
    try:
        try:
            pipeline.extract_with_pymupdf(
                "x.pdf",
                Path("/tmp/nonexistent-x.pdf"),
                force_ocr=False,
            )
        except TypeError:
            pass
        else:
            raise AssertionError("Non-string PyMuPDF result was accepted.")
    finally:
        pipeline.pymupdf4llm.to_markdown = original_to_markdown

    # extract_document with a missing file.
    try:
        pipeline.extract_document(
            "x.pdf",
            "application/pdf",
            Path("/tmp/definitely-missing-x.pdf"),
        )
    except pipeline.KnowledgePipelineError:
        pass
    else:
        raise AssertionError("Missing document file was accepted.")

    # extract_document where the converter raises.
    missing_convert_path = Path("/tmp/knowledge-pipeline-convert-fail.txt")
    missing_convert_path.write_bytes(b"content")
    original_convert_local = pipeline.MARKITDOWN.convert_local
    pipeline.MARKITDOWN.convert_local = (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    try:
        try:
            pipeline.extract_document(
                "convert-fail.txt",
                "text/plain",
                missing_convert_path,
            )
        except pipeline.KnowledgePipelineError as exc:
            assert "extraction failed" in str(exc)
        else:
            raise AssertionError("Converter failure was not wrapped.")
    finally:
        pipeline.MARKITDOWN.convert_local = original_convert_local
        missing_convert_path.unlink(missing_ok=True)

    # extract_document with no extractable text (converter returns whitespace).
    blank_path = Path("/tmp/knowledge-pipeline-blank.txt")
    blank_path.write_bytes(b"content")
    original_convert_local = pipeline.MARKITDOWN.convert_local
    pipeline.MARKITDOWN.convert_local = (
        lambda *_args, **_kwargs: SimpleNamespace(text_content="   \n  ")
    )
    try:
        try:
            pipeline.extract_document("blank.txt", "text/plain", blank_path)
        except pipeline.KnowledgePipelineError as exc:
            assert "no extractable text" in str(exc)
        else:
            raise AssertionError("Whitespace-only document was accepted.")
    finally:
        pipeline.MARKITDOWN.convert_local = original_convert_local
        blank_path.unlink(missing_ok=True)

    # Table detection: a row followed by a non-alignment row is not a table.
    non_table = pipeline.split_text_spans("| a |\n| b |")
    assert [span.content for span in non_table] == ["| a |\n| b |"]
    # A row followed by a line that is not pipe-delimited at all.
    non_pipe = pipeline.split_text_spans("| a |\nplain text")
    assert [span.content for span in non_pipe] == ["| a |\nplain text"]

    # Small table stays whole; trailing whitespace after the table is skipped.
    small_table = pipeline.split_text_spans("| h |\n| - |\n| d |\n\n")
    assert [span.content for span in small_table] == ["| h |\n| - |\n| d |\n"]

    # Header-only table that still exceeds the chunk size stays whole.
    header_only = pipeline.split_text_spans("| h |\n| - |\n", chunk_size=5)
    assert [span.content for span in header_only] == ["| h |\n| - |\n"]

    # Text before a table ends its run at the table boundary.
    prelude_table = pipeline.split_text_spans(
        "pre\n| h |\n| - |\n| d |",
        chunk_size=4,
    )
    assert [span.content for span in prelude_table] == [
        "pre",
        "| h |\n| - |\n| d |",
    ]

    # A child span whose content is only asset markers is dropped.
    drafts = pipeline.build_hierarchical_chunks("\ue000\ue000", chunk_size=10)
    assert drafts.children == []


# ---------------------------------------------------------------------------
# API-level flow
# ---------------------------------------------------------------------------


def test_knowledge_api_flow() -> None:
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
        alice_token = activate_user(
            client,
            "alice",
            alice_temp_password,
            MEMBER_PASSWORD,
        )
        bob_token = activate_user(
            client,
            "bob",
            bob_temp_password,
            MEMBER_PASSWORD,
        )

        research_admin_id, research_token = create_active_user(
            client,
            admin_token,
            "research-admin",
        )
        research_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "admin_user_id": research_admin_id,
            },
        )
        assert research_workspace.status_code == 201, research_workspace.text
        research_workspace_id = research_workspace.json()["workspace"]["id"]

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

        # -- Knowledge base CRUD -------------------------------------------
        knowledge_base = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={
                "name": "Product Docs",
                "description": "Internal product answers",
                "embedding_model_id": embedding_model_id,
                "reranker_model_id": reranker_model_id,
            },
        )
        assert knowledge_base.status_code == 201, knowledge_base.text
        knowledge_base_id = knowledge_base.json()["id"]

        duplicate_name = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(bob_token),
            json={"name": "Product Docs"},
        )
        assert duplicate_name.status_code == 409, duplicate_name.text

        missing_base = client.get(
            knowledge_url(default_workspace_id, "/00000000-0000-0000-0000-00000000dead"),
            headers=auth_headers(alice_token),
        )
        assert missing_base.status_code == 404, missing_base.text

        fetched_base = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
        )
        assert fetched_base.status_code == 200, fetched_base.text
        assert fetched_base.json()["permission"] == "edit"

        patched_base = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={"description": "Updated description"},
        )
        assert patched_base.status_code == 200, patched_base.text
        assert patched_base.json()["description"] == "Updated description"

        bad_limit = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            params={"limit": 0},
        )
        assert bad_limit.status_code == 422, bad_limit.text
        bad_offset = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            params={"offset": -1},
        )
        assert bad_offset.status_code == 422, bad_offset.text

        # -- Documents: attachment upload + creation ------------------------
        denied_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(bob_token),
        )
        assert denied_documents.status_code == 403, denied_documents.text

        attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("guide.txt", b"Hello from product docs", "text/plain")},
        )
        assert attachment.status_code == 201, attachment.text
        attachment_id = attachment.json()["id"]

        empty_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert empty_attachment.status_code == 422, empty_attachment.text

        restricted_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("机密-guide.txt", b"x", "text/plain")},
        )
        assert restricted_attachment.status_code == 422, restricted_attachment.text

        bob_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(bob_token),
            files={"file": ("bob.txt", b"nope", "text/plain")},
        )
        assert bob_attachment.status_code == 403, bob_attachment.text

        created_document = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            json={"attachment_ids": [attachment_id], "staged": False},
        )
        assert created_document.status_code == 201, created_document.text
        document_id = created_document.json()[0]["id"]
        assert created_document.json()[0]["status"] == "uploaded"

        consumed_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            json={"attachment_ids": [attachment_id]},
        )
        assert consumed_attachment.status_code == 409, consumed_attachment.text

        missing_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            json={"attachment_ids": ["00000000-0000-0000-0000-00000000deed"]},
        )
        assert missing_attachment.status_code == 404, missing_attachment.text

        documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert documents.status_code == 200, documents.text
        assert [item["id"] for item in documents.json()] == [document_id]
        staged_documents = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            params={"include_staged": True},
        )
        assert staged_documents.status_code == 200, staged_documents.text

        # -- Chunks / tasks / parse / index ---------------------------------
        empty_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert empty_chunks.status_code == 200, empty_chunks.text
        assert empty_chunks.json() == []

        missing_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/00000000-0000-0000-0000-00000000deed/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_chunks.status_code == 404, missing_chunks.text

        parsed_document = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"auto_index": False},
        )
        assert parsed_document.status_code == 202, parsed_document.text

        document_tasks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/tasks",
            ),
            headers=auth_headers(alice_token),
        )
        assert document_tasks.status_code == 200, document_tasks.text
        assert {"parse"} == {item["task_type"] for item in document_tasks.json()}

        knowledge_tasks = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/tasks"),
            headers=auth_headers(alice_token),
        )
        assert knowledge_tasks.status_code == 200, knowledge_tasks.text
        assert {"parse"} == {item["task_type"] for item in knowledge_tasks.json()}

        parsed_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert parsed_chunks.status_code == 200, parsed_chunks.text
        assert [chunk["content"] for chunk in parsed_chunks.json()] == [
            "Hello from product docs"
        ]

        indexed_document = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/index",
            ),
            headers=auth_headers(alice_token),
        )
        assert indexed_document.status_code == 202, indexed_document.text

        # -- Model test ------------------------------------------------------
        model_test = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/model-test"),
            headers=auth_headers(alice_token),
            json={"query": "Hello", "documents": ["Hello"]},
        )
        assert model_test.status_code == 200, model_test.text
        assert model_test.json()["embedding_dimensions"] == 1
        assert model_test.json()["reranker_results"] == 1

        bob_model_test = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/model-test"),
            headers=auth_headers(bob_token),
            json={"query": "Hello", "documents": ["Hello"]},
        )
        assert bob_model_test.status_code == 403, bob_model_test.text

        # -- Query endpoint --------------------------------------------------
        # Keyword search is PostgreSQL-only; on SQLite it returns no hits.
        keyword_query = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/query"),
            headers=auth_headers(alice_token),
            json={"query": "product docs", "limit": 5, "search_mode": "keywords"},
        )
        assert keyword_query.status_code == 200, keyword_query.text
        assert keyword_query.json() == []

        denied_query = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/query"),
            headers=auth_headers(bob_token),
            json={"query": "product docs", "limit": 5, "search_mode": "keywords"},
        )
        assert denied_query.status_code == 403, denied_query.text

        blend_query = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/query"),
            headers=auth_headers(alice_token),
            json={"query": "product docs", "limit": 5, "search_mode": "blend"},
        )
        assert blend_query.status_code == 200, blend_query.text
        assert blend_query.json()[0]["document_id"] == document_id
        assert blend_query.json()[0]["content"] == "Hello from product docs"

        # -- Permissions: list / grant / revoke ------------------------------
        permissions = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions"),
            headers=auth_headers(alice_token),
        )
        assert permissions.status_code == 200, permissions.text
        assert permissions.json() == []

        granted = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["permission"] == "view"

        permissions_after_grant = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions"),
            headers=auth_headers(alice_token),
        )
        assert permissions_after_grant.status_code == 200, permissions_after_grant.text
        assert [(item["user"]["username"], item["permission"]) for item in permissions_after_grant.json()] == [
            ("bob", "view")
        ]

        revoked = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert revoked.status_code == 204, revoked.text

        # -- Owner transfer ---------------------------------------------------
        transferred = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(alice_token),
            json={"user_id": bob_id},
        )
        assert transferred.status_code == 200, transferred.text
        assert transferred.json()["created_by_user_id"] == bob_id

        transferred_back = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(bob_token),
            json={"user_id": alice_id},
        )
        assert transferred_back.status_code == 200, transferred_back.text
        assert transferred_back.json()["created_by_user_id"] == alice_id

        # -- Lifecycle: download ----------------------------------------------
        denied_download = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/download",
            ),
            headers=auth_headers(bob_token),
        )
        assert denied_download.status_code == 403, denied_download.text

        downloaded = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/download",
            ),
            headers=auth_headers(alice_token),
        )
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == b"Hello from product docs"

        missing_download_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "missing-file.txt",
            b"File will disappear",
            "text/plain",
        )
        missing_download_document_id = missing_download_document["id"]
        asyncio.run(delete_document_file(missing_download_document_id))
        missing_download = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{missing_download_document_id}/download",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_download.status_code == 404, missing_download.text

        missing_document_download = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/00000000-0000-0000-0000-00000000deed/download",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_document_download.status_code == 404, missing_document_download.text

        # -- Lifecycle: assets -------------------------------------------------
        asset_id = "00000000-0000-0000-0000-0000000000a1"
        asset_object_key = "assets/asset-1.png"
        asyncio.run(
            insert_asset(
                default_workspace_id,
                knowledge_base_id,
                document_id,
                asset_id,
                0,
                asset_object_key,
                "asset-1.png",
                "image/png",
            )
        )
        asset_path = knowledge_application.knowledge_object_storage(
            test_settings()
        ).path(asset_object_key)
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(b"png-bytes")

        asset_response = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/assets/{asset_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert asset_response.status_code == 200, asset_response.text
        assert asset_response.content == b"png-bytes"

        missing_asset = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/assets/00000000-0000-0000-0000-00000000deed",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_asset.status_code == 404, missing_asset.text

        missing_file_asset_id = "00000000-0000-0000-0000-0000000000a2"
        asyncio.run(
            insert_asset(
                default_workspace_id,
                knowledge_base_id,
                document_id,
                missing_file_asset_id,
                1,
                "assets/asset-2.png",
                "asset-2.png",
                "image/png",
            )
        )
        missing_file_asset = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/assets/{missing_file_asset_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_file_asset.status_code == 404, missing_file_asset.text

        # -- Lifecycle: document status toggle ----------------------------------
        deactivated = client.patch(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}",
            ),
            headers=auth_headers(alice_token),
            json={"is_active": False},
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["is_active"] is False

        reactivated = client.patch(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}",
            ),
            headers=auth_headers(alice_token),
            json={"is_active": True},
        )
        assert reactivated.status_code == 200, reactivated.text
        assert reactivated.json()["is_active"] is True

        # -- Lifecycle: delete attachment ----------------------------------------
        disposable_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("disposable.txt", b"disposable", "text/plain")},
        )
        assert disposable_attachment.status_code == 201, disposable_attachment.text
        disposable_attachment_id = disposable_attachment.json()["id"]

        deleted_attachment = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/attachments/{disposable_attachment_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_attachment.status_code == 204, deleted_attachment.text

        missing_attachment_delete = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/attachments/00000000-0000-0000-0000-00000000deed",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_attachment_delete.status_code == 404, missing_attachment_delete.text

        # -- Hierarchical document + query aggregation branches -------------------
        hierarchical_content = (
            b"# First\n\n" + b"First paragraph " * 80 + b"\n\n# Second\n\n" + b"Second " * 80
        )
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
        hierarchical_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{hierarchical_document_id}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert hierarchical_chunks.status_code == 200, hierarchical_chunks.text
        assert all(
            chunk["parent_id"] is not None for chunk in hierarchical_chunks.json()
        )

        hierarchical_index = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{hierarchical_document_id}/index",
            ),
            headers=auth_headers(alice_token),
        )
        assert hierarchical_index.status_code == 202, hierarchical_index.text

        (
            _,
            hier_chunks,
            hier_parents,
            flat_chunk_id,
        ) = asyncio.run(
            load_hierarchical_rows(
                knowledge_base_id,
                hierarchical_document_id,
                document_id,
            )
        )
        first_children = [
            chunk for chunk in hier_chunks if chunk.parent_id == hier_parents[0].id
        ]
        second_children = [
            chunk for chunk in hier_chunks if chunk.parent_id == hier_parents[1].id
        ]
        assert first_children
        assert second_children

        # A reranker model of the wrong type falls back to raw order
        # (application 291-292: get_knowledge_model raises, caught).
        asyncio.run(
            set_knowledge_base_reranker_model(
                knowledge_base_id,
                embedding_model_id,
            )
        )

        def hierarchical_query(
            hits: list[VectorHit],
            limit: int,
            orphan_parents: bool = False,
        ) -> list:
            async def run() -> list:
                original_query_vectors = knowledge_application.query_vectors
                original_keyword_query = knowledge_repository.query_keyword_chunk_ids
                parent_lookup_patch = (
                    patch.object(
                        knowledge_repository,
                        "list_parent_chunks_by_ids",
                        new=AsyncMock(return_value=[]),
                    )
                    if orphan_parents
                    else nullcontext()
                )
                try:
                    async with get_session_factory()() as db:
                        knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
                        assert knowledge_base is not None

                        def fake_query_vectors(*_args) -> list[VectorHit]:
                            return hits

                        async def fake_keyword_query(*_args) -> list[str]:
                            return []

                        knowledge_application.query_vectors = fake_query_vectors
                        knowledge_repository.query_keyword_chunk_ids = fake_keyword_query
                        with parent_lookup_patch:
                            return await knowledge_application.query_knowledge_base(
                                db,
                                knowledge_base,
                                KnowledgeQueryRequest(
                                    query="hierarchical query",
                                    limit=limit,
                                ),
                                test_settings(),
                            )
                finally:
                    knowledge_application.query_vectors = original_query_vectors
                    knowledge_repository.query_keyword_chunk_ids = original_keyword_query

            return asyncio.run(run())

        # Reranker-missing fallback + duplicate parent unit deduplication.
        merged_hits = hierarchical_query(
            [
                VectorHit(chunk_id=first_children[0].id, distance=0.1),
                VectorHit(chunk_id=first_children[1].id, distance=0.2),
                VectorHit(chunk_id=second_children[0].id, distance=0.3),
            ],
            limit=2,
        )
        assert [hit.parent_id for hit in merged_hits] == [
            hier_parents[0].id,
            hier_parents[1].id,
        ]

        # Flat hit inside a hierarchical result set is aggregated by document.
        mixed_hits = hierarchical_query(
            [
                VectorHit(chunk_id=first_children[0].id, distance=0.1),
                VectorHit(chunk_id=flat_chunk_id, distance=0.2),
            ],
            limit=2,
        )
        assert [hit.parent_id for hit in mixed_hits] == [
            hier_parents[0].id,
            None,
        ]
        assert mixed_hits[1].document_id == document_id

        # Child whose parent is missing is skipped.
        orphan_hits = hierarchical_query(
            [
                VectorHit(chunk_id=first_children[0].id, distance=0.1),
                VectorHit(chunk_id=second_children[0].id, distance=0.2),
            ],
            limit=2,
            orphan_parents=True,
        )
        assert orphan_hits == []

        # -- Retry a failed task -------------------------------------------------
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
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{failed_parse_document_id}/parse",
            ),
            headers=auth_headers(alice_token),
        )
        assert failed_parse_enqueue.status_code == 202, failed_parse_enqueue.text
        failed_parse_tasks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{failed_parse_document_id}/tasks",
            ),
            headers=auth_headers(alice_token),
        )
        assert failed_parse_tasks.status_code == 200, failed_parse_tasks.text
        failed_task = next(
            item for item in failed_parse_tasks.json() if item["status"] == "failed"
        )
        retried_task = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/tasks/{failed_task['id']}/retry",
            ),
            headers=auth_headers(alice_token),
        )
        assert retried_task.status_code == 202, retried_task.text
        assert retried_task.json()["id"] == failed_task["id"]

        # -- Rebuild index ---------------------------------------------------------
        rebuild_task = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert rebuild_task.status_code == 202, rebuild_task.text
        assert rebuild_task.json()["task_type"] == "rebuild_index"

        # -- Model-less workspace: empty query + embedding-model-required error ----
        research_knowledge_base = client.post(
            knowledge_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"name": "Research KB"},
        )
        assert research_knowledge_base.status_code == 201, research_knowledge_base.text
        research_knowledge_base_id = research_knowledge_base.json()["id"]

        empty_query = client.post(
            knowledge_url(
                research_workspace_id,
                f"/{research_knowledge_base_id}/query",
            ),
            headers=auth_headers(research_token),
            json={"query": "anything", "limit": 5, "search_mode": "keywords"},
        )
        assert empty_query.status_code == 200, empty_query.text
        assert empty_query.json() == []

        embedding_required = client.post(
            knowledge_url(
                research_workspace_id,
                f"/{research_knowledge_base_id}/query",
            ),
            headers=auth_headers(research_token),
            json={"query": "anything", "limit": 5, "search_mode": "embedding"},
        )
        assert embedding_required.status_code == 422, embedding_required.text

        # -- Direct endpoint calls -------------------------------------------------
        # Restore the real reranker model first (the hierarchical query tests
        # pointed it at the embedding model to exercise the fallback branch).
        asyncio.run(
            set_knowledge_base_reranker_model(
                knowledge_base_id,
                reranker_model_id,
            )
        )

        # A freshly failed parse task for the direct retry call.
        direct_retry_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "direct-retry.bin",
            b"\x00\x01\x02",
            "application/octet-stream",
        )
        direct_retry_document_id = direct_retry_document["id"]
        direct_retry_enqueue = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{direct_retry_document_id}/parse",
            ),
            headers=auth_headers(alice_token),
        )
        assert direct_retry_enqueue.status_code == 202, direct_retry_enqueue.text
        direct_retry_tasks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{direct_retry_document_id}/tasks",
            ),
            headers=auth_headers(alice_token),
        )
        assert direct_retry_tasks.status_code == 200, direct_retry_tasks.text
        direct_retry_task_id = next(
            item["id"]
            for item in direct_retry_tasks.json()
            if item["status"] == "failed"
        )

        exercise_direct_endpoint_calls(
            default_workspace_id,
            knowledge_base_id,
            document_id,
            missing_download_document_id,
            direct_retry_task_id,
            alice_id,
            bob_id,
            reranker_model_id,
            asset_id,
            missing_file_asset_id,
            research_knowledge_base_id,
            research_admin_id,
        )

        # Settle the tasks the direct dispatch-free calls left queued.
        asyncio.run(recover_knowledge_tasks(test_settings()))

        # -- Lifecycle: delete documents -------------------------------------------
        deleted_document = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_document.status_code == 204, deleted_document.text

        deleted_missing_file_document = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{missing_download_document_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_missing_file_document.status_code == 204, deleted_missing_file_document.text

        # -- Concurrency conflicts on a scratch knowledge base -----------------------
        concurrent_knowledge_base = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={"name": "Concurrency KB"},
        )
        assert concurrent_knowledge_base.status_code == 201, concurrent_knowledge_base.text
        concurrent_knowledge_base_id = concurrent_knowledge_base.json()["id"]
        concurrent_document = upload_document(
            client,
            alice_token,
            default_workspace_id,
            concurrent_knowledge_base_id,
            "concurrent.txt",
            b"Concurrent document",
            "text/plain",
        )
        concurrent_document_id = concurrent_document["id"]
        asyncio.run(
            enqueue_recoverable_parse_task(
                concurrent_knowledge_base_id,
                concurrent_document_id,
                "alice",
            )
        )
        concurrent_parse = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{concurrent_knowledge_base_id}/documents/{concurrent_document_id}/parse",
            ),
            headers=auth_headers(alice_token),
        )
        assert concurrent_parse.status_code == 409, concurrent_parse.text
        concurrent_rebuild = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{concurrent_knowledge_base_id}/rebuild-index",
            ),
            headers=auth_headers(alice_token),
        )
        assert concurrent_rebuild.status_code == 409, concurrent_rebuild.text
        concurrent_delete = client.delete(
            knowledge_url(default_workspace_id, f"/{concurrent_knowledge_base_id}"),
            headers=auth_headers(alice_token),
        )
        assert concurrent_delete.status_code == 409, concurrent_delete.text

        # -- Delete the knowledge base (direct call, success path) -------------------
        original_storage_cleanup = (
            knowledge_application.enqueue_knowledge_storage_cleanup
        )
        knowledge_application.enqueue_knowledge_storage_cleanup = AsyncMock()

        async def delete_base_directly() -> None:
            async with get_session_factory()() as db:
                delete_ctx = SimpleNamespace(
                    workspace=SimpleNamespace(id=default_workspace_id),
                    user=SimpleNamespace(
                        id=alice_id,
                        username="alice",
                        name="Alice",
                    ),
                    membership_role=None,
                )
                deleted = await knowledge_api.delete_workspace_knowledge_base(
                    knowledge_base_id,
                    delete_ctx,
                    test_settings(),
                    db,
                )
                assert deleted.status_code == 204

        try:
            asyncio.run(delete_base_directly())
        finally:
            knowledge_application.enqueue_knowledge_storage_cleanup = (
                original_storage_cleanup
            )


def main() -> None:
    test_rerank_child_hits_edge_paths()
    test_query_application_vector_only_branch()
    test_vector_store_edge_paths()
    test_embedding_pipeline_edge_paths()
    test_knowledge_api_flow()
    print("KNOWLEDGE_API_COVERAGE_SUITE_OK")


if __name__ == "__main__":
    main()

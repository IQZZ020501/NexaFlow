"""Knowledge domain coverage suite.

Targets the knowledge shared domain (kb / lifecycle / orchestration /
documents / cleanup / permissions / task_runner), the Celery task bodies
(``app.tasks.knowledge``) and the knowledge repository.  Runs as a plain
script: ``uv run python -m tests.knowledge_domain_coverage`` from
``backend/``.
"""

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    create_active_user,
    settings as test_settings,
    test_client,
)
from tests.llm import model_test_server

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.session import get_session_factory
from app.infrastructure.model_utils import new_id, utc_now
from app.entities.knowledge import (
    CHUNK_INDEXED_STATUS,
    CHUNK_INDEX_FAILED_STATUS,
    CHUNK_PREVIEW_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_INDEX_FAILED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_INDEX_QUEUED_STATUS,
    DOCUMENT_PARSED_STATUS,
    KnowledgeAsset,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeStorageCleanup,
    KnowledgeTask,
    TASK_FAILED_STATUS,
    TASK_INDEX,
    TASK_PARSE,
    TASK_QUEUED_STATUS,
    TASK_REBUILD_INDEX,
    TASK_RUNNING_STATUS,
    TASK_SUCCEEDED_STATUS,
)
from app.entities.user import User
from app.entities.workflows import WorkflowUploadStorageCleanup
from app.infrastructure.celery import celery_app
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.shareddomain.knowledge import cleanup as cleanup_service
from app.shareddomain.knowledge import documents as documents_service
from app.shareddomain.knowledge import kb as kb_service
from app.shareddomain.knowledge import lifecycle as lifecycle_service
from app.shareddomain.knowledge import orchestration as orchestration_service
from app.shareddomain.knowledge import permissions as permissions_service
from app.shareddomain.knowledge import task_runner as task_runner_service
from app.shareddomain.knowledge import models as knowledge_models
from app.tasks import knowledge as knowledge_tasks_module
from app.tasks.knowledge import (
    enqueue_knowledge_storage_cleanup,
    enqueue_knowledge_task,
    recover_knowledge_tasks_job,
    reconcile_knowledge_graphs_job,
    enqueue_upload_storage_cleanups,
    recover_knowledge_storage_cleanups_job,
    recover_upload_storage_cleanups_job,
    run_knowledge_storage_cleanup_job,
    run_knowledge_task_job,
    run_upload_storage_cleanup_job,
)
from app.schemas.knowledge import (
    KnowledgeDocumentParseRequest,
    KnowledgeModelTestRequest,
)
from app.capabilities.embedding.pipeline import (
    ChildChunkDraft,
    DocumentAssetDraft,
    DocumentChunkDrafts,
    KnowledgePipelineError,
    ParentChunkDraft,
)
from app.ports.llm import ModelProviderError, ModelProviderStatusError
from app.shareddomain.knowledge.orchestration import (
    enqueue_parse_knowledge_document,
)
from app.shareddomain.knowledge.task_runner import (
    TASK_RUN_BUSY,
    TASK_RUN_FINISHED,
    batches,
    ensure_knowledge_task_lease,
    get_task_scope,
    maintain_knowledge_task_lease,
    mark_knowledge_task_failed,
    recover_knowledge_tasks,
    run_parse_task,
    run_knowledge_task,
)
from app.capabilities.llm.models import RegisteredModel

MEMBER_PASSWORD = "Member@12345."

# Stashed ids filled by the async scenario, consumed by the sync celery-job
# section (celery jobs call asyncio.run internally and cannot run inside an
# event loop).
STASH = {}


def knowledge_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge-bases{suffix}"


def models_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/models{suffix}"


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


def create_model(
    client,
    token: str,
    workspace_id: str,
    name: str,
    model_type: str,
    model_name: str,
    provider: str = "model_openai_provider",
    provider_type: str = "openai_compatible",
    api_base: str = "http://127.0.0.1:1/v1",
) -> str:
    response = client.post(
        models_url(workspace_id),
        headers=auth_headers(token),
        json={
            "name": name,
            "provider": provider,
            "provider_type": provider_type,
            "model_type": model_type,
            "model_name": model_name,
            "credential": {
                "api_base": api_base,
                "api_key": "sk-test-1234",
            },
            "meta": {"source": "coverage-suite"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


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


async def enqueue_parse(
    knowledge_base_id: str,
    document_id: str,
    actor_username: str,
    options: dict | None = None,
) -> str:
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
        payload = (
            KnowledgeDocumentParseRequest(**options) if options is not None else None
        )
        task = await enqueue_parse_knowledge_document(
            db,
            knowledge_base,
            document,
            actor,
            payload,
        )
        return task.id


async def create_task_row(
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str | None,
    task_type: str,
    actor_user_id: str,
    *,
    status: str = TASK_QUEUED_STATUS,
    attempts: int = 0,
    options: dict | None = None,
) -> KnowledgeTask:
    async with get_session_factory()() as db:
        task = KnowledgeTask(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            task_type=task_type,
            status=status,
            attempts=attempts,
            max_attempts=3,
            total_items=0,
            processed_items=0,
            options=options or {},
            created_by_user_id=actor_user_id,
        )
        task = await knowledge_repository.create_knowledge_task(db, task)
        await db.commit()
        return task


async def set_task_status_sync(db, task_id: str, status: str) -> None:
    task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
    assert task is not None
    task.status = status
    task.finished_at = utc_now()
    await knowledge_repository.save_knowledge_task(db, task)


async def create_cleanup_record(
    workspace_id: str,
    knowledge_base_id: str,
) -> str:
    async with get_session_factory()() as db:
        cleanup = await knowledge_repository.create_knowledge_storage_cleanup(
            db,
            KnowledgeStorageCleanup(
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base_id,
            ),
        )
        await db.commit()
        return cleanup.id


async def list_due_cleanup_ids(limit: int = 100) -> list[str]:
    async with get_session_factory()() as db:
        return await knowledge_repository.list_due_knowledge_storage_cleanup_ids(
            db,
            utc_now(),
            limit,
        )


async def run_single_cleanup(cleanup_id: str) -> None:
    await cleanup_service.run_knowledge_storage_cleanup(
        cleanup_id,
        test_settings(),
    )


async def write_preview_chunks(knowledge_base_id: str, document_id: str) -> None:
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, knowledge_base_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(db, document_id)
        assert kb is not None and doc is not None
        db.add(
            knowledge_models.KnowledgeDocumentChunk(
                id=new_id(),
                workspace_id=kb.workspace_id,
                knowledge_base_id=kb.id,
                document_id=document_id,
                parent_id=None,
                chunk_index=0,
                start_offset=None,
                end_offset=None,
                content="index me please",
                char_count=15,
                token_count=4,
                vector_id=None,
                status=CHUNK_PREVIEW_STATUS,
            )
        )
        await db.commit()


async def save_asset(db, asset: KnowledgeAsset) -> KnowledgeAsset:
    db.add(
        knowledge_models.KnowledgeAsset(
            id=asset.id,
            workspace_id=asset.workspace_id,
            knowledge_base_id=asset.knowledge_base_id,
            document_id=asset.document_id,
            asset_index=asset.asset_index,
            kind=asset.kind,
            filename=asset.filename,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            object_key=asset.object_key,
            alt_text=asset.alt_text,
            meta=asset.meta,
        )
    )
    await db.flush()
    return asset


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_parse_task_options() -> None:
    from fastapi import HTTPException

    options = orchestration_service.parse_task_options(None)
    assert options["strategy"] == "flat"
    assert options["cleaning_rules"] == []

    deduped = orchestration_service.parse_task_options(
        KnowledgeDocumentParseRequest(cleaning_rules=["trim_lines", "trim_lines"])
    )
    assert deduped["cleaning_rules"] == ["trim_lines"]

    try:
        orchestration_service.parse_task_options(
            KnowledgeDocumentParseRequest(chunk_size=100, chunk_overlap=100)
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("overlap >= chunk size must be rejected")

    try:
        orchestration_service.parse_task_options(
            KnowledgeDocumentParseRequest(split_separator=";;")
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("unsupported separator must be rejected")

    try:
        orchestration_service.parse_task_options(
            KnowledgeDocumentParseRequest(cleaning_rules=["bogus"])
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("unknown cleaning rule must be rejected")

    task = KnowledgeTask(
        id=new_id(),
        workspace_id="ws",
        knowledge_base_id="kb",
        task_type=TASK_PARSE,
        status=TASK_QUEUED_STATUS,
        attempts=0,
        max_attempts=3,
        total_items=0,
        processed_items=0,
        options={"chunk_size": 300},
        created_by_user_id="u",
    )
    from_task = orchestration_service.parse_task_options_from_task(task)
    assert from_task["chunk_size"] == 300
    assert from_task["strategy"] == "flat"


def test_clean_upload_filename() -> None:
    from fastapi import HTTPException

    assert documents_service.clean_upload_filename("guide.txt") == "guide.txt"
    long_name = "a" * 300 + ".txt"
    assert len(documents_service.clean_upload_filename(long_name)) == 255
    try:
        documents_service.clean_upload_filename("")
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("empty filename must be rejected")
    try:
        documents_service.clean_upload_filename("机密报告.pdf")
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("restricted filename must be rejected")


def test_batches_and_task_error_message() -> None:
    assert batches([], 2) == []
    assert batches([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert batches([1, 2, 3], 10) == [[1, 2, 3]]

    message = orchestration_service.task_error_message(
        SimpleNamespace(detail="detail message")
    )
    assert message == "detail message"
    assert orchestration_service.task_error_message(ValueError("plain")) == "plain"
    assert orchestration_service.task_error_message(ValueError("")) == "ValueError"


def test_run_knowledge_model_test_branches() -> None:
    from fastapi import HTTPException

    settings = test_settings()
    model = SimpleNamespace(id="model-1")
    request = KnowledgeModelTestRequest(query="q", documents=["d"])

    with patch.object(
        kb_service, "build_embeddings"
    ) as build_embeddings, patch.object(
        kb_service, "build_reranker"
    ) as build_reranker:
        build_embeddings.return_value = SimpleNamespace(
            embed_query=Mock(return_value=[0.1, 0.2])
        )
        build_reranker.return_value = SimpleNamespace(
            rerank=Mock(return_value=[{"index": 0, "relevance_score": 1.0}])
        )
        response = kb_service.run_knowledge_model_test(
            model,
            model,
            request,
            settings,
        )
        assert response.embedding_dimensions == 2
        assert response.reranker_results == 1
        assert response.reranker_model_id == "model-1"

        build_reranker.reset_mock()
        response_without_reranker = kb_service.run_knowledge_model_test(
            model,
            None,
            request,
            settings,
        )
        assert response_without_reranker.reranker_results == 0
        assert response_without_reranker.reranker_model_id is None
        build_reranker.assert_not_called()

        build_embeddings.return_value.embed_query = Mock(
            side_effect=ModelProviderStatusError(status_code=401)
        )
        try:
            kb_service.run_knowledge_model_test(model, None, request, settings)
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "401" in exc.detail
        else:
            raise AssertionError("provider status error must map to 400")

        build_embeddings.return_value.embed_query = Mock(
            side_effect=ModelProviderError("boom")
        )
        try:
            kb_service.run_knowledge_model_test(model, None, request, settings)
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "request failed" in exc.detail
        else:
            raise AssertionError("provider error must map to 400")


def test_ensure_knowledge_task_lease() -> None:
    event = asyncio.Event()
    event.set()
    try:
        ensure_knowledge_task_lease(event)
    except KnowledgePipelineError:
        pass
    else:
        raise AssertionError("lease-lost event must abort the task")

    ensure_knowledge_task_lease(asyncio.Event())


def test_maintain_knowledge_task_lease() -> None:
    async def scenario() -> None:
        event = asyncio.Event()
        with patch.object(
            knowledge_repository, "renew_knowledge_task_lease"
        ) as renew, patch.object(
            task_runner_service, "TASK_LEASE_RENEW_SECONDS", 0.01
        ):
            renew.side_effect = [True, False]
            await maintain_knowledge_task_lease("task-1", "worker-1", event)
            assert event.is_set()

        event2 = asyncio.Event()
        with patch.object(
            knowledge_repository, "renew_knowledge_task_lease"
        ) as renew, patch.object(
            task_runner_service, "TASK_LEASE_RENEW_SECONDS", 0.01
        ):
            renew.side_effect = RuntimeError("renew failed")
            await maintain_knowledge_task_lease("task-2", "worker-2", event2)
            assert event2.is_set()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# API-driven scenario
# ---------------------------------------------------------------------------


def test_api_scenario(model_base_url: str) -> None:
    with test_client() as client:
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
        research_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "description": "研究空间",
                "admin_user_id": research_admin_id,
            },
        )
        assert research_workspace.status_code == 201, research_workspace.text
        research_workspace_id = research_workspace.json()["workspace"]["id"]

        cleanup_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Cleanup Workspace",
                "description": "用于 cleanup 与模型校验",
                "admin_user_id": research_admin_id,
            },
        )
        assert cleanup_workspace.status_code == 201, cleanup_workspace.text
        cleanup_workspace_id = cleanup_workspace.json()["workspace"]["id"]

        delete_ws = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Delete Workspace",
                "description": "用于 delete_workspace_knowledge_bases",
                "admin_user_id": research_admin_id,
            },
        )
        assert delete_ws.status_code == 201, delete_ws.text
        delete_ws_id = delete_ws.json()["workspace"]["id"]

        # ---- model registration (main workspace) ----
        embedding_model_id = create_model(
            client,
            admin_token,
            default_workspace_id,
            "Coverage Embedding",
            "EMBEDDING",
            "text-embedding-3-small",
            api_base=model_base_url,
        )
        reranker_model_id = create_model(
            client,
            admin_token,
            default_workspace_id,
            "Coverage Reranker",
            "RERANKER",
            "custom-reranker",
            provider="model_custom_provider",
            api_base=model_base_url,
        )

        # ---- knowledge base creation ----
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
        assert knowledge_base.json()["embedding_model_id"] == embedding_model_id
        assert knowledge_base.json()["reranker_model_id"] == reranker_model_id
        assert knowledge_base.json()["permission"] == "edit"

        duplicate_name = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={"name": "Product Docs", "description": "duplicate"},
        )
        assert duplicate_name.status_code == 409, duplicate_name.text

        missing_model = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={
                "name": "Bad Model KB",
                "embedding_model_id": "00000000-0000-0000-0000-000000000099",
            },
        )
        assert missing_model.status_code == 422, missing_model.text

        wrong_type_model = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={
                "name": "Wrong Type KB",
                "embedding_model_id": reranker_model_id,
            },
        )
        assert wrong_type_model.status_code == 422, wrong_type_model.text

        bob_owned = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(bob_token),
            json={"name": "Bob Notes", "description": "private"},
        )
        assert bob_owned.status_code == 201, bob_owned.text
        bob_owned_id = bob_owned.json()["id"]

        # list pagination: bob sees only his own KB
        bob_first_page = client.get(
            knowledge_url(default_workspace_id) + "?limit=1&offset=0",
            headers=auth_headers(bob_token),
        )
        assert bob_first_page.status_code == 200, bob_first_page.text
        assert [item["id"] for item in bob_first_page.json()] == [bob_owned_id]

        bob_list = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(bob_token),
        )
        assert knowledge_base_id not in {item["id"] for item in bob_list.json()}

        denied_cross_workspace = client.get(
            knowledge_url(default_workspace_id),
            headers=auth_headers(research_token),
        )
        assert denied_cross_workspace.status_code == 404, denied_cross_workspace.text

        # ---- KB update paths ----
        renamed = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={"description": "updated description"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["description"] == "updated description"

        invalid_status = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={"status": "locked"},
        )
        assert invalid_status.status_code == 422, invalid_status.text

        cleared_embedding = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={"embedding_model_id": None},
        )
        assert cleared_embedding.status_code == 200, cleared_embedding.text
        assert cleared_embedding.json()["embedding_model_id"] is None

        cleared_reranker = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={"reranker_model_id": None},
        )
        assert cleared_reranker.status_code == 200, cleared_reranker.text

        restore_models = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={
                "embedding_model_id": embedding_model_id,
                "reranker_model_id": reranker_model_id,
            },
        )
        assert restore_models.status_code == 200, restore_models.text

        conflict_rename = client.patch(
            knowledge_url(default_workspace_id, f"/{bob_owned_id}"),
            headers=auth_headers(bob_token),
            json={"name": "Product Docs"},
        )
        assert conflict_rename.status_code == 409, conflict_rename.text
        assert conflict_rename.json()["detail"] == "Knowledge base name already exists."

        bob_edit_denied = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"description": "nope"},
        )
        assert bob_edit_denied.status_code == 403, bob_edit_denied.text

        # ---- upload paths ----
        empty_upload = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert empty_upload.status_code == 422, empty_upload.text

        with patch.object(
            documents_service, "MAX_DOCUMENT_UPLOAD_BYTES", 8
        ):
            too_large = client.post(
                knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
                headers=auth_headers(alice_token),
                files={"file": ("big.txt", b"x" * 64, "text/plain")},
            )
        assert too_large.status_code == 413, too_large.text

        restricted_name = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("机密文件.txt", b"x", "text/plain")},
        )
        assert restricted_name.status_code == 422, restricted_name.text

        missing_name = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("", b"x", "text/plain")},
        )
        assert missing_name.status_code == 422, missing_name.text

        # attachment deletion: ownership + missing checks run after bob has
        # edit permission (below); here just create the transient attachment.
        transient_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(alice_token),
            files={"file": ("transient.txt", b"temp", "text/plain")},
        )
        assert transient_attachment.status_code == 201, transient_attachment.text
        transient_attachment_id = transient_attachment.json()["id"]
        missing_attachment_delete = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/attachments/00000000-0000-0000-0000-000000000001",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_attachment_delete.status_code == 404, missing_attachment_delete.text

        # document creation error paths
        duplicate_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            json={
                "attachment_ids": [transient_attachment_id, transient_attachment_id],
                "staged": False,
            },
        )
        assert duplicate_attachment.status_code == 422, duplicate_attachment.text

        missing_attachment_doc = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            json={
                "attachment_ids": ["00000000-0000-0000-0000-000000000002"],
                "staged": False,
            },
        )
        assert missing_attachment_doc.status_code == 404, missing_attachment_doc.text

        # main document used by later flows
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
        document_id = uploaded_document["id"]
        assert uploaded_document["status"] == "uploaded"

        # documents listing + pagination
        document_list = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert document_list.status_code == 200, document_list.text
        assert [item["id"] for item in document_list.json()] == [document_id]

        document_list_page = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents?limit=1&offset=0"),
            headers=auth_headers(alice_token),
        )
        assert document_list_page.status_code == 200, document_list_page.text
        assert [item["id"] for item in document_list_page.json()] == [document_id]

        # staged document visible only with include_staged
        staged_doc = upload_document(
            client,
            alice_token,
            default_workspace_id,
            knowledge_base_id,
            "staged.txt",
            b"staged body",
            "text/plain",
            staged=True,
        )
        staged_doc_id = staged_doc["id"]
        without_staged = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
        )
        assert staged_doc_id not in {item["id"] for item in without_staged.json()}
        with_staged = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents?include_staged=true"),
            headers=auth_headers(alice_token),
        )
        assert staged_doc_id in {item["id"] for item in with_staged.json()}
        bob_staged_denied = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents?include_staged=true"),
            headers=auth_headers(bob_token),
        )
        assert bob_staged_denied.status_code == 403, bob_staged_denied.text

        # consumed attachment reuse -> 409
        consumed_reuse = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            json={
                "attachment_ids": [uploaded_document["attachment_id"]],
                "staged": False,
            },
        )
        assert consumed_reuse.status_code == 409, consumed_reuse.text

        # index before parse -> 409
        index_without_preview = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/index",
            ),
            headers=auth_headers(alice_token),
        )
        assert index_without_preview.status_code == 409, index_without_preview.text

        # parse options validation via API
        bad_overlap = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"chunk_size": 100, "chunk_overlap": 100},
        )
        assert bad_overlap.status_code == 422, bad_overlap.text

        bad_separator = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"split_separator": ";;"},
        )
        assert bad_separator.status_code == 422, bad_separator.text

        bad_rule = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"cleaning_rules": ["bogus"]},
        )
        assert bad_rule.status_code == 422, bad_rule.text

        # parse with auto_index False
        parsed = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/parse",
            ),
            headers=auth_headers(alice_token),
            json={"auto_index": False},
        )
        assert parsed.status_code == 202, parsed.text
        assert parsed.json()["task_type"] == "parse"

        chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert chunks.status_code == 200, chunks.text
        if [chunk["content"] for chunk in chunks.json()] != [
            "Hello from product docs"
        ]:
            print("DEBUG chunks:", [chunk["content"] for chunk in chunks.json()])
        assert [chunk["content"] for chunk in chunks.json()] == [
            "Hello from product docs"
        ]
        assert chunks.json()[0]["status"] == "preview"

        # index (eager; embedding upsert faked via module patch)
        original_upsert = task_runner_service.upsert_vectors
        task_runner_service.upsert_vectors = lambda *args: None
        try:
            indexed = client.post(
                knowledge_url(
                    default_workspace_id,
                    f"/{knowledge_base_id}/documents/{document_id}/index",
                ),
                headers=auth_headers(alice_token),
            )
        finally:
            task_runner_service.upsert_vectors = original_upsert
        assert indexed.status_code == 202, indexed.text
        assert indexed.json()["task_type"] == "index"
        indexed_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert indexed_chunks.status_code == 200, indexed_chunks.text
        assert {chunk["status"] for chunk in indexed_chunks.json()} == {"indexed"}
        assert indexed_chunks.json()[0]["vector_id"] == indexed_chunks.json()[0]["id"]

        # document activate/deactivate lifecycle
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
        deactivated_twice = client.patch(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}",
            ),
            headers=auth_headers(alice_token),
            json={"is_active": False},
        )
        assert deactivated_twice.status_code == 200, deactivated_twice.text
        reactivated = client.patch(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}",
            ),
            headers=auth_headers(alice_token),
            json={"is_active": True},
        )
        assert reactivated.status_code == 200, reactivated.text

        # document not found
        missing_doc_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/00000000-0000-0000-0000-000000000003/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert missing_doc_chunks.status_code == 404, missing_doc_chunks.text

        # tasks listing with document filter
        document_tasks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/tasks",
            ),
            headers=auth_headers(alice_token),
        )
        assert document_tasks.status_code == 200, document_tasks.text
        assert {item["task_type"] for item in document_tasks.json()} == {
            "parse",
            "index",
        }

        # task retry: non-failed task -> 409
        retry_succeeded = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/tasks/{document_tasks.json()[0]['id']}/retry",
            ),
            headers=auth_headers(alice_token),
        )
        assert retry_succeeded.status_code == 409, retry_succeeded.text

        # retry: unknown task -> 404
        retry_unknown = client.post(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/tasks/00000000-0000-0000-0000-000000000004/retry",
            ),
            headers=auth_headers(alice_token),
        )
        assert retry_unknown.status_code == 404, retry_unknown.text

        # rebuild with no indexed chunks -> 422 (fresh KB)
        empty_kb = client.post(
            knowledge_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={"name": "Empty KB", "description": "no documents"},
        )
        assert empty_kb.status_code == 201, empty_kb.text
        empty_kb_id = empty_kb.json()["id"]
        empty_rebuild = client.post(
            knowledge_url(default_workspace_id, f"/{empty_kb_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert empty_rebuild.status_code == 422, empty_rebuild.text

        # rebuild success on main KB
        rebuild = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/rebuild-index"),
            headers=auth_headers(alice_token),
        )
        assert rebuild.status_code == 202, rebuild.text
        assert rebuild.json()["total_items"] == 1

        # permission flows
        view_grant = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert view_grant.status_code == 200, view_grant.text
        assert view_grant.json()["permission"] == "view"

        invalid_permission = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
            json={"permission": "admin"},
        )
        assert invalid_permission.status_code == 422, invalid_permission.text

        missing_member = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{research_admin_id}",
            ),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert missing_member.status_code == 404, missing_member.text

        permission_list = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/permissions"),
            headers=auth_headers(alice_token),
        )
        assert permission_list.status_code == 200, permission_list.text
        assert [(item["user"]["username"], item["permission"]) for item in permission_list.json()] == [
            ("bob", "view")
        ]

        bob_get = client.get(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert bob_get.status_code == 200, bob_get.text
        assert bob_get.json()["permission"] == "view"

        bob_upload_denied = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(bob_token),
            files={"file": ("denied.txt", b"nope", "text/plain")},
        )
        assert bob_upload_denied.status_code == 403, bob_upload_denied.text

        edit_grant = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
            json={"permission": "edit"},
        )
        assert edit_grant.status_code == 200, edit_grant.text

        # bob has edit: cross-owner attachment deletion -> 404
        other_delete = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/attachments/{transient_attachment_id}",
            ),
            headers=auth_headers(bob_token),
        )
        assert other_delete.status_code == 404, other_delete.text
        deleted_attachment = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/attachments/{transient_attachment_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_attachment.status_code == 204, deleted_attachment.text

        bob_attachment = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(bob_token),
            files={"file": ("bob-file.txt", b"bob", "text/plain")},
        )
        assert bob_attachment.status_code == 201, bob_attachment.text
        cross_owner_doc = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/documents"),
            headers=auth_headers(alice_token),
            json={
                "attachment_ids": [bob_attachment.json()["id"]],
                "staged": False,
            },
        )
        assert cross_owner_doc.status_code == 409, cross_owner_doc.text

        update_grant = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert update_grant.status_code == 200, update_grant.text

        revoked = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert revoked.status_code == 204, revoked.text
        revoke_missing = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{bob_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert revoke_missing.status_code == 404, revoke_missing.text

        bob_grant_denied = client.put(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/permissions/{alice_id}",
            ),
            headers=auth_headers(bob_token),
            json={"permission": "view"},
        )
        assert bob_grant_denied.status_code == 403, bob_grant_denied.text

        # ---- delete document (happy path: attachment + chunks + vectors) ----
        deleted_document = client.delete(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_document.status_code == 204, deleted_document.text

        deleted_doc_chunks = client.get(
            knowledge_url(
                default_workspace_id,
                f"/{knowledge_base_id}/documents/{document_id}/chunks",
            ),
            headers=auth_headers(alice_token),
        )
        assert deleted_doc_chunks.status_code == 404, deleted_doc_chunks.text

        # ---- owner transfer ----
        transfer_denied = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(bob_token),
            json={"user_id": alice_id},
        )
        assert transfer_denied.status_code == 403, transfer_denied.text

        transfer_missing = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(alice_token),
            json={"user_id": research_admin_id},
        )
        assert transfer_missing.status_code == 404, transfer_missing.text

        transferred = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(alice_token),
            json={"user_id": bob_id},
        )
        assert transferred.status_code == 200, transferred.text
        assert transferred.json()["created_by_user_id"] == bob_id

        # ---- archive / restore lifecycle ----
        archived = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"status": "archived"},
        )
        assert archived.status_code == 200, archived.text

        archived_upload = client.post(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/attachments"),
            headers=auth_headers(bob_token),
            files={"file": ("archived.txt", b"nope", "text/plain")},
        )
        assert archived_upload.status_code == 403, archived_upload.text

        archived_patch = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"name": "Renamed while archived"},
        )
        assert archived_patch.status_code == 403, archived_patch.text

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

        alice_restore_denied = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
            json={"status": "active"},
        )
        assert alice_restore_denied.status_code == 403, alice_restore_denied.text

        restored = client.patch(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"status": "active"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"

        transferred_back = client.put(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}/owner"),
            headers=auth_headers(bob_token),
            json={"user_id": alice_id},
        )
        assert transferred_back.status_code == 200, transferred_back.text

        deleted = client.delete(
            knowledge_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted.status_code == 204, deleted.text
        deleted_bob_owned = client.delete(
            knowledge_url(default_workspace_id, f"/{bob_owned_id}"),
            headers=auth_headers(bob_token),
        )
        assert deleted_bob_owned.status_code == 204, deleted_bob_owned.text

        # ---- dedicated workspaces: direct domain tests ----
        asyncio.run(
            run_direct_domain_tests(
                client,
                admin_token,
                research_token,
                research_admin_id,
                default_workspace_id,
                research_workspace_id,
                cleanup_workspace_id,
                delete_ws_id,
                empty_kb_id,
                alice_token,
                model_base_url,
            )
        )
        run_celery_job_tests(
            client,
            research_token,
            STASH["cleanup_workspace_id"],
            STASH["research_admin_id"],
            STASH["no_model_kb_id"],
            STASH["no_model_doc_id"],
        )

        print("OK: knowledge_domain_coverage (api scenario)")


# ---------------------------------------------------------------------------
# Direct domain tests (async)
# ---------------------------------------------------------------------------


async def run_direct_domain_tests(
    client,
    admin_token: str,
    research_token: str,
    research_admin_id: str,
    default_workspace_id: str,
    research_workspace_id: str,
    cleanup_workspace_id: str,
    delete_ws_id: str,
    empty_kb_id: str,
    alice_token: str,
    model_base_url: str,
) -> None:
    from fastapi import HTTPException

    from app.application import knowledge as application_knowledge

    # ---- cross-workspace get -> 404 (research KB via main workspace route)
    async with get_session_factory()() as db:
        research_kb = KnowledgeBase(
            id=new_id(),
            workspace_id=research_workspace_id,
            name="Research KB",
            description="",
            status="active",
            embedding_model_id=None,
            reranker_model_id=None,
            created_by_user_id=research_admin_id,
        )
        research_kb = await knowledge_repository.create_knowledge_base(
            db,
            research_kb,
        )
        await db.commit()
        research_kb_id = research_kb.id

    cross_workspace_get = client.get(
        knowledge_url(default_workspace_id, f"/{research_kb_id}"),
        headers=auth_headers(alice_token),
    )
    assert cross_workspace_get.status_code == 404, cross_workspace_get.text

    # ---- cleanup workspace: model validation ----
    bad_embedding_model = create_model(
        client,
        research_token,
        cleanup_workspace_id,
        "Disabled Embedding",
        "EMBEDDING",
        "text-embedding-3-small",
        api_base=model_base_url,
    )
    async with get_session_factory()() as db:
        model = await db.get(RegisteredModel, bad_embedding_model)
        assert model is not None
        model.status = "disabled"
        await db.commit()

    llm_model = create_model(
        client,
        research_token,
        cleanup_workspace_id,
        "Chat Model",
        "LLM",
        "chat-model",
        provider="model_deepseek_provider",
        provider_type="deepseek",
        api_base=model_base_url,
    )

    disabled_model_kb = client.post(
        knowledge_url(cleanup_workspace_id),
        headers=auth_headers(research_token),
        json={"name": "Disabled Model KB", "embedding_model_id": bad_embedding_model},
    )
    assert disabled_model_kb.status_code == 422, disabled_model_kb.text

    wrong_type_kb = client.post(
        knowledge_url(cleanup_workspace_id),
        headers=auth_headers(research_token),
        json={"name": "Wrong Type KB", "embedding_model_id": llm_model},
    )
    assert wrong_type_kb.status_code == 422, wrong_type_kb.text

    no_model_kb = client.post(
        knowledge_url(cleanup_workspace_id),
        headers=auth_headers(research_token),
        json={"name": "No Model KB", "description": ""},
    )
    assert no_model_kb.status_code == 201, no_model_kb.text
    no_model_kb_id = no_model_kb.json()["id"]

    no_model_doc = upload_document(
        client,
        research_token,
        cleanup_workspace_id,
        no_model_kb_id,
        "plain.txt",
        b"plain text body",
        "text/plain",
    )
    no_model_doc_id = no_model_doc["id"]
    no_model_parse = client.post(
        knowledge_url(cleanup_workspace_id, f"/{no_model_kb_id}/documents/{no_model_doc_id}/parse"),
        headers=auth_headers(research_token),
        json={"auto_index": False},
    )
    assert no_model_parse.status_code == 202, no_model_parse.text
    no_model_index = client.post(
        knowledge_url(cleanup_workspace_id, f"/{no_model_kb_id}/documents/{no_model_doc_id}/index"),
        headers=auth_headers(research_token),
    )
    assert no_model_index.status_code == 422, no_model_index.text

    unsupported_doc = upload_document(
        client,
        research_token,
        cleanup_workspace_id,
        no_model_kb_id,
        "unsupported.bin",
        b"\x00\x01\x02",
        "application/octet-stream",
    )
    unsupported_doc_id = unsupported_doc["id"]
    unsupported_parse = client.post(
        knowledge_url(cleanup_workspace_id, f"/{no_model_kb_id}/documents/{unsupported_doc_id}/parse"),
        headers=auth_headers(research_token),
        json={"auto_index": False},
    )
    assert unsupported_parse.status_code == 202, unsupported_parse.text

    # dispatch failure -> 503 and task marked failed
    original_enqueue_knowledge_task = application_knowledge.enqueue_knowledge_task

    async def fail_dispatch(task_id: str, _settings) -> None:
        await knowledge_tasks_module.mark_task_dispatch_failed(task_id)
        raise RuntimeError("queue unavailable")

    application_knowledge.enqueue_knowledge_task = fail_dispatch
    try:
        degraded = client.post(
            knowledge_url(cleanup_workspace_id, f"/{no_model_kb_id}/documents/{no_model_doc_id}/parse"),
            headers=auth_headers(research_token),
            json={"auto_index": False},
        )
    finally:
        application_knowledge.enqueue_knowledge_task = original_enqueue_knowledge_task
    assert degraded.status_code == 503, degraded.text

    # index document without preview chunks -> 422 (main workspace KB with model)
    empty_kb_doc = upload_document(
        client,
        alice_token,
        default_workspace_id,
        empty_kb_id,
        "no-chunks.txt",
        b"no chunks yet",
        "text/plain",
    )
    async with get_session_factory()() as db:
        empty_kb = await knowledge_repository.get_knowledge_base_by_id(db, empty_kb_id)
        empty_kb_doc_entity = await knowledge_repository.get_knowledge_document_by_id(
            db,
            empty_kb_doc["id"],
        )
        alice = await user_repository.get_active_user_by_username(db, "alice")
        assert empty_kb is not None
        assert empty_kb_doc_entity is not None
        assert alice is not None
        try:
            await orchestration_service.create_knowledge_task(
                db,
                empty_kb,
                empty_kb_doc_entity,
                TASK_INDEX,
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
            assert "preview" in exc.detail
        else:
            raise AssertionError("index without preview chunks must 422")

    # ---- direct orchestration error branches ----
    async with get_session_factory()() as db:
        no_model_kb_entity = await knowledge_repository.get_knowledge_base_by_id(
            db,
            no_model_kb_id,
        )
        no_model_doc_entity = await knowledge_repository.get_knowledge_document_by_id(
            db,
            no_model_doc_id,
        )
        actor = await user_repository.get_active_user_by_username(db, "research-admin")
        assert no_model_kb_entity is not None
        assert no_model_doc_entity is not None
        assert actor is not None

        # create_knowledge_task: KB lock returns None -> 404
        ghost_kb = KnowledgeBase(
            id=new_id(),
            workspace_id=cleanup_workspace_id,
            name="Ghost",
            description="",
            status="active",
            created_by_user_id=actor.id,
        )
        try:
            await orchestration_service.create_knowledge_task(
                db,
                ghost_kb,
                None,
                TASK_REBUILD_INDEX,
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("ghost KB must 404")

        # archived KB -> 403
        archived_kb = KnowledgeBase(
            id=new_id(),
            workspace_id=cleanup_workspace_id,
            name="Archived Direct",
            description="",
            status="archived",
            created_by_user_id=actor.id,
        )
        archived_kb = await knowledge_repository.create_knowledge_base(
            db,
            archived_kb,
        )
        await db.commit()
        try:
            await orchestration_service.create_knowledge_task(
                db,
                archived_kb,
                None,
                TASK_REBUILD_INDEX,
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("archived KB must 403")

        # invalid task type -> 422
        try:
            await orchestration_service.create_knowledge_task(
                db,
                no_model_kb_entity,
                None,
                "weird",
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("invalid task type must 422")

        # rebuild with no indexed chunks -> 422
        try:
            await orchestration_service.create_knowledge_task(
                db,
                no_model_kb_entity,
                None,
                TASK_REBUILD_INDEX,
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("rebuild without indexed chunks must 422")

        # index with no embedding model -> 422
        try:
            await orchestration_service.create_knowledge_task(
                db,
                no_model_kb_entity,
                no_model_doc_entity,
                TASK_INDEX,
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("index without embedding model must 422")

        # get_knowledge_document 404 variants
        try:
            await orchestration_service.get_knowledge_document(
                db,
                no_model_kb_entity,
                "00000000-0000-0000-0000-000000000010",
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("missing document must 404")

        try:
            await orchestration_service.get_knowledge_document(
                db,
                ghost_kb,
                no_model_doc_id,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("cross-KB document must 404")

        deleted_marker_doc = KnowledgeDocument(
            id=new_id(),
            workspace_id=cleanup_workspace_id,
            knowledge_base_id=no_model_kb_id,
            filename="deleted.txt",
            content_type="text/plain",
            size_bytes=1,
            storage_path="none",
            status=DOCUMENT_DELETED_STATUS,
            created_by_user_id=actor.id,
        )
        await knowledge_repository.create_knowledge_document(db, deleted_marker_doc)
        await db.commit()
        try:
            await orchestration_service.get_knowledge_document(
                db,
                no_model_kb_entity,
                deleted_marker_doc.id,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("deleted document must 404")

        # retry_knowledge_task: task not found -> 404
        try:
            await orchestration_service.retry_knowledge_task(
                db,
                no_model_kb_entity,
                "00000000-0000-0000-0000-000000000014",
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("unknown task retry must 404")

        # retry_knowledge_task: KB lock None -> 404
        try:
            await orchestration_service.retry_knowledge_task(
                db,
                ghost_kb,
                "00000000-0000-0000-0000-000000000015",
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("ghost KB retry must 404")

        # enqueue_index_knowledge_document: uploaded doc -> 409
        try:
            await orchestration_service.enqueue_index_knowledge_document(
                db,
                no_model_kb_entity,
                no_model_doc_entity,
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("uploaded document index must 409")

    # extract_document_chunk_contents: no extractable chunks
    with patch.object(
        orchestration_service,
        "extract_document",
        new=Mock(return_value=("", [])),
    ):
        try:
            await orchestration_service.extract_document_chunk_contents(
                no_model_doc_entity,
                test_settings(),
                {"strategy": "flat", "chunk_size": 100, "chunk_overlap": 0, "split_separator": "\n\n", "cleaning_rules": []},
            )
        except KnowledgePipelineError:
            pass
        else:
            raise AssertionError("empty extraction must raise")

    # replace_document_chunks: invalid offsets -> error and asset cleanup
    async with get_session_factory()() as db:
        target_kb = await knowledge_repository.get_knowledge_base_by_id(
            db,
            no_model_kb_id,
        )
        target_doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            no_model_doc_id,
        )
        assert target_kb is not None
        assert target_doc is not None
        target_doc.status = DOCUMENT_PARSED_STATUS
        await knowledge_repository.save_knowledge_document(db, target_doc)
        await db.commit()
        invalid_drafts = DocumentChunkDrafts(
            parents=[ParentChunkDraft(title="P", content="hello world")],
            children=[
                ChildChunkDraft(
                    content="world",
                    parent_index=0,
                    start_offset=0,
                    end_offset=5,
                    asset_indexes=[99],
                )
            ],
            assets=[
                DocumentAssetDraft(
                    id="asset-invalid-1",
                    filename="a.png",
                    content_type="image/png",
                    content=b"\x89PNG",
                    alt_text="",
                )
            ],
        )
        try:
            await orchestration_service.replace_document_chunks(
                db,
                target_kb,
                target_doc,
                invalid_drafts,
                test_settings(),
            )
        except KnowledgePipelineError as exc:
            assert "offsets" in str(exc)
        else:
            raise AssertionError("invalid offsets must raise")

        # replace_document_chunks: success with out-of-range asset index skipped
        valid_drafts = DocumentChunkDrafts(
            parents=[ParentChunkDraft(title="P", content="hello world")],
            children=[
                ChildChunkDraft(
                    content="hello",
                    parent_index=0,
                    start_offset=0,
                    end_offset=5,
                    asset_indexes=[0, 99],
                ),
                ChildChunkDraft(
                    content="world",
                    parent_index=0,
                    start_offset=6,
                    end_offset=11,
                    asset_indexes=[],
                ),
            ],
            assets=[
                DocumentAssetDraft(
                    id="asset-valid-1",
                    filename="a.png",
                    content_type="image/png",
                    content=b"\x89PNG",
                    alt_text="",
                )
            ],
        )
        await orchestration_service.replace_document_chunks(
            db,
            target_kb,
            target_doc,
            valid_drafts,
            test_settings(),
        )
        await db.commit()
        # chunks listing exposes parents and assets
        responses = await orchestration_service.list_knowledge_document_chunks(
            db,
            target_kb,
            target_doc,
        )
        assert len(responses) == 2
        assert responses[0].parent_title == "P"
        assert len(responses[0].images) == 1
        assert responses[0].images[0].filename == "a.png"
        # pagination on chunk listing
        one = await orchestration_service.list_knowledge_document_chunks(
            db,
            target_kb,
            target_doc,
            limit=1,
            offset=0,
        )
        assert len(one) == 1

    # ---- cleanup service direct tests ----
    cleanup_kb = client.post(
        knowledge_url(cleanup_workspace_id),
        headers=auth_headers(research_token),
        json={"name": "Cleanup KB", "description": ""},
    )
    assert cleanup_kb.status_code == 201, cleanup_kb.text
    cleanup_kb_id = cleanup_kb.json()["id"]

    cleanup_created = await create_cleanup_record(cleanup_workspace_id, cleanup_kb_id)
    due_ids = await list_due_cleanup_ids(limit=10)
    assert cleanup_created in due_ids

    await run_single_cleanup(cleanup_created)
    await run_single_cleanup(cleanup_created)  # record already gone -> no-op

    async with get_session_factory()() as db:
        failed_cleanup = await knowledge_repository.create_knowledge_storage_cleanup(
            db,
            KnowledgeStorageCleanup(
                workspace_id=cleanup_workspace_id,
                knowledge_base_id=cleanup_kb_id,
            ),
        )
        await db.commit()
        failed_cleanup_id = failed_cleanup.id
    with patch.object(
        cleanup_service,
        "purge_knowledge_base_storage",
        new=AsyncMock(side_effect=RuntimeError("purge boom")),
    ):
        try:
            await cleanup_service.run_knowledge_storage_cleanup(
                failed_cleanup_id,
                test_settings(),
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("purge failure must propagate")
    async with get_session_factory()() as db:
        record = await knowledge_repository.lock_knowledge_storage_cleanup(
            db,
            failed_cleanup_id,
        )
        assert record is not None
        assert record.attempts == 1
        assert "purge boom" in (record.last_error or "")
        assert record.next_attempt_at > utc_now().replace(tzinfo=None)

    due_now_ids = await list_due_cleanup_ids(limit=100)
    assert failed_cleanup_id not in due_now_ids  # deferred by backoff
    assert await list_due_cleanup_ids(limit=0) == []

    # delete_workspace_knowledge_bases in the dedicated delete workspace
    conflict_kb = client.post(
        knowledge_url(delete_ws_id),
        headers=auth_headers(research_token),
        json={"name": "Conflict KB", "description": ""},
    )
    assert conflict_kb.status_code == 201, conflict_kb.text
    conflict_kb_id = conflict_kb.json()["id"]
    client.post(
        knowledge_url(delete_ws_id),
        headers=auth_headers(research_token),
        json={"name": "Plain KB", "description": ""},
    )
    conflict_task = await create_task_row(
        delete_ws_id,
        conflict_kb_id,
        None,
        TASK_REBUILD_INDEX,
        research_admin_id,
    )
    async with get_session_factory()() as db:
        try:
            await cleanup_service.delete_workspace_knowledge_bases(
                db,
                delete_ws_id,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("open task must block workspace cleanup")
        await set_task_status_sync(db, conflict_task.id, TASK_FAILED_STATUS)
        cleanup_ids = await cleanup_service.delete_workspace_knowledge_bases(
            db,
            delete_ws_id,
        )
        assert len(cleanup_ids) == 2
        await db.commit()
    for cleanup_id in cleanup_ids:
        await run_single_cleanup(cleanup_id)

    # ---- task runner direct tests ----
    runner_embedding_model_id = create_model(
        client,
        research_token,
        cleanup_workspace_id,
        "Runner Embedding",
        "EMBEDDING",
        "text-embedding-3-small",
        api_base=model_base_url,
    )
    await run_task_runner_direct_tests(
        client,
        research_token,
        cleanup_workspace_id,
        research_admin_id,
        no_model_kb_id,
        no_model_doc_id,
        runner_embedding_model_id,
    )

    # ---- repository direct tests ----
    await run_repository_direct_tests(
        cleanup_workspace_id,
        no_model_kb_id,
        no_model_doc_id,
        research_admin_id,
        runner_embedding_model_id,
    )

    # ---- direct shareddomain tests (portal execution is not reliably
    # traced by coverage in this environment, so exercise the domain
    # functions directly) ----
    await run_direct_shareddomain_tests(
        client,
        admin_token,
        default_workspace_id,
        model_base_url,
    )

    # recover_knowledge_tasks last (it re-runs every queued/running task)
    await recover_knowledge_tasks(test_settings())

    STASH["cleanup_workspace_id"] = cleanup_workspace_id
    STASH["research_admin_id"] = research_admin_id
    STASH["no_model_kb_id"] = no_model_kb_id
    STASH["no_model_doc_id"] = no_model_doc_id


# ---------------------------------------------------------------------------
# Task runner direct tests
# ---------------------------------------------------------------------------


async def run_task_runner_direct_tests(
    client,
    research_token: str,
    workspace_id: str,
    actor_user_id: str,
    no_model_kb_id: str,
    no_model_doc_id: str,
    embedding_model_id: str,
) -> None:
    settings = test_settings()
    assert run_knowledge_task_job.soft_time_limit == 900
    assert run_knowledge_task_job.time_limit == 960

    # get_task_scope error branches
    async with get_session_factory()() as db:
        missing_kb_task = KnowledgeTask(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id="00000000-0000-0000-0000-000000000011",
            task_type=TASK_PARSE,
            status=TASK_QUEUED_STATUS,
            attempts=0,
            max_attempts=3,
            total_items=0,
            processed_items=0,
            options={},
            created_by_user_id=actor_user_id,
        )
        try:
            await get_task_scope(db, missing_kb_task)
        except KnowledgePipelineError:
            pass
        else:
            raise AssertionError("missing KB must raise")

        missing_actor_task = KnowledgeTask(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=no_model_kb_id,
            task_type=TASK_PARSE,
            status=TASK_QUEUED_STATUS,
            attempts=0,
            max_attempts=3,
            total_items=0,
            processed_items=0,
            options={},
            created_by_user_id="00000000-0000-0000-0000-000000000012",
        )
        try:
            await get_task_scope(db, missing_actor_task)
        except KnowledgePipelineError:
            pass
        else:
            raise AssertionError("missing actor must raise")

        missing_doc_task = KnowledgeTask(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=no_model_kb_id,
            document_id="00000000-0000-0000-0000-000000000013",
            task_type=TASK_PARSE,
            status=TASK_QUEUED_STATUS,
            attempts=0,
            max_attempts=3,
            total_items=0,
            processed_items=0,
            options={},
            created_by_user_id=actor_user_id,
        )
        try:
            await get_task_scope(db, missing_doc_task)
        except KnowledgePipelineError:
            pass
        else:
            raise AssertionError("missing document must raise")

        # happy path scope
        valid_task = KnowledgeTask(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=no_model_kb_id,
            document_id=no_model_doc_id,
            task_type=TASK_PARSE,
            status=TASK_QUEUED_STATUS,
            attempts=0,
            max_attempts=3,
            total_items=0,
            processed_items=0,
            options={},
            created_by_user_id=actor_user_id,
        )
        scope_kb, scope_actor, scope_doc = await get_task_scope(db, valid_task)
        assert scope_kb.id == no_model_kb_id
        assert scope_actor.id == actor_user_id
        assert scope_doc is not None and scope_doc.id == no_model_doc_id

    # run_index_task: no embedding model -> error (real resolve)
    task = await create_task_row(
        workspace_id,
        no_model_kb_id,
        no_model_doc_id,
        TASK_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, no_model_kb_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            no_model_doc_id,
        )
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        task_entity = await knowledge_repository.get_knowledge_task_by_id(db, task.id)
        assert kb is not None and doc is not None and actor is not None
        assert task_entity is not None
        with patch.object(
            task_runner_service,
            "resolve_embedding_model",
            new=AsyncMock(return_value=None),
        ):
            try:
                await task_runner_service.run_index_task(
                    db,
                    task_entity,
                    kb,
                    doc,
                    actor,
                    settings,
                    asyncio.Event(),
                )
            except KnowledgePipelineError:
                pass
            else:
                raise AssertionError("index without embedding model must raise")
        await set_task_status_sync(db, task.id, TASK_FAILED_STATUS)
        await db.commit()

    # run_index_task: no chunks -> error (patched resolve)
    task2 = await create_task_row(
        workspace_id,
        no_model_kb_id,
        no_model_doc_id,
        TASK_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, no_model_kb_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            no_model_doc_id,
        )
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        task_entity = await knowledge_repository.get_knowledge_task_by_id(db, task2.id)
        assert kb is not None and doc is not None and actor is not None
        assert task_entity is not None
        # ensure the document really has no chunks (earlier flows added some)
        await knowledge_repository.delete_document_chunks(db, no_model_doc_id)
        await db.commit()
        with patch.object(
            task_runner_service,
            "resolve_embedding_model",
            new=AsyncMock(return_value=SimpleNamespace(id=embedding_model_id)),
        ):
            try:
                await task_runner_service.run_index_task(
                    db,
                    task_entity,
                    kb,
                    doc,
                    actor,
                    settings,
                    asyncio.Event(),
                )
            except KnowledgePipelineError:
                pass
            else:
                raise AssertionError("index without chunks must raise")
        await set_task_status_sync(db, task2.id, TASK_FAILED_STATUS)
        await db.commit()

    # run_index_task: chunk document missing -> error
    indexed_kb = client.post(
        knowledge_url(workspace_id),
        headers=auth_headers(research_token),
        json={"name": "Runner Index KB", "description": ""},
    )
    assert indexed_kb.status_code == 201, indexed_kb.text
    indexed_kb_id = indexed_kb.json()["id"]
    indexed_doc = upload_document(
        client,
        research_token,
        workspace_id,
        indexed_kb_id,
        "index-me.txt",
        b"index me please",
        "text/plain",
    )
    indexed_doc_id = indexed_doc["id"]
    await write_preview_chunks(indexed_kb_id, indexed_doc_id)

    task3 = await create_task_row(
        workspace_id,
        indexed_kb_id,
        indexed_doc_id,
        TASK_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        task_entity = await knowledge_repository.get_knowledge_task_by_id(db, task3.id)
        assert kb is not None and actor is not None and task_entity is not None
        with patch.object(
            task_runner_service,
            "resolve_embedding_model",
            new=AsyncMock(return_value=SimpleNamespace(id=embedding_model_id)),
        ), patch.object(
            knowledge_repository,
            "get_knowledge_document_by_id",
            new=AsyncMock(return_value=None),
        ):
            try:
                await task_runner_service.run_index_task(
                    db,
                    task_entity,
                    kb,
                    None,
                    actor,
                    settings,
                    asyncio.Event(),
                )
            except KnowledgePipelineError:
                pass
            else:
                raise AssertionError("missing chunk document must raise")
        await set_task_status_sync(db, task3.id, TASK_FAILED_STATUS)
        await db.commit()

    # run_index_task: chunk document deleted (after refresh) -> error
    task4 = await create_task_row(
        workspace_id,
        indexed_kb_id,
        indexed_doc_id,
        TASK_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        task_entity = await knowledge_repository.get_knowledge_task_by_id(db, task4.id)
        assert kb is not None and actor is not None and task_entity is not None
        deleted_doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            indexed_doc_id,
        )
        assert deleted_doc is not None
        deleted_doc.status = DOCUMENT_DELETED_STATUS
        with patch.object(
            task_runner_service,
            "resolve_embedding_model",
            new=AsyncMock(return_value=SimpleNamespace(id=embedding_model_id)),
        ), patch.object(
            knowledge_repository,
            "refresh_knowledge_document",
            new=AsyncMock(return_value=deleted_doc),
        ):
            try:
                await task_runner_service.run_index_task(
                    db,
                    task_entity,
                    kb,
                    deleted_doc,
                    actor,
                    settings,
                    asyncio.Event(),
                )
            except KnowledgePipelineError:
                pass
            else:
                raise AssertionError("deleted chunk document must raise")
        await set_task_status_sync(db, task4.id, TASK_FAILED_STATUS)
        await db.commit()

    # run_index_task: full success (index task; sets kb embedding model id)
    task5 = await create_task_row(
        workspace_id,
        indexed_kb_id,
        indexed_doc_id,
        TASK_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            indexed_doc_id,
        )
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        task_entity = await knowledge_repository.get_knowledge_task_by_id(db, task5.id)
        assert kb is not None and doc is not None and actor is not None
        assert task_entity is not None
        # force the KB back to "no embedding model" so the run sets it
        await knowledge_repository.set_knowledge_base_embedding_model_id(
            db,
            indexed_kb_id,
            None,
        )
        await db.commit()
        kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        assert kb is not None
        with patch.object(
            task_runner_service,
            "resolve_embedding_model",
            new=AsyncMock(return_value=SimpleNamespace(id=embedding_model_id)),
        ), patch.object(task_runner_service, "upsert_vectors", new=Mock()):
            await task_runner_service.run_index_task(
                db,
                task_entity,
                kb,
                doc,
                actor,
                settings,
                asyncio.Event(),
            )
        await db.commit()
        db_kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        assert db_kb is not None and db_kb.embedding_model_id == embedding_model_id
        chunks = await knowledge_repository.list_document_chunks(
            db,
            kb,
            indexed_doc_id,
        )
        assert chunks and all(chunk.status == CHUNK_INDEXED_STATUS for chunk in chunks)
        assert all(chunk.vector_id == chunk.id for chunk in chunks)
        doc_refresh = await knowledge_repository.get_knowledge_document_by_id(
            db,
            indexed_doc_id,
        )
        assert doc_refresh is not None
        assert doc_refresh.status == DOCUMENT_INDEXED_STATUS
        await set_task_status_sync(db, task5.id, TASK_SUCCEEDED_STATUS)
        await db.commit()

    # run_index_task: rebuild task over indexed chunks
    rebuild_task = await create_task_row(
        workspace_id,
        indexed_kb_id,
        None,
        TASK_REBUILD_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        task_entity = await knowledge_repository.get_knowledge_task_by_id(
            db,
            rebuild_task.id,
        )
        assert kb is not None and actor is not None and task_entity is not None
        with patch.object(
            task_runner_service,
            "resolve_embedding_model",
            new=AsyncMock(return_value=SimpleNamespace(id=embedding_model_id)),
        ), patch.object(task_runner_service, "upsert_vectors", new=Mock()):
            await task_runner_service.run_index_task(
                db,
                task_entity,
                kb,
                None,
                actor,
                settings,
                asyncio.Event(),
            )
        await db.commit()
        assert task_entity.total_items >= 1
        assert task_entity.processed_items == task_entity.total_items
        await set_task_status_sync(db, rebuild_task.id, TASK_SUCCEEDED_STATUS)
        await db.commit()

    # lease-lost event aborts run_index_task
    task6 = await create_task_row(
        workspace_id,
        indexed_kb_id,
        indexed_doc_id,
        TASK_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        task_entity = await knowledge_repository.get_knowledge_task_by_id(db, task6.id)
        assert kb is not None and actor is not None and task_entity is not None
        lease_lost = asyncio.Event()
        lease_lost.set()
        with patch.object(
            task_runner_service,
            "resolve_embedding_model",
            new=AsyncMock(return_value=SimpleNamespace(id=embedding_model_id)),
        ):
            try:
                await task_runner_service.run_index_task(
                    db,
                    task_entity,
                    kb,
                    None,
                    actor,
                    settings,
                    lease_lost,
                )
            except KnowledgePipelineError:
                pass
            else:
                raise AssertionError("lost lease must abort index task")
        await set_task_status_sync(db, task6.id, TASK_FAILED_STATUS)
        await db.commit()

    # run_parse_task: happy path with stale assets + commit failure
    await run_parse_task_direct_tests(
        workspace_id,
        actor_user_id,
        indexed_kb_id,
        indexed_doc_id,
    )

    # mark_knowledge_task_failed: task missing -> no-op
    async with get_session_factory()() as db:
        await mark_knowledge_task_failed(db, "00000000-0000-0000-0000-000000000020", "x")
        await db.commit()

    # mark_knowledge_task_failed: worker mismatch + only_if_queued guards
    parse_task_id = await enqueue_parse(
        indexed_kb_id,
        indexed_doc_id,
        "research-admin",
        {"auto_index": False},
    )
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, parse_task_id)
        assert task is not None
        task.status = TASK_RUNNING_STATUS
        task.worker_task_id = "other-worker"
        await knowledge_repository.save_knowledge_task(db, task)
        await db.commit()
        await mark_knowledge_task_failed(
            db,
            parse_task_id,
            "mismatch",
            worker_task_id="correct-worker",
        )
        await mark_knowledge_task_failed(
            db,
            parse_task_id,
            "not queued",
            only_if_queued=True,
        )
        await db.commit()
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, parse_task_id)
        assert task is not None
        assert task.status == TASK_RUNNING_STATUS

    # mark failed: index task -> document index_failed + chunks index_failed
    fail_index_task = await create_task_row(
        workspace_id,
        indexed_kb_id,
        indexed_doc_id,
        TASK_INDEX,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            indexed_doc_id,
        )
        assert doc is not None
        doc.status = DOCUMENT_INDEX_QUEUED_STATUS
        await knowledge_repository.save_knowledge_document(db, doc)
        await db.commit()
    async with get_session_factory()() as db:
        await mark_knowledge_task_failed(db, fail_index_task.id, "index exploded")
        await db.commit()
    async with get_session_factory()() as db:
        doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            indexed_doc_id,
        )
        task = await knowledge_repository.get_knowledge_task_by_id(
            db,
            fail_index_task.id,
        )
        kb = await knowledge_repository.get_knowledge_base_by_id(db, indexed_kb_id)
        assert doc is not None and task is not None and kb is not None
        assert doc.status == DOCUMENT_INDEX_FAILED_STATUS
        assert doc.last_error == "index exploded"
        assert task.status == TASK_FAILED_STATUS
        chunks = await knowledge_repository.list_document_chunks(db, kb, indexed_doc_id)
        assert chunks and all(
            chunk.status == CHUNK_INDEX_FAILED_STATUS for chunk in chunks
        )

    # mark failed: task with deleted document skips document updates
    deleted_doc = upload_document(
        client,
        research_token,
        workspace_id,
        indexed_kb_id,
        "doomed.txt",
        b"doomed",
        "text/plain",
    )
    deleted_doc_id = deleted_doc["id"]
    doomed_task = await create_task_row(
        workspace_id,
        indexed_kb_id,
        deleted_doc_id,
        TASK_PARSE,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            deleted_doc_id,
        )
        assert doc is not None
        doc.status = DOCUMENT_DELETED_STATUS
        await knowledge_repository.save_knowledge_document(db, doc)
        await db.commit()
    async with get_session_factory()() as db:
        await mark_knowledge_task_failed(db, doomed_task.id, "gone")
        await db.commit()

    # mark failed: parse task with missing actor (no audit log)
    ghost_actor_task = await create_task_row(
        workspace_id,
        indexed_kb_id,
        None,
        TASK_PARSE,
        actor_user_id,
    )
    async with get_session_factory()() as db:
        with patch.object(
            user_repository,
            "get_user_by_id",
            new=AsyncMock(return_value=None),
        ):
            await mark_knowledge_task_failed(db, ghost_actor_task.id, "no actor")
        await db.commit()

    # run_knowledge_task: busy / retry-limit / finished branches
    busy_task = await create_task_row(
        workspace_id,
        indexed_kb_id,
        indexed_doc_id,
        TASK_PARSE,
        actor_user_id,
        status=TASK_RUNNING_STATUS,
    )
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, busy_task.id)
        assert task is not None
        task.lease_expires_at = (utc_now() + timedelta(seconds=300)).replace(
            tzinfo=None
        )
        task.worker_task_id = "other-worker"
        await knowledge_repository.save_knowledge_task(db, task)
        await db.commit()
    with patch.object(
        task_runner_service,
        "utc_now",
        new=lambda: datetime.now(UTC).replace(tzinfo=None),
    ):
        outcome = await run_knowledge_task(busy_task.id, settings)
    assert outcome == TASK_RUN_BUSY
    async with get_session_factory()() as db:
        await set_task_status_sync(db, busy_task.id, TASK_FAILED_STATUS)
        await db.commit()

    exhausted_task = await create_task_row(
        workspace_id,
        indexed_kb_id,
        indexed_doc_id,
        TASK_PARSE,
        actor_user_id,
        status=TASK_RUNNING_STATUS,
        attempts=3,
    )
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(
            db,
            exhausted_task.id,
        )
        assert task is not None
        task.lease_expires_at = (utc_now() - timedelta(seconds=1)).replace(
            tzinfo=None
        )
        task.worker_task_id = "other-worker"
        await knowledge_repository.save_knowledge_task(db, task)
        await db.commit()
    with patch.object(
        task_runner_service,
        "utc_now",
        new=lambda: datetime.now(UTC).replace(tzinfo=None),
    ):
        outcome = await run_knowledge_task(exhausted_task.id, settings)
    assert outcome == TASK_RUN_FINISHED
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(
            db,
            exhausted_task.id,
        )
        assert task is not None
        assert task.status == TASK_FAILED_STATUS
        assert "retry limit" in (task.last_error or "")

    finished_task = await create_task_row(
        workspace_id,
        indexed_kb_id,
        None,
        TASK_REBUILD_INDEX,
        actor_user_id,
        status=TASK_SUCCEEDED_STATUS,
    )
    outcome = await run_knowledge_task(finished_task.id, settings)
    assert outcome == TASK_RUN_FINISHED

    # "unsupported task type" is unreachable: the DB CHECK constraint
    # ck_knowledge_tasks_task_type rejects any other task_type, so the
    # runner's fallback branch is dead code (documented in buglog).

    # owns-lease failure at the end -> rollback + finished
    chain_doc = upload_document(
        client,
        research_token,
        workspace_id,
        indexed_kb_id,
        "chain.txt",
        b"chain me",
        "text/plain",
    )
    chain_doc_id = chain_doc["id"]
    chain_task_id = await enqueue_parse(
        indexed_kb_id,
        chain_doc_id,
        "research-admin",
        {"auto_index": False},
    )
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, chain_task_id)
        assert task is not None
        assert task.status == TASK_QUEUED_STATUS
    with patch.object(
        task_runner_service,
        "maintain_knowledge_task_lease",
        new=AsyncMock(),
    ), patch.object(
        knowledge_repository,
        "renew_knowledge_task_lease",
        new=AsyncMock(return_value=False),
    ):
        outcome = await run_knowledge_task(chain_task_id, settings)
    assert outcome == TASK_RUN_FINISHED
    async with get_session_factory()() as db:
        await set_task_status_sync(db, chain_task_id, TASK_SUCCEEDED_STATUS)
        await db.commit()

    # chain failure: parse succeeded but chained index enqueue raises
    chain_task2_id = await enqueue_parse(
        indexed_kb_id,
        chain_doc_id,
        "research-admin",
        {"auto_index": True},
    )
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, chain_task2_id)
        assert task is not None
        assert task.status == TASK_QUEUED_STATUS
    with patch.object(
        task_runner_service,
        "enqueue_index_knowledge_document",
        new=AsyncMock(side_effect=RuntimeError("chain boom")),
    ):
        outcome = await run_knowledge_task(chain_task2_id, settings)
    assert outcome == TASK_RUN_FINISHED
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, chain_task2_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(
            db,
            chain_doc_id,
        )
        assert task is not None and doc is not None
        assert task.status == TASK_SUCCEEDED_STATUS
        assert doc.status == DOCUMENT_PARSED_STATUS
        assert "chain boom" in (doc.last_error or "")

    # chain success: enqueue_task callback receives the chained index task
    chain_task3_id = await enqueue_parse(
        indexed_kb_id,
        chain_doc_id,
        "research-admin",
        {"auto_index": True},
    )
    chained_ids: list[str] = []

    async def record_chain(task_id: str, _settings) -> None:
        chained_ids.append(task_id)

    outcome = await run_knowledge_task(
        chain_task3_id,
        settings,
        enqueue_task=record_chain,
    )
    assert outcome == TASK_RUN_FINISHED
    assert chained_ids, "chained index task must be enqueued"
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(
            db,
            chained_ids[0],
        )
        assert task is not None
        assert task.task_type == TASK_INDEX


async def run_parse_task_direct_tests(
    workspace_id: str,
    actor_user_id: str,
    knowledge_base_id: str,
    document_id: str,
) -> None:
    settings = test_settings()
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, knowledge_base_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(db, document_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        assert kb is not None and doc is not None and actor is not None
        doc.status = "uploaded"
        doc.last_error = None
        await knowledge_repository.save_knowledge_document(db, doc)
        await db.commit()

    task_id = await enqueue_parse(
        knowledge_base_id,
        document_id,
        "research-admin",
        {"auto_index": False},
    )

    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
        kb = await knowledge_repository.get_knowledge_base_by_id(db, knowledge_base_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(db, document_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        assert task is not None and kb is not None and doc is not None and actor is not None
        await run_parse_task(
            db,
            task,
            kb,
            doc,
            actor,
            settings,
            asyncio.Event(),
        )
        await db.commit()
        assert doc.status == DOCUMENT_PARSED_STATUS
        assert task.total_items == 1 and task.processed_items == 1
        initial_normalized_key = str(doc.meta["normalized_artifact_key"])
        initial_normalized_path = settings.knowledge_storage_dir / initial_normalized_key
        initial_document_version = int(doc.meta["document_version"])
        assert len(str(doc.meta["normalized_content_hash"])) == 64
        assert doc.meta["normalized_text_version"] == "normalized-markdown-v1"
        assert initial_normalized_path.exists()

    with_assets = DocumentChunkDrafts(
        parents=[ParentChunkDraft(title="P", content="index me revised")],
        children=[
            ChildChunkDraft(
                content="index me revised",
                parent_index=0,
                start_offset=0,
                end_offset=16,
                asset_indexes=[0],
            )
        ],
        assets=[
            DocumentAssetDraft(
                id="asset-parse-1",
                filename="pic.png",
                content_type="image/png",
                content=b"\x89PNG",
                alt_text="",
            )
        ],
        normalized_text="index me revised",
    )
    without_assets = DocumentChunkDrafts(
        parents=[ParentChunkDraft(title="P", content="index me changed")],
        children=[
            ChildChunkDraft(
                content="index me changed",
                parent_index=0,
                start_offset=0,
                end_offset=16,
                asset_indexes=[],
            )
        ],
        assets=[],
        normalized_text="index me changed",
    )

    async def reset_for_run(db, task, doc) -> None:
        task.status = TASK_QUEUED_STATUS
        task.finished_at = None
        task.attempts = 0
        task.total_items = 0
        task.processed_items = 0
        await knowledge_repository.save_knowledge_task(db, task)
        doc.status = "uploaded"
        doc.last_error = None
        await knowledge_repository.save_knowledge_document(db, doc)

    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
        kb = await knowledge_repository.get_knowledge_base_by_id(db, knowledge_base_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(db, document_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        assert task is not None and kb is not None and doc is not None and actor is not None
        await reset_for_run(db, task, doc)
        await db.commit()
        with patch.object(
            task_runner_service,
            "extract_document_chunk_contents",
            new=AsyncMock(return_value=with_assets),
        ):
            await run_parse_task(
                db,
                task,
                kb,
                doc,
                actor,
                settings,
                asyncio.Event(),
            )
        await db.commit()
        asset_rows = await knowledge_repository.list_document_assets(db, kb, document_id)
        assert asset_rows, "asset must be persisted"
        asset_object_key = asset_rows[0].object_key
        with_assets_normalized_key = str(doc.meta["normalized_artifact_key"])
        assert int(doc.meta["document_version"]) == initial_document_version + 1
        assert not initial_normalized_path.exists()
        assert (
            settings.knowledge_storage_dir / with_assets_normalized_key
        ).read_text(encoding="utf-8") == "index me revised"

        # third parse without assets -> stale asset cleanup
        await reset_for_run(db, task, doc)
        await db.commit()
        with patch.object(
            task_runner_service,
            "extract_document_chunk_contents",
            new=AsyncMock(return_value=without_assets),
        ):
            await run_parse_task(
                db,
                task,
                kb,
                doc,
                actor,
                settings,
                asyncio.Event(),
            )
        await db.commit()
        asset_rows_after = await knowledge_repository.list_document_assets(
            db,
            kb,
            document_id,
        )
        assert asset_rows_after == []
        assert not (
            test_settings().knowledge_storage_dir / asset_object_key
        ).exists()
        current_normalized_key = str(doc.meta["normalized_artifact_key"])
        current_normalized_path = settings.knowledge_storage_dir / current_normalized_key
        assert int(doc.meta["document_version"]) == initial_document_version + 2
        assert not (
            settings.knowledge_storage_dir / with_assets_normalized_key
        ).exists()
        assert current_normalized_path.read_text(encoding="utf-8") == "index me changed"

        # commit failure -> rollback + written assets cleanup
        await reset_for_run(db, task, doc)
        await db.commit()

        original_commit = db.commit

        async def failing_commit() -> None:
            raise RuntimeError("commit failed (test)")

        db.commit = failing_commit  # type: ignore[method-assign]
        try:
            with patch.object(
                task_runner_service,
                "extract_document_chunk_contents",
                new=AsyncMock(return_value=with_assets),
            ):
                try:
                    await run_parse_task(
                        db,
                        task,
                        kb,
                        doc,
                        actor,
                        settings,
                        asyncio.Event(),
                    )
                except RuntimeError as exc:
                    assert "commit failed" in str(exc)
                else:
                    raise AssertionError("commit failure must propagate")
        finally:
            db.commit = original_commit  # type: ignore[method-assign]
        await db.rollback()
        assert not (
            settings.knowledge_storage_dir / with_assets_normalized_key
        ).exists()
        assert current_normalized_path.exists()
        # the direct runs never claimed the task; close it so later enqueues
        # for the same document do not see an open task
        task.status = TASK_SUCCEEDED_STATUS
        task.finished_at = utc_now()
        await knowledge_repository.save_knowledge_task(db, task)
        await db.commit()

    async with get_session_factory()() as db:
        persisted_doc = await knowledge_repository.get_knowledge_document_by_id(
            db, document_id
        )
        assert persisted_doc is not None
        assert persisted_doc.meta["normalized_artifact_key"] == current_normalized_key
        assert int(persisted_doc.meta["document_version"]) == initial_document_version + 2


# ---------------------------------------------------------------------------
# Celery job bodies (sync section: the jobs call asyncio.run internally)
# ---------------------------------------------------------------------------


def _create_kb(client, token: str, workspace_id: str, name: str) -> str:
    response = client.post(
        knowledge_url(workspace_id),
        headers=auth_headers(token),
        json={"name": name, "description": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class _RetrySentinel(Exception):
    pass


class _FakeTaskSelf:
    def __init__(self) -> None:
        self.retry_kwargs: list[dict] = []

    def retry(self, **kwargs):
        self.retry_kwargs.append(kwargs)
        raise _RetrySentinel()


def run_celery_job_tests(
    client,
    research_token: str,
    workspace_id: str,
    actor_user_id: str,
    no_model_kb_id: str,
    no_model_doc_id: str,
) -> None:
    settings = test_settings()
    # celery does not map CELERY_TASK_ALWAYS_EAGER onto its own config, so
    # apply_async-based recover jobs would hit the broker; force eager mode.
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)

    # run_knowledge_task_job: success
    job_doc = upload_document(
        client,
        research_token,
        workspace_id,
        no_model_kb_id,
        "job.txt",
        b"job body",
        "text/plain",
    )
    job_doc_id = job_doc["id"]
    job_task_id = asyncio.run(
        enqueue_parse(
            no_model_kb_id,
            job_doc_id,
            "research-admin",
            {"auto_index": False},
        )
    )
    fake_self = _FakeTaskSelf()
    run_knowledge_task_job.run.__func__(fake_self, job_task_id)  # type: ignore[attr-defined]
    async def _assert_succeeded() -> None:
        async with get_session_factory()() as db:
            task = await knowledge_repository.get_knowledge_task_by_id(db, job_task_id)
            assert task is not None
            assert task.status == TASK_SUCCEEDED_STATUS
    asyncio.run(_assert_succeeded())

    # run_knowledge_task_job: crash
    with patch.object(
        knowledge_tasks_module,
        "run_knowledge_task",
        new=Mock(side_effect=RuntimeError("job crash")),
    ):
        try:
            run_knowledge_task_job.run.__func__(  # type: ignore[attr-defined]
                _FakeTaskSelf(),
                "00000000-0000-0000-0000-000000000030",
            )
        except RuntimeError as exc:
            assert "job crash" in str(exc)
        else:
            raise AssertionError("job crash must propagate")

    # run_knowledge_task_job: busy -> retry
    busy_job_task = asyncio.run(
        create_task_row(
            workspace_id,
            no_model_kb_id,
            no_model_doc_id,
            TASK_PARSE,
            actor_user_id,
            status=TASK_RUNNING_STATUS,
        )
    )
    asyncio.run(_make_running_with_lease(busy_job_task.id))
    fake_self_busy = _FakeTaskSelf()
    with patch.object(
        task_runner_service,
        "utc_now",
        new=lambda: datetime.now(UTC).replace(tzinfo=None),
    ):
        try:
            run_knowledge_task_job.run.__func__(  # type: ignore[attr-defined]
                fake_self_busy,
                busy_job_task.id,
            )
        except _RetrySentinel:
            pass
        else:
            raise AssertionError("busy outcome must request a retry")
    assert fake_self_busy.retry_kwargs

    # recover_knowledge_tasks_job: only redispatches task ids selected by the
    # durable lease-aware recovery query.
    with (
        patch.object(
            knowledge_tasks_module,
            "list_recoverable_knowledge_task_ids",
            new=AsyncMock(return_value=["task-recover-1", "task-recover-2"]),
        ),
        patch.object(
            knowledge_tasks_module.run_knowledge_task_job,
            "apply_async",
        ) as apply_async,
    ):
        recover_knowledge_tasks_job()
    assert [call.kwargs for call in apply_async.call_args_list] == [
        {"args": ("task-recover-1",)},
        {"args": ("task-recover-2",)},
    ]

    with (
        patch.object(
            knowledge_tasks_module,
            "reconcile_knowledge_graphs",
            new=AsyncMock(return_value=["graph-task-1", "graph-task-2"]),
        ),
        patch.object(
            knowledge_tasks_module.run_knowledge_task_job,
            "apply_async",
        ) as apply_async,
    ):
        reconcile_knowledge_graphs_job()
    assert [call.kwargs for call in apply_async.call_args_list] == [
        {"args": ("graph-task-1",)},
        {"args": ("graph-task-2",)},
    ]

    # run_knowledge_storage_cleanup_job: success
    cleanup_kb_id = _create_kb(client, research_token, workspace_id, "Cleanup Job KB")
    cleanup_id = asyncio.run(create_cleanup_record(workspace_id, cleanup_kb_id))
    fake_self_cleanup = _FakeTaskSelf()
    run_knowledge_storage_cleanup_job.run.__func__(  # type: ignore[attr-defined]
        fake_self_cleanup,
        cleanup_id,
    )
    assert fake_self_cleanup.retry_kwargs == []

    # run_knowledge_storage_cleanup_job: failure -> retry
    failing_kb_id = _create_kb(client, research_token, workspace_id, "Failing Cleanup KB")
    failing_cleanup_id = asyncio.run(
        create_cleanup_record(workspace_id, failing_kb_id)
    )
    with patch.object(
        cleanup_service,
        "purge_knowledge_base_storage",
        new=AsyncMock(side_effect=RuntimeError("cleanup boom")),
    ):
        fake_self_fail = _FakeTaskSelf()
        try:
            run_knowledge_storage_cleanup_job.run.__func__(  # type: ignore[attr-defined]
                fake_self_fail,
                failing_cleanup_id,
            )
        except _RetrySentinel:
            pass
        else:
            raise AssertionError("cleanup failure must request a retry")
    assert fake_self_fail.retry_kwargs

    # recover_knowledge_storage_cleanups_job
    recover_kb_id = _create_kb(client, research_token, workspace_id, "Recover Cleanup KB")
    recover_cleanup_id = asyncio.run(
        create_cleanup_record(workspace_id, recover_kb_id)
    )
    recover_knowledge_storage_cleanups_job()
    asyncio.run(_assert_cleanup_gone(recover_cleanup_id))

    # run_upload_storage_cleanup_job: success
    upload_cleanup_id = asyncio.run(
        _create_upload_cleanup(workspace_id, actor_user_id, "uploads/missing-file.bin")
    )
    fake_self_upload = _FakeTaskSelf()
    run_upload_storage_cleanup_job.run.__func__(  # type: ignore[attr-defined]
        fake_self_upload,
        upload_cleanup_id,
    )
    assert fake_self_upload.retry_kwargs == []

    # run_upload_storage_cleanup_job: failure -> retry
    failing_upload_cleanup_id = asyncio.run(
        _create_upload_cleanup(workspace_id, actor_user_id, "uploads/failing.bin")
    )
    from app.shareddomain.workflows import uploads as uploads_module

    with patch.object(
        uploads_module,
        "create_object_storage",
    ) as create_storage:
        create_storage.return_value = SimpleNamespace(
            delete=Mock(side_effect=RuntimeError("delete boom"))
        )
        fake_self_upload_fail = _FakeTaskSelf()
        try:
            run_upload_storage_cleanup_job.run.__func__(  # type: ignore[attr-defined]
                fake_self_upload_fail,
                failing_upload_cleanup_id,
            )
        except _RetrySentinel:
            pass
        else:
            raise AssertionError("upload cleanup failure must request a retry")
    assert fake_self_upload_fail.retry_kwargs

    # recover_upload_storage_cleanups_job
    due_upload_cleanup_id = asyncio.run(
        _create_upload_cleanup(workspace_id, actor_user_id, "uploads/due.bin")
    )
    recover_upload_storage_cleanups_job()
    asyncio.run(_assert_upload_cleanup_gone(due_upload_cleanup_id))

    # enqueue_knowledge_task: non-eager dispatch failure
    non_eager_settings = replace(settings, celery_task_always_eager=False)
    dispatch_fail_task = asyncio.run(
        create_task_row(
            workspace_id,
            no_model_kb_id,
            no_model_doc_id,
            TASK_PARSE,
            actor_user_id,
        )
    )
    with patch.object(
        knowledge_tasks_module.run_knowledge_task_job,
        "apply_async",
        new=Mock(side_effect=RuntimeError("broker down")),
    ):
        try:
            asyncio.run(
                enqueue_knowledge_task(dispatch_fail_task.id, non_eager_settings)
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("non-eager dispatch failure must propagate")
    asyncio.run(_assert_task_failed_dispatch(dispatch_fail_task.id))
    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=True,
    )

    # enqueue_knowledge_task: eager path for a missing task (no raise)
    asyncio.run(
        enqueue_knowledge_task("00000000-0000-0000-0000-000000000031", settings)
    )

    # enqueue_knowledge_storage_cleanup: eager failure swallowed
    with patch.object(
        knowledge_tasks_module,
        "run_knowledge_storage_cleanup",
        new=AsyncMock(side_effect=RuntimeError("eager cleanup boom")),
    ):
        asyncio.run(enqueue_knowledge_storage_cleanup("cleanup-x", settings))

    # enqueue_knowledge_storage_cleanup: non-eager dispatch failure swallowed
    with patch.object(
        knowledge_tasks_module.run_knowledge_storage_cleanup_job,
        "apply_async",
        new=Mock(side_effect=RuntimeError("broker down")),
    ):
        asyncio.run(
            enqueue_knowledge_storage_cleanup("cleanup-y", non_eager_settings)
        )
    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=True,
    )

    # enqueue_upload_storage_cleanups: eager failure swallowed + continue
    with patch.object(
        knowledge_tasks_module,
        "run_upload_storage_cleanup",
        new=AsyncMock(side_effect=RuntimeError("upload boom")),
    ):
        asyncio.run(enqueue_upload_storage_cleanups(["upload-a", "upload-b"], settings))

    # enqueue_upload_storage_cleanups: non-eager dispatch failure swallowed
    with patch.object(
        knowledge_tasks_module.run_upload_storage_cleanup_job,
        "apply_async",
        new=Mock(side_effect=RuntimeError("broker down")),
    ):
        asyncio.run(
            enqueue_upload_storage_cleanups(["upload-c", "upload-d"], non_eager_settings)
        )
    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=True,
    )


async def _make_running_with_lease(task_id: str) -> None:
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
        assert task is not None
        task.lease_expires_at = (utc_now() + timedelta(seconds=300)).replace(
            tzinfo=None
        )
        task.worker_task_id = "other-worker"
        await knowledge_repository.save_knowledge_task(db, task)
        await db.commit()


async def _assert_cleanup_gone(cleanup_id: str) -> None:
    async with get_session_factory()() as db:
        row = await knowledge_repository.lock_knowledge_storage_cleanup(
            db,
            cleanup_id,
        )
        assert row is None


async def _assert_upload_cleanup_gone(cleanup_id: str) -> None:
    async with get_session_factory()() as db:
        row = await workflow_repository.lock_upload_cleanup(db, cleanup_id)
        assert row is None


async def _assert_task_failed_dispatch(task_id: str) -> None:
    async with get_session_factory()() as db:
        task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
        assert task is not None
        assert task.status == TASK_FAILED_STATUS
        assert "queue is unavailable" in (task.last_error or "")


async def _create_upload_cleanup(
    workspace_id: str,
    actor_user_id: str,
    object_key: str,
) -> str:
    async with get_session_factory()() as db:
        cleanup = WorkflowUploadStorageCleanup(
            id=new_id(),
            workspace_id=workspace_id,
            uploaded_by_user_id=actor_user_id,
            object_key=object_key,
            size_bytes=1,
        )
        cleanup = await workflow_repository.create_upload_cleanup(db, cleanup)
        await db.commit()
        return cleanup.id


# ---------------------------------------------------------------------------
# Repository direct tests
# ---------------------------------------------------------------------------


async def run_repository_direct_tests(
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    actor_user_id: str,
    embedding_model_id: str,
) -> None:
    async with get_session_factory()() as db:
        kb = await knowledge_repository.get_knowledge_base_by_id(db, knowledge_base_id)
        doc = await knowledge_repository.get_knowledge_document_by_id(db, document_id)
        actor = await user_repository.get_user_by_id(db, actor_user_id)
        assert kb is not None and doc is not None and actor is not None

        # seed one preview chunk so chunk-level helpers have data
        db.add(
            knowledge_models.KnowledgeDocumentChunk(
                id=new_id(),
                workspace_id=kb.workspace_id,
                knowledge_base_id=kb.id,
                document_id=document_id,
                parent_id=None,
                chunk_index=0,
                start_offset=None,
                end_offset=None,
                content="repo probe chunk",
                char_count=16,
                token_count=3,
                vector_id=None,
                status=CHUNK_PREVIEW_STATUS,
            )
        )
        await db.commit()

        # list_knowledge_bases_with_user_grants: empty + populated
        assert (
            await knowledge_repository.list_knowledge_bases_with_user_grants(
                db,
                workspace_id,
                [],
                actor.id,
                "knowledge_base",
            )
            == []
        )
        rows = await knowledge_repository.list_knowledge_bases_with_user_grants(
            db,
            workspace_id,
            [knowledge_base_id],
            actor.id,
            "knowledge_base",
        )
        assert [row[0].id for row in rows] == [knowledge_base_id]

        # list_and_lock_knowledge_bases_in_workspace
        locked = await knowledge_repository.list_and_lock_knowledge_bases_in_workspace(
            db,
            workspace_id,
        )
        assert knowledge_base_id in {item.id for item in locked}

        assert (
            await knowledge_repository.get_knowledge_base_by_id(
                db,
                "00000000-0000-0000-0000-000000000040",
            )
            is None
        )

        await knowledge_repository.set_knowledge_base_embedding_model_id(
            db,
            knowledge_base_id,
            embedding_model_id,
        )
        await db.commit()
        refreshed = await knowledge_repository.get_knowledge_base_by_id(
            db,
            knowledge_base_id,
        )
        assert refreshed is not None
        assert refreshed.embedding_model_id == embedding_model_id

        # delete_knowledge_base (entity-level; missing row is a no-op)
        ghost_entity = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="Ghost Entity",
            description="",
            status="active",
            created_by_user_id=actor.id,
        )
        await knowledge_repository.delete_knowledge_base(db, ghost_entity)
        assert (
            await knowledge_repository.get_knowledge_base_by_id(db, ghost_entity.id)
            is None
        )

        # document helpers
        assert (
            await knowledge_repository.get_knowledge_document_by_id(
                db,
                "00000000-0000-0000-0000-000000000041",
            )
            is None
        )
        list_docs = await knowledge_repository.list_knowledge_documents(
            db,
            kb,
            include_staged=True,
        )
        assert document_id in {item.id for item in list_docs}
        one_page = await knowledge_repository.list_knowledge_documents(
            db,
            kb,
            include_staged=True,
            limit=1,
            offset=0,
        )
        assert len(one_page) == 1

        counts = await knowledge_repository.count_document_chunks(db, kb)
        assert isinstance(counts, dict)

        doc_chunks = await knowledge_repository.list_indexable_chunks(
            db,
            kb,
            document_id=document_id,
        )
        assert doc_chunks
        by_status = await knowledge_repository.list_indexable_chunks(
            db,
            kb,
            statuses={CHUNK_PREVIEW_STATUS},
        )
        assert by_status

        chunk_entity = await knowledge_repository.list_document_chunks(
            db,
            kb,
            document_id,
            limit=1,
        )
        assert chunk_entity
        chunk_entity[0].status = CHUNK_INDEXED_STATUS
        await knowledge_repository.save_knowledge_document_chunk(db, chunk_entity[0])
        await db.commit()

        assert await knowledge_repository.list_chunks_by_ids(db, kb, []) == []
        found_chunks = await knowledge_repository.list_chunks_by_ids(
            db,
            kb,
            [chunk_entity[0].id],
        )
        assert [chunk.id for chunk in found_chunks] == [chunk_entity[0].id]

        assert await knowledge_repository.list_parent_chunks_by_ids(db, kb, set()) == []
        assert (
            await knowledge_repository.list_parent_chunks_by_ids(
                db,
                kb,
                {"00000000-0000-0000-0000-000000000042"},
            )
            == []
        )

        assert (
            await knowledge_repository.list_active_documents_by_ids(db, kb, set())
            == []
        )
        active = await knowledge_repository.list_active_documents_by_ids(
            db,
            kb,
            {document_id},
        )
        assert [item.id for item in active] == [document_id]

        assert (
            await knowledge_repository.query_keyword_chunk_ids(
                db,
                kb,
                "query",
                10,
            )
            == []
        )

        doc_tasks = await knowledge_repository.list_knowledge_tasks(
            db,
            kb,
            document_id=document_id,
            limit=1,
            offset=0,
        )
        assert doc_tasks
        all_tasks = await knowledge_repository.list_knowledge_tasks(
            db,
            kb,
            limit=100,
            offset=0,
        )
        assert len(all_tasks) >= len(doc_tasks)

        sample_task = doc_tasks[0]
        by_id = await knowledge_repository.get_knowledge_task_by_id(db, sample_task.id)
        assert by_id is not None and by_id.id == sample_task.id
        locked_task = await knowledge_repository.lock_knowledge_task(db, sample_task.id)
        assert locked_task is not None
        await knowledge_repository.save_knowledge_task(db, locked_task)
        refreshed_task = await knowledge_repository.refresh_knowledge_task(
            db,
            locked_task,
        )
        assert refreshed_task.id == locked_task.id

        queued_claim = await knowledge_repository.claim_knowledge_task(
            db,
            sample_task.id,
            utc_now(),
            utc_now() + timedelta(seconds=300),
            "worker-claim-1",
        )
        assert queued_claim is False  # task already finished
        running_task = await knowledge_repository.get_knowledge_task_by_id(
            db,
            sample_task.id,
        )
        assert running_task is not None
        running_task.status = TASK_RUNNING_STATUS
        running_task.worker_task_id = "worker-claim-2"
        running_task.lease_expires_at = (utc_now() + timedelta(seconds=300)).replace(
            tzinfo=None
        )
        await knowledge_repository.save_knowledge_task(db, running_task)
        await db.commit()
        recoverable = await knowledge_repository.list_recoverable_tasks(
            db,
            utc_now(),
        )
        assert sample_task.id not in {task.id for task in recoverable}
        claimed = await knowledge_repository.claim_knowledge_task(
            db,
            sample_task.id,
            utc_now(),
            utc_now() + timedelta(seconds=300),
            "worker-claim-3",
        )
        assert claimed is False  # running with valid lease

        running_task.lease_expires_at = (utc_now() - timedelta(seconds=1)).replace(
            tzinfo=None
        )
        await knowledge_repository.save_knowledge_task(db, running_task)
        await db.commit()
        recoverable = await knowledge_repository.list_recoverable_tasks(
            db,
            utc_now(),
        )
        assert sample_task.id in {task.id for task in recoverable}

        running_task.attempts = running_task.max_attempts
        await knowledge_repository.save_knowledge_task(db, running_task)
        await db.commit()
        recoverable = await knowledge_repository.list_recoverable_tasks(
            db,
            utc_now(),
        )
        assert sample_task.id not in {task.id for task in recoverable}

        renewed_wrong = await knowledge_repository.renew_knowledge_task_lease(
            db,
            sample_task.id,
            "worker-other",
            utc_now() + timedelta(seconds=300),
        )
        assert renewed_wrong is False
        renewed_right = await knowledge_repository.renew_knowledge_task_lease(
            db,
            sample_task.id,
            "worker-claim-2",
            utc_now() + timedelta(seconds=300),
        )
        assert renewed_right is True

        open_doc = await knowledge_repository.get_open_document_task(
            db,
            kb,
            document_id,
        )
        assert isinstance(open_doc, (KnowledgeTask, type(None)))
        open_kb_task = await knowledge_repository.get_open_knowledge_task(
            db,
            kb,
            TASK_PARSE,
            document_id,
        )
        assert isinstance(open_kb_task, (KnowledgeTask, type(None)))
        open_base = await knowledge_repository.get_open_knowledge_base_task(db, kb)
        assert isinstance(open_base, (KnowledgeTask, type(None)))

        await knowledge_repository.fail_open_document_tasks(
            db,
            kb,
            document_id,
            "failed by test",
        )
        await db.commit()

        # attachment + asset helpers
        attachment = KnowledgeAttachment(
            id=new_id(),
            workspace_id=kb.workspace_id,
            knowledge_base_id=kb.id,
            filename="a.txt",
            content_type="text/plain",
            size_bytes=1,
            object_key=f"{kb.workspace_id}/{kb.id}/attachments/{new_id()}/a.txt",
            status="available",
            created_by_user_id=actor.id,
        )
        attachment = await knowledge_repository.create_knowledge_attachment(
            db,
            attachment,
        )
        await db.commit()
        by_attachment = await knowledge_repository.get_knowledge_attachment_by_id(
            db,
            attachment.id,
        )
        assert by_attachment is not None
        locked_attachments = await knowledge_repository.lock_knowledge_attachments(
            db,
            [attachment.id],
        )
        assert [item.id for item in locked_attachments] == [attachment.id]
        await knowledge_repository.save_knowledge_attachment(db, attachment)
        refreshed_attachment = await knowledge_repository.refresh_knowledge_attachment(
            db,
            attachment,
        )
        assert refreshed_attachment.id == attachment.id
        await knowledge_repository.delete_knowledge_attachment(db, attachment)
        await db.commit()
        assert (
            await knowledge_repository.get_knowledge_attachment_by_id(
                db,
                attachment.id,
            )
            is None
        )

        asset = KnowledgeAsset(
            id=new_id(),
            workspace_id=kb.workspace_id,
            knowledge_base_id=kb.id,
            document_id=document_id,
            asset_index=1,
            kind="image",
            filename="pic.png",
            content_type="image/png",
            size_bytes=4,
            object_key=f"{kb.workspace_id}/{kb.id}/assets/{document_id}/pic.png",
            alt_text="",
        )
        await save_asset(db, asset)
        await db.commit()
        assets = await knowledge_repository.list_document_assets(db, kb, document_id)
        assert asset.id in {item.id for item in assets}
        one_asset = await knowledge_repository.get_document_asset(
            db,
            kb,
            document_id,
            asset.id,
        )
        assert one_asset is not None
        assert (
            await knowledge_repository.get_document_asset(
                db,
                kb,
                document_id,
                "00000000-0000-0000-0000-000000000043",
            )
            is None
        )
        assert await knowledge_repository.list_chunk_assets(db, kb, set()) == []
        chunk_assets = await knowledge_repository.list_chunk_assets(
            db,
            kb,
            {chunk_entity[0].id},
        )
        assert chunk_assets == []
        await db.commit()

        keys = await knowledge_repository.delete_document_assets(db, document_id)
        assert asset.object_key in keys
        await db.commit()
        assert (
            await knowledge_repository.list_document_assets(db, kb, document_id)
            == []
        )

        await knowledge_repository.delete_document_chunks(db, document_id)
        await db.commit()
        assert (
            await knowledge_repository.list_document_chunks(db, kb, document_id)
            == []
        )

        # replace_document_chunks with parents/children/links
        parent = KnowledgeDocumentParentChunk(
            id=new_id(),
            workspace_id=kb.workspace_id,
            knowledge_base_id=kb.id,
            document_id=document_id,
            parent_index=0,
            title="Parent",
            content="parent content",
            char_count=14,
        )
        child = KnowledgeDocumentChunk(
            id=new_id(),
            workspace_id=kb.workspace_id,
            knowledge_base_id=kb.id,
            document_id=document_id,
            parent_id=parent.id,
            chunk_index=0,
            start_offset=0,
            end_offset=6,
            content="parent",
            char_count=6,
            token_count=1,
            status=CHUNK_PREVIEW_STATUS,
        )
        link_asset = KnowledgeAsset(
            id=new_id(),
            workspace_id=kb.workspace_id,
            knowledge_base_id=kb.id,
            document_id=document_id,
            asset_index=2,
            kind="image",
            filename="link.png",
            content_type="image/png",
            size_bytes=4,
            object_key=f"{kb.workspace_id}/{kb.id}/assets/{document_id}/link.png",
            alt_text="",
        )
        await knowledge_repository.replace_document_chunks(
            db,
            kb,
            document_id,
            [parent],
            [child],
            [link_asset],
            [(child.id, link_asset.id, 0)],
        )
        await db.commit()
        parents = await knowledge_repository.list_parent_chunks_by_ids(
            db,
            kb,
            {parent.id},
        )
        assert [item.id for item in parents] == [parent.id]
        chunk_assets = await knowledge_repository.list_chunk_assets(
            db,
            kb,
            {child.id},
        )
        assert [item[0].asset_id for item in chunk_assets] == [link_asset.id]

        # replace_document_chunks: empty variant (rows deleted first)
        await knowledge_repository.delete_document_chunks(db, document_id)
        await db.commit()
        await knowledge_repository.replace_document_chunks(
            db,
            kb,
            document_id,
            [],
            [],
            [],
            [],
        )
        await db.commit()
        assert (
            await knowledge_repository.list_document_chunks(db, kb, document_id)
            == []
        )

        # delete_knowledge_base_graph cascades
        marker_kb = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="Graph KB",
            description="",
            status="active",
            created_by_user_id=actor.id,
        )
        marker_kb = await knowledge_repository.create_knowledge_base(db, marker_kb)
        await db.commit()
        marker_doc = KnowledgeDocument(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=marker_kb.id,
            filename="g.txt",
            content_type="text/plain",
            size_bytes=1,
            storage_path="none",
            status="uploaded",
            created_by_user_id=actor.id,
        )
        marker_doc = await knowledge_repository.create_knowledge_document(
            db,
            marker_doc,
        )
        await db.commit()
        marker_task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id=new_id(),
                workspace_id=workspace_id,
                knowledge_base_id=marker_kb.id,
                document_id=marker_doc.id,
                task_type=TASK_PARSE,
                status=TASK_QUEUED_STATUS,
                attempts=0,
                max_attempts=3,
                total_items=0,
                processed_items=0,
                options={},
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()
        marker_parent = KnowledgeDocumentParentChunk(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=marker_kb.id,
            document_id=marker_doc.id,
            parent_index=0,
            title="P",
            content="x",
            char_count=1,
        )
        marker_child = KnowledgeDocumentChunk(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=marker_kb.id,
            document_id=marker_doc.id,
            chunk_index=0,
            content="x",
            char_count=1,
            token_count=1,
            status=CHUNK_PREVIEW_STATUS,
        )
        marker_asset = KnowledgeAsset(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=marker_kb.id,
            document_id=marker_doc.id,
            asset_index=0,
            kind="image",
            filename="x.png",
            content_type="image/png",
            size_bytes=1,
            object_key=f"{workspace_id}/{marker_kb.id}/assets/x.png",
            alt_text="",
        )
        await knowledge_repository.replace_document_chunks(
            db,
            marker_kb,
            marker_doc.id,
            [marker_parent],
            [marker_child],
            [marker_asset],
            [],
        )
        await db.commit()
        await knowledge_repository.delete_knowledge_base_graph(
            db,
            marker_kb,
            "knowledge_base",
        )
        await db.commit()
        assert (
            await knowledge_repository.get_knowledge_base_by_id(db, marker_kb.id)
            is None
        )
        assert (
            await knowledge_repository.get_knowledge_document_by_id(
                db,
                marker_doc.id,
            )
            is None
        )
        assert (
            await knowledge_repository.get_knowledge_task_by_id(db, marker_task.id)
            is None
        )

        # delete_knowledge_document (repo-level): row + missing row no-op
        marker_doc2 = KnowledgeDocument(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            filename="g2.txt",
            content_type="text/plain",
            size_bytes=1,
            storage_path="none",
            status="uploaded",
            created_by_user_id=actor.id,
        )
        await knowledge_repository.create_knowledge_document(db, marker_doc2)
        await db.commit()
        await knowledge_repository.delete_knowledge_document(db, marker_doc2)
        await db.commit()
        assert (
            await knowledge_repository.get_knowledge_document_by_id(
                db,
                marker_doc2.id,
            )
            is None
        )
        await knowledge_repository.delete_knowledge_document(db, marker_doc2)


def test_evaluation_migrations_support_sqlite() -> None:
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    def load_migration(filename: str, module_name: str):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    evaluation = load_migration(
        "202608150003_knowledge_evaluation.py",
        "knowledge_evaluation_migration",
    )
    answer_points = load_migration(
        "202608160002_remove_evaluation_answer_points.py",
        "knowledge_answer_points_migration",
    )
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "knowledge",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.UniqueConstraint("workspace_id", "id"),
    )
    sa.Table(
        "knowledge_tasks",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(36), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "task_type IN ('parse', 'index', 'rebuild_index')",
            name="ck_knowledge_tasks_task_type",
        ),
    )

    with engine.begin() as connection:
        metadata.create_all(connection)
        operations = Operations(MigrationContext.configure(connection))
        evaluation.op = operations
        answer_points.op = operations

        evaluation.upgrade()
        answer_points.upgrade()

        inspector = sa.inspect(connection)
        assert "knowledge_evaluation_cases" in inspector.get_table_names()
        constraints = inspector.get_check_constraints("knowledge_tasks")
        assert any("evaluate" in item["sqltext"] for item in constraints)
        defaults = {
            item["name"]: item["default"]
            for item in inspector.get_columns("knowledge_evaluation_cases")
        }
        assert "[]" in defaults["answer_points"]

        answer_points.downgrade()
        evaluation.downgrade()
        inspector = sa.inspect(connection)
        assert "knowledge_evaluation_cases" not in inspector.get_table_names()
        constraints = inspector.get_check_constraints("knowledge_tasks")
        assert all("evaluate" not in item["sqltext"] for item in constraints)

    engine.dispose()


def main() -> None:
    import app.tasks as tasks_package

    tasks_package._configured_process_id = os.getpid()

    test_parse_task_options()
    test_clean_upload_filename()
    test_batches_and_task_error_message()
    test_run_knowledge_model_test_branches()
    test_ensure_knowledge_task_lease()
    test_maintain_knowledge_task_lease()
    test_evaluation_migrations_support_sqlite()
    with model_test_server() as model_base_url:
        test_api_scenario(model_base_url)
    print("OK: knowledge_domain_coverage")




# ---------------------------------------------------------------------------
# Direct shareddomain tests (documents / lifecycle / kb / permissions /
# orchestration / task runner tails)
# ---------------------------------------------------------------------------


async def run_direct_shareddomain_tests(
    client,
    admin_token: str,
    workspace_id: str,
    model_base_url: str,
) -> None:
    from io import BytesIO

    from fastapi import HTTPException, UploadFile

    from app.schemas.knowledge import (
        KnowledgeBaseCreateRequest,
        KnowledgeBaseUpdateRequest,
        KnowledgeDocumentCreateRequest,
        KnowledgeModelTestRequest,
    )
    from app.shareddomain.knowledge.services import (
        get_knowledge_model as services_get_knowledge_model,
    )
    from app.infrastructure.repositories import (
        resource_permission as permission_repository,
    )
    from app.entities.resource_permission import ResourcePermission

    settings = test_settings()
    direct_embedding = create_model(
        client,
        admin_token,
        workspace_id,
        "Direct Embedding",
        "EMBEDDING",
        "text-embedding-3-small",
        api_base=model_base_url,
    )
    direct_reranker = create_model(
        client,
        admin_token,
        workspace_id,
        "Direct Reranker",
        "RERANKER",
        "custom-reranker",
        provider="model_custom_provider",
        api_base=model_base_url,
    )

    async with get_session_factory()() as db:
        alice = await user_repository.get_active_user_by_username(db, "alice")
        assert alice is not None

        # ---- kb.get_knowledge_model branches ----
        default_model = await services_get_knowledge_model(
            db,
            workspace_id,
            None,
            "EMBEDDING",
            use_default=True,
        )
        assert default_model is not None and default_model.id == direct_embedding
        explicit = await services_get_knowledge_model(
            db,
            workspace_id,
            direct_embedding,
            "EMBEDDING",
        )
        assert explicit is not None
        try:
            await services_get_knowledge_model(
                db,
                workspace_id,
                "00000000-0000-0000-0000-000000000050",
                "EMBEDDING",
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("missing model must 422")

        # ---- kb.require_can_manage_permissions ----
        # create a fresh KB via repository for direct tests
        direct_kb = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="Direct KB",
            description="direct",
            status="active",
            embedding_model_id=direct_embedding,
            reranker_model_id=direct_reranker,
            created_by_user_id=alice.id,
        )
        direct_kb = await knowledge_repository.create_knowledge_base(db, direct_kb)
        await db.commit()

        kb_service.require_can_manage_permissions(direct_kb, alice, "member")
        other = SimpleNamespace(id="00000000-0000-0000-0000-000000000051")
        try:
            kb_service.require_can_manage_permissions(direct_kb, other, "member")
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("non-owner must 403")
        kb_service.require_can_manage_permissions(direct_kb, other, "admin")

        # ---- kb.list_knowledge_bases ----
        listed = await kb_service.list_knowledge_bases(
            db,
            workspace_id,
            alice,
            "member",
            limit=10,
            offset=0,
        )
        assert any(item.id == direct_kb.id for item in listed)

        # ---- kb.get_knowledge_base 404 ----
        try:
            await kb_service.get_knowledge_base(
                db,
                "00000000-0000-0000-0000-000000000052",
                direct_kb.id,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("cross-workspace KB must 404")

        # ---- kb.create_knowledge_base (success + IntegrityError) ----
        created = await kb_service.create_knowledge_base(
            db,
            workspace_id,
            KnowledgeBaseCreateRequest(
                name="Direct Created KB",
                description="x",
                embedding_model_id=None,
                reranker_model_id=None,
            ),
            alice,
        )
        assert created.name == "Direct Created KB"
        assert created.embedding_model_id == direct_embedding  # default resolved
        try:
            await kb_service.create_knowledge_base(
                db,
                workspace_id,
                KnowledgeBaseCreateRequest(name="Direct Created KB", description="y"),
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("duplicate KB name must 409")

        # ---- kb.update_knowledge_base ----
        updated = await kb_service.update_knowledge_base(
            db,
            direct_kb,
            KnowledgeBaseUpdateRequest(
                name="Direct KB Renamed",
                description="updated",
                status="active",
                embedding_model_id=None,
                reranker_model_id=None,
            ),
            alice,
            "member",
        )
        assert updated.name == "Direct KB Renamed"
        assert updated.embedding_model_id is None
        try:
            await kb_service.update_knowledge_base(
                db,
                direct_kb,
                KnowledgeBaseUpdateRequest(status="locked"),
                alice,
                "member",
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("invalid status must 422")
        # restore models for later index flows
        await kb_service.update_knowledge_base(
            db,
            direct_kb,
            KnowledgeBaseUpdateRequest(
                embedding_model_id=direct_embedding,
                reranker_model_id=direct_reranker,
            ),
            alice,
            "member",
        )
        # archived KB: non-restore writes rejected
        await kb_service.update_knowledge_base(
            db,
            direct_kb,
            KnowledgeBaseUpdateRequest(status="archived"),
            alice,
            "member",
        )
        try:
            await kb_service.update_knowledge_base(
                db,
                direct_kb,
                KnowledgeBaseUpdateRequest(description="nope"),
                alice,
                "member",
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("archived write must 403")
        bob_entity = await user_repository.get_active_user_by_username(db, "bob")
        assert bob_entity is not None
        try:
            await kb_service.update_knowledge_base(
                db,
                direct_kb,
                KnowledgeBaseUpdateRequest(status="active"),
                bob_entity,
                "member",
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("archived restore by non-owner must 403")
        await kb_service.update_knowledge_base(
            db,
            direct_kb,
            KnowledgeBaseUpdateRequest(status="active"),
            alice,
            "admin",
        )

        # ---- kb.test_knowledge_base_models ----
        model_test = await kb_service.test_knowledge_base_models(
            db,
            direct_kb,
            KnowledgeModelTestRequest(query="q", documents=["d"]),
            settings,
        )
        assert model_test.embedding_dimensions >= 0

        no_model_kb_entity = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="No Model Direct",
            description="",
            status="active",
            embedding_model_id=None,
            reranker_model_id=None,
            created_by_user_id=alice.id,
        )
        no_model_kb_entity = await knowledge_repository.create_knowledge_base(
            db,
            no_model_kb_entity,
        )
        await db.commit()
        with patch.object(
            kb_service,
            "get_knowledge_model",
            new=AsyncMock(return_value=None),
        ):
            try:
                await kb_service.test_knowledge_base_models(
                    db,
                    no_model_kb_entity,
                    KnowledgeModelTestRequest(query="q", documents=["d"]),
                    settings,
                )
            except HTTPException as exc:
                assert exc.status_code == 422
            else:
                raise AssertionError("missing embedding model must 422")

        # ---- kb.transfer_knowledge_base_owner ----
        bob = await user_repository.get_active_user_by_username(db, "bob")
        assert bob is not None
        try:
            await kb_service.transfer_knowledge_base_owner(
                db,
                direct_kb,
                "00000000-0000-0000-0000-000000000053",
                alice,
                "member",
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("missing transfer target must 404")
        transferred = await kb_service.transfer_knowledge_base_owner(
            db,
            direct_kb,
            bob.id,
            alice,
            "member",
        )
        assert transferred.created_by_user_id == bob.id
        # transfer back
        await kb_service.transfer_knowledge_base_owner(
            db,
            direct_kb,
            alice.id,
            bob,
            "member",
        )

        # ---- permissions: upsert / revoke / require ----
        from app.shareddomain.knowledge.permissions import (
            require_knowledge_base_permission,
        )

        granted = await permissions_service.upsert_resource_permission(
            db,
            direct_kb,
            bob.id,
            "view",
            alice,
        )
        assert granted.permission == "view"
        upgraded = await permissions_service.upsert_resource_permission(
            db,
            direct_kb,
            bob.id,
            "edit",
            alice,
        )
        assert upgraded.permission == "edit"
        permission = await require_knowledge_base_permission(
            db,
            direct_kb,
            bob,
            "member",
            {"edit"},
        )
        assert permission == "edit"
        stranger = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000054",
            username="stranger",
            name="Stranger",
        )
        try:
            await require_knowledge_base_permission(
                db,
                direct_kb,
                stranger,
                "member",
                {"view"},
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("no-grant access must 403")
        await permissions_service.revoke_resource_permission(
            db,
            direct_kb,
            bob.id,
            alice,
        )
        try:
            await permissions_service.revoke_resource_permission(
                db,
                direct_kb,
                bob.id,
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("double revoke must 404")

        # ---- documents: upload / delete / create directly ----
        upload = UploadFile(
            BytesIO(b"direct document body"),
            filename="direct.txt",
        )
        attachment = await documents_service.upload_knowledge_attachment(
            db,
            direct_kb,
            upload,
            alice,
            settings,
        )
        assert attachment.filename == "direct.txt"

        # upload commit failure -> rollback + storage cleanup
        second_upload = UploadFile(
            BytesIO(b"second body"),
            filename="second.txt",
        )
        original_commit = db.commit

        async def failing_commit() -> None:
            raise RuntimeError("upload commit failed (test)")

        db.commit = failing_commit  # type: ignore[method-assign]
        try:
            try:
                await documents_service.upload_knowledge_attachment(
                    db,
                    direct_kb,
                    second_upload,
                    alice,
                    settings,
                )
            except RuntimeError as exc:
                assert "upload commit failed" in str(exc)
            else:
                raise AssertionError("upload commit failure must propagate")
        finally:
            db.commit = original_commit  # type: ignore[method-assign]
        await db.rollback()

        # delete attachment: missing -> 404; success -> 204 path
        try:
            await documents_service.delete_knowledge_attachment(
                db,
                direct_kb,
                "00000000-0000-0000-0000-000000000055",
                alice,
                settings,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("missing attachment delete must 404")
        await documents_service.delete_knowledge_attachment(
            db,
            direct_kb,
            attachment.id,
            alice,
            settings,
        )

        # create documents from attachments (success + error branches)
        att1 = await documents_service.upload_knowledge_attachment(
            db,
            direct_kb,
            UploadFile(BytesIO(b"one"), filename="one.txt"),
            alice,
            settings,
        )
        att2 = await documents_service.upload_knowledge_attachment(
            db,
            direct_kb,
            UploadFile(BytesIO(b"two"), filename="two.txt"),
            alice,
            settings,
        )
        try:
            await documents_service.create_knowledge_documents_from_attachments(
                db,
                direct_kb,
                KnowledgeDocumentCreateRequest(
                    attachment_ids=[att1.id, att1.id],
                    staged=False,
                ),
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("duplicate attachment ids must 422")
        try:
            await documents_service.create_knowledge_documents_from_attachments(
                db,
                direct_kb,
                KnowledgeDocumentCreateRequest(
                    attachment_ids=["00000000-0000-0000-0000-000000000056"],
                    staged=False,
                ),
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("missing attachment must 404")
        created_docs = (
            await documents_service.create_knowledge_documents_from_attachments(
                db,
                direct_kb,
                KnowledgeDocumentCreateRequest(
                    attachment_ids=[att1.id, att2.id],
                    staged=True,
                ),
                alice,
            )
        )
        assert len(created_docs) == 2
        assert created_docs[0].meta["staged"] is True
        # consumed attachment reuse -> 409
        try:
            await documents_service.create_knowledge_documents_from_attachments(
                db,
                direct_kb,
                KnowledgeDocumentCreateRequest(
                    attachment_ids=[att1.id],
                    staged=False,
                ),
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("consumed attachment must 409")

        # ---- lifecycle.delete_knowledge_document ----
        direct_doc = created_docs[0]
        # give the document chunks + a vector id
        await knowledge_repository.replace_document_chunks(
            db,
            direct_kb,
            direct_doc.id,
            [],
            [
                KnowledgeDocumentChunk(
                    id=new_id(),
                    workspace_id=workspace_id,
                    knowledge_base_id=direct_kb.id,
                    document_id=direct_doc.id,
                    parent_id=None,
                    chunk_index=0,
                    start_offset=None,
                    end_offset=None,
                    content="delete me",
                    char_count=9,
                    token_count=2,
                    vector_id="vector-1",
                    status=CHUNK_PREVIEW_STATUS,
                )
            ],
            [],
            [],
        )
        await db.commit()
        doc_entity = await knowledge_repository.get_knowledge_document_by_id(
            db,
            direct_doc.id,
        )
        assert doc_entity is not None
        normalized_key = (
            f"{workspace_id}/{direct_kb.id}/normalized/{direct_doc.id}/delete.md"
        )
        normalized_path = settings.knowledge_storage_dir / normalized_key
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text("delete me", encoding="utf-8")
        doc_entity.meta = {
            **(doc_entity.meta or {}),
            "normalized_artifact_key": normalized_key,
        }
        await knowledge_repository.save_knowledge_document(db, doc_entity)
        await db.commit()
        await lifecycle_service.delete_knowledge_document(
            db,
            direct_kb,
            doc_entity,
            alice,
            settings,
        )
        after_delete = await knowledge_repository.get_knowledge_document_by_id(
            db,
            direct_doc.id,
        )
        assert after_delete is not None
        assert after_delete.status == DOCUMENT_DELETED_STATUS
        assert not normalized_path.exists()
        assert (
            await knowledge_repository.list_document_chunks(
                db,
                direct_kb,
                direct_doc.id,
            )
            == []
        )

        # lifecycle: lock None -> 404
        ghost = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="Ghost Lifecycle",
            description="",
            status="active",
            created_by_user_id=alice.id,
        )
        try:
            await lifecycle_service.delete_knowledge_document(
                db,
                ghost,
                doc_entity,
                alice,
                settings,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("ghost KB delete must 404")

        # lifecycle: archived KB -> 403
        archived_kb2 = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="Archived Lifecycle",
            description="",
            status="archived",
            created_by_user_id=alice.id,
        )
        archived_kb2 = await knowledge_repository.create_knowledge_base(
            db,
            archived_kb2,
        )
        await db.commit()
        try:
            await lifecycle_service.delete_knowledge_document(
                db,
                archived_kb2,
                doc_entity,
                alice,
                settings,
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("archived KB delete must 403")

        # lifecycle: set_knowledge_document_active
        try:
            await lifecycle_service.set_knowledge_document_active(
                db,
                direct_kb,
                doc_entity,
                alice,
                False,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("deleted document status update must 404")
        status_document = await knowledge_repository.get_knowledge_document_by_id(
            db,
            created_docs[1].id,
        )
        assert status_document is not None
        unchanged = await lifecycle_service.set_knowledge_document_active(
            db,
            direct_kb,
            status_document,
            alice,
            status_document.is_active,
        )
        assert unchanged.is_active is status_document.is_active
        deactivated_document = await lifecycle_service.set_knowledge_document_active(
            db,
            direct_kb,
            status_document,
            alice,
            False,
        )
        assert deactivated_document.is_active is False
        reactivated_document = await lifecycle_service.set_knowledge_document_active(
            db,
            direct_kb,
            status_document,
            alice,
            True,
        )
        assert reactivated_document.is_active is True

        # ---- orchestration tails ----
        # get_knowledge_document success
        found = await orchestration_service.get_knowledge_document(
            db,
            direct_kb,
            created_docs[1].id,
        )
        assert found.id == created_docs[1].id

        # resolve_embedding_model sets kb model id when absent
        bare_kb = await knowledge_repository.get_knowledge_base_by_id(
            db,
            no_model_kb_entity.id,
        )
        assert bare_kb is not None
        resolved = await orchestration_service.resolve_embedding_model(db, bare_kb)
        assert resolved is not None
        assert bare_kb.embedding_model_id == resolved.id

        # get_conflicting_open_task: document open task branch
        open_task = await orchestration_service.get_conflicting_open_task(
            db,
            direct_kb,
            TASK_PARSE,
            direct_doc.id,
        )
        assert open_task is None or open_task.status in ("queued", "running")

        # create_knowledge_task: conflicting open task -> 409
        conflict_doc_entity = await knowledge_repository.get_knowledge_document_by_id(
            db,
            created_docs[1].id,
        )
        assert conflict_doc_entity is not None
        await orchestration_service.create_knowledge_task(
            db,
            direct_kb,
            conflict_doc_entity,
            TASK_PARSE,
            alice,
            {"auto_index": False},
        )
        try:
            await orchestration_service.create_knowledge_task(
                db,
                direct_kb,
                conflict_doc_entity,
                TASK_PARSE,
                alice,
                {"auto_index": False},
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("conflicting open task must 409")

        # create_knowledge_task: index without embedding model -> 422
        bare_doc = KnowledgeDocument(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=bare_kb.id,
            filename="bare.txt",
            content_type="text/plain",
            size_bytes=1,
            storage_path="none",
            status="uploaded",
            created_by_user_id=alice.id,
        )
        await knowledge_repository.create_knowledge_document(db, bare_doc)
        await db.commit()
        try:
            await orchestration_service.create_knowledge_task(
                db,
                bare_kb,
                bare_doc,
                TASK_INDEX,
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("index without model must 422")

        # create_knowledge_task: index with model but no preview chunks -> 422
        await knowledge_repository.set_knowledge_base_embedding_model_id(
            db,
            no_model_kb_entity.id,
            direct_embedding,
        )
        await db.commit()
        bare_kb = await knowledge_repository.get_knowledge_base_by_id(
            db,
            no_model_kb_entity.id,
        )
        assert bare_kb is not None
        try:
            await orchestration_service.create_knowledge_task(
                db,
                bare_kb,
                bare_doc,
                TASK_INDEX,
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
            assert "preview" in exc.detail
        else:
            raise AssertionError("index without preview chunks must 422")

        # create_knowledge_task: rebuild with indexed chunks -> task created
        indexed_doc = KnowledgeDocument(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=direct_kb.id,
            filename="indexed.txt",
            content_type="text/plain",
            size_bytes=1,
            storage_path="none",
            status="indexed",
            created_by_user_id=alice.id,
        )
        await knowledge_repository.create_knowledge_document(db, indexed_doc)
        await db.commit()
        await knowledge_repository.replace_document_chunks(
            db,
            direct_kb,
            indexed_doc.id,
            [],
            [
                KnowledgeDocumentChunk(
                    id=new_id(),
                    workspace_id=workspace_id,
                    knowledge_base_id=direct_kb.id,
                    document_id=indexed_doc.id,
                    parent_id=None,
                    chunk_index=0,
                    start_offset=None,
                    end_offset=None,
                    content="indexed",
                    char_count=7,
                    token_count=2,
                    vector_id="vector-2",
                    status=CHUNK_INDEXED_STATUS,
                )
            ],
            [],
            [],
        )
        await db.commit()
        # close the open parse task created by the conflict test above
        open_kb_task = await knowledge_repository.get_open_knowledge_base_task(
            db,
            direct_kb,
        )
        if open_kb_task is not None:
            await set_task_status_sync(db, open_kb_task.id, TASK_FAILED_STATUS)
            await db.commit()
        rebuild_task = await orchestration_service.create_knowledge_task(
            db,
            direct_kb,
            None,
            TASK_REBUILD_INDEX,
            alice,
        )
        assert rebuild_task.total_items == 1
        async with get_session_factory()() as db2:
            await set_task_status_sync(db2, rebuild_task.id, TASK_FAILED_STATUS)
            await db2.commit()

        # retry_knowledge_task branches (uses the non-deleted document)
        failed_task = await create_task_row(
            workspace_id,
            direct_kb.id,
            conflict_doc_entity.id,
            TASK_PARSE,
            alice.id,
        )
        async with get_session_factory()() as db2:
            await set_task_status_sync(db2, failed_task.id, TASK_FAILED_STATUS)
            await db2.commit()
        # retry with a conflicting open task -> 409
        async with get_session_factory()() as db2:
            blocker = await create_task_row(
                workspace_id,
                direct_kb.id,
                conflict_doc_entity.id,
                TASK_PARSE,
                alice.id,
            )
            await db2.commit()
        try:
            await orchestration_service.retry_knowledge_task(
                db,
                direct_kb,
                failed_task.id,
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("retry with open task must 409")
        async with get_session_factory()() as db2:
            await set_task_status_sync(db2, blocker.id, TASK_FAILED_STATUS)
            await db2.commit()
        retried = await orchestration_service.retry_knowledge_task(
            db,
            direct_kb,
            failed_task.id,
            alice,
        )
        assert retried.status == TASK_QUEUED_STATUS
        # retry non-failed -> 409
        try:
            await orchestration_service.retry_knowledge_task(
                db,
                direct_kb,
                failed_task.id,
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("retry non-failed task must 409")
        # retry at limit -> 409
        async with get_session_factory()() as db2:
            t = await knowledge_repository.get_knowledge_task_by_id(db2, failed_task.id)
            assert t is not None
            t.status = TASK_FAILED_STATUS
            t.attempts = 3
            await knowledge_repository.save_knowledge_task(db2, t)
            await db2.commit()
        try:
            await orchestration_service.retry_knowledge_task(
                db,
                direct_kb,
                failed_task.id,
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("retry at limit must 409")
        # retry unknown task -> 404
        try:
            await orchestration_service.retry_knowledge_task(
                db,
                direct_kb,
                "00000000-0000-0000-0000-000000000057",
                alice,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("retry unknown task must 404")

        # ---- task runner tails (direct runs) ----
        # run_parse_task aborts for deleted document (line 119)
        doomed = KnowledgeDocument(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=direct_kb.id,
            filename="doomed2.txt",
            content_type="text/plain",
            size_bytes=1,
            storage_path="none",
            status=DOCUMENT_DELETED_STATUS,
            created_by_user_id=alice.id,
        )
        await knowledge_repository.create_knowledge_document(db, doomed)
        await db.commit()
        doomed_task_row = await create_task_row(
            workspace_id,
            direct_kb.id,
            doomed.id,
            TASK_PARSE,
            alice.id,
        )
        async with get_session_factory()() as db2:
            task_entity = await knowledge_repository.get_knowledge_task_by_id(
                db2,
                doomed_task_row.id,
            )
            kb_entity2 = await knowledge_repository.get_knowledge_base_by_id(
                db2,
                direct_kb.id,
            )
            doc_entity2 = await knowledge_repository.get_knowledge_document_by_id(
                db2,
                doomed.id,
            )
            assert task_entity is not None and kb_entity2 is not None
            assert doc_entity2 is not None
            try:
                await run_parse_task(
                    db2,
                    task_entity,
                    kb_entity2,
                    doc_entity2,
                    alice,
                    settings,
                    asyncio.Event(),
                )
            except KnowledgePipelineError:
                pass
            else:
                raise AssertionError("deleted document parse must abort")
            await set_task_status_sync(db2, doomed_task_row.id, TASK_FAILED_STATUS)
            await db2.commit()

        # run_knowledge_task failure path (outer except handler)
        failing_task_id = await enqueue_parse(
            direct_kb.id,
            direct_doc.id,
            "alice",
            {"auto_index": False},
        )
        async with get_session_factory()() as db2:
            # remove the file so extraction fails
            doc2 = await knowledge_repository.get_knowledge_document_by_id(
                db2,
                direct_doc.id,
            )
            assert doc2 is not None
            path = settings.knowledge_storage_dir / doc2.storage_path
            if path.exists():
                path.unlink()
            await db2.commit()
        outcome = await run_knowledge_task(failing_task_id, settings)
        assert outcome == TASK_RUN_FINISHED

        # chained index recursion (enqueue_task=None)
        chain_doc = KnowledgeDocument(
            id=new_id(),
            workspace_id=workspace_id,
            knowledge_base_id=direct_kb.id,
            filename="chain-direct.txt",
            content_type="text/plain",
            size_bytes=8,
            storage_path=f"{workspace_id}/{direct_kb.id}/attachments/chain.txt",
            status="uploaded",
            created_by_user_id=alice.id,
        )
        await knowledge_repository.create_knowledge_document(db, chain_doc)
        (settings.knowledge_storage_dir / chain_doc.storage_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )
        (settings.knowledge_storage_dir / chain_doc.storage_path).write_bytes(
            b"chain body"
        )
        await db.commit()
        chain_task_id = await enqueue_parse(
            direct_kb.id,
            chain_doc.id,
            "alice",
            {"auto_index": True},
        )
        with patch.object(
            task_runner_service,
            "upsert_vectors",
            new=Mock(),
        ):
            outcome = await run_knowledge_task(chain_task_id, settings)
        assert outcome == TASK_RUN_FINISHED

        # ---- kb.delete_knowledge_base_permanently ----
        deleted_kb = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="Direct Deleted KB",
            description="",
            status="active",
            embedding_model_id=None,
            reranker_model_id=None,
            created_by_user_id=alice.id,
        )
        deleted_kb = await knowledge_repository.create_knowledge_base(db, deleted_kb)
        await db.commit()
        cleanup_id = await kb_service.delete_knowledge_base_permanently(
            db,
            deleted_kb,
            alice,
            "member",
        )
        assert (
            await knowledge_repository.get_knowledge_base_by_id(db, deleted_kb.id)
            is None
        )
        await cleanup_service.run_knowledge_storage_cleanup(cleanup_id, settings)
        # archived delete -> 403
        archived_delete_kb = KnowledgeBase(
            id=new_id(),
            workspace_id=workspace_id,
            name="Archived Delete KB",
            description="",
            status="archived",
            created_by_user_id=alice.id,
        )
        archived_delete_kb = await knowledge_repository.create_knowledge_base(
            db,
            archived_delete_kb,
        )
        await db.commit()
        try:
            await kb_service.delete_knowledge_base_permanently(
                db,
                archived_delete_kb,
                alice,
                "member",
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("archived delete must 403")
        # open task delete -> 409
        busy_delete_task = await create_task_row(
            workspace_id,
            archived_delete_kb.id,
            None,
            TASK_REBUILD_INDEX,
            alice.id,
        )
        async with get_session_factory()() as db2:
            archived_delete_kb.status = "active"
            await knowledge_repository.save_knowledge_base(db2, archived_delete_kb)
            await db2.commit()
        try:
            await kb_service.delete_knowledge_base_permanently(
                db,
                archived_delete_kb,
                alice,
                "member",
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("open-task delete must 409")
        # resolve the open task and delete
        async with get_session_factory()() as db2:
            await set_task_status_sync(db2, busy_delete_task.id, TASK_FAILED_STATUS)
            await db2.commit()
        cleanup_id2 = await kb_service.delete_knowledge_base_permanently(
            db,
            archived_delete_kb,
            alice,
            "member",
        )
        await cleanup_service.run_knowledge_storage_cleanup(cleanup_id2, settings)


if __name__ == "__main__":
    main()

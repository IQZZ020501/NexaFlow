"""Knowledge-wide indexing scope, queue state, and isolation regressions."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from tests.support import activate_admin, auth_headers, create_active_user, test_client
from tests.support import settings as test_settings

from app.domain.knowledge.models import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeTask,
)
from app.infra.db.session import get_session_factory


async def seed(workspace_id, kb_id, other_kb_id, actor_id):
    async with get_session_factory()() as db:
        documents = [
            (f"pending-{i}", kb_id, "parsed" if i % 2 else "index_failed", {})
            for i in range(125)
        ] + [
            ("indexed", kb_id, "indexed", {}),
            ("busy", kb_id, "index_failed", {}),
            ("draft", kb_id, "index_failed", {"staged": True}),
            ("deleted", kb_id, "deleted", {}),
            ("no-chunks", kb_id, "index_failed", {}),
            ("unparsed", kb_id, "uploaded", {}),
            ("other-kb", other_kb_id, "index_failed", {}),
        ]
        for doc_id, scope, status, meta in documents:
            db.add(
                KnowledgeDocument(
                    id=doc_id,
                    workspace_id=workspace_id,
                    knowledge_base_id=scope,
                    filename=f"{doc_id}.md",
                    size_bytes=10,
                    storage_path=doc_id,
                    content_type="text/markdown",
                    status=status,
                    meta=meta,
                    last_error="old failure" if status == "index_failed" else None,
                    created_by_user_id=actor_id,
                )
            )
        await db.flush()
        for doc_id, scope, _, _ in documents:
            if doc_id in {"no-chunks", "unparsed"}:
                continue
            db.add(
                KnowledgeDocumentChunk(
                    workspace_id=workspace_id,
                    knowledge_base_id=scope,
                    document_id=doc_id,
                    content="A provision.",
                    char_count=12,
                    token_count=3,
                    chunk_index=0,
                    status="preview",
                )
            )
        db.add(
            KnowledgeTask(
                id="busy-task",
                workspace_id=workspace_id,
                knowledge_base_id=kb_id,
                document_id="busy",
                task_type="index",
                status="running",
                created_by_user_id=actor_id,
            )
        )
        await db.commit()


async def assert_queued(expected):
    async with get_session_factory()() as db:
        tasks = list(
            await db.scalars(
                select(KnowledgeTask).where(KnowledgeTask.status == "queued")
            )
        )
        assert len(tasks) == expected
        assert all(task.total_items == 1 and task.attempts == 0 for task in tasks)
        for task in tasks:
            document = await db.get(KnowledgeDocument, task.document_id)
            assert document.status == "index_queued"
            assert document.last_error is None
        for doc_id in ("busy", "draft", "deleted", "no-chunks", "unparsed", "other-kb"):
            document = await db.get(KnowledgeDocument, doc_id)
            assert document.status != "index_queued", doc_id


async def set_base_task(workspace, kb, actor, status):
    async with get_session_factory()() as db:
        task = await db.get(KnowledgeTask, "base-task")
        if task is None:
            task = KnowledgeTask(
                id="base-task",
                workspace_id=workspace,
                knowledge_base_id=kb,
                task_type="evaluate",
                created_by_user_id=actor,
            )
            db.add(task)
        task.status = status
        await db.commit()


def main():
    with test_client() as client:
        token, workspace = activate_admin(client)
        headers = auth_headers(token)
        base = f"/api/v1/workspaces/{workspace}/knowledge-bases"
        kb = client.post(base, headers=headers, json={"name": "Batch"}).json()["id"]
        other = client.post(base, headers=headers, json={"name": "Other"}).json()["id"]
        actor = client.get("/api/v1/auth/me", headers=headers).json()["user"]["id"]
        asyncio.run(seed(workspace, kb, other, actor))
        url = f"{base}/{kb}/documents/index"
        response = client.post(url, headers=headers, json={"scope": "invalid"})
        assert response.status_code == 422, response.text
        assert client.post(url, headers=headers, json={}).status_code == 422

        asyncio.run(set_base_task(workspace, kb, actor, "running"))
        response = client.post(url, headers=headers, json={"scope": "all"})
        assert response.status_code == 409, response.text
        asyncio.run(set_base_task(workspace, kb, actor, "failed"))

        with patch(
            "app.domain.knowledge.tasks.batch.resolve_embedding_model",
            new=AsyncMock(return_value=None),
        ):
            response = client.post(url, headers=headers, json={"scope": "unsuccessful"})
            assert response.status_code == 422, response.text
        asyncio.run(assert_queued(0))

        # Existing base pin avoids writing an invented model foreign key.
        with (
            patch(
                "app.domain.knowledge.tasks.batch.resolve_embedding_model",
                new=AsyncMock(return_value=SimpleNamespace(id="embedding-model")),
            ),
            patch(
                "app.domain.knowledge.tasks.batch.knowledge_base_repository.set_knowledge_base_embedding_model_id",
                new=AsyncMock(),
            ),
            patch(
                "app.api.v1.knowledge.routes.dispatch_knowledge_tasks", new=AsyncMock()
            ) as dispatch,
        ):
            from app.infra.db.repositories.knowledge import indexing

            original_create = indexing.create_batch_index_tasks

            async def fail_after_write(*args):
                await original_create(*args)
                raise RuntimeError("injected batch write failure")

            with patch.object(
                indexing, "create_batch_index_tasks", side_effect=fail_after_write
            ):
                failed = client.post(url, headers=headers, json={"scope": "all"})
                assert failed.status_code == 500, failed.text
                assert failed.json() == {"detail": "Internal Server Error"}
                assert dispatch.await_count == 0
            asyncio.run(assert_queued(0))

            response = client.post(url, headers=headers, json={"scope": "unsuccessful"})
            assert response.status_code == 202, response.text
            assert response.json() == {"queued_count": 125}
            assert len(dispatch.await_args.args[0]) == 125
            asyncio.run(assert_queued(125))

            # A second click skips every already-queued/running document.
            response = client.post(url, headers=headers, json={"scope": "unsuccessful"})
            assert response.status_code == 202, response.text
            assert response.json() == {"queued_count": 0}
            assert dispatch.await_count == 1
            asyncio.run(assert_queued(125))

            response = client.post(url, headers=headers, json={"scope": "all"})
            assert response.status_code == 202, response.text
            assert response.json() == {"queued_count": 1}
            asyncio.run(assert_queued(126))

        viewer_id, viewer_token = create_active_user(client, token, "batch-viewer")
        denied = client.post(
            url, headers=auth_headers(viewer_token), json={"scope": "all"}
        )
        assert denied.status_code in {403, 404}, denied.text
        member = client.post(
            f"/api/v1/workspaces/{workspace}/members",
            headers=headers,
            json={"user_id": viewer_id, "role": "member"},
        )
        assert member.status_code == 201, member.text
        grant = client.put(
            f"{base}/{kb}/permissions/{viewer_id}",
            headers=headers,
            json={"permission": "view"},
        )
        assert grant.status_code == 200, grant.text
        denied = client.post(
            url, headers=auth_headers(viewer_token), json={"scope": "all"}
        )
        assert denied.status_code == 403, denied.text

        archived = client.patch(
            f"{base}/{kb}", headers=headers, json={"status": "archived"}
        )
        assert archived.status_code == 200, archived.text
        denied = client.post(url, headers=headers, json={"scope": "all"})
        assert denied.status_code == 403, denied.text

        # A broker outage leaves the atomic batch queued for periodic recovery.
        from app.application.knowledge.documents.service import dispatch_knowledge_tasks

        with patch(
            "app.infra.queue.celery.publish_task",
            new=AsyncMock(side_effect=[None, OSError("offline")]),
        ) as publish:
            asyncio.run(
                dispatch_knowledge_tasks(
                    ["first", "second", "third"],
                    replace(test_settings(), celery_task_always_eager=False),
                )
            )
        assert publish.await_count == 2
        asyncio.run(assert_queued(126))
    print("KNOWLEDGE_BATCH_INDEXING_OK")


if __name__ == "__main__":
    main()

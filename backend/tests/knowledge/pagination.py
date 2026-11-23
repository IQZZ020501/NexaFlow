"""Knowledge lists paginate and aggregate the whole authorized resource."""

import asyncio
from datetime import UTC, datetime, timedelta

from tests.support import activate_admin, auth_headers, create_active_user, test_client

from app.domain.knowledge.models import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeTask,
)
from app.infra.db.session import get_session_factory


async def seed(workspace_id, kb_id, other_kb_id, actor_id):
    async with get_session_factory()() as db:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(125):
            status = (
                "indexed"
                if index < 100
                else "index_queued"
                if index < 110
                else "parse_queued"
                if index < 120
                else "parse_failed"
            )
            db.add(
                KnowledgeDocument(
                    id=f"doc-{index}",
                    workspace_id=workspace_id,
                    knowledge_base_id=kb_id,
                    filename=f"law-{index:03}.md",
                    content_type="text/markdown",
                    size_bytes=index + 1,
                    storage_path=f"original/{index}",
                    status=status,
                    created_by_user_id=actor_id,
                    created_at=start + timedelta(seconds=index),
                )
            )
            db.add(
                KnowledgeTask(
                    id=f"task-{index}",
                    workspace_id=workspace_id,
                    knowledge_base_id=kb_id,
                    document_id=f"doc-{index}",
                    task_type="parse",
                    status="running" if index == 0 else "succeeded",
                    created_by_user_id=actor_id,
                    created_at=start + timedelta(seconds=index),
                )
            )
        for doc_id, scope, status, meta in (
            ("staged", kb_id, "uploaded", {"staged": True}),
            ("deleted", kb_id, "deleted", {}),
            ("other", other_kb_id, "indexed", {}),
        ):
            db.add(
                KnowledgeDocument(
                    id=doc_id,
                    workspace_id=workspace_id,
                    knowledge_base_id=scope,
                    filename=f"{doc_id}.md",
                    size_bytes=1,
                    storage_path=doc_id,
                    status=status,
                    meta=meta,
                    created_by_user_id=actor_id,
                )
            )
        await db.flush()
        for index in range(2):
            db.add(
                KnowledgeDocumentChunk(
                    workspace_id=workspace_id,
                    knowledge_base_id=kb_id,
                    document_id="doc-124",
                    chunk_index=index,
                    content="law text",
                    char_count=8,
                    token_count=2,
                )
            )
        db.add(
            KnowledgeTask(
                id="rebuild",
                workspace_id=workspace_id,
                knowledge_base_id=kb_id,
                task_type="rebuild_index",
                status="queued",
                created_by_user_id=actor_id,
                total_items=200,
                processed_items=20,
                created_at=start,
            )
        )
        db.add(
            KnowledgeTask(
                id="staged-task",
                workspace_id=workspace_id,
                knowledge_base_id=kb_id,
                document_id="staged",
                task_type="parse",
                status="succeeded",
                created_by_user_id=actor_id,
            )
        )
        await db.commit()


def main():
    with test_client() as client:
        token, workspace = activate_admin(client)
        headers = auth_headers(token)
        base = f"/api/v1/workspaces/{workspace}/knowledge-bases"
        kb = client.post(base, headers=headers, json={"name": "Law"}).json()["id"]
        other = client.post(base, headers=headers, json={"name": "Other"}).json()["id"]
        actor = client.get("/api/v1/auth/me", headers=headers).json()["user"]["id"]
        asyncio.run(seed(workspace, kb, other, actor))
        url = f"{base}/{kb}"

        first = client.get(f"{url}/documents/page?limit=10", headers=headers)
        assert first.status_code == 200, first.text
        first = first.json()
        assert len(first["items"]) == 10 and first["total"] == 125
        assert first["summary"] == {
            "total": 125,
            "indexed": 100,
            "indexing": 10,
            "pending": 10,
            "failed": 5,
            "processing": 20,
        }, first["summary"]
        assert first["active_rebuild_task"]["id"] == "rebuild"
        assert first["items"][0]["id"] == "doc-124"
        assert first["items"][0]["chunk_count"] == 2
        last = client.get(
            f"{url}/documents/page?limit=10&offset=120", headers=headers
        ).json()
        assert len(last["items"]) == 5 and last["items"][-1]["id"] == "doc-0"
        assert {item["id"] for item in first["items"]}.isdisjoint(
            item["id"] for item in last["items"]
        )
        assert any(task["id"] == "task-0" for task in last["document_tasks"])
        found = client.get(
            f"{url}/documents/page?search=law-000", headers=headers
        ).json()
        assert found["total"] == 1 and found["summary"]["total"] == 125
        assert found["items"][0]["id"] == "doc-0"
        assert (
            client.get(f"{url}/documents/page?search=%25", headers=headers).json()[
                "total"
            ]
            == 0
        )
        sorted_page = client.get(
            f"{url}/documents/page?sort_by=chunk_count&sort_direction=desc&limit=1",
            headers=headers,
        ).json()
        assert sorted_page["items"][0]["id"] == "doc-124"
        assert (
            client.get(f"{url}/documents/page?limit=201", headers=headers).status_code
            == 422
        )
        assert (
            client.get(
                f"{url}/documents/page?sort_by=invalid", headers=headers
            ).status_code
            == 422
        )
        options = client.get(f"{url}/documents/options", headers=headers).json()
        assert len(options) == 125 and set(options[0]) == {
            "id",
            "filename",
            "is_active",
        }

        detail = client.get(f"{url}/documents/doc-0", headers=headers)
        assert detail.status_code == 200 and detail.json()["filename"] == "law-000.md"
        assert client.get(f"{url}/documents/other", headers=headers).status_code == 404
        assert (
            client.get(f"{url}/documents/deleted", headers=headers).status_code == 404
        )
        assert client.get(f"{url}/documents/staged", headers=headers).status_code == 200
        tasks = client.get(f"{url}/tasks/page?limit=10", headers=headers).json()
        assert tasks["total"] == 127 and tasks["has_processing"] is True
        assert len(tasks["items"]) == 10
        assert tasks["items"][1]["document_filename"] == "law-124.md"
        assert (
            len(
                client.get(
                    f"{url}/tasks/page?limit=10&offset=120", headers=headers
                ).json()["items"]
            )
            == 7
        )

        _, outsider = create_active_user(client, token, "outsider")
        denied = auth_headers(outsider)
        for path in (
            "documents/page",
            "documents/options",
            "tasks/page",
            "documents/doc-0",
        ):
            assert client.get(f"{url}/{path}", headers=denied).status_code in {403, 404}
        user_id = client.get("/api/v1/auth/me", headers=denied).json()["user"]["id"]
        client.post(
            f"/api/v1/workspaces/{workspace}/members",
            headers=headers,
            json={"user_id": user_id, "role": "member"},
        )
        granted = client.put(
            f"{url}/permissions/{user_id}", headers=headers, json={"permission": "view"}
        )
        assert granted.status_code == 200, granted.text
        assert (
            client.get(f"{url}/documents/page", headers=denied).json()["total"] == 125
        )
        assert client.get(f"{url}/tasks/page", headers=denied).json()["total"] == 126
        assert client.get(f"{url}/documents/staged", headers=denied).status_code == 404
        assert (
            client.get(
                f"{url}/documents/page?include_staged=true", headers=denied
            ).status_code
            == 403
        )
    print("Knowledge pagination, global statistics, detail and access checks passed.")


if __name__ == "__main__":
    main()

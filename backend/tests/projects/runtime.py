"""Real project/Run persistence, guest imports, conflicts and worker fencing."""

import asyncio
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.agents.agents import agent_model_server, agents_url, model_payload
from tests.support import activate_admin, auth_headers, settings, test_client

from app.application.agents.runs import service
from app.application.projects import runtime
from app.entities.defaults import utc_now
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.projects import repository
from app.infra.db.session import get_session_factory
from app.ports.execution import ExecutionError, ExecutionScope, execution_scope


async def claim(run_id):
    async with get_session_factory()() as db:
        assert await runs.claim_agent_run(
            db,
            run_id,
            "worker",
            utc_now(),
            utc_now() + timedelta(seconds=120),
            generation="unified",
            execution_deadline_at=utc_now() + timedelta(seconds=900),
        )
        await db.commit()
        return await runs.get_agent_run_by_id(db, run_id)


async def finish(run_id):
    async with get_session_factory()() as db:
        assert await runs.finalize_agent_run(
            db,
            run_id,
            "worker",
            status="succeeded",
            result="done",
            events=[],
            last_error=None,
            finished_at=utc_now(),
        )
        await db.commit()


async def save(run, contents, *, worker="worker"):
    exports = {
        f"/tmp/nexaflow-exports/test/{i}": content
        for i, content in enumerate(contents.values())
    }
    manifest = [
        {
            "relative_path": path,
            "path": key,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "deleted": False,
        }
        for (path, content), key in zip(contents.items(), exports, strict=True)
    ]
    platform = SimpleNamespace(
        read_session_file=AsyncMock(side_effect=lambda _w, _r, path, _m: exports[path])
    )
    context = SimpleNamespace(
        workspace_id=run.workspace_id,
        run_id=run.id,
        invocation_id="call",
        idempotency_key="call-" + run.id,
    )
    token = execution_scope.set(
        ExecutionScope(run.workspace_id, "call", run.id, worker)
    )
    try:
        return await runtime.save_project_files(
            settings(),
            run,
            context,
            platform,
            {"project_snapshot": True, "project_changes": manifest},
            {},
        )
    finally:
        execution_scope.reset(token)


def main():
    with (
        test_client() as client,
        agent_model_server() as model_url,
        patch.object(service, "enqueue_prepared_agent_run", AsyncMock()),
    ):
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        root = f"/api/v1/workspaces/{workspace_id}/projects"
        project = client.post(root, headers=headers, json={"name": "Persistent"}).json()
        base = f"{root}/{project['id']}"
        for path, content, role in [
            ("source.csv", b"amount\n12\n", "source"),
            ("script.py", b"print(1)", "work"),
        ]:
            uploaded = client.post(
                f"{base}/files",
                headers=headers,
                data={"path": path, "role": role},
                files={"file": (path, content)},
            )
            assert uploaded.status_code == 200, uploaded.text
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_url, "Project model"),
        )
        agent = client.post(
            agents_url(workspace_id),
            headers=headers,
            json={"name": "Project Agent", "model_id": model.json()["id"]},
        )
        assert agent.status_code == 201, agent.text
        run_url = agents_url(workspace_id, f"/{agent.json()['id']}/runs")

        def create(conversation, project_id=project["id"]):
            result = client.post(
                run_url,
                headers=headers,
                json={
                    "goal": "Edit project",
                    "conversation_id": conversation,
                    **({"project_id": project_id} if project_id else {}),
                },
            )
            assert result.status_code == 201, result.text
            assert result.json()["project_id"] == project["id"]
            return asyncio.run(claim(result.json()["id"]))

        first, concurrent = create("conversation-1"), create("conversation-2")
        assert client.delete(base, headers=headers).status_code == 409
        imports = SimpleNamespace(execute=AsyncMock(return_value={"ok": True}))
        asyncio.run(runtime.restore_project_files(first, imports, timeout_seconds=20))
        assert {
            call.args[0]["restore_project_files"]["role"]
            for call in imports.execute.await_args_list
        } == {"source", "work"}
        saved = asyncio.run(save(first, {"script.py": b"print(2)"}))
        assert saved["project_saved"] is True, saved
        unchanged = asyncio.run(save(first, {"script.py": b"print(2)"}))
        assert unchanged["project_revision"] == saved["project_revision"]
        conflict = asyncio.run(save(concurrent, {"script.py": b"print(3)"}))
        assert (
            conflict["project_saved"] is False
            and conflict["project_conflicts"][0]["artifact_id"]
        ), conflict
        assert (
            client.get(f"{base}/files", headers=headers).json()[0]["content_hash"]
            == hashlib.sha256(b"print(2)").hexdigest()
        )
        try:
            asyncio.run(
                save(first, {"script.py": b"stale worker"}, worker="old-worker")
            )
        except ExecutionError as exc:
            assert "lease" in str(exc)
        else:
            raise AssertionError("Old worker wrote project files")
        deleted = asyncio.run(save(first, {}))
        assert deleted["project_saved"] and deleted["project_files"][0]["deleted"]
        asyncio.run(finish(first.id))
        inherited = create("conversation-1", project_id=None)
        imports.execute.reset_mock()
        asyncio.run(
            runtime.restore_project_files(inherited, imports, timeout_seconds=20)
        )
        assert [
            call.args[0]["restore_project_files"]["role"]
            for call in imports.execute.await_args_list
        ] == ["source"]
        assert (
            "private persistent project"
            in service.execution_messages(inherited)[0]["content"]
        )
        asyncio.run(finish(inherited.id))
        other = client.post(root, headers=headers, json={"name": "Other"}).json()
        switched = client.post(
            run_url,
            headers=headers,
            json={
                "goal": "Switch",
                "conversation_id": "conversation-1",
                "project_id": other["id"],
            },
        )
        assert switched.status_code == 409, switched.text
        regenerated = client.post(
            f"{run_url}/{inherited.id}/regenerate", headers=headers, json={}
        )
        assert regenerated.status_code == 200, regenerated.text
        imports.execute.reset_mock()
        rebuilt = asyncio.run(claim(regenerated.json()["id"]))
        asyncio.run(runtime.restore_project_files(rebuilt, imports, timeout_seconds=20))
        assert imports.execute.await_count == 1

        async def cursor():
            async with get_session_factory()() as db:
                return await repository.get_run_state(db, rebuilt.id)

        assert asyncio.run(cursor()).file_heads
    print("PROJECT_RUNTIME_OK")


if __name__ == "__main__":
    main()

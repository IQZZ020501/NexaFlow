"""Conversation file imports, persistence, isolation and worker fencing."""

import asyncio
import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.agents.agents import agent_model_server, agents_url, model_payload
from tests.support import activate_admin, auth_headers, settings, test_client

from app.application.agents.runs import service
from app.application.projects import runtime
from app.application.projects import service as files_service
from app.entities.defaults import new_id, utc_now
from app.entities.projects import AgentProject as Project
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


async def stored(run):
    async with get_session_factory()() as db:
        project = run.application_snapshot["project"]
        result = {}
        for item in await repository.latest_files(db, project["id"]):
            if not item.deleted:
                version = await repository.get_version(db, project["id"], item.id)
                result[item.path] = version.content
        return result


def main():
    from sqlalchemy import select
    from tests.projects.api import archive
    from tests.support import create_active_user

    from app.application.agents.access import service as access
    from app.domain.projects.models import AgentProject

    with (
        test_client() as client,
        agent_model_server() as model_url,
        patch.object(service, "enqueue_prepared_agent_run", AsyncMock()),
        patch.object(access, "enqueue_prepared_agent_run", AsyncMock()),
    ):
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_url, "Conversation model"),
        )
        agent = client.post(
            agents_url(workspace_id),
            headers=headers,
            json={"name": "File Agent", "model_id": model.json()["id"]},
        )
        assert agent.status_code == 201, agent.text
        agent_id = agent.json()["id"]
        base = agents_url(workspace_id, f"/{agent_id}")
        assert (
            client.patch(base, headers=headers, json={"published": True}).status_code
            == 200
        )
        public = f"/api/v1/public/agents/{agent_id}"
        other_id, other_token = create_active_user(
            client, token, "conversation-files-user"
        )
        assert (
            client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=headers,
                json={"user_id": other_id, "role": "member"},
            ).status_code
            == 201
        )
        other_headers = auth_headers(other_token)

        def upload(root, identity, files):
            result = client.post(
                f"{root}/uploads",
                headers=identity,
                files=[("files", (name, content)) for name, content in files],
            )
            assert result.status_code == 201, result.text
            return [item["id"] for item in result.json()]

        def create(root, identity, conversation, file_ids=(), **extra):
            result = client.post(
                f"{root}/runs",
                headers=identity,
                json={
                    "goal": "Use the files",
                    "conversation_id": conversation,
                    "file_ids": list(file_ids),
                    **extra,
                },
            )
            assert result.status_code == 201, result.text
            assert "project_id" not in result.json()
            return asyncio.run(claim(result.json()["id"]))

        ids = upload(
            base,
            headers,
            [
                ("quarterly/data.csv", b"amount\n12\n"),
                (
                    "project.zip",
                    archive(
                        [
                            ("scripts/main.py", b"print(12)"),
                            ("node_modules/a.js", b"ignored"),
                        ]
                    ),
                ),
            ],
        )
        first = create(base, headers, "conversation-1", ids)
        assert asyncio.run(stored(first)) == {
            "quarterly/data.csv": b"amount\n12\n",
            "scripts/main.py": b"print(12)",
        }
        imports = SimpleNamespace(execute=AsyncMock(return_value={"ok": True}))
        assert asyncio.run(
            runtime.restore_project_files(first, imports, timeout_seconds=20)
        )
        assert len(imports.execute.await_args_list) == 2
        assert all(
            call.args[0]["restore_project_files"]["role"] == "work"
            for call in imports.execute.await_args_list
        )
        changed = {
            "quarterly/data.csv": b"amount\n24\n",
            "scripts/renamed.py": b"print(24)",
        }
        assert asyncio.run(save(first, changed))["project_saved"]
        assert asyncio.run(stored(first)) == changed
        try:
            asyncio.run(save(first, changed, worker="old-worker"))
        except ExecutionError as exc:
            assert "lease" in str(exc)
        else:
            raise AssertionError("Lost worker lease wrote files")
        # Another Run's checkpoint cannot be smuggled into this consumer scope.
        different = create(base, headers, "conversation-2")
        assert asyncio.run(stored(different)) == {}
        assert (
            first.application_snapshot["project"]["id"]
            != different.application_snapshot["project"]["id"]
        )
        asyncio.run(finish(first.id))
        next_run = create(base, headers, "conversation-1")
        assert asyncio.run(stored(next_run)) == changed
        old_version = first.application_snapshot["project"]["files"][0]

        async def original_bytes():
            async with get_session_factory()() as db:
                return (
                    await repository.get_version(
                        db,
                        first.application_snapshot["project"]["id"],
                        old_version["version_id"],
                    )
                ).content

        assert asyncio.run(original_bytes()) == b"amount\n12\n"
        asyncio.run(finish(next_run.id))
        ids = upload(base, headers, [("quarterly/data.csv", b"amount\n36\n")])
        replaced = create(base, headers, "conversation-1", ids)
        assert asyncio.run(stored(replaced))["quarterly/data.csv"] == b"amount\n36\n"
        asyncio.run(finish(replaced.id))

        empty_ids = upload(base, headers, [("package/__init__.py", b"")])
        empty_run = create(base, headers, "empty-files", empty_ids)
        assert asyncio.run(stored(empty_run)) == {"package/__init__.py": b""}
        assert asyncio.run(
            runtime.restore_project_files(empty_run, imports, timeout_seconds=20)
        )
        assert asyncio.run(save(empty_run, {"package/__init__.py": b""}))[
            "project_saved"
        ]
        with patch.object(
            runtime, "save_changes", AsyncMock(side_effect=ValueError("conflict"))
        ):
            conflict = asyncio.run(
                save(empty_run, {"package/__init__.py": b"", "new.txt": b""})
            )
        assert not conflict["project_saved"]
        assert conflict["project_conflicts"] == [
            {"relative_path": "new.txt", "empty_file": True}
        ]
        assert asyncio.run(stored(empty_run)) == {"package/__init__.py": b""}
        asyncio.run(finish(empty_run.id))

        async def legacy_conversation():
            async with get_session_factory()() as db:
                project = await repository.save_project(
                    db,
                    Project(
                        workspace_id=workspace_id,
                        created_by_user_id=replaced.consumer_id,
                        name="Old standalone project",
                    ),
                )
                await files_service.save_changes(
                    db,
                    project,
                    [
                        {"path": "old.txt", "role": "source", "content": b"legacy"},
                    ],
                )
                snapshot = deepcopy(replaced.application_snapshot)
                snapshot["project"] = await files_service.project_run_snapshot(
                    db, workspace_id, project.id, replaced.consumer_id
                )
                old_id = new_id()
                old = replace(
                    replaced,
                    id=old_id,
                    root_run_id=old_id,
                    status="succeeded",
                    finished_at=utc_now(),
                    worker_task_id=None,
                    lease_expires_at=None,
                    conversation_id="legacy",
                    application_snapshot=snapshot,
                )
                await runs.create_agent_run(db, old)
                await files_service.initialize_project_run(db, old)
                await db.commit()
                return project.id

        legacy_id = asyncio.run(legacy_conversation())
        migrated = create(base, headers, "legacy")
        assert migrated.application_snapshot["project"]["id"] != legacy_id
        assert asyncio.run(stored(migrated)) == {"old.txt": b"legacy"}
        assert migrated.application_snapshot["project"]["files"][0]["role"] == "work"
        asyncio.run(finish(migrated.id))

        # Public consumers own their own trees even though execution uses the publisher.
        ids = upload(
            public, other_headers, [("app/main.ts", b"export const value = 1")]
        )
        public_run = create(public, other_headers, "same-conversation", ids)
        assert public_run.execution_user_id != other_id
        assert public_run.application_snapshot["project"]["owner_id"] == other_id
        asyncio.run(
            runtime.restore_project_files(public_run, imports, timeout_seconds=20)
        )
        assert asyncio.run(
            save(public_run, {"app/main.ts": b"export const value = 2"})
        )["project_saved"]
        admin_run = create(public, headers, "same-conversation")
        assert asyncio.run(stored(admin_run)) == {}
        assert (
            client.delete(
                f"{public}/conversations/same-conversation", headers=other_headers
            ).status_code
            == 409
        )
        # A guessed file id never imports another user's upload.
        private_ids = upload(public, headers, [("secret.txt", b"private")])
        denied = client.post(
            f"{public}/runs",
            headers=other_headers,
            json={"goal": "use", "conversation_id": "other", "file_ids": private_ids},
        )
        assert denied.status_code == 404, denied.text
        forged = public_run.application_snapshot["project"].copy()
        public_run.application_snapshot["project"] = admin_run.application_snapshot[
            "project"
        ]
        try:
            asyncio.run(
                runtime.restore_project_files(public_run, imports, timeout_seconds=20)
            )
        except ExecutionError:
            pass
        else:
            raise AssertionError("Cross-user tree was accepted")
        public_run.application_snapshot["project"] = forged
        asyncio.run(finish(public_run.id))
        resumed = create(public, other_headers, "same-conversation")
        assert asyncio.run(stored(resumed)) == {
            "app/main.ts": b"export const value = 2"
        }
        asyncio.run(finish(resumed.id))
        regenerated_response = client.post(
            f"{public}/runs/{resumed.id}/regenerate", headers=other_headers, json={}
        )
        assert regenerated_response.status_code == 200, regenerated_response.text
        regenerated = asyncio.run(claim(regenerated_response.json()["id"]))
        assert regenerated.application_snapshot["project"]["id"] == forged["id"]
        assert asyncio.run(stored(regenerated)) == {
            "app/main.ts": b"export const value = 2"
        }
        asyncio.run(finish(regenerated.id))
        deleted = client.delete(
            f"{public}/conversations/same-conversation", headers=other_headers
        )
        assert deleted.status_code == 204, deleted.text

        async def tree_exists():
            async with get_session_factory()() as db:
                return await db.scalar(
                    select(AgentProject.id).where(AgentProject.id == forged["id"])
                )

        assert asyncio.run(tree_exists()) is None
        assert asyncio.run(stored(admin_run)) == {}
        # Standalone project management has been removed.
        assert (
            client.get(
                f"/api/v1/workspaces/{workspace_id}/projects", headers=headers
            ).status_code
            == 404
        )
        # Validation errors do not create partially imported conversations.
        ids = upload(base, headers, [("bad.zip", archive([("../escape.txt", b"bad")]))])
        invalid = client.post(
            f"{base}/runs",
            headers=headers,
            json={"goal": "use", "conversation_id": "invalid", "file_ids": ids},
        )
        assert invalid.status_code == 422, invalid.text
    print("CONVERSATION_FILES_RUNTIME_OK")


if __name__ == "__main__":
    main()

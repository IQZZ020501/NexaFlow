"""Project ownership, immutable context, file isolation and lifecycle integration."""

import asyncio
import base64
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.agents.agents import agent_model_server, agents_url, model_payload
from tests.projects.api import archive
from tests.projects.runtime import claim, finish
from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    settings,
    test_client,
)

from app.application.agents.access import service as access
from app.application.agents.runs import service
from app.application.artifacts.service import create_generated_artifact
from app.application.projects.chat import frozen_source_files
from app.application.projects.runtime import restore_project_files
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.session import get_session_factory


async def stored_run(run_id):
    async with get_session_factory()() as db:
        return await runs.get_agent_run_by_id(db, run_id)


async def sources(run):
    async with get_session_factory()() as db:
        return await frozen_source_files(db, run)


async def artifact(run, content=b"saved result"):
    async with get_session_factory()() as db:
        result = await create_generated_artifact(
            db,
            settings(),
            workspace_id=run.workspace_id,
            run_id=run.id,
            idempotency_key=run.id,
            artifact_format="txt",
            filename="result.txt",
            content=content,
        )
        await db.commit()
        return result.artifact_id


def main():
    with (
        test_client() as client,
        agent_model_server() as model_url,
        patch.object(access, "enqueue_prepared_agent_run", AsyncMock()),
        patch.object(service, "enqueue_prepared_agent_run", AsyncMock()),
    ):
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_url, "Project model"),
        ).json()

        def agent(name):
            response = client.post(
                agents_url(workspace_id),
                headers=headers,
                json={"name": name, "model_id": model["id"]},
            )
            assert response.status_code == 201, response.text
            agent_id = response.json()["id"]
            assert (
                client.patch(
                    agents_url(workspace_id, f"/{agent_id}"),
                    headers=headers,
                    json={"published": True},
                ).status_code
                == 200
            )
            return agent_id

        agent_id, second_agent_id = agent("Project agent"), agent("Other agent")
        base = f"/api/v1/public/agents/{agent_id}"
        other_base = f"/api/v1/public/agents/{second_agent_id}"
        other_id, other_token = create_active_user(client, token, "project-owner")
        assert (
            client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=headers,
                json={"user_id": other_id, "role": "member"},
            ).status_code
            == 201
        )
        other_headers = auth_headers(other_token)

        def call(method, path, expected=200, **kwargs):
            response = getattr(client, method)(
                base + path, headers=kwargs.pop("headers", headers), **kwargs
            )
            assert response.status_code == expected, response.text
            return response.json() if response.content else None

        assert client.get(base + "/projects").status_code == 401
        assert call("get", "/projects") == {"items": []}
        call("post", "/projects", expected=422, json={"name": "   "})
        project = call(
            "post",
            "/projects",
            expected=201,
            json={"name": "Research", "instructions": "Use concise answers."},
        )
        pid = project["id"]
        path = f"/projects/{pid}"
        assert call("get", "/projects", headers=other_headers)["items"] == []
        for method, suffix, extra in [
            ("get", "/files", {}),
            ("post", "/conversations", {}),
            ("put", "", {"json": {"name": "steal"}}),
            ("delete", "", {}),
        ]:
            call(method, path + suffix, expected=404, headers=other_headers, **extra)
        assert (
            client.get(other_base + path + "/files", headers=headers).status_code == 404
        )

        files = call(
            "post",
            path + "/files",
            expected=201,
            files=[
                (
                    "files",
                    ("sources.zip", archive([("notes/a.txt", b"original source")])),
                )
            ],
        )["items"]
        source = files[0]
        download = client.get(
            base + path + f"/files/{source['id']}/content", headers=headers
        )
        assert download.status_code == 200 and download.content == b"original source"
        assert "attachment" in download.headers["content-disposition"]
        assert download.headers["x-content-type-options"] == "nosniff"
        call(
            "post",
            path + "/files",
            expected=409,
            files=[("files", ("notes/a.txt", b"overwrite"))],
        )
        call(
            "post",
            path + "/files",
            expected=422,
            files=[("files", ("bad.zip", archive([("../escape.txt", b"bad")])))],
        )
        assert len(call("get", path + "/files")["items"]) == 1

        c1 = call("post", path + "/conversations", expected=201)["conversation_id"]
        c2 = call("post", path + "/conversations", expected=201)["conversation_id"]
        listing = call("get", "/conversations")["items"]
        assert {item["conversation_id"] for item in listing} == {c1, c2}
        assert all(
            item["project_id"] == pid and item["run_count"] == 0 for item in listing
        )
        run_json = call(
            "post",
            "/runs",
            expected=201,
            json={"goal": "Read sources", "conversation_id": c1},
        )
        run = asyncio.run(stored_run(run_json["id"]))
        frozen = deepcopy(run.application_snapshot["chat_project"])
        assert frozen["instructions"] == project["instructions"]
        assert asyncio.run(sources(run)) == {f"{pid}/notes/a.txt": b"original source"}
        messages = service.execution_messages(run)
        assert any("Use concise answers." in item["content"] for item in messages)
        assert not any(
            "has no uploaded or saved project files" in item["content"]
            for item in messages
        )
        platform = SimpleNamespace(execute=AsyncMock(return_value={"ok": True}))
        asyncio.run(restore_project_files(run, platform, timeout_seconds=5))
        restores = [
            item.args[0]["restore_project_files"]
            for item in platform.execute.call_args_list
        ]
        assert len(restores) == 1 and restores[0]["role"] == "source"
        assert (
            base64.b64decode(restores[0]["files"][f"{pid}/notes/a.txt"])
            == b"original source"
        )
        call(
            "patch",
            f"/conversations/{c1}/project",
            expected=409,
            json={"project_id": None},
        )
        call("delete", path, expected=409)

        # Source replacement and instruction edits affect only later Runs.
        call("delete", path + f"/files/{source['id']}", expected=204)
        call(
            "post",
            path + "/files",
            expected=201,
            files=[("files", ("notes/a.txt", b"new source"))],
        )
        project = call(
            "put",
            path,
            json={
                "name": "Updated",
                "instructions": "New instructions",
                "archived": False,
            },
        )
        assert run.application_snapshot["chat_project"] == frozen
        assert asyncio.run(sources(run))[f"{pid}/notes/a.txt"] == b"original source"
        asyncio.run(claim(run.id))
        asyncio.run(finish(run.id))
        aid = asyncio.run(artifact(run))
        call("post", path + "/artifacts", expected=201, json={"artifact_id": aid})
        assert {file["path"] for file in call("get", path + "/files")["items"]} == {
            "notes/a.txt",
            "result.txt",
        }
        # Even a project owner cannot import another user's artifact.
        foreign = call(
            "post",
            "/projects",
            expected=201,
            headers=other_headers,
            json={"name": "Other"},
        )
        call(
            "post",
            f"/projects/{foreign['id']}/artifacts",
            expected=404,
            headers=other_headers,
            json={"artifact_id": aid},
        )

        later = call(
            "post", "/runs", expected=201, json={"goal": "Next", "conversation_id": c2}
        )
        later_run = asyncio.run(stored_run(later["id"]))
        assert (
            later_run.application_snapshot["chat_project"]["instructions"]
            == "New instructions"
        )
        assert (
            later_run.application_snapshot["project"]["id"]
            != run.application_snapshot["project"]["id"]
        )
        assert later_run.application_snapshot["project"]["files"] == []
        asyncio.run(claim(later_run.id))
        asyncio.run(finish(later_run.id))
        call("delete", f"/conversations/{c2}", expected=204)
        assert len(call("get", path + "/files")["items"]) == 2

        call("put", path, json={**project, "archived": True})
        call("post", path + "/conversations", expected=409)
        call("post", f"/runs/{run.id}/regenerate", expected=409, json={})
        call(
            "put",
            path,
            expected=409,
            json={**project, "archived": True, "name": "Edited"},
        )
        call(
            "post",
            "/runs",
            expected=409,
            json={"goal": "archived", "conversation_id": c1},
        )
        call(
            "post",
            path + "/files",
            expected=409,
            files=[("files", ("new.txt", b"new"))],
        )
        call("put", path, json={**project, "archived": False})
        regenerated = call("post", f"/runs/{run.id}/regenerate", json={})
        regenerated_run = asyncio.run(stored_run(regenerated["id"]))
        assert regenerated_run.application_snapshot["chat_project"] == frozen
        assert (
            asyncio.run(sources(regenerated_run))[f"{pid}/notes/a.txt"]
            == b"original source"
        )
        asyncio.run(claim(regenerated_run.id))
        asyncio.run(finish(regenerated_run.id))
        call("patch", f"/conversations/{c1}/project", json={"project_id": None})
        ordinary = call(
            "post",
            "/runs",
            expected=201,
            json={"goal": "ordinary", "conversation_id": c1},
        )
        ordinary_run = asyncio.run(stored_run(ordinary["id"]))
        assert "chat_project" not in ordinary_run.application_snapshot
        assert ordinary_run.application_snapshot["project"]["files"] == []
        asyncio.run(claim(ordinary_run.id))
        asyncio.run(finish(ordinary_run.id))
        call("patch", f"/conversations/{c1}/project", json={"project_id": pid})
        call(
            "patch",
            f"/conversations/{c1}/project",
            expected=404,
            headers=other_headers,
            json={"project_id": foreign["id"]},
        )
        call("delete", path, expected=204)
        assert call("get", "/projects")["items"] == []
        assert call("get", "/conversations")["items"][0].get("project_id") is None
        assert asyncio.run(sources(run))[f"{pid}/notes/a.txt"] == b"original source"
        call("get", path + "/files", expected=404)
        # Deleting the published application also removes project source trees.
        response = client.delete(
            agents_url(workspace_id, f"/{agent_id}"), headers=headers
        )
        assert response.status_code == 204, response.text
    print("PUBLIC_CHAT_PROJECTS_OK")


if __name__ == "__main__":
    main()

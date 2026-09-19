"""Agent Skill control-plane API smoke tests."""

import asyncio
import base64
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from tests.models.llm import model_payload, model_test_server
from tests.support import activate_user, auth_headers, settings, test_client

from app.application.tools.runtime.contracts import ToolInvocationContext
from app.application.tools.runtime.service import (
    execute_tool_invocation,
    queue_tool_invocation,
)
from app.domain.tools.runtime import tool_snapshot_from_payload
from app.entities.defaults import utc_now
from app.infra.db.repositories.agent_skills import repository as skills
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.session import get_session_factory
from app.ports.execution import execution_scope


async def assert_script_ledger(run_id, workspace_id, actor_id, version_id):
    async with get_session_factory()() as db:
        run = await runs.get_agent_run_by_id(db, run_id)
        assert run is not None
        snapshot = next(
            tool_snapshot_from_payload(item)
            for item in run.tool_snapshots
            if item["function_name"] == "run_skill_script"
        )
        assert await runs.claim_agent_run(
            db,
            run_id,
            "skill-run-worker",
            utc_now(),
            utc_now() + timedelta(seconds=90),
            generation="unified",
        )
        await db.commit()

    content = b"generated-result"
    requests = []

    async def execute(request, **kwargs):
        scope = execution_scope.get()
        assert scope is not None and scope.workspace_id == workspace_id
        assert scope.run_id == run_id and scope.invocation_id == "skill-script"
        requests.append(request)
        assert request["script"] == "scripts/main.py"
        assert json.loads(request["stdin"]) == {"value": 3}
        assert base64.b64decode(request["files"]["assets/data.bin"]) == b"\x00\xff"
        assert "network_domains" not in request
        return {
            "ok": True,
            "exit_code": 0,
            "stdout": "script-completed",
            "stderr": "",
            "artifact": {
                "format": "txt",
                "filename": "result.txt",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode(),
            },
        }

    platform = AsyncMock()
    platform.execute.side_effect = execute
    arguments = {
        "version_id": version_id,
        "path": "scripts/main.py",
        "inputs": {"value": 3},
        "filename": "result.txt",
    }
    context = ToolInvocationContext(
        workspace_id=workspace_id,
        origin="agent",
        root_run_id=run_id,
        run_id=run_id,
        invocation_id="skill-script",
        execution_user_id=actor_id,
        access_source="console",
        deadline_at=utc_now() + timedelta(seconds=30),
        idempotency_key="skill-script:" + run_id,
    )

    async def queue(args, call_context):
        async with get_session_factory()() as db:
            invocation = await queue_tool_invocation(db, snapshot, args, call_context)
            await db.commit()
            return invocation

    with patch(
        "app.application.agent_skills.scripts.build_execution_platform",
        return_value=platform,
    ):
        invocation = await queue(arguments, context)
        assert (await queue(arguments, context)).id == invocation.id
        result = await execute_tool_invocation(
            invocation.id, settings(), "script-worker"
        )
        assert result.ok, (result.error_code, result.error_message)
        replay = await execute_tool_invocation(
            invocation.id, settings(), "script-worker-2"
        )
        assert replay.data == result.data
        assert len(requests) == 1
        for number, invalid in enumerate(
            (
                {**arguments, "version_id": "not-bound"},
                {**arguments, "path": "../outside.py"},
                {**arguments, "path": "assets/data.bin"},
            )
        ):
            bad_context = replace(
                context,
                invocation_id=f"bad-{number}",
                idempotency_key=f"bad-{number}:" + run_id,
            )
            bad = await queue(invalid, bad_context)
            outcome = await execute_tool_invocation(bad.id, settings(), "bad-worker")
            assert not outcome.ok and outcome.error_code == "skill_script_failed", (
                outcome
            )
        assert len(requests) == 1
        drifted = await queue(
            arguments,
            replace(context, invocation_id="drift", idempotency_key="drift:" + run_id),
        )
        changed = await execute_tool_invocation(
            drifted.id, replace(settings(), opensandbox_image="changed"), "drift-worker"
        )
        assert not changed.ok
        async with get_session_factory()() as db:
            skill = await skills.get_agent_skill(
                db, workspace_id, run.skill_snapshots[0]["skill_id"]
            )
            skill.status = "disabled"
            await skills.save_agent_skill(db, skill)
            await db.commit()
        revoked = await queue(
            arguments,
            replace(
                context, invocation_id="revoked", idempotency_key="revoked:" + run_id
            ),
        )
        outcome = await execute_tool_invocation(
            revoked.id, settings(), "revoked-worker"
        )
        assert not outcome.ok
        assert len(requests) == 1
    return result.data["artifacts"][0]["download_url"], content


def test_agent_skill_lifecycle() -> None:
    with test_client() as client, model_test_server() as model_base_url:
        token = activate_user(client, "admin", "NexaFlow@123.", "NexaFlow@12345.")
        me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["user"]
        workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(token),
            json={"name": "skill-api", "admin_user_id": me["id"]},
        )
        assert workspace.status_code == 201, workspace.text
        workspace_id = workspace.json()["workspace"]["id"]
        package = BytesIO()
        with ZipFile(package, "w") as archive:
            archive.writestr(
                "research/SKILL.md",
                "---\nname: research\ndescription: Research tasks\nlicense: MIT\n---\n\nUse the pinned script when needed.",
            )
            archive.writestr("research/scripts/main.py", "print('pinned-script')")
            archive.writestr("research/assets/data.bin", b"\x00\xff")
        inspected = client.post(
            f"/api/v1/workspaces/{workspace_id}/agent-skills/imports/inspect",
            headers=auth_headers(token),
            files={"file": ("research.zip", package.getvalue())},
        )
        assert inspected.status_code == 200, inspected.text
        imported_files = inspected.json()["definition"]["files"]
        assert base64.b64decode(imported_files["assets/data.bin"]) == b"\x00\xff"
        bad = BytesIO()
        with ZipFile(bad, "w") as archive:
            archive.writestr("../escape.py", "evil")
        rejected = client.post(
            f"/api/v1/workspaces/{workspace_id}/agent-skills/imports/inspect",
            headers=auth_headers(token),
            files={"file": ("bad.zip", bad.getvalue())},
        )
        assert rejected.status_code == 422, rejected.text
        assert (
            client.get(
                f"/api/v1/workspaces/{workspace_id}/agent-skills",
                headers=auth_headers(token),
            ).json()
            == []
        )
        created = client.post(
            f"/api/v1/workspaces/{workspace_id}/agent-skills",
            headers=auth_headers(token),
            json={
                "name": "Research Skill",
                "description": "Evidence-backed answers",
                "definition": {
                    "intents": ["research"],
                    "instructions": "Use workspace evidence.",
                    "knowledge_base_ids": [],
                    "tools": [],
                    "files": imported_files,
                },
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        markdown = base64.b64decode(skill["definition"]["files"]["SKILL.md"]).decode()
        assert "license: MIT" in markdown and "name: Research Skill" in markdown
        published = client.post(
            f"/api/v1/workspaces/{workspace_id}/agent-skills/{skill['id']}/publish",
            headers=auth_headers(token),
        )
        assert published.status_code == 200, published.text
        listed = client.get(
            f"/api/v1/workspaces/{workspace_id}/agent-skills",
            headers=auth_headers(token),
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["current_version_number"] == 1
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=auth_headers(token),
            json={**model_payload(model_base_url), "name": "Skill API Model"},
        )
        assert model.status_code == 201, model.text
        agent = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=auth_headers(token),
            json={
                "name": "Skill API Agent",
                "instructions": "Use the attached skill.",
                "model_id": model.json()["id"],
                "skills": [
                    {"skill_id": skill["id"], "version_id": published.json()["id"]}
                ],
            },
        )
        assert agent.status_code == 201, agent.text
        assert agent.json()["skills"] == [
            {"skill_id": skill["id"], "version_id": published.json()["id"]}
        ]
        with patch(
            "app.application.agents.runs.service.enqueue_prepared_agent_run",
            new=AsyncMock(),
        ):
            prepared = client.post(
                f"/api/v1/workspaces/{workspace_id}/agents/{agent.json()['id']}/runs",
                headers=auth_headers(token),
                json={"goal": "Use the script"},
            )
        assert prepared.status_code == 201, prepared.text
        download, content = asyncio.run(
            assert_script_ledger(
                prepared.json()["id"], workspace_id, me["id"], published.json()["id"]
            )
        )
        downloaded = client.get(download)
        assert downloaded.status_code == 200 and downloaded.content == content
        assert downloaded.headers["x-content-type-options"] == "nosniff"
        assert "attachment" in downloaded.headers["content-disposition"]


def main() -> None:
    test_agent_skill_lifecycle()
    print("AGENT_SKILLS_API_OK")


if __name__ == "__main__":
    main()

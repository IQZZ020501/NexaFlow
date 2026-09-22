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
from app.domain.tools.catalog.service import build_skill_dependency_installer_tool
from app.domain.tools.runtime import tool_snapshot_from_payload
from app.entities.defaults import utc_now
from app.entities.tools import ApplicationToolBinding
from app.infra.db.repositories.agent_skills import repository as skills
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.tools import repository as tool_repository
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
        installer_snapshot = next(
            tool_snapshot_from_payload(item)
            for item in run.tool_snapshots
            if item["function_name"] == "install_skill_dependencies"
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
    initial_environment_hash = "b" * 64
    final_environment_hash = "c" * 64

    async def execute(request, **kwargs):
        scope = execution_scope.get()
        assert scope is not None and scope.workspace_id == workspace_id
        assert scope.run_id == run_id
        requests.append(request)
        if "shell" in request:
            assert scope.invocation_id in {
                "skill-install-1",
                "skill-install-2",
                "skill-script",
            }
            assert request["shell"]["manager"] == "python"
            assert request["network_domains"] == [
                "pypi.org",
                "files.pythonhosted.org",
            ]
            environment_hash = (
                initial_environment_hash
                if scope.invocation_id == "skill-install-1"
                else final_environment_hash
            )
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": "dependencies-ready",
                "stderr": "",
                "environment_hash": environment_hash,
                "environment_lock": {
                    "manager": "python",
                    "packages": [{"name": "demo", "version": "1.0.0"}],
                },
            }
        assert scope.invocation_id == "skill-script"
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

    async def queue(args, call_context, *, snapshot=snapshot):
        async with get_session_factory()() as db:
            invocation = await queue_tool_invocation(db, snapshot, args, call_context)
            await db.commit()
            return invocation

    with patch(
        "app.application.agent_skills.scripts.build_execution_platform",
        return_value=platform,
    ), patch(
        "app.application.agent_skills.dependencies.build_execution_platform",
        return_value=platform,
    ), patch(
        "app.application.agent_skills.dependencies._require_package_domains"
    ):
        install_context = replace(
            context,
            invocation_id="skill-install-1",
            idempotency_key="skill-install-1:" + run_id,
        )
        install = await queue(
            {
                "version_id": version_id,
                "manager": "python",
                "packages": ["demo==1.0.0"],
            },
            install_context,
            snapshot=installer_snapshot,
        )
        assert install.status == "awaiting_approval"
        pending = await execute_tool_invocation(
            install.id, settings(), "install-before-approval"
        )
        assert not pending.ok and pending.error_code == "approval_required"
        assert requests == []
        async with get_session_factory()() as db:
            assert await tool_repository.resolve_tool_invocation_approval(
                db,
                workspace_id,
                install.id,
                actor_id,
                utc_now(),
                utc_now() + timedelta(seconds=30),
                approve=True,
            )
            await db.commit()
        installed = await execute_tool_invocation(
            install.id, settings(), "install-worker"
        )
        assert (
            installed.ok
            and installed.data["environment_hash"] == initial_environment_hash
        )
        second_context = replace(
            context,
            invocation_id="skill-install-2",
            idempotency_key="skill-install-2:" + run_id,
        )
        second_install = await queue(
            {
                "version_id": version_id,
                "manager": "python",
                "packages": ["other-demo==2.0.0"],
            },
            second_context,
            snapshot=installer_snapshot,
        )
        async with get_session_factory()() as db:
            assert await tool_repository.resolve_tool_invocation_approval(
                db,
                workspace_id,
                second_install.id,
                actor_id,
                utc_now(),
                utc_now() + timedelta(seconds=30),
                approve=True,
            )
            await db.commit()
        installed = await execute_tool_invocation(
            second_install.id, settings(), "install-worker-2"
        )
        assert (
            installed.ok
            and installed.data["environment_hash"] == final_environment_hash
        )
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
        assert len(requests) == 5
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
        assert len(requests) == 5
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
        assert len(requests) == 5
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
        installer, installer_version, _ = build_skill_dependency_installer_tool(
            workspace_id
        )

        async def bind_legacy_installer(agent_id: str):
            async with get_session_factory()() as db:
                await tool_repository.sync_application_tool_bindings(
                    db,
                    workspace_id,
                    agent_id,
                    [
                        ApplicationToolBinding(
                            workspace_id=workspace_id,
                            application_id=agent_id,
                            tool_id=installer.id,
                            tool_version_id=installer_version.id,
                            bound_by_user_id=me["id"],
                        )
                    ],
                )
                await db.commit()

        asyncio.run(bind_legacy_installer(agent.json()["id"]))
        listed_agent = client.get(
            f"/api/v1/workspaces/{workspace_id}/agents/{agent.json()['id']}",
            headers=auth_headers(token),
        )
        assert listed_agent.status_code == 200, listed_agent.text
        assert listed_agent.json()["tools"] == []
        published_agent = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{agent.json()['id']}",
            headers=auth_headers(token),
            json={"published": True},
        )
        assert published_agent.status_code == 200, published_agent.text
        assert published_agent.json()["tools"] == []

        async def assert_no_manual_binding():
            async with get_session_factory()() as db:
                assert not await tool_repository.list_application_tool_bindings(
                    db, workspace_id, agent.json()["id"]
                )

        asyncio.run(assert_no_manual_binding())
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

        saved = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{agent.json()['id']}",
            headers=auth_headers(token),
            json={
                "tools": [{"tool_id": installer.id, "version_id": installer_version.id}]
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["tools"] == []
        asyncio.run(assert_no_manual_binding())

        plain_agent = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=auth_headers(token),
            json={"name": "No Skill Agent", "model_id": model.json()["id"]},
        )
        assert plain_agent.status_code == 201, plain_agent.text
        asyncio.run(bind_legacy_installer(plain_agent.json()["id"]))
        with patch(
            "app.application.agents.runs.service.enqueue_prepared_agent_run",
            new=AsyncMock(),
        ):
            plain_run = client.post(
                f"/api/v1/workspaces/{workspace_id}/agents/{plain_agent.json()['id']}/runs",
                headers=auth_headers(token),
                json={"goal": "No Skill is attached"},
            )
        assert plain_run.status_code == 201, plain_run.text

        async def assert_no_implicit_tool_without_skill():
            async with get_session_factory()() as db:
                run = await runs.get_agent_run_by_id(db, plain_run.json()["id"])
                assert run is not None
                assert all(
                    item["function_name"] != "install_skill_dependencies"
                    for item in run.tool_snapshots
                )

        asyncio.run(assert_no_implicit_tool_without_skill())


def main() -> None:
    test_agent_skill_lifecycle()
    print("AGENT_SKILLS_API_OK")


if __name__ == "__main__":
    main()

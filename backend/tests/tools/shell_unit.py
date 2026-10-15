"""Bash authorization, result mapping, deadlines and artifact identity."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401
from tests.support import settings

from app.application.agents.runs.snapshots import AgentRuntimePolicy
from app.application.agents.tools.runtime import UnifiedAgentToolRuntime
from app.application.tools.runtime.adapters import shell
from app.application.tools.runtime.adapters.builtin import BuiltinToolAdapter
from app.application.tools.runtime.contracts import (
    ToolAdapterBusy,
    ToolInvocationContext,
)
from app.domain.agent_skills.contracts import (
    agent_skill_definition_hash,
    agent_skill_snapshot_payload,
)
from app.domain.agent_skills.paths import skill_mount_name
from app.domain.tools.catalog.service import build_shell_tool
from app.entities.agent_skills import AgentSkillSnapshot
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.ports.execution import ExecutionBusy


@asynccontextmanager
async def database():
    yield SimpleNamespace(commit=AsyncMock())


async def check():
    config = settings()
    tool, version, policy = build_shell_tool("workspace")
    assert tool.function_name == "bash" and version.execution_spec == {
        "builtin": "shell"
    }
    assert (
        policy.approval == "auto"
        and policy.effect == "pure"
        and not policy.workflow_callable
        and not policy.parallel_safe
    )
    assert policy.allowed_access_sources == ["console", "public", "api"]
    budget = AgentRuntimePolicy.from_settings(config, shell=True)
    assert (budget.max_runtime_seconds, budget.max_turns, budget.max_tool_calls) == (
        900,
        24,
        64,
    )
    run = AgentRun(
        workspace_id="workspace",
        execution_user_id="user",
        status="running_v2",
        execution_deadline_at=utc_now() + timedelta(seconds=900),
    )
    runtime = UnifiedAgentToolRuntime(run, [], "worker", config, asyncio.Event())
    snapshot = SimpleNamespace(execution_spec={"builtin": "shell"})
    assert (
        178
        <= (
            runtime._tool_deadline(snapshot, {"timeout_seconds": 120}) - utc_now()
        ).total_seconds()
        <= 180
    )
    context = ToolInvocationContext(
        workspace_id="workspace",
        origin="agent",
        root_run_id=run.id,
        run_id=run.id,
        invocation_id="call",
        execution_user_id="user",
        access_source="console",
        deadline_at=utc_now() + timedelta(seconds=180),
        idempotency_key="command-identity",
    )
    skill = AgentSkillSnapshot(
        schema_version=2,
        skill_id="skill",
        version_id="version",
        version_number=1,
        name="Unsafe /../ 名称",
        description="test",
        definition={"files": {"scripts/main.sh": "ZWNobyB0ZXN0"}},
        definition_hash="hash",
        bound_by_user_id="user",
    )
    from dataclasses import replace

    skill = replace(
        skill,
        definition_hash=agent_skill_definition_hash(
            skill.name, skill.description, skill.definition
        ),
    )
    run.skill_snapshots = [agent_skill_snapshot_payload(skill)]
    content = b"output"
    response = {
        "ok": True,
        "exit_code": 124,
        "timed_out": True,
        "stdout": "partial",
        "stderr": "",
        "truncated": False,
        "workspace_reset": True,
        "artifacts": [
            {
                "path": "/tmp/nexaflow-exports/test/0",
                "relative_path": "nested/result.txt",
                "filename": "result.txt",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    platform = SimpleNamespace(
        execute=AsyncMock(return_value=response),
        read_session_file=AsyncMock(return_value=content),
    )
    link = SimpleNamespace(
        artifact_id="artifact",
        filename="result.txt",
        format="txt",
        download_url="/api/v1/artifacts/token",
        size_bytes=len(content),
        expires_at=utc_now(),
        media_type="text/plain",
    )
    with (
        patch.object(shell, "get_session_factory", return_value=database),
        patch.object(shell.runs, "get_agent_run_by_id", AsyncMock(return_value=run)),
        patch.object(shell, "_installed_dependency_plans", AsyncMock(return_value=[])),
        patch.object(shell, "require_pinned_skill_access", AsyncMock()) as access,
        patch.object(shell, "build_execution_platform", return_value=platform),
        patch.object(
            shell, "create_generated_artifact", AsyncMock(return_value=link)
        ) as create,
    ):
        result = await shell.execute_shell(
            config,
            {"command": "echo output > outputs/result.txt", "timeout_seconds": 120},
            context,
        )
        assert (
            result.ok
            and result.data["exit_code"] == 124
            and result.data["workspace_reset"]
        )
        assert result.data["artifacts"][0]["artifact_id"] == "artifact"
        key = create.call_args.kwargs["idempotency_key"]
        assert key == hashlib.sha256(b"command-identity:nested/result.txt").hexdigest()
        assert set(platform.execute.call_args.args[0]["skill_mounts"]) == {
            skill_mount_name(skill.name, skill.version_id)
        }
        access.assert_awaited_once()
        await shell.execute_shell(config, {"command": "true"}, context)
        assert create.call_args.kwargs["idempotency_key"] == key
        access.side_effect = ValueError("revoked")
        count = platform.execute.await_count
        try:
            await shell.execute_shell(config, {"command": "true"}, context)
        except ValueError as exc:
            assert str(exc) == "revoked"
        else:
            raise AssertionError("Revoked Skill was mounted")
        assert platform.execute.await_count == count
        access.side_effect = None
        platform.execute.return_value = {"ok": True, "exit_code": 3, "artifacts": []}
        result = await shell.execute_shell(config, {"command": "exit 3"}, context)
        assert result.ok and result.data["exit_code"] == 3
        platform.execute.return_value = {
            "ok": True,
            "exit_code": 0,
            "artifacts": [None],
        }
        from app.ports.execution import ExecutionError

        try:
            await shell.execute_shell(config, {"command": "true"}, context)
        except ExecutionError:
            pass
        else:
            raise AssertionError("Malformed artifact manifest was accepted")
    with patch.object(
        shell, "execute_shell", AsyncMock(side_effect=ExecutionBusy("full"))
    ):
        try:
            await BuiltinToolAdapter(config).invoke(snapshot, {}, context)
        except ToolAdapterBusy:
            pass
        else:
            raise AssertionError("Busy capacity failed the Tool instead of requeueing")
    try:
        await shell.execute_shell(
            config, {"command": "true"}, SimpleNamespace(run_id=None)
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Command ran without a Run")


def main():
    asyncio.run(check())
    print("SHELL_UNIT_OK")


if __name__ == "__main__":
    main()

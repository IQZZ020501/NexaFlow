"""Opt-in real guest rebuild with private persistent sources and work files."""

from contextlib import ExitStack
from dataclasses import replace
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

import tests.support  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.adapters.execution.opensandbox import OpenSandboxExecution
from app.application.artifacts import service as artifacts
from app.application.artifacts import workspace
from app.application.projects import runtime, service
from app.application.tools.runtime.adapters import shell
from app.entities.defaults import utc_now
from app.entities.identity.user import User
from app.entities.projects import AgentProject
from app.entities.runs import AgentRun
from app.entities.workspaces.models import Workspace, WorkspaceMembership
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.projects import repository
from app.infra.db.repositories.workspaces import repository as workspaces
from app.infra.execution import sessions
from app.infra.execution.profile import execution_profile
from app.ports.execution import ExecutionScope, execution_scope
from app.ports.tools import ToolInvocationContext


async def check(config):
    config = replace(
        config,
        jwt_secret_key=settings().jwt_secret_key,
        model_secret_key=settings().model_secret_key,
    )
    platform = OpenSandboxExecution(config)
    created = []
    with TemporaryDirectory(prefix="nexaflow-project-smoke-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{directory}/files.db")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async def new_run(project):
            async with factory() as db:
                snapshot = await service.project_run_snapshot(
                    db, project.workspace_id, project.id, project.created_by_user_id
                )
                run = AgentRun(
                    workspace_id=project.workspace_id,
                    agent_id="agent",
                    requested_by_user_id=project.created_by_user_id,
                    execution_user_id=project.created_by_user_id,
                    consumer_id=project.created_by_user_id,
                    conversation_id="project-smoke",
                    configuration_source="draft",
                    status="running_v2",
                    worker_task_id="worker",
                    lease_expires_at=utc_now() + timedelta(seconds=600),
                    execution_deadline_at=utc_now() + timedelta(seconds=600),
                    application_snapshot={
                        "project": snapshot,
                        "execution_profile": execution_profile(config),
                        "sandbox_requirements": {
                            "schema_version": 1,
                            "profiles": ["standard"],
                            "max_stdio_hosts": 0,
                        },
                    },
                )
                run = await runs.create_agent_run(db, run)
                await service.initialize_project_run(db, run)
                await db.commit()
                created.append(run)
                return run

        async def command(run, text, key):
            context = ToolInvocationContext(
                workspace_id=run.workspace_id,
                origin="agent",
                root_run_id=run.id,
                run_id=run.id,
                invocation_id=key,
                execution_user_id=run.execution_user_id,
                access_source="console",
                deadline_at=utc_now() + timedelta(seconds=180),
                idempotency_key=key,
            )
            token = execution_scope.set(
                ExecutionScope(run.workspace_id, key, run.id, "worker")
            )
            try:
                result = await shell.execute_shell(config, {"command": text}, context)
                assert (
                    result.ok
                    and result.data["exit_code"] == 0
                    and result.data["project_saved"] is True
                ), result
                return result.data
            finally:
                execution_scope.reset(token)

        async def finish(run):
            async with factory() as db:
                assert await runs.finalize_agent_run(
                    db,
                    run.id,
                    "worker",
                    status="succeeded",
                    result="saved",
                    events=[],
                    last_error=None,
                    finished_at=utc_now(),
                )
                await db.commit()
            await platform.close_session(run.workspace_id, run.id)

        try:
            with ExitStack() as stack:
                for module in (shell, artifacts, workspace, runtime, sessions):
                    stack.enter_context(
                        patch.object(
                            module, "get_session_factory", return_value=factory
                        )
                    )
                stack.enter_context(
                    patch.object(
                        shell, "build_execution_platform", return_value=platform
                    )
                )
                async with factory() as db:
                    owner = await users.save_user(
                        db,
                        User(
                            username="project-smoke",
                            email="project@example.test",
                            password_hash="unused",
                        ),
                    )
                    ws = await workspaces.save_workspace(
                        db, Workspace(name="Project smoke")
                    )
                    await workspaces.save_workspace_membership(
                        db,
                        WorkspaceMembership(
                            workspace_id=ws.id, user_id=owner.id, role="member"
                        ),
                    )
                    project = await repository.save_project(
                        db,
                        AgentProject(
                            workspace_id=ws.id,
                            created_by_user_id=owner.id,
                            name="Project smoke",
                        ),
                    )
                    await db.commit()
                    await service.save_changes(
                        db,
                        project,
                        [
                            {
                                "path": "source.csv",
                                "role": "source",
                                "content": b"amount\n12\n",
                            },
                            {
                                "path": "script.py",
                                "role": "work",
                                "content": b"from pathlib import Path\nprint(int(Path('/project/sources/source.csv').read_text().splitlines()[1])*2)\n",
                            },
                        ],
                    )
                    await db.commit()
                first = await new_run(project)
                original = await command(
                    first,
                    "python3 project/script.py > outputs/result.txt; if echo unsafe > /project/sources/source.csv; then exit 1; fi; mv project/script.py project/main.py",
                    "project-create",
                )
                assert {item["path"] for item in original["project_files"]} == {
                    "script.py",
                    "main.py",
                }
                await platform.close_session(first.workspace_id, first.id)
                rebuilt = await command(
                    first,
                    "test ! -e project/script.py && python3 project/main.py && cat /project/sources/source.csv",
                    "project-rebuild",
                )
                assert (
                    rebuilt["stdout"] == "24\namount\n12\n"
                    and not rebuilt["project_files"]
                )
                await finish(first)
                second = await new_run(project)
                edited = await command(
                    second,
                    "test ! -e project/script.py && python3 project/main.py; rm project/main.py",
                    "project-delete",
                )
                assert edited["project_files"][0]["deleted"]
                await finish(second)
                third = await new_run(project)
                await command(
                    third,
                    "test ! -e project/main.py && test ! -e project/script.py && test -f /project/sources/source.csv",
                    "project-no-resurrection",
                )
                async with factory() as db:
                    artifact = await artifacts.get_generated_artifact(
                        db,
                        config,
                        original["artifacts"][0]["download_url"].rsplit("/", 1)[-1],
                    )
                    assert artifact.content == b"24\n"
        finally:
            with patch.object(sessions, "get_session_factory", return_value=factory):
                for run in created:
                    await platform.close_session(run.workspace_id, run.id)
            await engine.dispose()
    print("PROJECT_FILES_OPENSANDBOX_OK")


if __name__ == "__main__":
    raise SystemExit(
        "Invoke check(settings) with an explicitly configured isolated execution environment."
    )

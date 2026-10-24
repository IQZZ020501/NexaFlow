"""Opt-in create/close/restore/edit check; never writes to the business database."""

import argparse
import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

import tests.support  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.adapters.execution.opensandbox import OpenSandboxExecution
from app.application.artifacts import service, workspace
from app.application.tools.runtime.adapters import shell
from app.application.tools.runtime.contracts import ToolInvocationContext
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.execution import sessions
from app.infra.execution.profile import execution_profile
from app.ports.execution import ExecutionScope, execution_scope


async def check(runtime):
    runtime = replace(
        runtime,
        database_url=settings().database_url,
        jwt_secret_key=settings().jwt_secret_key,
        model_secret_key=settings().model_secret_key,
    )
    platform = OpenSandboxExecution(runtime)
    with TemporaryDirectory(prefix="nexaflow-conversation-files-") as temporary:
        engine = create_async_engine(f"sqlite+aiosqlite:///{temporary}/files.db")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        first = AgentRun(
            workspace_id="conversation-file-smoke",
            agent_id="agent",
            requested_by_user_id="user",
            conversation_id="conversation",
            configuration_source="draft",
            status="running_v2",
            worker_task_id="worker",
            execution_deadline_at=utc_now() + timedelta(seconds=600),
            tool_snapshots=[{"execution_spec": {"builtin": "shell"}}],
            application_snapshot={"execution_profile": execution_profile(runtime)},
        )
        second = replace(first, id="second", root_run_id="second", created_at=utc_now())
        separate = replace(
            first,
            id="separate",
            root_run_id="separate",
            conversation_id="separate",
            created_at=utc_now(),
        )

        async def command(run, text, key):
            context = ToolInvocationContext(
                workspace_id=run.workspace_id,
                origin="agent",
                root_run_id=run.id,
                run_id=run.id,
                invocation_id=key,
                execution_user_id=run.execution_user_id,
                access_source=run.access_source,
                deadline_at=utc_now() + timedelta(seconds=180),
                idempotency_key=key,
            )
            token = execution_scope.set(
                ExecutionScope(run.workspace_id, key, run.id, "worker")
            )
            try:
                result = await shell.execute_shell(runtime, {"command": text}, context)
                assert result.ok and result.data["exit_code"] == 0, result
                return result
            finally:
                execution_scope.reset(token)

        try:
            with (
                patch.object(shell, "get_session_factory", return_value=factory),
                patch.object(service, "get_session_factory", return_value=factory),
                patch.object(workspace, "get_session_factory", return_value=factory),
                patch.object(sessions, "get_session_factory", return_value=factory),
            ):
                async with factory() as db:
                    await runs.create_agent_run(db, first)
                    await db.commit()
                original = await command(
                    first, "printf '<h1>original</h1>' > outputs/page.html", "original"
                )
                async with factory() as db:
                    assert await runs.finalize_agent_run(
                        db,
                        first.id,
                        "worker",
                        status="succeeded",
                        result="saved",
                        events=[],
                        last_error=None,
                        finished_at=utc_now(),
                    )
                    await db.commit()
                await platform.close_session(first.workspace_id, first.id)
                async with factory() as db:
                    await runs.create_agent_run(db, second)
                    await db.commit()
                updated = await command(
                    second,
                    "python3 -c \"from pathlib import Path; p=Path('outputs/page.html'); "
                    "assert p.read_text()=='<h1>original</h1>'; "
                    "p.write_text(p.read_text().replace('original','updated'))\"",
                    "updated",
                )
                old_file = original.data["artifacts"][0]
                new_file = updated.data["artifacts"][0]
                assert old_file["artifact_id"] != new_file["artifact_id"]
                async with factory() as db:
                    for item, expected in (
                        (old_file, b"<h1>original</h1>"),
                        (new_file, b"<h1>updated</h1>"),
                    ):
                        artifact = await service.get_generated_artifact(
                            db, runtime, item["download_url"].rsplit("/", 1)[-1]
                        )
                        assert artifact.content == expected
                unchanged = await command(
                    second, "cat outputs/page.html", "verify-current"
                )
                assert unchanged.data["stdout"] == "<h1>updated</h1>"
                assert not unchanged.data["artifacts"]
                async with factory() as db:
                    await runs.create_agent_run(db, separate)
                    await db.commit()
                await command(
                    separate, "test ! -e outputs/page.html", "verify-isolation"
                )
        finally:
            with patch.object(sessions, "get_session_factory", return_value=factory):
                for run in (first, second, separate):
                    await platform.close_session(run.workspace_id, run.id)
            await engine.dispose()
    print("CONVERSATION_FILES_OPENSANDBOX_OK")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    arguments = parser.parse_args()
    runtime = replace(
        settings(),
        opensandbox_url=arguments.url,
        opensandbox_image=arguments.image,
        opensandbox_api_key=os.environ["OPENSANDBOX_API_KEY"],
    )
    asyncio.run(check(runtime))


if __name__ == "__main__":
    main()

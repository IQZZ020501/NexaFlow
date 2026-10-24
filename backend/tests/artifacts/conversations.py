"""Conversation file retention, immutable versions and tenant boundaries."""

import asyncio
import base64
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.application.artifacts import service, workspace
from app.domain.artifacts.models import GeneratedArtifact as ArtifactRow
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.artifacts import repository


async def check():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = utc_now()
    first = AgentRun(
        workspace_id="workspace",
        agent_id="agent",
        execution_user_id="user",
        consumer_id="user",
        access_source="public",
        conversation_id="conversation",
        status="succeeded",
        created_at=now - timedelta(days=2),
    )
    current = replace(
        first,
        id="current",
        root_run_id="current",
        created_at=now,
        status="running",
    )
    try:
        with (
            patch.object(service, "get_session_factory", return_value=factory),
            patch.object(workspace, "get_session_factory", return_value=factory),
        ):
            async with factory() as db:
                await runs.create_agent_run(db, first)
                await runs.create_agent_run(db, current)
                with patch.object(service, "utc_now", return_value=first.created_at):
                    old = await service.create_generated_artifact(
                        db,
                        settings(),
                        workspace_id=first.workspace_id,
                        run_id=first.id,
                        idempotency_key="old",
                        artifact_format="html",
                        filename="page.html",
                        content=b"<h1>old</h1>",
                    )
                latest = await service.create_generated_artifact(
                    db,
                    settings(),
                    workspace_id=first.workspace_id,
                    run_id=first.id,
                    idempotency_key="latest",
                    artifact_format="html",
                    filename="page.html",
                    content=b"<h1>latest</h1>",
                )
                nested = await service.create_generated_artifact(
                    db,
                    settings(),
                    workspace_id=first.workspace_id,
                    run_id=first.id,
                    idempotency_key="nested",
                    artifact_format="html",
                    filename="page.html",
                    relative_path="nested/page.html",
                    content=b"nested",
                )
                for index, change in enumerate(
                    (
                        {"workspace_id": "other-workspace"},
                        {"agent_id": "other-agent"},
                        {"consumer_id": "other-user"},
                        {"access_source": "console", "requested_by_user_id": "user"},
                        {"conversation_id": "other-conversation"},
                        {"execution_user_id": "other-executor"},
                        {"status": "failed"},
                    )
                ):
                    other = replace(
                        first,
                        id=f"other-{index}",
                        root_run_id=f"other-{index}",
                        created_at=now - timedelta(hours=1),
                        **change,
                    )
                    await runs.create_agent_run(db, other)
                    await service.create_generated_artifact(
                        db,
                        settings(),
                        workspace_id=other.workspace_id,
                        run_id=other.id,
                        idempotency_key=f"foreign-{index}",
                        artifact_format="html",
                        filename="page.html",
                        content=b"foreign",
                    )
                with patch.object(service, "utc_now", return_value=first.created_at):
                    temporary = await service.create_generated_artifact(
                        db,
                        settings(),
                        workspace_id=first.workspace_id,
                        run_id=None,
                        idempotency_key="temporary",
                        artifact_format="html",
                        filename="temporary.html",
                        content=b"temporary",
                    )
                await db.commit()
                files = await repository.list_conversation_files(db, current)
                assert {(item[0], item[1]) for item in files} == {
                    (latest.artifact_id, "page.html"),
                    (nested.artifact_id, "nested/page.html"),
                }, files
                assert (
                    await db.get(ArtifactRow, old.artifact_id)
                ).content == b"<h1>old</h1>"
                for artifact_id, _path, _size in files:
                    row = await db.get(ArtifactRow, artifact_id)
                    row.expires_at = now - timedelta(days=1)
                await db.commit()
            await service.cleanup_expired_generated_artifacts()
            platform = SimpleNamespace(execute=AsyncMock(return_value={"ok": True}))
            await workspace.restore_conversation_files(
                current, platform, timeout_seconds=10
            )
            restored = {}
            for call in platform.execute.await_args_list:
                for path, content in call.args[0]["restore_files"].items():
                    restored[path] = base64.b64decode(content)
            assert restored == {
                "page.html": b"<h1>latest</h1>",
                "nested/page.html": b"nested",
            }
            async with factory() as db:
                assert await db.get(ArtifactRow, old.artifact_id) is not None
                assert await db.get(ArtifactRow, temporary.artifact_id) is None
                current_version = await service.create_generated_artifact(
                    db,
                    settings(),
                    workspace_id=current.workspace_id,
                    run_id=current.id,
                    idempotency_key="current-version",
                    artifact_format="html",
                    filename="page.html",
                    content=b"updated",
                )
                assert current_version.artifact_id != latest.artifact_id
                assert (
                    await db.get(ArtifactRow, latest.artifact_id)
                ).content == b"<h1>latest</h1>"
                assert (
                    current_version.artifact_id,
                    "page.html",
                    7,
                ) in await repository.list_conversation_files(db, current)
                deleted, active = await runs.delete_consumer_conversation(
                    db, "agent", "public", "user", "conversation"
                )
                assert not deleted and active
                await runs.finalize_agent_run(
                    db,
                    current.id,
                    None,
                    status="succeeded",
                    result="done",
                    finished_at=now,
                    events=[],
                    last_error=None,
                )
                await db.commit()
                deleted, active = await runs.delete_consumer_conversation(
                    db, "agent", "public", "user", "conversation"
                )
                assert deleted and not active
                await db.commit()
                assert await db.get(ArtifactRow, old.artifact_id) is None
                assert await db.get(ArtifactRow, latest.artifact_id) is None
                assert await db.scalar(select(ArtifactRow.id)) is not None
    finally:
        await engine.dispose()


def main():
    asyncio.run(check())
    print("CONVERSATION_ARTIFACTS_OK")


if __name__ == "__main__":
    main()

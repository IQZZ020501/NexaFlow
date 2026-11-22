"""Refresh leases and disconnect fencing on an explicitly isolated PostgreSQL DB."""

import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import delete, select
from tests.support import settings

from app.domain.platform.models import User, Workspace
from app.domain.tools.integrations import service
from app.domain.tools.integrations.models import IntegrationConnection as ConnectionOrm
from app.domain.tools.models import ToolSource, ToolVersion
from app.entities.defaults import new_id, utc_now
from app.entities.tools.integrations import (
    IntegrationConnection,
)
from app.infra.db.repositories.tools import integrations as repository
from app.infra.db.repositories.tools import repository as tools
from app.infra.db.session import configure_database, get_engine, get_session_factory
from app.ports.integrations import IntegrationProviderError
from app.ports.tools import ToolAdapterBusy


async def check(configuration):
    assert configuration.database_url.startswith("postgresql+psycopg://")
    configure_database(configuration)
    user_id, workspace_id = new_id(), new_id()
    label = "integration-lock-" + uuid4().hex
    try:
        async with get_session_factory()() as db:
            db.add(
                User(
                    id=user_id,
                    username=label,
                    email=label + "@example.com",
                    name=label,
                    password_hash="test-only",
                )
            )
            db.add(Workspace(id=workspace_id, name=label, slug=label))
            await db.flush()
            connection = IntegrationConnection(
                workspace_id=workspace_id,
                user_id=user_id,
                provider="feishu",
                application_revision=0,
                generation=1,
            )
            service.accept_tokens(
                connection,
                {
                    "access_token": "expired",
                    "refresh_token": "first-refresh",
                    "expires_in": 3600,
                },
                configuration,
                {
                    "brand": "feishu",
                    "client_id": "test-client",
                    "client_secret": "test-only",
                },
            )
            connection.access_expires_at = utc_now() - timedelta(seconds=1)
            await repository.save_connection(db, connection)
            await service.install_tools(db, connection)
            await db.commit()

        async def read_grant():
            async with get_session_factory()() as db:
                return await service.credentials(
                    db,
                    connection.id,
                    workspace_id,
                    user_id,
                    connection.generation,
                    configuration,
                )

        async def slow_refresh(*_args, **_kwargs):
            await asyncio.sleep(0.1)
            return {
                "access_token": "refreshed",
                "refresh_token": "rotated",
                "expires_in": 3600,
            }

        refresh = AsyncMock(side_effect=slow_refresh)
        with patch.object(service.provider_api, "feishu_authorization", refresh):
            results = await asyncio.gather(
                *(read_grant() for _ in range(8)), return_exceptions=True
            )
            assert refresh.await_count == 1, refresh.await_count
            assert any(
                isinstance(item, dict) and item["access_token"] == "refreshed"
                for item in results
            )
            assert all(isinstance(item, (dict, ToolAdapterBusy)) for item in results), (
                results
            )
            assert (await read_grant())["access_token"] == "refreshed"
            assert refresh.await_count == 1

        async with get_session_factory()() as db:
            saved = await repository.connection_by_id(db, connection.id, lock=True)
            saved.access_expires_at = utc_now() - timedelta(seconds=1)
            await repository.save_connection(db, saved)
            await db.commit()
        started, release = asyncio.Event(), asyncio.Event()

        async def late_refresh(*_args, **_kwargs):
            started.set()
            await release.wait()
            return {
                "access_token": "late-token",
                "refresh_token": "late-refresh",
                "expires_in": 3600,
            }

        with patch.object(
            service.provider_api,
            "feishu_authorization",
            AsyncMock(side_effect=late_refresh),
        ):
            pending = asyncio.create_task(read_grant())
            await asyncio.wait_for(started.wait(), 5)
            async with get_session_factory()() as db:
                await service.uninstall(
                    db, workspace_id, type("Actor", (), {"id": user_id})(), "feishu"
                )
            release.set()
            try:
                await pending
                raise AssertionError(
                    "A late refresh must not restore an uninstalled grant"
                )
            except IntegrationProviderError:
                pass
        async with get_session_factory()() as db:
            saved = await repository.connection_by_id(db, connection.id)
            assert saved.status == "disconnected" and saved.secrets_ciphertext == ""
            saved.generation += 1
            service.accept_tokens(
                saved,
                {
                    "access_token": "expired-again",
                    "refresh_token": "do-not-replay",
                    "expires_in": 3600,
                },
                configuration,
                {
                    "brand": "feishu",
                    "client_id": "test-client",
                    "client_secret": "test-only",
                },
            )
            saved.access_expires_at = utc_now() - timedelta(seconds=1)
            saved.refresh_owner = new_id()
            saved.refresh_expires_at = utc_now() - timedelta(seconds=1)
            await repository.save_connection(db, saved)
            await db.commit()
            connection = saved
        with patch.object(
            service.provider_api, "feishu_authorization", AsyncMock()
        ) as replay:
            try:
                await read_grant()
                raise AssertionError(
                    "An expired refresh lease cannot replay rotating credentials"
                )
            except IntegrationProviderError:
                pass
            assert replay.await_count == 0

        # PostgreSQL must cascade both the connection and its same-workspace
        # source without a new foreign key blocking permanent workspace deletion.
        async with get_session_factory()() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()
            assert (
                await db.scalar(
                    select(ConnectionOrm.id).where(
                        ConnectionOrm.workspace_id == workspace_id
                    )
                )
                is None
            )
            assert (
                await db.scalar(
                    select(ToolSource.id).where(ToolSource.workspace_id == workspace_id)
                )
                is None
            )
    finally:
        async with get_session_factory()() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await get_engine().dispose()


async def check_catalog_updates(configuration):
    configure_database(configuration)
    user_id, workspace_id = new_id(), new_id()
    actor = type("Actor", (), {"id": user_id})()
    label = "integration-catalog-" + uuid4().hex
    try:
        async with get_session_factory()() as db:
            db.add(
                User(
                    id=user_id,
                    username=label,
                    email=label + "@example.com",
                    name=label,
                    password_hash="test-only",
                )
            )
            db.add(Workspace(id=workspace_id, name=label, slug=label))
            await db.flush()
            connection = IntegrationConnection(
                workspace_id=workspace_id,
                user_id=user_id,
                provider="tencent_meeting",
                status="connected",
                generation=1,
                secrets_ciphertext="unchanged-test-ciphertext",
            )
            await repository.save_connection(db, connection)
            await db.commit()

        async def sync():
            async with get_session_factory()() as db:
                return await service.sync_tools(
                    db, workspace_id, actor, "tencent_meeting"
                )

        results = await asyncio.gather(*(sync() for _ in range(6)))
        assert all(result["status"] == "connected" for result in results)
        async with get_session_factory()() as db:
            current = await repository.connection_by_id(db, connection.id)
            installed = await tools.list_tools_by_source(
                db, workspace_id, current.source_id
            )
            assert len(installed) == 35
            assert current.secrets_ciphertext == "unchanged-test-ciphertext"
            assert current.generation == 1
            for tool in installed:
                versions = await tools.list_tool_versions(db, workspace_id, tool.id)
                policy = await tools.get_tool_policy(db, workspace_id, tool.id)
                assert len(versions) == 1 and policy.revision == 1

        # Whichever operation acquires the connection lock first, uninstall wins
        # permanently: a later sync cannot reactivate the disconnected account.
        async def uninstall():
            async with get_session_factory()() as db:
                return await service.uninstall(
                    db, workspace_id, actor, "tencent_meeting"
                )

        await asyncio.gather(sync(), uninstall(), return_exceptions=True)
        async with get_session_factory()() as db:
            current = await repository.connection_by_id(db, connection.id)
            source = await tools.get_tool_source(db, workspace_id, current.source_id)
            assert current.status == "disconnected" and current.secrets_ciphertext == ""
            assert source.status == "archived"
            assert all(
                tool.status == "archived"
                for tool in await tools.list_tools_by_source(
                    db, workspace_id, source.id
                )
            )
            versions = (
                await db.scalars(
                    select(ToolVersion).where(ToolVersion.workspace_id == workspace_id)
                )
            ).all()
            assert len(versions) == 35
    finally:
        async with get_session_factory()() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await get_engine().dispose()


if __name__ == "__main__":
    configuration = replace(
        settings(), database_url=os.environ["NEXAFLOW_TEST_DATABASE_URL"]
    )
    asyncio.run(check(configuration))
    asyncio.run(check_catalog_updates(configuration))
    print(
        "Integration PostgreSQL refresh, concurrent catalog update, uninstall fencing and deletion checks passed."
    )

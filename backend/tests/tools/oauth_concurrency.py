"""Real PostgreSQL row-lock check; requires an explicitly isolated database URL."""

import asyncio
import os
import threading
import time
from dataclasses import replace
from datetime import timedelta
from http.server import ThreadingHTTPServer
from uuid import uuid4

from sqlalchemy import delete
from tests.support import settings
from tests.tools.oauth import Provider

from app.domain.platform.models import User, Workspace
from app.domain.tools.mcp import oauth
from app.domain.tools.models import McpServer
from app.entities.defaults import new_id, utc_now
from app.entities.mcp_oauth import McpOAuthConnection
from app.infra.db.repositories.tools import mcp as mcp_repository
from app.infra.db.repositories.tools import oauth as repository
from app.infra.db.session import configure_database, get_engine, get_session_factory
from app.ports.mcp import McpClientError


class SlowProvider(Provider):
    def do_POST(self):
        time.sleep(0.15)
        super().do_POST()


async def check(configuration):
    assert configuration.database_url.startswith("postgresql+psycopg://")
    configure_database(configuration)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), SlowProvider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{provider.server_port}"
    user_id, workspace_id, server_id = new_id(), new_id(), new_id()
    label = "oauth-lock-" + uuid4().hex
    Provider.records = []
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
            db.add(
                McpServer(
                    id=server_id,
                    workspace_id=workspace_id,
                    name=label,
                    url=origin + "/mcp",
                    created_by_user_id=user_id,
                    auth_mode="oauth",
                    network_policy="deployment",
                )
            )
            await db.flush()
            connection = McpOAuthConnection(
                server_id=server_id,
                status="connected",
                configuration={
                    "token_endpoint": origin + "/token",
                    "revocation_endpoint": origin + "/revoke",
                    "client_id": "test-client",
                    "client_auth_method": "none",
                    "resource": origin + "/mcp",
                    "network_policy": "deployment",
                },
                secrets_ciphertext=oauth._encrypt(
                    {"access_token": "expired", "refresh_token": "first-refresh"},
                    configuration,
                ),
                access_expires_at=utc_now() - timedelta(seconds=1),
            )
            await repository.save_connection(db, connection)
            await db.commit()
            server = await mcp_repository.get_mcp_server_by_id(db, server_id)
        tokens = await asyncio.gather(
            *(oauth.access_token(server, configuration) for _ in range(10))
        )
        assert tokens == ["test-access-1"] * 10 and len(Provider.records) == 1, (
            tokens,
            len(Provider.records),
        )
        async with get_session_factory()() as db:
            connection = await repository.get_connection(db, server_id, lock=True)
            assert (
                connection.access_expires_at > utc_now()
                and connection.status == "connected"
            )
            connection.status = "refreshing"
            connection.refresh_owner = new_id()
            connection.refresh_expires_at = utc_now() - timedelta(seconds=1)
            await repository.save_connection(db, connection)
            await db.commit()
        try:
            await oauth.access_token(server, configuration)
            raise AssertionError(
                "An expired claim cannot replay a rotated refresh token"
            )
        except McpClientError as exc:
            assert not exc.request_sent
        assert len(Provider.records) == 1
        async with get_session_factory()() as db:
            assert (
                await repository.get_connection(db, server_id)
            ).status == "reauthorization_required"
    finally:
        async with get_session_factory()() as db:
            await db.execute(delete(McpServer).where(McpServer.id == server_id))
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await get_engine().dispose()
        await asyncio.to_thread(provider.shutdown)
        provider.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    url = os.environ["NEXAFLOW_TEST_DATABASE_URL"]
    asyncio.run(
        check(replace(settings(), database_url=url, mcp_allow_private_networks=True))
    )
    print("MCP_OAUTH_POSTGRES_CONCURRENCY_OK")

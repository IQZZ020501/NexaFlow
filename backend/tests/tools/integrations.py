"""Real HTTP routes and ledger, with isolated simulated provider grants."""

import asyncio
import base64
import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from sqlalchemy import select
from tests import support
from tests.support import activate_admin, auth_headers, create_active_user, test_client

from app.application.tools.runtime.service import (
    execute_tool_invocation,
    queue_tool_invocation,
)
from app.domain.agents.approval import agent_tool_requires_approval
from app.domain.tools.integrations import service
from app.domain.tools.integrations.catalog import OPERATIONS
from app.domain.tools.integrations.models import (
    IntegrationApplication,
    IntegrationAuthorization,
    IntegrationConnection,
)
from app.domain.tools.runtime import build_tool_snapshot
from app.entities.defaults import utc_now
from app.infra.db.repositories.tools import integrations as connections
from app.infra.db.repositories.tools import repository as tools
from app.infra.db.session import get_session_factory
from app.ports import integrations as provider_api
from app.ports.tools import ToolInvocationContext
from app.schemas.agents.contracts import (
    AgentRunEventResponse,
    ExternalAgentProgressEventResponse,
)


async def saved_snapshot(workspace_id, user_id, source_id, stable_key="list_projects"):
    async with get_session_factory()() as db:
        source = await tools.get_tool_source(db, workspace_id, source_id)
        tool = await tools.get_tool_by_source_key(
            db, workspace_id, source_id, stable_key
        )
        version = await tools.get_tool_version(
            db, workspace_id, tool.current_version_id
        )
        policy = await tools.get_tool_policy(db, workspace_id, tool.id)
        return build_tool_snapshot(tool, source, version, policy, user_id)


async def invoke(snapshot, workspace_id, user_id, settings):
    identity = str(uuid4())
    context = ToolInvocationContext(
        workspace_id=workspace_id,
        origin="test",
        root_run_id=None,
        run_id=None,
        invocation_id=identity,
        execution_user_id=user_id,
        access_source="console",
        deadline_at=utc_now() + timedelta(seconds=30),
        idempotency_key=identity,
    )
    async with get_session_factory()() as db:
        invocation = await queue_tool_invocation(db, snapshot, {}, context)
        await db.commit()
    return await execute_tool_invocation(invocation.id, settings, str(uuid4()))


async def assert_encryption(workspace_id, user_id, provider):
    async with get_session_factory()() as db:
        app = await db.scalar(
            select(IntegrationApplication).where(
                IntegrationApplication.provider == provider
            )
        )
        connection = await connections.connection(db, workspace_id, user_id, provider)
        if provider == "dida":
            assert app is None, "Dida must not need a manually configured application"
        else:
            assert "private-application-secret" not in app.client_secret_ciphertext
        assert "private-user-token" not in connection.secrets_ciphertext
        return connection


async def expire(workspace_id, user_id, provider, *, lease=False):
    async with get_session_factory()() as db:
        connection = await connections.connection(db, workspace_id, user_id, provider)
        connection.access_expires_at = utc_now() - timedelta(seconds=5)
        if lease:
            connection.refresh_owner = str(uuid4())
            connection.refresh_expires_at = utc_now() - timedelta(seconds=1)
        await connections.save_connection(db, connection)
        await db.commit()
        return connection


def main():
    settings = replace(support.settings(), public_app_url="https://nexaflow.example")
    exchange = AsyncMock(
        return_value={
            "access_token": "private-user-token",
            "token_type": "bearer",
            "expires_in": 3600,
        }
    )
    device_api = AsyncMock(return_value={"auth_code": "device-user-code"})
    registration = AsyncMock(return_value="registered-public-client")
    with (
        patch.object(support, "settings", return_value=settings),
        patch.object(provider_api, "exchange_tokens", exchange),
        patch.object(provider_api, "device_authorization", device_api),
        patch.object(provider_api, "register_public_client", registration),
        test_client() as client,
    ):
        admin_token, workspace_id = activate_admin(client)
        admin = auth_headers(admin_token)
        owner_id, owner_token = create_active_user(
            client, admin_token, "integration-owner"
        )
        other_id, other_token = create_active_user(
            client, admin_token, "integration-other"
        )
        for user_id in (owner_id, other_id):
            added = client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=admin,
                json={"user_id": user_id, "role": "member"},
            )
            assert added.status_code == 201, added.text
        owner, other = auth_headers(owner_token), auth_headers(other_token)
        root = f"/api/v1/workspaces/{workspace_id}/integrations"

        catalog = client.get(root, headers=owner)
        assert catalog.status_code == 200, catalog.text
        assert len(catalog.json()) == 3
        assert {entry["status"] for entry in catalog.json()} == {"disconnected"}
        assert catalog.json()[0]["configured"] is True
        assert exchange.await_count == 0
        assert registration.await_count == 0
        # Dida opens browser OAuth with no SMTP site URL or application setup.
        browser_login = client.post(root + "/dida/authorize", headers=owner)
        assert browser_login.status_code == 200, browser_login.text
        callback = "https://nexaflow.example/app/tools/integrations/callback"
        assert parse_qs(urlparse(browser_login.json()["authorization_url"]).query)[
            "redirect_uri"
        ] == [callback]
        assert registration.call_args.args == (
            "dida",
            callback,
            ["tasks:read", "tasks:write"],
        )
        assert exchange.await_count == 0
        assert client.get(root, headers=owner).json()[0]["status"] == "disconnected"
        calls = registration.await_count
        for origin in (
            "https://attacker.example",
            "null",
            "https://nexaflow.example/path",
        ):
            response = client.post(
                root + "/dida/authorize", headers={**owner, "Origin": origin}
            )
            assert response.status_code == 400, response.text
        assert registration.await_count == calls, (
            "untrusted origins must not register a client"
        )
        spoofed_host = client.post(
            root + "/dida/authorize",
            headers={
                **owner,
                "Host": "attacker.example",
                "X-Forwarded-Host": "attacker.example",
                "X-Forwarded-Proto": "http",
                "Origin": "https://nexaflow.example",
            },
        )
        assert spoofed_host.status_code == 200, spoofed_host.text
        assert parse_qs(urlparse(spoofed_host.json()["authorization_url"]).query)[
            "redirect_uri"
        ] == [callback]
        client.app.state.settings = replace(
            settings, public_app_url="http://127.0.0.1:3001", environment="development"
        )
        try:
            local_login = client.post(
                root + "/dida/authorize",
                headers={**owner, "Origin": "http://localhost:3001"},
            )
            assert local_login.status_code == 200, local_login.text
            assert parse_qs(urlparse(local_login.json()["authorization_url"]).query)[
                "redirect_uri"
            ] == ["http://localhost:3001/app/tools/integrations/callback"]
        finally:
            client.app.state.settings = settings
        site = client.patch(
            "/api/v1/admin/smtp",
            headers=admin,
            json={"site_url": "https://nexaflow.example", "enabled": False},
        )
        assert site.status_code == 200, site.text
        for provider in ("feishu",):
            app = {
                "client_id": f"{provider}-client",
                "client_secret": "private-application-secret",
            }
            assert (
                client.put(
                    root + f"/{provider}/application", headers=owner, json=app
                ).status_code
                == 403
            )
            configured = client.put(
                root + f"/{provider}/application", headers=admin, json=app
            )
            assert configured.status_code == 200, configured.text
            assert "private-application-secret" not in configured.text
            assert (
                configured.json()["redirect_uri"]
                == "https://nexaflow.example/app/tools/integrations/callback"
            )
        assert (
            client.get(root + "/feishu/application", headers=owner).status_code == 403
        )
        for headers in (admin, owner):
            assert (
                client.get(root + "/dida/application", headers=headers).status_code
                == 422
            )
            assert (
                client.put(
                    root + "/dida/application",
                    headers=headers,
                    json={"client_id": "old-client", "client_secret": "old-secret"},
                ).status_code
                == 422
            )

        def begin(provider="dida"):
            response = client.post(root + f"/{provider}/authorize", headers=owner)
            assert response.status_code == 200, response.text
            return response.json()

        def complete(authorization, provider="dida", headers=owner):
            return client.post(
                root + f"/{provider}/callback",
                headers=headers,
                json={"state": authorization["state"], "code": "temporary-code"},
            )

        with patch.object(
            provider_api,
            "register_public_client",
            AsyncMock(
                side_effect=provider_api.IntegrationProviderError(
                    "Integration authorization failed. Please authorize again."
                )
            ),
        ):
            assert (
                client.post(root + "/dida/authorize", headers=owner).status_code == 502
            )
            assert client.get(root, headers=owner).json()[0]["status"] == "disconnected"

        async def late_registration(*_args):
            async with get_session_factory()() as db:
                actor = type("Actor", (), {"id": owner_id})()
                await service.uninstall(db, workspace_id, actor, "dida")
            return "late-client"

        with patch.object(
            provider_api,
            "register_public_client",
            AsyncMock(side_effect=late_registration),
        ):
            assert (
                client.post(root + "/dida/authorize", headers=owner).status_code == 409
            )
            assert client.get(root, headers=owner).json()[0]["status"] == "disconnected"

        authorization = begin()
        query = parse_qs(urlparse(authorization["authorization_url"]).query)
        assert registration.call_args.args == (
            "dida",
            "https://nexaflow.example/app/tools/integrations/callback",
            ["tasks:read", "tasks:write"],
        )
        assert query["client_id"] == ["registered-public-client"]
        assert query["redirect_uri"] == [
            "https://nexaflow.example/app/tools/integrations/callback"
        ]
        assert query["code_challenge_method"] == ["S256"]

        async def read_verifier():
            async with get_session_factory()() as db:
                attempt = await connections.authorization(
                    db, hashlib.sha256(authorization["state"].encode()).hexdigest()
                )
                values = service.unseal(attempt.secrets_ciphertext, settings)
                assert values["client_id"] == "registered-public-client"
                assert values["verifier"] not in attempt.secrets_ciphertext
                return values["verifier"]

        verifier = asyncio.run(read_verifier())
        assert query["code_challenge"] == [
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        ]
        assert query["state"] == [authorization["state"]]
        assert query["scope"] == ["tasks:read tasks:write"]
        assert "private-application-secret" not in authorization["authorization_url"]
        assert complete(authorization, headers=other).status_code == 400
        assert exchange.await_count == 0
        legacy_dida = deepcopy(
            [
                operation
                for operation in OPERATIONS["dida"]
                if operation["name"]
                in {"list_projects", "get_project_data", "create_task", "complete_task"}
            ]
        )
        next(
            operation
            for operation in legacy_dida
            if operation["name"] == "get_project_data"
        )["name"] = "list_tasks"
        with patch.dict(OPERATIONS, {"dida": legacy_dida}):
            installed = complete(authorization)
        assert installed.status_code == 200, installed.text
        assert installed.json()["status"] == "connected"
        assert exchange.await_count == 1
        assert exchange.call_args.args == ("dida", "registered-public-client", "")
        assert exchange.call_args.kwargs["code_verifier"] == verifier
        assert complete(authorization).status_code == 200
        assert exchange.await_count == 1, "callbacks must not exchange a code twice"
        assert client.post(root + "/dida/authorize", headers=owner).status_code == 409
        assert (
            client.put(
                root + "/dida/application",
                headers=admin,
                json={"client_id": "new-client"},
            ).status_code
            == 422
        )
        source_id = installed.json()["source_id"]
        connection = asyncio.run(assert_encryption(workspace_id, owner_id, "dida"))
        tools_root = f"/api/v1/workspaces/{workspace_id}/tools"

        async def dida_catalog_state():
            async with get_session_factory()() as db:
                entries = await tools.list_tools_by_source(db, workspace_id, source_id)
                versions = {
                    tool.stable_key: [
                        version.id
                        for version in await tools.list_tool_versions(
                            db, workspace_id, tool.id
                        )
                    ]
                    for tool in entries
                }
                active = {
                    tool.stable_key for tool in entries if tool.status == "active"
                }
                for tool in entries:
                    if tool.stable_key == "list_tasks":
                        assert (
                            tool.status == "archived"
                            and tool.availability == "unavailable"
                        )
                    elif tool.status == "active":
                        operation = next(
                            item
                            for item in OPERATIONS["dida"]
                            if item["name"] == tool.stable_key
                        )
                        policy = await tools.get_tool_policy(db, workspace_id, tool.id)
                        assert policy.effect == (
                            "external_write" if operation["write"] else "external_read"
                        )
                        assert policy.approval == (
                            "each_call" if operation["write"] else "auto"
                        )
                        assert policy.parallel_safe == (not operation["write"])
                        assert policy.allowed_access_sources == ["console"]
                        assert not policy.workflow_callable
                saved = await connections.connection(db, workspace_id, owner_id, "dida")
                assert saved.generation == connection.generation
                assert saved.secrets_ciphertext == connection.secrets_ciphertext
                return active, versions

        sync_url = root + "/dida/sync"
        for headers in (admin, other):
            assert client.post(sync_url, headers=headers).status_code == 409
        auth_calls = exchange.await_count
        assert client.post(sync_url, headers=owner).status_code == 200
        active_tools, dida_versions = asyncio.run(dida_catalog_state())
        assert active_tools == {operation["name"] for operation in OPERATIONS["dida"]}
        assert "list_tasks" in dida_versions, (
            "historical versions remain available for audit"
        )
        assert client.post(sync_url, headers=owner).status_code == 200
        assert asyncio.run(dida_catalog_state()) == (active_tools, dida_versions)
        assert exchange.await_count == auth_calls, (
            "tool updates must preserve the account authorization"
        )
        owned_tools = [
            entry
            for entry in client.get(tools_root, headers=owner).json()
            if entry["kind"] == "integration"
        ]
        assert len(owned_tools) == len(OPERATIONS["dida"])
        for headers in (admin, other):
            assert not [
                entry
                for entry in client.get(tools_root, headers=headers).json()
                if entry["kind"] == "integration"
            ]
        tool_id = owned_tools[0]["id"]
        assert (
            client.put(
                tools_root + f"/{tool_id}/permissions/{other_id}",
                headers=owner,
                json={"permission": "use"},
            ).status_code
            == 422
        )

        snapshot = asyncio.run(saved_snapshot(workspace_id, owner_id, source_id))
        assert len(snapshot.function_name) <= 64
        event = AgentRunEventResponse(
            turn=1,
            tool_name=snapshot.function_name,
            tool_kind="integration",
            status="running",
            summary="Reading task lists",
        )
        assert event.model_dump()["tool_kind"] == "integration"
        public_event = ExternalAgentProgressEventResponse(
            id="integration-event",
            type="tool",
            status="running",
            stage="running",
            turn=1,
            tool_kind="integration",
            tool_name=snapshot.function_name,
            summary="Reading task lists",
        )
        assert public_event.model_dump()["tool_kind"] == "integration"
        assert agent_tool_requires_approval("always_ask", snapshot)
        assert not agent_tool_requires_approval("full_access", snapshot)
        assert not agent_tool_requires_approval(
            "ask_risky", snapshot, model_decides_mcp=True, model_requires_approval=False
        )
        assert agent_tool_requires_approval(
            "ask_risky", snapshot, model_decides_mcp=True, model_requires_approval=None
        )
        with patch(
            "app.application.tools.runtime.adapters.integration.call_integration",
            AsyncMock(return_value={"lists": ["Work"]}),
        ) as call:
            result = asyncio.run(invoke(snapshot, workspace_id, owner_id, settings))
            assert result.ok, result
            assert call.await_count == 1
            assert call.call_args.args[3]["access_token"] == "private-user-token"
            assert "private-user-token" not in str(result.data)
            deleted = client.delete(root + "/dida", headers=owner)
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["status"] == "disconnected"
            result = asyncio.run(invoke(snapshot, workspace_id, owner_id, settings))
            assert not result.ok
            assert call.await_count == 1, (
                "uninstall must prevent a queued snapshot from dispatching"
            )
        assert complete(authorization).status_code == 400
        assert client.delete(root + "/dida", headers=owner).status_code == 200
        assert not [
            entry
            for entry in client.get(tools_root, headers=owner).json()
            if entry["kind"] == "integration"
        ]

        async def assert_removed():
            async with get_session_factory()() as db:
                saved = await connections.connection(db, workspace_id, owner_id, "dida")
                assert saved.secrets_ciphertext == ""
                assert saved.generation > connection.generation

        asyncio.run(assert_removed())

        async def restore_retired_confidential_connection():
            async with get_session_factory()() as db:
                db.add(
                    IntegrationApplication(
                        workspace_id=workspace_id,
                        provider="dida",
                        client_id="retired-manual-client",
                        client_secret_ciphertext=service.seal(
                            {"client_secret": "retired-application-secret"}, settings
                        ),
                        scopes=["tasks:read", "tasks:write"],
                        revision=1,
                    )
                )
                saved = await connections.connection(db, workspace_id, owner_id, "dida")
                saved.application_revision = 1
                saved.status = "connected"
                saved.secrets_ciphertext = service.seal(
                    {"access_token": "retired-token"}, settings
                )
                await connections.save_connection(db, saved)
                await db.commit()
                try:
                    await service.credentials(
                        db, saved.id, workspace_id, owner_id, saved.generation, settings
                    )
                    raise AssertionError(
                        "retired confidential-client grants must be rejected"
                    )
                except provider_api.IntegrationProviderError:
                    pass

        asyncio.run(restore_retired_confidential_connection())
        assert (
            client.get(root, headers=owner).json()[0]["status"]
            == "reauthorization_required"
        )
        assert client.post(root + "/dida/sync", headers=owner).status_code == 409

        authorization = begin()
        with patch.object(
            provider_api,
            "exchange_tokens",
            AsyncMock(
                side_effect=provider_api.IntegrationProviderError(
                    "Integration authorization failed. Please authorize again."
                )
            ),
        ):
            assert complete(authorization).status_code == 502
            assert complete(authorization).status_code == 409
        assert client.get(root, headers=owner).json()[0]["status"] == "disconnected"
        authorization = begin()
        assert complete(authorization).status_code == 200
        assert exchange.call_args.args == ("dida", "registered-public-client", ""), (
            "retired application credentials must not be reused"
        )
        reinstalled = asyncio.run(saved_snapshot(workspace_id, owner_id, source_id))
        assert reinstalled.definition_hash != snapshot.definition_hash
        asyncio.run(expire(workspace_id, owner_id, "dida"))
        assert (
            client.get(root, headers=owner).json()[0]["status"]
            == "reauthorization_required"
        )
        authorization = begin()
        assert complete(authorization).status_code == 200

        # Revocation of local installation while an exchange is in flight fences
        # the late result. The account is never reported installed afterward.
        client.delete(root + "/dida", headers=owner)
        authorization = begin()

        async def late_grant(*_args, **_kwargs):
            async with get_session_factory()() as db:
                actor = type("Actor", (), {"id": owner_id})()
                await service.uninstall(db, workspace_id, actor, "dida")
            return {"access_token": "late-token"}

        with patch.object(
            provider_api, "exchange_tokens", AsyncMock(side_effect=late_grant)
        ):
            assert complete(authorization).status_code == 409
        assert client.get(root, headers=owner).json()[0]["status"] == "disconnected"

        # Feishu uses PKCE and retains only server-side refresh credentials.
        exchange.return_value = {
            "access_token": "feishu-access",
            "refresh_token": "feishu-refresh",
            "expires_in": 3600,
        }
        feishu = begin("feishu")
        query = parse_qs(urlparse(feishu["authorization_url"]).query)
        assert query["code_challenge_method"] == ["S256"]
        assert complete(feishu, "feishu").json()["status"] == "connected"
        expired = asyncio.run(expire(workspace_id, owner_id, "feishu"))
        exchange.return_value = {
            "access_token": "feishu-access-new",
            "refresh_token": "feishu-refresh-new",
            "expires_in": 3600,
        }

        async def refresh_grant():
            async with get_session_factory()() as db:
                return await service.credentials(
                    db, expired.id, workspace_id, owner_id, expired.generation, settings
                )

        assert asyncio.run(refresh_grant())["access_token"] == "feishu-access-new"
        assert exchange.call_args.kwargs["grant_type"] == "refresh_token"
        asyncio.run(expire(workspace_id, owner_id, "feishu", lease=True))
        try:
            asyncio.run(refresh_grant())
            raise AssertionError(
                "an expired refresh lease must require fresh authorization"
            )
        except provider_api.IntegrationProviderError:
            pass
        assert (
            client.get(root, headers=owner).json()[1]["status"]
            == "reauthorization_required"
        )

        # Tencent's official device authorization opens the platform login page;
        # an empty polling result is pending, never a successful installation.
        device = begin("tencent_meeting")
        assert device["mode"] == "device"
        assert urlparse(device["authorization_url"]).hostname == "meeting.tencent.com"
        device_api.return_value = {}
        assert complete(device, "tencent_meeting").json()["status"] == "disconnected"

        async def allow_poll():
            async with get_session_factory()() as db:
                attempt = await connections.authorization(
                    db, hashlib.sha256(device["state"].encode()).hexdigest()
                )
                attempt.next_poll_at = utc_now() - timedelta(seconds=1)
                await connections.save_authorization(db, attempt)
                await db.commit()

        asyncio.run(allow_poll())
        device_api.return_value = {
            "access_token": "meeting-access",
            "refresh_token": "meeting-refresh",
            "access_token_expire_time": str(
                int((utc_now() + timedelta(hours=1)).timestamp())
            ),
            "open_id": "meeting-user",
            "sdk_id": "meeting-sdk",
        }
        # Simulate an account installed before the expanded catalog was released.
        legacy_operations = deepcopy(OPERATIONS["tencent_meeting"][:2])
        legacy_operations[0]["description"] = "Legacy meeting list contract."
        with patch.dict(OPERATIONS, {"tencent_meeting": legacy_operations}):
            installed = complete(device, "tencent_meeting").json()
        assert installed["status"] == "connected"
        assert (
            client.delete(root + "/tencent_meeting", headers=other).json()["status"]
            == "disconnected"
        )
        assert client.get(root, headers=owner).json()[2]["status"] == "connected"
        sync_url = root + "/tencent_meeting/sync"
        for headers in (other, admin):
            assert client.post(sync_url, headers=headers).status_code == 409

        async def installation_state():
            async with get_session_factory()() as db:
                saved = await connections.connection(
                    db, workspace_id, owner_id, "tencent_meeting"
                )
                installed_tools = await tools.list_tools_by_source(
                    db, workspace_id, saved.source_id
                )
                versions, policies = {}, {}
                for tool in installed_tools:
                    assert len(tool.function_name) <= 64
                    versions[tool.stable_key] = [
                        v.id
                        for v in await tools.list_tool_versions(
                            db, workspace_id, tool.id
                        )
                    ]
                    policies[tool.stable_key] = await tools.get_tool_policy(
                        db, workspace_id, tool.id
                    )
                return saved, versions, policies

        old_connection, old_versions, _ = asyncio.run(installation_state())
        auth_calls = device_api.await_count
        assert len(old_versions) == 2
        assert client.post(sync_url, headers=owner).status_code == 200
        new_connection, new_versions, policies = asyncio.run(installation_state())
        assert len(new_versions) == 35
        assert new_versions["get_meeting"] == old_versions["get_meeting"]
        assert len(new_versions["list_meetings"]) == 2
        assert old_versions["list_meetings"][0] in new_versions["list_meetings"]
        assert new_connection.secrets_ciphertext == old_connection.secrets_ciphertext
        assert new_connection.generation == old_connection.generation
        assert new_connection.source_id == old_connection.source_id
        for operation in OPERATIONS["tencent_meeting"]:
            policy = policies[operation["name"]]
            assert policy.effect == (
                "external_write" if operation["write"] else "external_read"
            )
            assert policy.approval == ("each_call" if operation["write"] else "auto")
            assert not policy.workflow_callable
            assert policy.allowed_access_sources == ["console"]
        assert client.post(sync_url, headers=owner).status_code == 200
        _, repeated_versions, repeated_policies = asyncio.run(installation_state())
        assert repeated_versions == new_versions, (
            "unchanged updates must not create new versions"
        )
        assert {key: p.revision for key, p in repeated_policies.items()} == {
            key: p.revision for key, p in policies.items()
        }
        assert device_api.await_count == auth_calls, (
            "catalog updates must not exchange credentials"
        )
        meeting_snapshot = asyncio.run(
            saved_snapshot(
                workspace_id, owner_id, installed["source_id"], "list_meetings"
            )
        )
        with patch(
            "app.application.tools.runtime.adapters.integration.call_integration",
            AsyncMock(
                side_effect=provider_api.IntegrationProviderError(
                    "Integration authorization expired. Please install again.",
                    unauthorized=True,
                )
            ),
        ) as call:
            result = asyncio.run(
                invoke(meeting_snapshot, workspace_id, owner_id, settings)
            )
            assert not result.ok
            assert result.outcome == "confirmed"
            assert result.error_message == (
                "Integration authorization expired. Please install again."
            )
            assert (
                client.get(root, headers=owner).json()[2]["status"]
                == "reauthorization_required"
            )
            result = asyncio.run(
                invoke(meeting_snapshot, workspace_id, owner_id, settings)
            )
            assert not result.ok
            assert call.await_count == 1, "expired grants must not be dispatched again"
        assert client.post(sync_url, headers=owner).status_code == 409
        client.delete(root + "/tencent_meeting", headers=owner)
        assert client.post(sync_url, headers=owner).status_code == 409
        assert complete(device, "tencent_meeting").status_code == 400

        # The account's private grants cascade away; public tool history remains.
        deleted = client.delete(f"/api/v1/admin/users/{owner_id}", headers=admin)
        assert deleted.status_code == 204, deleted.text

        async def assert_no_private_grants():
            async with get_session_factory()() as db:
                assert not (
                    await db.scalars(
                        select(IntegrationConnection).where(
                            IntegrationConnection.user_id == owner_id
                        )
                    )
                ).all()
                assert not (await db.scalars(select(IntegrationAuthorization))).all()

        asyncio.run(assert_no_private_grants())
    print(
        "Integration installation, OAuth, isolation, refresh, uninstall and ledger checks passed."
    )


if __name__ == "__main__":
    main()

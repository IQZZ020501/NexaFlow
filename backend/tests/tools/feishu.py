"""Official CLI wire contracts, scoped grants and ledger regression checks."""

import asyncio
import base64
import hashlib
import json
import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx2
from jsonschema import Draft202012Validator
from tests import support
from tests.support import activate_admin, auth_headers, create_active_user, test_client
from tests.tools.integrations import invoke, saved_snapshot

from app.adapters.integrations import client, feishu
from app.domain.tools.integrations import service
from app.domain.tools.integrations.feishu_catalog import FEISHU_OPERATIONS
from app.domain.tools.integrations.models import IntegrationConnection as ConnectionOrm
from app.entities.defaults import utc_now
from app.entities.tools.integrations import IntegrationConnection
from app.infra.db.repositories.tools import integrations as repository
from app.infra.db.repositories.tools import repository as tools
from app.infra.db.session import get_session_factory
from app.ports import integrations as provider_api


class FeishuContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.responses = []

        async def handler(request):
            self.requests.append(request)
            return self.responses.pop(0)

        def factory(**_kwargs):
            return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

        for patcher in (
            patch.object(
                client, "validate_mcp_destination", AsyncMock(return_value=object())
            ),
            patch.object(client, "_hardened_http_client_factory", factory),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def response(self, data, status=200):
        self.responses.append(httpx2.Response(status, json=data))

    def test_full_cli_grants_accept_long_opaque_tokens_with_a_bound(self):
        configuration = support.settings()
        connection = IntegrationConnection(provider="feishu")
        previous = {
            "brand": "feishu",
            "client_id": "client",
            "client_secret": "private",
        }
        service.accept_tokens(
            connection,
            {
                "access_token": "u-" + "a" * 12000,
                "refresh_token": "r-" + "r" * 12000,
                "expires_in": 7200,
            },
            configuration,
            previous,
        )
        self.assertEqual(
            len(
                service.unseal(connection.secrets_ciphertext, configuration)[
                    "access_token"
                ]
            ),
            12002,
        )
        for token in ("a" * (64 * 1024 + 1), "bad\ntoken", ""):
            with (
                self.subTest(length=len(token)),
                self.assertRaises(provider_api.IntegrationProviderError),
            ):
                service.accept_tokens(
                    connection, {"access_token": token}, configuration, previous
                )

    async def test_personal_app_and_user_login_match_official_cli(self):
        self.response(
            {
                "device_code": "registration-private",
                "user_code": "visible",
                "interval": 5,
                "expire_in": 600,
            }
        )
        begin = await client.feishu_authorization("start", {})
        self.assertEqual(
            str(self.requests[0].url),
            "https://accounts.feishu.cn/oauth/v1/app/registration",
        )
        self.assertEqual(
            parse_qs(self.requests[0].content.decode()),
            {
                "action": ["begin"],
                "archetype": ["PersonalAgent"],
                "auth_method": ["client_secret"],
                "request_user_info": ["open_id tenant_brand"],
            },
        )
        self.assertEqual(
            begin["authorization"]["authorization_url"],
            "https://open.feishu.cn/page/cli?user_code=visible",
        )
        self.assertNotIn("registration-private", str(begin["authorization"]))
        self.response(
            {
                "client_id": "personal-client",
                "client_secret": "private-secret",
                "user_info": {"tenant_brand": "feishu"},
            }
        )
        self.response(
            {
                "device_code": "login-private",
                "verification_uri_complete": "https://accounts.feishu.cn/device?code=visible",
                "expires_in": 240,
            }
        )
        login = await client.feishu_authorization("poll", begin["credentials"])
        self.assertEqual(login["authorization"]["phase"], "login")
        request = self.requests[2]
        self.assertEqual(
            str(request.url), "https://accounts.feishu.cn/oauth/v1/device_authorization"
        )
        self.assertEqual(
            request.headers["authorization"],
            "Basic " + base64.b64encode(b"personal-client:private-secret").decode(),
        )
        scopes = parse_qs(request.content.decode())["scope"][0].split()
        self.assertIn("offline_access", scopes)
        self.assertIn("docx:document:readonly", scopes)
        self.assertIn("calendar:calendar.event:create", scopes)
        self.assertIn("im:message.send_as_user", scopes)
        self.assertNotIn("im:message:send_as_bot", scopes)
        # These retired aliases are absent from the official CLI's current
        # user-scope directory and make the next authorization request fail.
        self.assertNotIn("calendar:calendar:readonly", scopes)
        self.assertNotIn("docs:doc", scopes)
        self.assertIn("base:view:write_only", scopes)
        self.assertNotIn("base:view:create", scopes)
        self.response(
            {
                "access_token": "private-access",
                "refresh_token": "private-refresh",
                "expires_in": 7200,
            }
        )
        token = await client.feishu_authorization("poll", login["credentials"])
        self.assertEqual(token["access_token"], "private-access")
        self.assertEqual(
            str(self.requests[3].url), "https://accounts.feishu.cn/oauth/v3/token"
        )
        self.assertEqual(
            parse_qs(self.requests[3].content.decode()),
            {
                "grant_type": ["urn:ietf:params:oauth:grant-type:device_code"],
                "device_code": ["login-private"],
                "client_id": ["personal-client"],
                "client_secret": ["private-secret"],
            },
        )

    async def test_lark_registration_switches_only_between_official_brands(self):
        values = {"stage": "application", "brand": "feishu", "device_code": "code"}
        self.response(
            {"error": "authorization_pending", "user_info": {"tenant_brand": "lark"}},
            400,
        )
        self.response(
            {
                "client_id": "lark-client",
                "client_secret": "lark-secret",
                "user_info": {"tenant_brand": "lark"},
            }
        )
        self.response(
            {
                "device_code": "login-code",
                "verification_uri_complete": "https://accounts.larksuite.com/device",
            }
        )
        result = await client.feishu_authorization("poll", values)
        self.assertEqual(result["credentials"]["brand"], "lark")
        self.assertEqual(
            str(self.requests[1].url),
            "https://accounts.larksuite.com/oauth/v1/app/registration",
        )
        self.assertEqual(
            str(self.requests[2].url),
            "https://accounts.larksuite.com/oauth/v1/device_authorization",
        )
        self.response({"access_token": "rotated", "expires_in": 7200})
        await client.feishu_authorization(
            "refresh", {**result["credentials"], "refresh_token": "refresh"}
        )
        self.assertEqual(
            str(self.requests[3].url), "https://accounts.larksuite.com/oauth/v3/token"
        )
        self.assertEqual(
            json.loads(self.requests[3].content)["grant_type"], "refresh_token"
        )

    async def test_pending_slowdown_and_denied_grants_are_sanitized(self):
        values = {
            "stage": "login",
            "brand": "feishu",
            "device_code": "code",
            "client_id": "client",
            "client_secret": "private",
            "poll_seconds": 5,
        }
        for error in ("authorization_pending", "slow_down"):
            self.response({"code": 20094, "error": error}, 400)
            result = await client.feishu_authorization("poll", values)
            self.assertTrue(result["pending"])
            self.assertEqual(
                result["credentials"]["poll_seconds"], 10 if error == "slow_down" else 5
            )
        self.response(
            {
                "error": "access_denied",
                "error_description": "private-provider-diagnostic",
            },
            400,
        )
        with self.assertRaises(provider_api.IntegrationProviderError) as error:
            await client.feishu_authorization("poll", values)
        self.assertNotIn("private-provider-diagnostic", str(error.exception))
        with self.assertRaises(provider_api.IntegrationProviderError):
            await client.feishu_authorization(
                "poll", {**values, "brand": "attacker.example"}
            )
        self.assertEqual(len(self.requests), 3)

    async def test_login_links_and_malformed_credentials_are_rejected(self):
        for changes in (
            {"verification_uri_complete": "https://attacker.example/login"},
            {"verification_uri_complete": "javascript:alert(1)"},
            {"verification_uri_complete": "https://accounts.feishu.cn.evil.example/"},
            {"device_code": "bad\ncode"},
            {"expires_in": -1},
        ):
            self.response({"client_id": "client", "client_secret": "private"})
            self.response(
                {
                    "device_code": "code",
                    "verification_uri_complete": "https://accounts.feishu.cn/device",
                    **changes,
                }
            )
            with (
                self.subTest(changes=changes),
                self.assertRaises(provider_api.IntegrationProviderError),
            ):
                await client.feishu_authorization(
                    "poll",
                    {"stage": "application", "brand": "feishu", "device_code": "code"},
                )

    async def test_catalog_is_schema_valid_user_scoped_and_discoverable(self):
        definitions = feishu.catalog()
        self.assertEqual(len(definitions), 289)
        for name, definition in definitions.items():
            Draft202012Validator.check_schema(definition["params_schema"])
            Draft202012Validator.check_schema(definition["body_schema"])
            self.assertTrue(definition["path"].startswith("/open-apis/"), name)
            self.assertNotIn("..", definition["path"])
        result = await client.call_integration(
            "feishu", "list_operations", {"domain": "okr", "limit": 2}, {}, "request"
        )
        self.assertEqual(len(result["operations"]), 2)
        self.assertEqual(result["next_offset"], 2)
        detail = await client.call_integration(
            "feishu",
            "describe_operation",
            {"operation": "calendar.freebusys.list"},
            {},
            "request",
        )
        self.assertFalse(detail["write"], "a free/busy POST is read-only")
        self.assertEqual(detail["method"], "POST")
        self.assertEqual(self.requests, [])

    async def test_fixed_paths_user_tokens_and_message_idempotency(self):
        grant = {"access_token": "private-token", "brand": "feishu"}
        self.response({"code": 0, "data": {"items": []}})
        await client.call_integration(
            "feishu",
            "read_api",
            {"operation": "calendar.calendars.list", "params": {"page_size": 20}},
            grant,
            "read",
        )
        self.assertEqual(
            str(self.requests[0].url),
            "https://open.feishu.cn/open-apis/calendar/v4/calendars?page_size=20",
        )
        self.assertEqual(
            self.requests[0].headers["authorization"], "Bearer private-token"
        )
        self.assertNotIn("private-token", str(self.requests[0].url))
        for _ in range(2):
            self.response({"code": 0, "data": {"message_id": "sent"}})
            await client.call_integration(
                "feishu",
                "write_api",
                {
                    "operation": "im.messages.create",
                    "params": {"receive_id_type": "chat_id"},
                    "body": {
                        "receive_id": "oc_target",
                        "msg_type": "text",
                        "content": '{"text":"Hello"}',
                    },
                },
                grant,
                "same-request",
            )
        self.assertEqual(
            json.loads(self.requests[1].content)["uuid"],
            hashlib.sha256(b"same-request").hexdigest()[:32],
        )
        self.assertEqual(
            json.loads(self.requests[2].content), json.loads(self.requests[1].content)
        )

    async def test_reads_cannot_smuggle_writes_paths_or_credentials(self):
        grant = {"access_token": "private-token", "brand": "feishu"}
        cases = [
            (
                "read_api",
                {"operation": "task.tasks.create", "body": {"summary": "task"}},
            ),
            ("read_api", {"operation": "https://attacker.example/api"}),
            ("write_api", {"operation": "calendar.calendars.list"}),
            ("read_document", {"document_id": "retired"}),
            ("send_message", {"open_id": "retired", "text": "retired"}),
            (
                "read_api",
                {
                    "operation": "calendar.calendars.list",
                    "params": {"page_size": 10000},
                },
            ),
            (
                "read_api",
                {
                    "operation": "calendar.calendars.list",
                    "params": {"Authorization": "fake"},
                },
            ),
        ]
        cases += [
            (
                "read_api",
                {"operation": "minutes.minutes.get", "params": {"minute_token": value}},
            )
            for value in ("../other", "x/y", "x%2fy", "x?token=y", "x#y")
        ]
        for operation, args in cases:
            with (
                self.subTest(operation=operation, args=args),
                self.assertRaises(provider_api.IntegrationProviderError),
            ):
                await client.call_integration("feishu", operation, args, grant, "test")
        self.assertEqual(self.requests, [])

    async def test_lark_reads_and_expired_or_uncertain_results(self):
        grant = {"access_token": "private-token", "brand": "lark"}
        self.response({"code": 99991668, "msg": "private-token"})
        with self.assertRaises(provider_api.IntegrationProviderError) as error:
            await client.call_integration(
                "feishu", "read_api", {"operation": "im.chats.list"}, grant, "read"
            )
        self.assertTrue(error.exception.unauthorized)
        self.assertEqual(
            str(self.requests[0].url),
            "https://open.larksuite.com/open-apis/im/v1/chats",
        )
        self.response({"msg": "private-diagnostic"}, 500)
        with self.assertRaises(provider_api.IntegrationProviderError) as error:
            await client.call_integration(
                "feishu",
                "write_api",
                {
                    "operation": "docs.documents.create",
                    "body": {"content": "# Title", "format": "markdown"},
                },
                grant,
                "write",
            )
        self.assertTrue(error.exception.uncertain)
        self.assertNotIn("private-diagnostic", str(error.exception))


def installation():
    settings = replace(support.settings(), public_app_url="")
    application = {
        "authorization_url": "https://open.feishu.cn/page/cli?user_code=visible",
        "phase": "application",
        "mode": "device",
        "poll_seconds": 5,
        "expires_in": 600,
    }
    login = {
        **application,
        "authorization_url": "https://accounts.feishu.cn/device",
        "phase": "login",
        "expires_in": 240,
    }
    app_values = {
        "stage": "application",
        "brand": "feishu",
        "device_code": "private-device",
        "poll_seconds": 5,
    }
    login_values = {
        "stage": "login",
        "brand": "feishu",
        "client_id": "personal-client",
        "client_secret": "private-client-secret",
        "device_code": "private-login-device",
        "poll_seconds": 5,
    }
    api = AsyncMock(
        return_value={
            "pending": True,
            "credentials": app_values,
            "authorization": application,
        }
    )
    with (
        patch.object(provider_api, "feishu_authorization", api),
        test_client() as client_http,
    ):
        admin_token, workspace_id = activate_admin(client_http)
        admin = auth_headers(admin_token)
        owner_id, owner_token = create_active_user(
            client_http, admin_token, "feishu-owner"
        )
        other_id, other_token = create_active_user(
            client_http, admin_token, "feishu-other"
        )
        for user_id in (owner_id, other_id):
            assert (
                client_http.post(
                    f"/api/v1/workspaces/{workspace_id}/members",
                    headers=admin,
                    json={"user_id": user_id, "role": "member"},
                ).status_code
                == 201
            )
        root = f"/api/v1/workspaces/{workspace_id}/integrations/feishu"
        owner, other = auth_headers(owner_token), auth_headers(other_token)
        assert client_http.get(root + "/application", headers=admin).status_code == 404
        assert (
            client_http.put(
                root + "/application", headers=admin, json={"client_id": "retired"}
            ).status_code
            == 404
        )
        started = client_http.post(root + "/authorize", headers=owner)
        assert started.status_code == 200, started.text
        state = started.json()["state"]
        assert started.json()["phase"] == "application"
        assert "private-device" not in started.text

        async def allow_poll():
            async with get_session_factory()() as db:
                attempt = await repository.authorization(
                    db, hashlib.sha256(state.encode()).hexdigest()
                )
                attempt.next_poll_at = utc_now() - timedelta(seconds=1)
                await repository.save_authorization(db, attempt)
                await db.commit()

        def poll(headers=owner):
            asyncio.run(allow_poll())
            return client_http.post(
                root + "/callback", headers=headers, json={"state": state}
            )

        assert poll(other).status_code == 400
        assert api.await_count == 1
        api.return_value = {
            "pending": True,
            "credentials": login_values,
            "authorization": login,
        }
        pending = poll()
        assert pending.status_code == 200, pending.text
        assert pending.json()["status"] == "disconnected"
        assert pending.json()["authorization"]["phase"] == "login"
        assert "private-client-secret" not in pending.text
        assert "private-login-device" not in pending.text
        # The interval is enforced before contacting the provider again.
        calls = api.await_count
        assert (
            client_http.post(
                root + "/callback", headers=owner, json={"state": state}
            ).status_code
            == 200
        )
        assert api.await_count == calls
        api.return_value = {
            "access_token": "private-access",
            "refresh_token": "private-refresh",
            "expires_in": 7200,
        }
        connected = poll()
        assert connected.status_code == 200, connected.text
        assert connected.json()["status"] == "connected"
        source_id = connected.json()["source_id"]
        assert client_http.post(root + "/authorize", headers=owner).status_code == 409
        assert poll().json()["status"] == "connected"

        async def persisted():
            async with get_session_factory()() as db:
                connection = await repository.connection(
                    db, workspace_id, owner_id, "feishu"
                )
                assert "private-access" not in connection.secrets_ciphertext
                assert "private-client-secret" not in connection.secrets_ciphertext
                values = service.unseal(connection.secrets_ciphertext, settings)
                assert values["client_id"] == "personal-client"
                assert values["client_secret"] == "private-client-secret"
                installed = await tools.list_tools_by_source(
                    db, workspace_id, source_id
                )
                assert {tool.stable_key for tool in installed} == {
                    op["name"] for op in FEISHU_OPERATIONS
                }
                for tool in installed:
                    policy = await tools.get_tool_policy(db, workspace_id, tool.id)
                    assert policy.effect == (
                        "external_write"
                        if tool.stable_key == "write_api"
                        else "external_read"
                    )
                connection.access_expires_at = utc_now() - timedelta(seconds=1)
                await repository.save_connection(db, connection)
                await db.commit()
                return connection

        connection = asyncio.run(persisted())
        api.return_value = {
            "access_token": "refreshed",
            "refresh_token": "rotated",
            "expires_in": 7200,
        }

        async def refresh():
            async with get_session_factory()() as db:
                return await service.credentials(
                    db,
                    connection.id,
                    workspace_id,
                    owner_id,
                    connection.generation,
                    settings,
                )

        assert asyncio.run(refresh())["client_secret"] == "private-client-secret"
        assert api.call_args.args[0] == "refresh"
        snapshot = asyncio.run(
            saved_snapshot(workspace_id, owner_id, source_id, "list_operations")
        )
        with patch(
            "app.application.tools.runtime.adapters.integration.call_integration",
            AsyncMock(return_value={"operations": []}),
        ) as business:
            result = asyncio.run(invoke(snapshot, workspace_id, owner_id, settings))
            assert result.ok, result
            assert business.await_count == 1
            assert client_http.delete(root, headers=owner).status_code == 200
            assert not asyncio.run(
                invoke(snapshot, workspace_id, owner_id, settings)
            ).ok
            assert business.await_count == 1
        api.return_value = {
            "pending": True,
            "credentials": app_values,
            "authorization": application,
        }
        started = client_http.post(root + "/authorize", headers=owner)
        state = started.json()["state"]

        async def late_result(*_args):
            async with get_session_factory()() as db:
                await service.uninstall(
                    db, workspace_id, type("Actor", (), {"id": owner_id})(), "feishu"
                )
            return {
                "pending": True,
                "credentials": login_values,
                "authorization": login,
            }

        api.side_effect = late_result
        assert poll().status_code == 409
        api.side_effect = None
        assert (
            client_http.get(root.rsplit("/", 1)[0], headers=owner).json()[1]["status"]
            == "disconnected"
        )

        # Old app-based grants are rejected even if their access token is live.
        async def retired():
            async with get_session_factory()() as db:
                saved = await repository.connection(
                    db, workspace_id, owner_id, "feishu"
                )
                saved.application_revision, saved.status = 1, "connected"
                saved.secrets_ciphertext = service.seal(
                    {"access_token": "old-token"}, settings
                )
                await repository.save_connection(db, saved)
                await db.commit()
                try:
                    await service.credentials(
                        db, saved.id, workspace_id, owner_id, saved.generation, settings
                    )
                    raise AssertionError("retired grants must not execute")
                except provider_api.IntegrationProviderError:
                    pass
                assert await db.get(ConnectionOrm, saved.id)

        asyncio.run(retired())
        assert (
            client_http.get(root.rsplit("/", 1)[0], headers=owner).json()[1]["status"]
            == "reauthorization_required"
        )
        assert client_http.post(root + "/sync", headers=owner).status_code == 409
        # Failed or interrupted second-stage requests must leave a terminal
        # attempt, rather than a forever-processing installation.
        started = client_http.post(root + "/authorize", headers=owner)
        state = started.json()["state"]
        api.side_effect = provider_api.IntegrationProviderError(
            "Integration authorization failed. Please authorize again."
        )
        assert poll().status_code == 502

        async def authorization_status():
            async with get_session_factory()() as db:
                attempt = await repository.authorization(
                    db, hashlib.sha256(state.encode()).hexdigest()
                )
                return attempt.status

        assert asyncio.run(authorization_status()) == "failed"
        api.side_effect = None
        started = client_http.post(root + "/authorize", headers=owner)
        state = started.json()["state"]
        asyncio.run(allow_poll())
        api.side_effect = asyncio.CancelledError()

        async def interrupted():
            async with get_session_factory()() as db:
                try:
                    await service.complete(
                        db,
                        workspace_id,
                        type("Actor", (), {"id": owner_id})(),
                        "feishu",
                        type("Payload", (), {"state": state, "code": None})(),
                        settings,
                    )
                    raise AssertionError("cancellation must propagate")
                except asyncio.CancelledError:
                    pass

        asyncio.run(interrupted())
        assert asyncio.run(authorization_status()) == "failed"
    print(
        "Feishu personal installation, refresh, isolation, retirement and ledger checks passed."
    )


if __name__ == "__main__":
    if not unittest.main(exit=False).result.wasSuccessful():
        raise SystemExit(1)
    installation()

"""OAuth HTTP exchange, encrypted storage, ownership, rotation and revocation."""

import asyncio
import base64
import hashlib
import json
import threading
from dataclasses import replace
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from sqlalchemy import func, select
from tests import support
from tests.support import activate_admin, auth_headers, create_active_user, test_client

from app.domain.tools.mcp import oauth
from app.domain.tools.mcp.oauth_models import McpOAuthRevocation
from app.entities.defaults import utc_now
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.repositories.tools import mcp as mcp_repository
from app.infra.db.repositories.tools import oauth as repository
from app.infra.db.session import get_session_factory
from app.ports.mcp import McpClientError, McpDiscovery
from app.schemas.tools.oauth import McpOAuthCallback


class Provider(BaseHTTPRequestHandler):
    records = []
    fail_refresh = False

    def log_message(self, *_args):
        pass

    def do_POST(self):
        values = {
            key: value[0]
            for key, value in parse_qs(
                self.rfile.read(int(self.headers["Content-Length"])).decode()
            ).items()
        }
        self.records.append((self.path, values))
        if self.path == "/revoke":
            payload, code = {}, 200
        elif values.get("grant_type") == "refresh_token" and self.fail_refresh:
            payload, code = {"error": "invalid_grant"}, 400
        else:
            count = sum(path == "/token" for path, _ in self.records)
            payload, code = (
                {
                    "access_token": f"test-access-{count}",
                    "refresh_token": f"test-refresh-{count}",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
                200,
            )
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


async def expire_access(server_id):
    async with get_session_factory()() as db:
        connection = await repository.get_connection(db, server_id, lock=True)
        connection.access_expires_at = utc_now() - timedelta(seconds=1)
        await repository.save_connection(db, connection)
        await db.commit()


def main():
    Provider.records = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    settings = replace(support.settings(), mcp_allow_private_networks=True)
    try:
        with (
            patch.object(support, "settings", return_value=settings),
            test_client() as client,
        ):
            token, workspace_id = activate_admin(client)
            headers = auth_headers(token)
            root = f"/api/v1/workspaces/{workspace_id}/mcp-servers"
            configuration = {
                "authorization_endpoint": origin + "/authorize",
                "token_endpoint": origin + "/token",
                "revocation_endpoint": origin + "/revoke",
                "client_id": "test-client",
                "scopes": ["read", "write"],
            }
            payload = {
                "name": "OAuth fixture",
                "url": origin + "/mcp",
                "oauth": configuration,
            }
            created = client.post(root, headers=headers, json=payload)
            assert created.status_code == 201, created.text
            server_id = created.json()["id"]
            base = f"{root}/{server_id}"
            assert (
                created.json()["auth_mode"] == "oauth"
                and not created.json()["has_bearer_token"]
            )
            assert (
                client.post(base + "/oauth/authorize", headers=headers).status_code
                == 422
            )
            site = client.patch(
                "/api/v1/admin/smtp",
                headers=headers,
                json={
                    "host": "smtp.example.com",
                    "port": 587,
                    "security": "starttls",
                    "from_email": "noreply@example.com",
                    "from_name": "NexaFlow",
                    "site_url": "https://nexaflow.example",
                    "enabled": False,
                },
            )
            assert site.status_code == 200, site.text

            def start():
                response = client.post(base + "/oauth/authorize", headers=headers)
                assert response.status_code == 200, response.text
                query = parse_qs(urlparse(response.json()["authorization_url"]).query)
                assert query["code_challenge_method"] == ["S256"]
                assert query["resource"] == [origin + "/mcp"]
                assert query["redirect_uri"] == [
                    "https://nexaflow.example/app/mcp/oauth/callback"
                ]
                return query

            query = start()
            state = query["state"][0]
            other_id, other_token = create_active_user(client, token, "oauth-other")
            assert (
                client.post(
                    f"/api/v1/workspaces/{workspace_id}/members",
                    headers=headers,
                    json={"user_id": other_id, "role": "admin"},
                ).status_code
                == 201
            )
            for suffix in ("", "/authorize", "/disconnect", "/callback"):
                method = "GET" if not suffix else "POST"
                response = client.request(
                    method,
                    base + "/oauth" + suffix,
                    headers=auth_headers(other_token),
                    json={"state": state, "code": "code"}
                    if suffix == "/callback"
                    else None,
                )
                assert response.status_code == 404, response.text
            assert (
                client.post(
                    base + "/oauth/callback",
                    headers=headers,
                    json={"state": state + "x", "code": "bad"},
                ).status_code
                == 400
            )
            connected = client.post(
                base + "/oauth/callback",
                headers=headers,
                json={"state": state, "code": "test-code"},
            )
            assert connected.status_code == 200, connected.text
            assert connected.json()["expires_at"] is not None
            assert (
                connected.json()["status"] == "connected"
                and "test-access" not in connected.text
                and "secret" not in connected.text
            )
            request = Provider.records[-1][1]
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(request["code_verifier"].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            assert (
                challenge == query["code_challenge"][0]
                and request["code"] == "test-code"
            )
            replay = client.post(
                base + "/oauth/callback",
                headers=headers,
                json={"state": state, "code": "test-code"},
            )
            assert replay.status_code == 200 and len(Provider.records) == 1
            assert (
                client.post(base + "/oauth/authorize", headers=headers).status_code
                == 409
            )
            assert (
                client.put(
                    base + "/oauth", headers=headers, json=configuration
                ).status_code
                == 409
            )

            async def inspect():
                async with get_session_factory()() as db:
                    connection = await repository.get_connection(db, server_id)
                    attempt = await repository.get_attempt(
                        db, hashlib.sha256(state.encode()).hexdigest()
                    )
                    assert (
                        "test-access" not in connection.secrets_ciphertext
                        and "test-refresh" not in connection.secrets_ciphertext
                    )
                    assert (
                        attempt.verifier_ciphertext == ""
                        and attempt.status == "completed"
                    )
                    return await mcp_repository.get_mcp_server_by_id(db, server_id)

            entity = client.portal.call(inspect)
            assert (
                client.portal.call(oauth.access_token, entity, settings)
                == "test-access-1"
            )
            client.portal.call(expire_access, server_id)
            assert (
                client.portal.call(oauth.access_token, entity, settings)
                == "test-access-2"
            )
            assert Provider.records[-1][1]["refresh_token"] == "test-refresh-1"
            with patch(
                "app.domain.tools.mcp.service.discover_mcp_tools",
                new=AsyncMock(return_value=McpDiscovery(tools=[])),
            ) as discovery:
                refreshed = client.post(base + "/refresh", headers=headers)
                assert refreshed.status_code == 200, refreshed.text
                assert discovery.await_args.args[0].bearer_token == "test-access-2"
            client.portal.call(expire_access, server_id)
            Provider.fail_refresh = True
            try:
                client.portal.call(oauth.access_token, entity, settings)
                raise AssertionError("refresh must require reconnection")
            except McpClientError as exc:
                assert exc.request_sent is False
            assert (
                client.get(base + "/oauth", headers=headers).json()["status"]
                == "reauthorization_required"
            )
            count = len(Provider.records)
            try:
                client.portal.call(oauth.access_token, entity, settings)
                raise AssertionError("unknown refresh must not replay")
            except McpClientError:
                pass
            assert len(Provider.records) == count
            Provider.fail_refresh = False
            assert (
                client.post(base + "/oauth/disconnect", headers=headers).json()[
                    "status"
                ]
                == "disconnected"
            )
            client.portal.call(oauth.recover_revocations, settings)
            assert [
                values["token"]
                for path, values in Provider.records
                if path == "/revoke"
            ] == ["test-refresh-2", "test-access-2"]

            # A callback response arriving after disconnect cannot restore authority.
            query = start()

            async def late_callback():
                sent, release = asyncio.Event(), asyncio.Event()

                async def delayed(*_args, **_kwargs):
                    sent.set()
                    await release.wait()
                    return {
                        "access_token": "late-token",
                        "refresh_token": "late-refresh",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }

                async with get_session_factory()() as db:
                    actor = await user_repository.get_user_by_id(
                        db, created.json()["created_by_user_id"]
                    )
                    current_server = await mcp_repository.get_mcp_server_by_id(
                        db, server_id
                    )
                    with patch.object(oauth, "oauth_post", new=delayed):
                        pending = asyncio.create_task(
                            oauth.callback(
                                db,
                                current_server,
                                actor,
                                McpOAuthCallback(state=query["state"][0], code="late"),
                                settings,
                            )
                        )
                        await sent.wait()
                        async with get_session_factory()() as other_db:
                            await oauth.queue_disconnect(other_db, server_id)
                            await other_db.commit()
                        release.set()
                        try:
                            await pending
                            raise AssertionError("late callback must fail")
                        except HTTPException as exc:
                            assert exc.status_code == 400
                async with get_session_factory()() as db:
                    connection = await repository.get_connection(db, server_id)
                    assert (
                        connection.status == "disconnected"
                        and connection.secrets_ciphertext == ""
                    )
                    assert (
                        await db.scalar(
                            select(func.count()).select_from(McpOAuthRevocation)
                        )
                        == 1
                    )

            client.portal.call(late_callback)
            assert client.delete(base, headers=headers).status_code == 204
            client.portal.call(oauth.recover_revocations, settings)
            assert [
                values["token"]
                for path, values in Provider.records
                if path == "/revoke"
            ][-2:] == ["late-refresh", "late-token"]
            assert (
                client.post(
                    root,
                    headers=headers,
                    json=payload
                    | {
                        "name": "Insecure",
                        "oauth": configuration
                        | {"token_endpoint": "http://example.com/token"},
                    },
                ).status_code
                == 422
            )
            # Workspace graph deletion must retain revocation intent too.
            created = client.post(
                root, headers=headers, json=payload | {"name": "Workspace revoke"}
            )
            assert created.status_code == 201, created.text
            base = f"{root}/{created.json()['id']}"
            next_query = start()
            connected = client.post(
                base + "/oauth/callback",
                headers=headers,
                json={"state": next_query["state"][0], "code": "workspace-code"},
            )
            assert connected.status_code == 200, connected.text
            before = len([path for path, _ in Provider.records if path == "/revoke"])
            assert (
                client.delete(
                    f"/api/v1/workspaces/{workspace_id}", headers=headers
                ).status_code
                == 204
            )
            client.portal.call(oauth.recover_revocations, settings)
            assert (
                len([path for path, _ in Provider.records if path == "/revoke"])
                == before + 2
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print("MCP_OAUTH_OK")


if __name__ == "__main__":
    main()

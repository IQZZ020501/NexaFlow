import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

from app.capabilities.enterprise_identity import (
    EnterpriseProviderError,
    ExternalPrincipal,
    _request_json,
    build_authorization_url,
    resolve_external_principal,
)
from app.entities.enterprise_identity import EnterpriseIdentityConnection
from app.infrastructure import enterprise_login_rate_limit as rate_limit
from app.infrastructure.enterprise_login_rate_limit import (
    EnterpriseLoginRateLimitExceeded,
    EnterpriseLoginRateLimitUnavailable,
)
from app.shareddomain.enterprise_identity.services import (
    safe_next_path,
    validate_connection_fields,
)
from tests.support import activate_admin, auth_headers, settings, test_client


def _raises(error_type, callback):
    try:
        callback()
    except error_type as exc:
        return exc
    raise AssertionError(f"Expected {error_type.__name__}")


class _ProviderResponse:
    def __init__(self, payload, *, chunks: list[bytes] | None = None) -> None:
        self.chunks = chunks or [json.dumps(payload).encode()]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self, *, chunk_size: int):
        assert chunk_size == 8192
        for chunk in self.chunks:
            yield chunk


class _ProviderClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def _start(client, connection_id: str, provider: str = "feishu") -> tuple[str, str]:
    response = client.get(
        f"/api/v1/auth/enterprise/{connection_id}/start?next=/app/agents",
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["state"][0]
    if provider == "feishu":
        assert query["code_challenge_method"] == ["S256"]
    return query["state"][0], response.headers["location"]


def main() -> None:
    assert safe_next_path("/app/agents") == "/app/agents"
    assert safe_next_path("https://evil.example") == "/app/apps"
    assert safe_next_path("//evil.example") == "/app/apps"
    assert safe_next_path("/\\evil.example") == "/app/apps"
    assert safe_next_path("/\t/evil.example") == "/app/apps"
    assert safe_next_path("/app/agents\\evil") == "/app/apps"
    assert safe_next_path("/" + "a" * 2048) == "/app/apps"
    _raises(Exception, lambda: validate_connection_fields("unknown", "id", "tenant", None))
    _raises(Exception, lambda: validate_connection_fields("feishu", " ", "tenant", None))
    _raises(Exception, lambda: validate_connection_fields("wecom", "id", "tenant", None))

    feishu = EnterpriseIdentityConnection(
        provider="feishu", client_id="fei-client", tenant_id="fei-tenant"
    )
    feishu_query = parse_qs(
        urlsplit(
            build_authorization_url(
                feishu, "https://app.example.com/callback", "state", "challenge"
            )
        ).query
    )
    assert feishu_query["code_challenge_method"] == ["S256"]
    feishu_qr_url = build_authorization_url(
        feishu,
        "https://app.example.com/callback",
        "feishu_qr.state",
        "unused",
        feishu_qr=True,
    )
    assert urlsplit(feishu_qr_url).netloc == "passport.feishu.cn"
    feishu_qr_query = parse_qs(urlsplit(feishu_qr_url).query)
    assert feishu_qr_query["state"] == ["feishu_qr.state"]
    assert "code_challenge" not in feishu_qr_query
    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(
            side_effect=[
                {"access_token": "token"},
                {
                    "data": {
                        "open_id": "ou-feishu",
                        "tenant_key": "fei-tenant",
                        "name": "Feishu User",
                        "email": "fei@example.com",
                    }
                },
            ]
        ),
    ):
        resolved = asyncio.run(
            resolve_external_principal(
                feishu, "secret", "code", "https://app.example.com/callback", "verifier"
            )
        )
    assert resolved.subject_id == "ou-feishu"
    assert resolved.email == "fei@example.com"
    qr_requests = AsyncMock(
        side_effect=[
            {"access_token": "qr-token"},
            {
                "open_id": "ou-feishu-qr",
                "tenant_key": "fei-tenant",
                "name": "Feishu QR User",
            },
        ]
    )
    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=qr_requests,
    ):
        resolved = asyncio.run(
            resolve_external_principal(
                feishu,
                "secret",
                "code",
                "https://app.example.com/callback",
                "unused",
                feishu_qr=True,
            )
        )
    assert resolved.subject_id == "ou-feishu-qr"
    assert qr_requests.await_args_list[0].args[1] == (
        "https://passport.feishu.cn/suite/passport/oauth/token"
    )
    assert "code_verifier" not in qr_requests.await_args_list[0].kwargs["data"]
    assert qr_requests.await_args_list[1].args[1] == (
        "https://passport.feishu.cn/suite/passport/oauth/userinfo"
    )
    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(return_value={}),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    feishu, "secret", "code", "https://app.example.com/callback", "verifier"
                )
            ),
        )
    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(side_effect=[{"access_token": "token"}, {"data": []}]),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    feishu, "secret", "code", "https://app.example.com/callback", "verifier"
                )
            ),
        )

    unsupported = EnterpriseIdentityConnection(provider="unknown")
    _raises(
        EnterpriseProviderError,
        lambda: build_authorization_url(unsupported, "https://app.example.com", "state", "challenge"),
    )
    _raises(
        EnterpriseProviderError,
        lambda: asyncio.run(
            resolve_external_principal(
                unsupported, "secret", "code", "https://app.example.com", "verifier"
            )
        ),
    )

    with patch(
        "app.capabilities.enterprise_identity.httpx2.AsyncClient",
        return_value=_ProviderClient(_ProviderResponse({"ok": True})),
    ):
        assert asyncio.run(_request_json("GET", "https://provider.example")) == {"ok": True}
    with patch(
        "app.capabilities.enterprise_identity.httpx2.AsyncClient",
        return_value=_ProviderClient(
            _ProviderResponse({}, chunks=[b"x" * (32 * 1024), b"x" * (33 * 1024)])
        ),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(_request_json("GET", "https://provider.example")),
        )
    with patch(
        "app.capabilities.enterprise_identity.httpx2.AsyncClient",
        return_value=_ProviderClient(_ProviderResponse([])),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(_request_json("GET", "https://provider.example")),
        )
    with patch(
        "app.capabilities.enterprise_identity.httpx2.AsyncClient",
        return_value=_ProviderClient(error=OSError("offline")),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(_request_json("GET", "https://provider.example")),
        )

    rate_limit._client = SimpleNamespace(eval=AsyncMock(return_value=[61, 0]))
    exceeded = _raises(
        EnterpriseLoginRateLimitExceeded,
        lambda: asyncio.run(rate_limit.enforce_enterprise_login_rate_limit(settings(), None)),
    )
    assert exceeded.retry_after == 1
    rate_limit._client = SimpleNamespace(eval=AsyncMock(side_effect=ValueError("bad reply")))
    _raises(
        EnterpriseLoginRateLimitUnavailable,
        lambda: asyncio.run(rate_limit.enforce_enterprise_login_rate_limit(settings(), "127.0.0.1")),
    )
    rate_limit._client = None

    dingtalk = EnterpriseIdentityConnection(
        provider="dingtalk", client_id="ding-client", tenant_id="ding-corp"
    )
    dingtalk_query = parse_qs(
        urlsplit(
            build_authorization_url(
                dingtalk, "https://app.example.com/callback", "state", "challenge"
            )
        ).query
    )
    assert dingtalk_query["corpId"] == ["ding-corp"]
    assert dingtalk_query["scope"] == ["openid corpid"]

    wecom = EnterpriseIdentityConnection(
        provider="wecom",
        client_id="unused",
        tenant_id="wecom-corp",
        agent_id="1000002",
    )
    wecom_query = parse_qs(
        urlsplit(
            build_authorization_url(
                wecom, "https://app.example.com/callback", "state", "challenge"
            )
        ).query
    )
    assert wecom_query["appid"] == ["wecom-corp"]
    assert wecom_query["agentid"] == ["1000002"]

    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(
            side_effect=[
                {"accessToken": "token", "corpId": "ding-corp"},
                {"unionId": "union-id", "nick": "Ding User"},
            ]
        ),
    ):
        resolved = asyncio.run(
            resolve_external_principal(
                dingtalk, "secret", "code", "https://app.example.com/callback", "verifier"
            )
        )
    assert resolved.subject_id == "union-id"
    assert resolved.tenant_id == "ding-corp"
    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(
            side_effect=[
                {"accessToken": "token", "corpId": "ding-corp"},
                {},
            ]
        ),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    dingtalk, "secret", "code", "https://app.example.com/callback", "verifier"
                )
            ),
        )

    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(
            side_effect=[
                {"errcode": 0, "access_token": "token"},
                {"errcode": 0, "userid": "wecom-user"},
            ]
        ),
    ):
        resolved = asyncio.run(
            resolve_external_principal(
                wecom, "secret", "code", "https://app.example.com/callback", "verifier"
            )
        )
    assert resolved.subject_id == "wecom-user"
    assert resolved.tenant_id == "wecom-corp"
    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(return_value={"errcode": 40013}),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    wecom, "secret", "code", "https://app.example.com/callback", "verifier"
                )
            ),
        )
    with patch(
        "app.capabilities.enterprise_identity._request_json",
        new=AsyncMock(
            side_effect=[
                {"errcode": 0, "access_token": "token"},
                {"errcode": 40029},
            ]
        ),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    wecom, "secret", "code", "https://app.example.com/callback", "verifier"
                )
            ),
        )

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        headers = auth_headers(admin_token)
        base = f"/api/v1/admin/enterprise-identity/workspaces/{workspace_id}"

        created = client.put(
            f"{base}/connections/feishu",
            headers=headers,
            json={
                "name": "Company Feishu",
                "client_id": "cli_test",
                "client_secret": "super-secret",
                "tenant_id": "tenant_test",
                "enabled": True,
            },
        )
        assert created.status_code == 200, created.text
        connection = created.json()
        assert connection["has_client_secret"] is True
        assert connection["client_secret_hint"] == "****cret"
        assert "super-secret" not in created.text
        assert connection["callback_url"].endswith("/api/v1/auth/enterprise/callback/feishu")
        assert connection["login_url"].endswith(f"/login?workspace={workspace_id}")
        assert client.get(f"{base}/connections", headers=headers).status_code == 200
        assert client.get(
            "/api/v1/admin/enterprise-identity/workspaces/missing/connections",
            headers=headers,
        ).status_code == 404
        assert client.put(
            "/api/v1/admin/enterprise-identity/workspaces/missing/connections/feishu",
            headers=headers,
            json={
                "name": "Missing",
                "client_id": "client",
                "client_secret": "secret",
                "tenant_id": "tenant",
                "enabled": True,
            },
        ).status_code == 404
        assert client.get(
            "/api/v1/auth/enterprise/connections?workspace_id=missing"
        ).status_code == 404
        assert client.get(
            "/api/v1/auth/enterprise/missing/start", follow_redirects=False
        ).status_code == 404
        blank_name = client.put(
            f"{base}/connections/dingtalk",
            headers=headers,
            json={
                "name": " ",
                "client_id": "ding-client",
                "client_secret": "secret",
                "tenant_id": "ding-corp",
                "enabled": True,
            },
        )
        assert blank_name.status_code == 422
        missing_secret = client.put(
            f"{base}/connections/dingtalk",
            headers=headers,
            json={
                "name": "Company DingTalk",
                "client_id": "ding-client",
                "tenant_id": "ding-corp",
                "enabled": True,
            },
        )
        assert missing_secret.status_code == 422
        blank_secret = client.put(
            f"{base}/connections/dingtalk",
            headers=headers,
            json={
                "name": "Company DingTalk",
                "client_id": "ding-client",
                "client_secret": " ",
                "tenant_id": "ding-corp",
                "enabled": True,
            },
        )
        assert blank_secret.status_code == 422

        public = client.get(
            f"/api/v1/auth/enterprise/connections?workspace_id={workspace_id}"
        )
        assert public.status_code == 200, public.text
        assert public.json()["connections"] == [
            {
                "id": connection["id"],
                "provider": "feishu",
                "name": "Company Feishu",
                "start_url": f"/api/v1/auth/enterprise/{connection['id']}/start",
            }
        ]
        public_without_workspace = client.get("/api/v1/auth/enterprise/connections")
        assert public_without_workspace.status_code == 200, public_without_workspace.text
        assert public_without_workspace.json() == {
            "workspace_id": None,
            "workspace_name": None,
            "connections": public.json()["connections"],
        }

        state, authorize_url = _start(client, connection["id"])
        assert urlsplit(authorize_url).netloc == "accounts.feishu.cn"
        principal = ExternalPrincipal(
            subject_id="ou_external",
            tenant_id="tenant_test",
            display_name="Enterprise User",
            email="untrusted@example.com",
        )
        qr_prepared = client.post(
            f"/api/v1/auth/enterprise/{connection['id']}/qr?next=/app/agents"
        )
        assert qr_prepared.status_code == 200, qr_prepared.text
        qr_authorize_url = qr_prepared.json()["authorization_url"]
        assert urlsplit(qr_authorize_url).netloc == "passport.feishu.cn"
        qr_query = parse_qs(urlsplit(qr_authorize_url).query)
        assert qr_query["state"][0].startswith("feishu_qr.")
        assert "code_challenge" not in qr_query
        qr_resolver = AsyncMock(return_value=principal)
        with patch(
            "app.application.enterprise_identity.resolve_external_principal",
            new=qr_resolver,
        ):
            qr_login = client.get(
                "/api/v1/auth/enterprise/callback/feishu"
                f"?state={qr_query['state'][0]}&code=qr-code",
                follow_redirects=False,
            )
        assert qr_login.status_code == 303, qr_login.text
        assert qr_resolver.await_args.kwargs["feishu_qr"] is True
        state, _ = _start(client, connection["id"])
        with patch(
            "app.application.enterprise_identity.resolve_external_principal",
            new=AsyncMock(return_value=principal),
        ):
            first_login = client.get(
                f"/api/v1/auth/enterprise/callback/feishu?state={state}&code=code-1",
                follow_redirects=False,
            )
        assert first_login.status_code == 303, first_login.text
        assert f"workspace={workspace_id}" in first_login.headers["location"]
        assert "next=%2Fapp%2Fagents" in first_login.headers["location"]

        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text
        jit_access_token = refreshed.json()["access_token"]
        jit_me = client.get(
            "/api/v1/auth/me",
            headers=auth_headers(jit_access_token),
        )
        assert jit_me.status_code == 200, jit_me.text
        jit_user = jit_me.json()["user"]
        assert jit_user["username"].startswith("feishu_")
        assert jit_user["email"].endswith("@sso.nexaflow.invalid")
        assert jit_user["email"] != principal.email
        assert jit_user["name"] == "Enterprise User"
        assert jit_user["is_global_admin"] is False
        assert jit_user["must_change_password"] is False
        assert jit_me.json()["memberships"] == [
            {"workspace_id": workspace_id, "role": "member"}
        ]

        identities = client.get(f"{base}/identities", headers=headers)
        assert identities.status_code == 200, identities.text
        identity = identities.json()[0]
        assert identity["status"] == "active"
        assert identity["user_id"] == jit_user["id"]
        assert identity["email"] == principal.email

        repeat_state, _ = _start(client, connection["id"])
        with patch(
            "app.application.enterprise_identity.resolve_external_principal",
            new=AsyncMock(return_value=principal),
        ):
            repeated = client.get(
                f"/api/v1/auth/enterprise/callback/feishu?state={repeat_state}&code=code-repeat",
                follow_redirects=False,
            )
        assert repeated.status_code == 303, repeated.text
        repeat_refresh = client.post("/api/v1/auth/refresh")
        assert repeat_refresh.status_code == 200, repeat_refresh.text
        repeat_me = client.get(
            "/api/v1/auth/me",
            headers=auth_headers(repeat_refresh.json()["access_token"]),
        )
        assert repeat_me.json()["user"]["id"] == jit_user["id"]

        assert client.put(
            f"{base}/identities/missing/binding",
            headers=headers,
            json={"user_id": None},
        ).status_code == 404
        assert client.put(
            f"/api/v1/admin/enterprise-identity/workspaces/other/identities/{identity['id']}/binding",
            headers=headers,
            json={"user_id": None},
        ).status_code == 404
        assert client.put(
            f"{base}/identities/{identity['id']}/binding",
            headers=headers,
            json={"user_id": "missing"},
        ).status_code == 422

        me = client.get("/api/v1/auth/me", headers=headers).json()
        assert jit_user["id"] != me["user"]["id"]
        bound = client.put(
            f"{base}/identities/{identity['id']}/binding",
            headers=headers,
            json={"user_id": me["user"]["id"]},
        )
        assert bound.status_code == 200, bound.text
        assert bound.json()["status"] == "active"
        assert bound.json()["user_id"] == me["user"]["id"]
        assert client.get(
            "/api/v1/auth/me",
            headers=auth_headers(jit_access_token),
        ).status_code == 401

        missing_code = client.get(
            "/api/v1/auth/enterprise/callback/feishu?state=12345678901234567890",
            follow_redirects=False,
        )
        assert "error=provider_error" in missing_code.headers["location"]

        wrong_provider_state, _ = _start(client, connection["id"])
        wrong_provider = client.get(
            f"/api/v1/auth/enterprise/callback/dingtalk?state={wrong_provider_state}&authCode=code",
            follow_redirects=False,
        )
        assert "error=invalid_state" in wrong_provider.headers["location"]

        provider_error_state, _ = _start(client, connection["id"])
        with patch(
            "app.application.enterprise_identity.resolve_external_principal",
            new=AsyncMock(side_effect=EnterpriseProviderError("failed")),
        ):
            provider_error = client.get(
                f"/api/v1/auth/enterprise/callback/feishu?state={provider_error_state}&code=code",
                follow_redirects=False,
            )
        assert "error=provider_error" in provider_error.headers["location"]

        wrong_tenant_state, _ = _start(client, connection["id"])
        with patch(
            "app.application.enterprise_identity.resolve_external_principal",
            new=AsyncMock(
                return_value=ExternalPrincipal(
                    subject_id="ou_external",
                    tenant_id="another-tenant",
                    display_name="Enterprise User",
                )
            ),
        ):
            wrong_tenant = client.get(
                f"/api/v1/auth/enterprise/callback/feishu?state={wrong_tenant_state}&code=code",
                follow_redirects=False,
            )
        assert "error=tenant_mismatch" in wrong_tenant.headers["location"]

        state, _ = _start(client, connection["id"])
        with patch(
            "app.application.enterprise_identity.resolve_external_principal",
            new=AsyncMock(return_value=principal),
        ):
            completed = client.get(
                f"/api/v1/auth/enterprise/callback/feishu?state={state}&code=code-2",
                follow_redirects=False,
            )
        assert completed.status_code == 303, completed.text
        assert f"workspace={workspace_id}" in completed.headers["location"]
        assert "next=%2Fapp%2Fagents" in completed.headers["location"]

        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text
        enterprise_access_token = refreshed.json()["access_token"]
        enterprise_me = client.get(
            "/api/v1/auth/me",
            headers=auth_headers(enterprise_access_token),
        )
        assert enterprise_me.status_code == 200, enterprise_me.text
        assert enterprise_me.json()["user"]["id"] == me["user"]["id"]

        reconfigured = client.put(
            f"{base}/connections/feishu",
            headers=headers,
            json={
                "name": "Company Feishu",
                "client_id": "cli_reconfigured",
                "tenant_id": "tenant_test",
                "enabled": True,
            },
        )
        assert reconfigured.status_code == 200, reconfigured.text
        assert (
            client.get(
                "/api/v1/auth/me", headers=auth_headers(enterprise_access_token)
            ).status_code
            == 401
        )
        disabled = client.put(
            f"{base}/connections/feishu",
            headers=headers,
            json={
                "name": "Company Feishu",
                "client_id": "cli_reconfigured",
                "tenant_id": "tenant_test",
                "enabled": False,
            },
        )
        assert disabled.status_code == 200, disabled.text

        replay = client.get(
            f"/api/v1/auth/enterprise/callback/feishu?state={state}&code=code-2",
            follow_redirects=False,
        )
        assert replay.status_code == 303, replay.text
        assert "error=invalid_state" in replay.headers["location"]

        with patch(
            "app.api.v1.endpoints.enterprise_identity.enforce_enterprise_login_rate_limit",
            new=AsyncMock(side_effect=EnterpriseLoginRateLimitExceeded(7)),
        ):
            limited = client.get(
                f"/api/v1/auth/enterprise/{connection['id']}/start",
                follow_redirects=False,
            )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "7"
        with patch(
            "app.api.v1.endpoints.enterprise_identity.enforce_enterprise_login_rate_limit",
            new=AsyncMock(side_effect=EnterpriseLoginRateLimitUnavailable()),
        ):
            unavailable = client.get(
                f"/api/v1/auth/enterprise/{connection['id']}/start",
                follow_redirects=False,
            )
        assert unavailable.status_code == 503

        unbound = client.put(
            f"{base}/identities/{identity['id']}/binding",
            headers=headers,
            json={"user_id": None},
        )
        assert unbound.status_code == 200, unbound.text
        assert unbound.json()["status"] == "disabled"
        assert (
            client.get(
                "/api/v1/auth/me", headers=auth_headers(enterprise_access_token)
            ).status_code
            == 401
        )
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

        reenabled = client.put(
            f"{base}/connections/feishu",
            headers=headers,
            json={
                "name": "Company Feishu",
                "client_id": "cli_reconfigured",
                "tenant_id": "tenant_test",
                "enabled": True,
            },
        )
        assert reenabled.status_code == 200, reenabled.text
        disabled_identity_state, _ = _start(client, connection["id"])
        with patch(
            "app.application.enterprise_identity.resolve_external_principal",
            new=AsyncMock(return_value=principal),
        ):
            disabled_identity = client.get(
                f"/api/v1/auth/enterprise/callback/feishu?state={disabled_identity_state}&code=code-3",
                follow_redirects=False,
            )
        assert "error=identity_disabled" in disabled_identity.headers["location"]

        wecom_config = client.put(
            f"{base}/connections/wecom",
            headers=headers,
            json={
                "name": "Company WeCom",
                "client_secret": "wecom-secret",
                "tenant_id": "wecom-corp",
                "agent_id": "1000002",
                "enabled": True,
            },
        )
        assert wecom_config.status_code == 200, wecom_config.text
        assert wecom_config.json()["client_id"] == "wecom-corp"

        dingtalk_config = client.put(
            f"{base}/connections/dingtalk",
            headers=headers,
            json={
                "name": "Company DingTalk",
                "client_id": "ding-client",
                "client_secret": "ding-secret",
                "tenant_id": "ding-corp",
                "enabled": True,
            },
        )
        assert dingtalk_config.status_code == 200, dingtalk_config.text
        assert (
            client.post(
                f"/api/v1/auth/enterprise/{dingtalk_config.json()['id']}/qr"
            ).status_code
            == 404
        )

        direct_login_cases = [
            (
                "dingtalk",
                dingtalk_config.json()["id"],
                "authCode",
                ExternalPrincipal(
                    subject_id="ding-user",
                    tenant_id="ding-corp",
                    display_name="Ding User",
                ),
            ),
            (
                "wecom",
                wecom_config.json()["id"],
                "code",
                ExternalPrincipal(
                    subject_id="wecom-user",
                    tenant_id="wecom-corp",
                    display_name="WeCom User",
                ),
            ),
        ]
        for provider, connection_id, code_parameter, external_principal in direct_login_cases:
            state, _ = _start(client, connection_id, provider)
            with patch(
                "app.application.enterprise_identity.resolve_external_principal",
                new=AsyncMock(return_value=external_principal),
            ):
                completed = client.get(
                    f"/api/v1/auth/enterprise/callback/{provider}"
                    f"?state={state}&{code_parameter}=code",
                    follow_redirects=False,
                )
            assert completed.status_code == 303, completed.text
            assert f"workspace={workspace_id}" in completed.headers["location"]
            refreshed = client.post("/api/v1/auth/refresh")
            assert refreshed.status_code == 200, refreshed.text
            enterprise_me = client.get(
                "/api/v1/auth/me",
                headers=auth_headers(refreshed.json()["access_token"]),
            )
            assert enterprise_me.status_code == 200, enterprise_me.text
            assert enterprise_me.json()["user"]["username"].startswith(f"{provider}_")
            assert enterprise_me.json()["memberships"] == [
                {"workspace_id": workspace_id, "role": "member"}
            ]

        all_public = client.get("/api/v1/auth/enterprise/connections")
        assert all_public.status_code == 200, all_public.text
        assert {item["provider"] for item in all_public.json()["connections"]} == {
            "feishu",
            "dingtalk",
            "wecom",
        }


if __name__ == "__main__":
    main()

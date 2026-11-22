import asyncio
import json
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urljoin, urlsplit

from tests.support import activate_admin, auth_headers, settings, test_client

from app.adapters.identity.enterprise import (
    EnterpriseProviderError,
    ExternalPrincipal,
    _request_json,
    build_authorization_url,
    resolve_external_principal,
)
from app.domain.identity.enterprise.services import (
    safe_next_path,
    validate_connection_fields,
)
from app.entities.identity.enterprise import EnterpriseIdentityConnection
from app.infra.security import enterprise_login_rate_limit as rate_limit
from app.infra.security.enterprise_login_rate_limit import (
    EnterpriseLoginRateLimitExceeded,
    EnterpriseLoginRateLimitUnavailable,
)
from app.infra.security.keyring import application_secret_key
from app.infra.security.secrets import encrypt_secret
from app.ports.enterprise_identity import (
    resolve_external_principal as resolve_external_principal_via_port,
)


def _raises(error_type, callback):
    try:
        callback()
    except error_type as exc:
        return exc
    raise AssertionError(f"Expected {error_type.__name__}")


class _ProviderResponse:
    def __init__(
        self, payload, *, chunks: list[bytes] | None = None, status_code: int = 200
    ) -> None:
        self.chunks = chunks or [json.dumps(payload).encode()]
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
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


class _WeComRedis:
    def __init__(self) -> None:
        self.values = {}
        self.expires_at = {}
        self.locks = {}
        self.now = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, key):
        if self.expires_at.get(key, 0) <= self.now:
            return None
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        self.values[key] = value
        self.expires_at[key] = self.now + ex

    def lock(self, key, *, timeout, blocking_timeout):
        assert timeout > blocking_timeout > 0
        return self.locks.setdefault(key, asyncio.Lock())


async def _test_wecom_token_cache() -> None:
    cache = _WeComRedis()
    connection = EnterpriseIdentityConnection(
        provider="wecom", tenant_id="cache-corp", agent_id="1000002"
    )
    token_requests = []
    user_requests = []
    rejected_tokens = set()

    async def request(_method, url, **kwargs):
        if url.endswith("/gettoken"):
            token_requests.append(kwargs["params"])
            await asyncio.sleep(0)
            return {
                "errcode": 0,
                "access_token": f"cached-token-{len(token_requests)}",
                "expires_in": 7200,
            }
        user_requests.append(kwargs["params"])
        if kwargs["params"]["access_token"] in rejected_tokens:
            return {"errcode": 42001}
        return {"errcode": 0, "userid": "cache-user"}

    async def login(code, *, secret="cache-secret", target=connection):
        return await resolve_external_principal(
            target,
            secret,
            code,
            "https://app.example.com/callback",
            settings=settings(),
        )

    with (
        patch("redis.asyncio.Redis.from_url", return_value=cache),
        patch("app.adapters.identity.enterprise._request_json", new=request),
    ):
        for code in ("first-code", "second-code"):
            principal = await login(code)
            assert principal.subject_id == "cache-user"
        assert len(token_requests) == 1, (
            "Repeated logins must share the WeCom application token."
        )
        assert [item["code"] for item in user_requests] == ["first-code", "second-code"]
        assert len(cache.values) == 1
        key, encrypted = next(iter(cache.values.items()))
        assert "cache-secret" not in key and "cache-corp" not in key
        assert "cached-token" not in encrypted
        assert cache.expires_at[key] == 7140

        # The credential scope is shared by separate workspace connections.
        await login(
            "other-connection",
            target=EnterpriseIdentityConnection(
                provider="wecom", tenant_id="cache-corp", agent_id="1000003"
            ),
        )
        assert len(token_requests) == 1

        cache.now = 7140
        await asyncio.gather(*(login(f"concurrent-{i}") for i in range(8)))
        assert len(token_requests) == 2, (
            "Only one instance should refresh an expired token."
        )
        assert all(
            item["access_token"] == "cached-token-2" for item in user_requests[-8:]
        )

        await login("rotated-secret", secret="new-cache-secret")
        assert len(token_requests) == 3
        await login(
            "other-corp",
            target=EnterpriseIdentityConnection(
                provider="wecom", tenant_id="other-corp"
            ),
        )
        assert len(token_requests) == 4

        rejected_tokens.add("cached-token-2")
        await asyncio.gather(*(login(f"revoked-{i}") for i in range(8)))
        assert len(token_requests) == 5, "Revoked tokens should be refreshed once."
        assert user_requests[-1]["access_token"] == "cached-token-5"

        # Invalid cached ciphertext is replaced without using it as a bearer token.
        cache.values[key] = "damaged-ciphertext"
        await login("damaged-cache")
        assert len(token_requests) == 6

        for response in ({"errcode": 0, "openid": "external-user"}, {"errcode": 40029}):
            failed_request = AsyncMock(return_value=response)
            with patch(
                "app.adapters.identity.enterprise._request_json", new=failed_request
            ):
                try:
                    await login("invalid-code")
                except EnterpriseProviderError:
                    pass
                else:
                    raise AssertionError(
                        "External users and invalid codes must be rejected."
                    )
            assert failed_request.await_count == 1, (
                "One-time code failures must not be retried."
            )

        failed_request = AsyncMock(
            side_effect=[
                {"errcode": 40014},
                {"errcode": 0, "access_token": "still-invalid", "expires_in": 7200},
                {"errcode": 40014},
            ]
        )
        with patch(
            "app.adapters.identity.enterprise._request_json", new=failed_request
        ):
            try:
                await login("repeated-token-failure")
            except EnterpriseProviderError:
                pass
            else:
                raise AssertionError(
                    "Repeated token rejection must fail after one refresh."
                )
        assert failed_request.await_count == 3

        cache.get = AsyncMock(side_effect=OSError("cache offline"))
        failed_request = AsyncMock()
        with patch(
            "app.adapters.identity.enterprise._request_json", new=failed_request
        ):
            try:
                await login("cache-offline")
            except EnterpriseProviderError:
                pass
            else:
                raise AssertionError(
                    "Cache failures must not trigger an uncached token refresh."
                )
        failed_request.assert_not_awaited()

    for expiration in (None, True, 0, -1, "7200"):
        invalid_cache = _WeComRedis()
        with (
            patch("redis.asyncio.Redis.from_url", return_value=invalid_cache),
            patch(
                "app.adapters.identity.enterprise._request_json",
                new=AsyncMock(
                    return_value={
                        "errcode": 0,
                        "access_token": "invalid-expiration",
                        "expires_in": expiration,
                    }
                ),
            ),
        ):
            try:
                await login("invalid-expiration")
            except EnterpriseProviderError:
                pass
            else:
                raise AssertionError("Invalid token expiration must be rejected.")
        assert not invalid_cache.values


async def _test_wecom_error_diagnostics() -> None:
    connection = EnterpriseIdentityConnection(
        provider="wecom", tenant_id="diagnostic-corp", agent_id="1000002"
    )
    runtime_settings = settings()
    callback = "https://app.example.com/callback"

    async def failed_login(cache, response):
        with (
            patch("redis.asyncio.Redis.from_url", return_value=cache),
            patch(
                "app.adapters.identity.enterprise._request_json",
                new=AsyncMock(return_value=response),
            ),
        ):
            try:
                await resolve_external_principal(
                    connection,
                    "diagnostic-secret",
                    "diagnostic-code",
                    callback,
                    settings=runtime_settings,
                )
            except EnterpriseProviderError as exc:
                return exc
        raise AssertionError("The failed WeCom login should retain safe diagnostics.")

    credential_error = await failed_login(_WeComRedis(), {"errcode": 40013})
    assert credential_error.operation == "/cgi-bin/gettoken"
    assert credential_error.http_status == 200
    assert credential_error.provider_code == 40013
    assert "diagnostic-secret" not in str(credential_error)

    user_error_cache = _WeComRedis()
    credential_id = sha256(
        f"{connection.tenant_id}\0diagnostic-secret".encode()
    ).hexdigest()
    cache_key = f"nexaflow:enterprise-login:wecom-token:{credential_id}"
    user_error_cache.values[cache_key] = encrypt_secret(
        "diagnostic-access-token",
        application_secret_key(runtime_settings),
    )
    user_error_cache.expires_at[cache_key] = 7200
    authorization_error = await failed_login(user_error_cache, {"errcode": 40029})
    assert authorization_error.operation == "/cgi-bin/auth/getuserinfo"
    assert authorization_error.http_status == 200
    assert authorization_error.provider_code == 40029
    assert "diagnostic-access-token" not in str(authorization_error)

    member_error_cache = _WeComRedis()
    member_error_cache.values[cache_key] = encrypt_secret(
        "diagnostic-access-token",
        application_secret_key(runtime_settings),
    )
    member_error_cache.expires_at[cache_key] = 7200
    member_error = await failed_login(
        member_error_cache, {"errcode": 0, "openid": "external-contact"}
    )
    assert member_error.operation == "/cgi-bin/auth/getuserinfo"
    assert member_error.missing_field == "userid"
    assert member_error.provider_code == 0


def _start(client, connection_id: str, provider: str = "feishu") -> tuple[str, str]:
    response = client.get(
        f"/api/v1/auth/enterprise/{connection_id}/start?next=/app/agents",
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["state"][0]
    if provider == "feishu":
        assert "code_challenge" not in query
        assert "code_challenge_method" not in query
    return query["state"][0], response.headers["location"]


def _test_login_origin(client) -> None:
    canonical_origin = "http://127.0.0.1:3000"
    config = replace(client.app.state.settings, public_app_url=canonical_origin)
    principal = ExternalPrincipal(
        subject_id="origin-test-member",
        tenant_id="tenant_test",
        display_name="Origin Test",
    )
    with patch.object(client.app.state, "settings", config):
        for entry_origin in ("http://localhost:3000", canonical_origin):
            client.cookies.clear()
            discovered = client.get(
                f"{entry_origin}/api/v1/auth/enterprise/connections",
                headers={
                    "x-forwarded-host": "untrusted.example",
                    "x-forwarded-proto": "https",
                },
            )
            connection = next(
                item
                for item in discovered.json()["connections"]
                if item["provider"] == "feishu"
            )
            start_url = urljoin(entry_origin, connection["start_url"])
            started = client.get(
                start_url, params={"next": "/app/agents"}, follow_redirects=False
            )
            query = parse_qs(urlsplit(started.headers["location"]).query)
            resolver = AsyncMock(return_value=principal)
            with patch(
                "app.application.identity.enterprise.resolve_external_principal",
                new=resolver,
            ):
                completed = client.get(
                    query["redirect_uri"][0],
                    params={"state": query["state"][0], "code": "origin-test-code"},
                    follow_redirects=False,
                )
            assert urlsplit(completed.headers["location"]).path == "/auth/complete", (
                "Opening the login page at localhost must not lose the nonce on a 127.0.0.1 callback.",
                completed.headers["location"],
            )
            assert "nexaflow_sso_nonce=" in completed.request.headers.get("cookie", "")
            assert start_url.startswith(canonical_origin + "/api/v1/auth/enterprise/")
            assert "next=%2Fapp%2Fagents" in completed.headers["location"]
            assert resolver.await_count == 1

            # Canonicalizing the entry must preserve the browser binding check.
            started = client.get(start_url, follow_redirects=False)
            query = parse_qs(urlsplit(started.headers["location"]).query)
            client.cookies.clear()
            resolver.reset_mock()
            with patch(
                "app.application.identity.enterprise.resolve_external_principal",
                new=resolver,
            ):
                rejected = client.get(
                    query["redirect_uri"][0],
                    params={"state": query["state"][0], "code": "missing-nonce-code"},
                    follow_redirects=False,
                )
            assert "error=invalid_state" in rejected.headers["location"]
            resolver.assert_not_awaited()


def main() -> None:
    asyncio.run(_test_wecom_token_cache())
    asyncio.run(_test_wecom_error_diagnostics())
    assert safe_next_path("/app/agents") == "/app/agents"
    assert safe_next_path("https://evil.example") == "/app/apps"
    assert safe_next_path("//evil.example") == "/app/apps"
    assert safe_next_path("/\\evil.example") == "/app/apps"
    assert safe_next_path("/\t/evil.example") == "/app/apps"
    assert safe_next_path("/app/agents\\evil") == "/app/apps"
    assert safe_next_path("/" + "a" * 2048) == "/app/apps"
    _raises(Exception, lambda: validate_connection_fields("unknown", "id", "tenant", None))
    _raises(Exception, lambda: validate_connection_fields("feishu", " ", "tenant", None))
    validate_connection_fields("feishu", "client", None, None)
    _raises(Exception, lambda: validate_connection_fields("dingtalk", "client", None, None))
    _raises(Exception, lambda: validate_connection_fields("wecom", "id", "tenant", None))

    feishu = EnterpriseIdentityConnection(
        provider="feishu", client_id="fei-client", tenant_id="fei-tenant"
    )
    feishu_query = parse_qs(
        urlsplit(
            build_authorization_url(
                feishu, "https://app.example.com/callback", "state"
            )
        ).query
    )
    assert "code_challenge_method" not in feishu_query
    assert "code_challenge" not in feishu_query
    assert feishu_query["redirect_uri"] == ["https://app.example.com/callback"]
    with patch(
        "app.adapters.identity.enterprise._request_json",
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
    ) as feishu_requests:
        resolved = asyncio.run(
            resolve_external_principal(
                feishu,
                "secret",
                "code",
                "https://app.example.com/callback",
                settings=settings(),
            )
        )
    assert resolved.subject_id == "ou-feishu"
    assert resolved.email == "fei@example.com"
    assert feishu_requests.await_args_list[0].args == (
        "POST", "https://accounts.feishu.cn/oauth/v3/token"
    )
    assert feishu_requests.await_args_list[0].kwargs["data"] == {
        "grant_type": "authorization_code",
        "client_id": "fei-client",
        "client_secret": "secret",
        "code": "code",
        "redirect_uri": "https://app.example.com/callback",
    }
    assert feishu_requests.await_args_list[1].args == (
        "GET", "https://open.feishu.cn/open-apis/authen/v1/user_info"
    )
    delegated = AsyncMock(
        return_value=ExternalPrincipal(
            subject_id="ou-delegated",
            tenant_id="fei-tenant",
            display_name="Delegated User",
        )
    )
    with patch(
        "app.adapters.identity.enterprise.resolve_external_principal",
        new=delegated,
    ):
        resolved = asyncio.run(
            resolve_external_principal_via_port(
                feishu,
                "secret",
                "code",
                "https://app.example.com/callback",
                settings=settings(),
            )
        )
    assert resolved.subject_id == "ou-delegated"
    assert delegated.await_args is not None
    assert delegated.await_args.args == (
        feishu,
        "secret",
        "code",
        "https://app.example.com/callback",
    )
    assert delegated.await_args.kwargs["settings"] == settings()
    with patch(
        "app.adapters.identity.enterprise._request_json",
        new=AsyncMock(return_value={}),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    feishu,
                    "secret",
                    "code",
                    "https://app.example.com/callback",
                    settings=settings(),
                )
            ),
        )
    with patch(
        "app.adapters.identity.enterprise._request_json",
        new=AsyncMock(side_effect=[{"access_token": "token"}, {"data": []}]),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    feishu,
                    "secret",
                    "code",
                    "https://app.example.com/callback",
                    settings=settings(),
                )
            ),
        )

    unsupported = EnterpriseIdentityConnection(provider="unknown")
    _raises(
        EnterpriseProviderError,
        lambda: build_authorization_url(unsupported, "https://app.example.com", "state"),
    )
    _raises(
        EnterpriseProviderError,
        lambda: asyncio.run(
            resolve_external_principal(
                unsupported,
                "secret",
                "code",
                "https://app.example.com",
                settings=settings(),
            )
        ),
    )

    with patch(
        "app.adapters.identity.enterprise.httpx2.AsyncClient",
        return_value=_ProviderClient(_ProviderResponse({"ok": True})),
    ):
        assert asyncio.run(_request_json("GET", "https://provider.example")) == {"ok": True}
    with patch(
        "app.adapters.identity.enterprise.httpx2.AsyncClient",
        return_value=_ProviderClient(
            _ProviderResponse({}, chunks=[b"x" * (32 * 1024), b"x" * (33 * 1024)])
        ),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(_request_json("GET", "https://provider.example")),
        )
    with patch(
        "app.adapters.identity.enterprise.httpx2.AsyncClient",
        return_value=_ProviderClient(_ProviderResponse([])),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(_request_json("GET", "https://provider.example")),
        )
    with patch(
        "app.adapters.identity.enterprise.httpx2.AsyncClient",
        return_value=_ProviderClient(error=OSError("offline")),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(_request_json("GET", "https://provider.example")),
        )

    for http_status in (200, 400):
        with patch(
            "app.adapters.identity.enterprise.httpx2.AsyncClient",
            return_value=_ProviderClient(
                _ProviderResponse(
                    {"code": 20071, "error_description": "secret=must-not-be-recorded"},
                    status_code=http_status,
                )
            ),
        ):
            failure = _raises(
                EnterpriseProviderError,
                lambda: asyncio.run(
                    _request_json("POST", "https://accounts.feishu.cn/oauth/v3/token")
                ),
            )
        assert failure.http_status == http_status
        assert failure.provider_code == 20071
        assert failure.operation == "/oauth/v3/token"
        assert "must-not-be-recorded" not in str(failure)

    # WeCom's caller needs explicit token errors to trigger its bounded refresh.
    with patch(
        "app.adapters.identity.enterprise.httpx2.AsyncClient",
        return_value=_ProviderClient(_ProviderResponse({"errcode": 42001})),
    ):
        assert asyncio.run(
            _request_json("GET", "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo")
        ) == {"errcode": 42001}

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
                dingtalk, "https://app.example.com/callback", "state"
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
                wecom, "https://app.example.com/callback", "state"
            )
        ).query
    )
    assert wecom_query["appid"] == ["wecom-corp"]
    assert wecom_query["agentid"] == ["1000002"]

    with patch(
        "app.adapters.identity.enterprise._request_json",
        new=AsyncMock(
            side_effect=[
                {"accessToken": "token", "corpId": "ding-corp"},
                {"unionId": "union-id", "nick": "Ding User"},
            ]
        ),
    ):
        resolved = asyncio.run(
            resolve_external_principal(
                dingtalk,
                "secret",
                "code",
                "https://app.example.com/callback",
                settings=settings(),
            )
        )
    assert resolved.subject_id == "union-id"
    assert resolved.tenant_id == "ding-corp"
    with patch(
        "app.adapters.identity.enterprise._request_json",
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
                    dingtalk,
                    "secret",
                    "code",
                    "https://app.example.com/callback",
                    settings=settings(),
                )
            ),
        )

    with (
        patch("redis.asyncio.Redis.from_url", return_value=_WeComRedis()),
        patch(
            "app.adapters.identity.enterprise._request_json",
            new=AsyncMock(
                side_effect=[
                    {"errcode": 0, "access_token": "token", "expires_in": 7200},
                    {"errcode": 0, "userid": "wecom-user"},
                ]
            ),
        ),
    ):
        resolved = asyncio.run(
            resolve_external_principal(
                wecom,
                "secret",
                "code",
                "https://app.example.com/callback",
                settings=settings(),
            )
        )
    assert resolved.subject_id == "wecom-user"
    assert resolved.tenant_id == "wecom-corp"
    with (
        patch("redis.asyncio.Redis.from_url", return_value=_WeComRedis()),
        patch(
            "app.adapters.identity.enterprise._request_json",
            new=AsyncMock(return_value={"errcode": 40013}),
        ),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    wecom,
                    "secret",
                    "code",
                    "https://app.example.com/callback",
                    settings=settings(),
                )
            ),
        )
    with (
        patch("redis.asyncio.Redis.from_url", return_value=_WeComRedis()),
        patch(
            "app.adapters.identity.enterprise._request_json",
            new=AsyncMock(
                side_effect=[
                    {"errcode": 0, "access_token": "token", "expires_in": 7200},
                    {"errcode": 40029},
                ]
            ),
        ),
    ):
        _raises(
            EnterpriseProviderError,
            lambda: asyncio.run(
                resolve_external_principal(
                    wecom,
                    "secret",
                    "code",
                    "https://app.example.com/callback",
                    settings=settings(),
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
                "enabled": True,
            },
        )
        assert created.status_code == 200, created.text
        connection = created.json()
        assert connection["tenant_id"] == ""
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
                "start_url": (
                    f"{settings().public_app_url}/api/v1/auth/enterprise/{connection['id']}/start"
                ),
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
        assert parse_qs(urlsplit(authorize_url).query)["redirect_uri"] == [
            connection["callback_url"]
        ]
        principal = ExternalPrincipal(
            subject_id="ou_external",
            tenant_id="tenant_test",
            display_name="Enterprise User",
            email="untrusted@example.com",
        )
        assert client.post(
            f"/api/v1/auth/enterprise/{connection['id']}/qr"
        ).status_code == 404
        with patch(
            "app.application.identity.enterprise.resolve_external_principal",
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
            "app.application.identity.enterprise.resolve_external_principal",
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
            "app.application.identity.enterprise.resolve_external_principal",
            new=AsyncMock(
                side_effect=EnterpriseProviderError(
                    "must-not-log-this-provider-description",
                    operation="/oauth/v3/token",
                    http_status=400,
                    provider_code=20049,
                )
            ),
        ):
            provider_error = client.get(
                f"/api/v1/auth/enterprise/callback/feishu?state={provider_error_state}&code=code",
                follow_redirects=False,
            )
        assert "error=provider_error" in provider_error.headers["location"]
        failure_logs = client.get(
            "/api/v1/admin/system-logs?event=enterprise_identity.login_failed", headers=headers
        )
        assert failure_logs.status_code == 200, failure_logs.text
        assert failure_logs.json()[0]["details"] == {
            "provider": "feishu",
            "operation": "/oauth/v3/token",
            "http_status": 400,
            "provider_code": 20049,
            "missing_field": None,
        }
        assert "must-not-log" not in failure_logs.text

        wrong_tenant_state, _ = _start(client, connection["id"])
        with patch(
            "app.application.identity.enterprise.resolve_external_principal",
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
            "app.application.identity.enterprise.resolve_external_principal",
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
                "enabled": True,
            },
        )
        assert reconfigured.status_code == 200, reconfigured.text
        assert reconfigured.json()["tenant_id"] == ""
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
            "app.api.v1.identity.enterprise.enforce_enterprise_login_rate_limit",
            new=AsyncMock(side_effect=EnterpriseLoginRateLimitExceeded(7)),
        ):
            limited = client.get(
                f"/api/v1/auth/enterprise/{connection['id']}/start",
                follow_redirects=False,
            )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "7"
        with patch(
            "app.api.v1.identity.enterprise.enforce_enterprise_login_rate_limit",
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
                "enabled": True,
            },
        )
        assert reenabled.status_code == 200, reenabled.text
        disabled_identity_state, _ = _start(client, connection["id"])
        with patch(
            "app.application.identity.enterprise.resolve_external_principal",
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
        wecom_error_state, _ = _start(
            client, wecom_config.json()["id"], provider="wecom"
        )
        with patch(
            "app.application.identity.enterprise.resolve_external_principal",
            new=AsyncMock(
                side_effect=EnterpriseProviderError(
                    "raw provider text must not be logged",
                    operation="/cgi-bin/gettoken",
                    http_status=200,
                    provider_code=40013,
                )
            ),
        ):
            failed_wecom = client.get(
                "/api/v1/auth/enterprise/callback/wecom"
                f"?state={wecom_error_state}&code=wecom-error-code",
                follow_redirects=False,
            )
        assert "error=provider_error" in failed_wecom.headers["location"]
        wecom_failure_logs = client.get(
            "/api/v1/admin/system-logs?event=enterprise_identity.login_failed",
            headers=headers,
        )
        assert wecom_failure_logs.status_code == 200, wecom_failure_logs.text
        assert wecom_failure_logs.json()[0]["details"] == {
            "provider": "wecom",
            "operation": "/cgi-bin/gettoken",
            "http_status": 200,
            "provider_code": 40013,
            "missing_field": None,
        }
        assert "wecom-error-code" not in wecom_failure_logs.text
        assert "raw provider text" not in wecom_failure_logs.text

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
                "app.application.identity.enterprise.resolve_external_principal",
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
        _test_login_origin(client)


if __name__ == "__main__":
    main()

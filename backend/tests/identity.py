import asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from tests.support import (
    ADMIN_PASSWORD,
    BOOTSTRAP_ADMIN_PASSWORD,
    MANAGED_USER_INITIAL_PASSWORD,
    auth_headers,
    login,
    settings as test_settings,
    test_client,
)
from app.api.v1.endpoints.auth import REFRESH_TOKEN_COOKIE
from app.entities.user import RefreshSession
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.security import hash_refresh_token
from app.infrastructure import agent_rate_limit
from app.infrastructure.agent_rate_limit import LoginRateLimitExceeded
from app.infrastructure.session import get_session_factory
from app.infrastructure.system_log import SystemLog


async def get_system_log_events() -> list[str]:
    async with get_session_factory()() as db:
        result = await db.scalars(select(SystemLog.event))
        return list(result.all())


async def get_refresh_session(token: str) -> RefreshSession | None:
    async with get_session_factory()() as db:
        return await user_repository.get_active_refresh_session(
            db,
            hash_refresh_token(token),
            utc_now(),
        )


async def check_login_rate_limit() -> None:
    class FakeRedis:
        args: tuple = ()

        async def eval(self, *args):
            self.args = args
            return [11, 1, 42, 42]

    redis = FakeRedis()
    with patch.object(agent_rate_limit, "_rate_limit_redis", return_value=redis):
        try:
            await agent_rate_limit.enforce_login_rate_limit(
                test_settings(),
                "rate-limited-user",
                "203.0.113.10",
            )
            raise AssertionError("expected LoginRateLimitExceeded")
        except LoginRateLimitExceeded as exc:
            assert exc.retry_after == 42
    assert "rate-limited-user" not in repr(redis.args)


def main() -> None:
    asyncio.run(check_login_rate_limit())
    with test_client() as client:
        first_login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_ADMIN_PASSWORD},
        )
        assert first_login_response.status_code == 200, first_login_response.text
        first_login = first_login_response.json()
        admin_token = first_login["access_token"]
        assert first_login["expires_in"] == 24 * 60 * 60
        assert first_login["must_change_password"] is True
        assert "refresh_token" not in first_login
        refresh_token = client.cookies.get(REFRESH_TOKEN_COOKIE)
        assert refresh_token
        set_cookie = first_login_response.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "path=/api/v1/auth" in set_cookie
        stored_refresh_session = asyncio.run(get_refresh_session(refresh_token))
        assert stored_refresh_session is not None
        assert stored_refresh_session.token_hash == hash_refresh_token(refresh_token)
        assert stored_refresh_session.token_hash != refresh_token

        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["expires_in"] == 24 * 60 * 60

        logged_out = client.post("/api/v1/auth/logout")
        assert logged_out.status_code == 204, logged_out.text
        assert asyncio.run(get_refresh_session(refresh_token)) is None
        assert client.post("/api/v1/auth/refresh").status_code == 401

        blocked = client.get("/api/v1/workspaces", headers=auth_headers(admin_token))
        assert blocked.status_code == 403, blocked.text

        weak_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": "abcdef"},
        )
        assert weak_password.status_code == 422, weak_password.text

        missing_current_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": ADMIN_PASSWORD},
        )
        assert missing_current_password.status_code == 400, missing_current_password.text

        changed = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": BOOTSTRAP_ADMIN_PASSWORD,
                "new_password": ADMIN_PASSWORD,
            },
        )
        assert changed.status_code == 204, changed.text
        assert client.post("/api/v1/auth/refresh").status_code == 200

        rotated_password = "NexaFlow@123456."
        wrong_current_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": "Wrong@12345.",
                "new_password": rotated_password,
            },
        )
        assert wrong_current_password.status_code == 400, wrong_current_password.text

        repeated_change = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": ADMIN_PASSWORD,
                "new_password": rotated_password,
            },
        )
        assert repeated_change.status_code == 204, repeated_change.text

        same_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": rotated_password,
                "new_password": rotated_password,
            },
        )
        assert same_password.status_code == 400, same_password.text

        second_login = login(client, "admin", rotated_password)
        admin_token = second_login["access_token"]
        assert second_login["must_change_password"] is False

        failed_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Wrong@12345."},
        )
        assert failed_login.status_code == 401, failed_login.text

        with patch(
            "app.application.identity.enforce_login_rate_limit",
            new=AsyncMock(side_effect=LoginRateLimitExceeded(42)),
        ):
            limited_login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": rotated_password},
            )
        assert limited_login.status_code == 429, limited_login.text
        assert limited_login.headers["retry-after"] == "42"

        users = client.get("/api/v1/admin/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        admin_user = users.json()[0]
        assert admin_user["username"] == "admin"
        assert admin_user["is_active"] is True
        assert admin_user["created_at"]
        admin_user_id = admin_user["id"]

        created_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "analyst",
                "email": "analyst@example.com",
                "name": "Analyst",
            },
        )
        assert created_user.status_code == 201, created_user.text
        payload = created_user.json()
        assert payload["initial_password"] == MANAGED_USER_INITIAL_PASSWORD
        assert payload["user"]["username"] == "analyst"
        assert payload["user"]["workspaces"] == []
        analyst_id = payload["user"]["id"]
        analyst_login = login(client, "analyst", payload["initial_password"])
        assert analyst_login["must_change_password"] is True
        analyst_token = analyst_login["access_token"]
        analyst_refresh_token = client.cookies.get(REFRESH_TOKEN_COOKIE)
        assert analyst_refresh_token

        analyst_self_password = "AnalystSelf@123"
        analyst_missing_current = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(analyst_token),
            json={"new_password": analyst_self_password},
        )
        assert analyst_missing_current.status_code == 400, analyst_missing_current.text
        analyst_wrong_current = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(analyst_token),
            json={
                "current_password": "Wrong@12345.",
                "new_password": analyst_self_password,
            },
        )
        assert analyst_wrong_current.status_code == 400, analyst_wrong_current.text
        analyst_self_changed = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(analyst_token),
            json={
                "current_password": payload["initial_password"],
                "new_password": analyst_self_password,
            },
        )
        assert analyst_self_changed.status_code == 204, analyst_self_changed.text

        updated_user = client.patch(
            f"/api/v1/admin/users/{analyst_id}",
            headers=auth_headers(admin_token),
            json={"name": "Data Analyst", "is_active": True},
        )
        assert updated_user.status_code == 200, updated_user.text
        assert updated_user.json()["name"] == "Data Analyst"

        analyst_changed_password = "AnalystPass@123"
        change_managed_password = client.post(
            f"/api/v1/admin/users/{analyst_id}/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": analyst_changed_password},
        )
        assert change_managed_password.status_code == 200, change_managed_password.text
        assert change_managed_password.json()["must_change_password"] is False
        assert client.post("/api/v1/auth/refresh").status_code == 401
        assert asyncio.run(get_refresh_session(analyst_refresh_token)) is None
        analyst_changed_login = login(client, "analyst", analyst_changed_password)
        assert analyst_changed_login["must_change_password"] is False

        self_disable = client.patch(
            f"/api/v1/admin/users/{admin_user_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert self_disable.status_code == 400, self_disable.text

        self_delete = client.delete(
            f"/api/v1/admin/users/{admin_user_id}",
            headers=auth_headers(admin_token),
        )
        assert self_delete.status_code == 400, self_delete.text

        deleted_user = client.delete(
            f"/api/v1/admin/users/{analyst_id}",
            headers=auth_headers(admin_token),
        )
        assert deleted_user.status_code == 204, deleted_user.text

        users = client.get("/api/v1/admin/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        assert all(item["id"] != analyst_id for item in users.json())
        deleted_login = client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": analyst_changed_password},
        )
        assert deleted_login.status_code == 401, deleted_login.text

        audit_logs = client.get("/api/v1/admin/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "user.create" in actions
        assert "user.update" in actions
        assert "user.change_password" in actions
        assert "user.delete" in actions

        events = asyncio.run(get_system_log_events())
        assert "auth.login_failed" in events


if __name__ == "__main__":
    main()

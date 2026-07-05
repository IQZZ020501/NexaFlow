import asyncio

from sqlalchemy import select

from nexaflow.testing import (
    ADMIN_PASSWORD,
    BOOTSTRAP_ADMIN_PASSWORD,
    auth_headers,
    login,
    test_client,
)
from nexaflow.db.session import get_session_factory
from nexaflow.system_logs.models import SystemLog


async def get_system_log_events() -> list[str]:
    async with get_session_factory()() as db:
        result = await db.scalars(select(SystemLog.event))
        return list(result.all())


def main() -> None:
    with test_client() as client:
        first_login = login(client, "admin", BOOTSTRAP_ADMIN_PASSWORD)
        admin_token = first_login["access_token"]
        assert first_login["must_change_password"] is True

        blocked = client.get("/workspaces", headers=auth_headers(admin_token))
        assert blocked.status_code == 403, blocked.text

        weak_password = client.post(
            "/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": "abcdef"},
        )
        assert weak_password.status_code == 422, weak_password.text

        changed = client.post(
            "/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": ADMIN_PASSWORD},
        )
        assert changed.status_code == 204, changed.text

        rotated_password = "NexaFlow@123456."
        wrong_current_password = client.post(
            "/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": "Wrong@12345.",
                "new_password": rotated_password,
            },
        )
        assert wrong_current_password.status_code == 400, wrong_current_password.text

        repeated_change = client.post(
            "/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": ADMIN_PASSWORD,
                "new_password": rotated_password,
            },
        )
        assert repeated_change.status_code == 204, repeated_change.text

        same_password = client.post(
            "/auth/change-password",
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
            "/auth/login",
            json={"username": "admin", "password": "Wrong@12345."},
        )
        assert failed_login.status_code == 401, failed_login.text

        users = client.get("/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        admin_user = users.json()[0]
        assert admin_user["username"] == "admin"
        assert admin_user["is_active"] is True
        assert admin_user["created_at"]
        admin_user_id = admin_user["id"]

        created_user = client.post(
            "/users",
            headers=auth_headers(admin_token),
            json={
                "username": "analyst",
                "email": "analyst@example.com",
                "name": "Analyst",
            },
        )
        assert created_user.status_code == 201, created_user.text
        payload = created_user.json()
        assert payload["initial_password"]
        assert payload["user"]["username"] == "analyst"
        assert payload["user"]["workspaces"] == []
        analyst_id = payload["user"]["id"]

        updated_user = client.patch(
            f"/users/{analyst_id}",
            headers=auth_headers(admin_token),
            json={"name": "Data Analyst", "is_active": True},
        )
        assert updated_user.status_code == 200, updated_user.text
        assert updated_user.json()["name"] == "Data Analyst"

        reset_password = client.post(
            f"/users/{analyst_id}/reset-password",
            headers=auth_headers(admin_token),
        )
        assert reset_password.status_code == 200, reset_password.text
        assert reset_password.json()["initial_password"]
        assert reset_password.json()["user"]["must_change_password"] is True

        self_disable = client.patch(
            f"/users/{admin_user_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert self_disable.status_code == 400, self_disable.text

        deleted_user = client.delete(
            f"/users/{analyst_id}",
            headers=auth_headers(admin_token),
        )
        assert deleted_user.status_code == 204, deleted_user.text

        users = client.get("/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        analyst = next(item for item in users.json() if item["id"] == analyst_id)
        assert analyst["is_active"] is False

        audit_logs = client.get("/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "user.create" in actions
        assert "user.update" in actions
        assert "user.reset_password" in actions
        assert "user.deactivate" in actions

        events = asyncio.run(get_system_log_events())
        assert "auth.login_failed" in events


if __name__ == "__main__":
    main()

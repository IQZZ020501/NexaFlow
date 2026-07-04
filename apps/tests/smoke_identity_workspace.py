import asyncio

from fastapi.testclient import TestClient

from nexaflow.core.config import Settings
from nexaflow.db.base import Base
from nexaflow.db.session import get_engine
from nexaflow.main import create_app

BOOTSTRAP_ADMIN_PASSWORD = "NexaFlow@123."


def auth_headers(token: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if workspace_id:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def main() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret-for-nexaflow-smoke-suite",
        bootstrap_admin_username="admin",
        bootstrap_admin_email="admin@nexaflow.local",
        bootstrap_admin_name="NexaFlow Admin",
        bootstrap_admin_password=BOOTSTRAP_ADMIN_PASSWORD,
        default_workspace_name="Default Workspace",
        default_workspace_slug="default",
        default_team_name="Default Team",
        default_team_slug="default",
        environment="test",
    )
    app = create_app(settings)

    async def create_schema() -> None:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())

    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"username_or_email": "admin", "password": BOOTSTRAP_ADMIN_PASSWORD},
        )
        assert login.status_code == 200, login.text
        admin_token = login.json()["access_token"]
        assert login.json()["must_change_password"] is True

        blocked = client.get("/workspaces", headers=auth_headers(admin_token))
        assert blocked.status_code == 403, blocked.text

        me = client.get("/auth/me", headers=auth_headers(admin_token))
        assert me.status_code == 200, me.text
        default_workspace_id = me.json()["memberships"][0]["workspace_id"]

        weak_password = client.post(
            "/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": "abcdef"},
        )
        assert weak_password.status_code == 422, weak_password.text

        changed = client.post(
            "/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": "NexaFlow@12345."},
        )
        assert changed.status_code == 204, changed.text

        repeated_change = client.post(
            "/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": "NexaFlow@123456."},
        )
        assert repeated_change.status_code == 400, repeated_change.text

        login = client.post(
            "/auth/login",
            json={"username_or_email": "admin", "password": "NexaFlow@12345."},
        )
        assert login.status_code == 200, login.text
        admin_token = login.json()["access_token"]
        assert login.json()["must_change_password"] is False

        workspaces = client.get("/workspaces", headers=auth_headers(admin_token))
        assert workspaces.status_code == 200, workspaces.text
        assert len(workspaces.json()) == 1

        default_teams = client.get(
            "/teams",
            headers=auth_headers(admin_token, default_workspace_id),
        )
        assert default_teams.status_code == 200, default_teams.text
        assert [item["slug"] for item in default_teams.json()] == ["default"]
        default_team_id = default_teams.json()[0]["id"]

        users = client.get("/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        users_payload = users.json()
        assert [item["username"] for item in users_payload] == ["admin"]
        assert users_payload[0]["is_active"] is True
        assert users_payload[0]["created_at"]
        assert users_payload[0]["workspaces"] == [
            {
                "id": default_workspace_id,
                "name": "Default Workspace",
                "slug": "default",
                "is_default": True,
                "role": "owner",
            }
        ]
        assert users_payload[0]["teams"] == [
            {
                "id": default_team_id,
                "workspace_id": default_workspace_id,
                "name": "Default Team",
                "slug": "default",
                "is_default": True,
                "role": "admin",
            }
        ]
        admin_user_id = users_payload[0]["id"]

        created = client.post(
            "/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "slug": "research",
                "admin": {
                    "username": "research-admin",
                    "email": "research-admin@example.com",
                    "name": "Research Admin",
                },
            },
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        research_workspace_id = payload["workspace"]["id"]
        temp_password = payload["admin_initial_password"]
        assert payload["admin_created"] is True
        assert temp_password

        research_login = client.post(
            "/auth/login",
            json={
                "username_or_email": "research-admin",
                "password": temp_password,
            },
        )
        assert research_login.status_code == 200, research_login.text
        research_token = research_login.json()["access_token"]
        assert research_login.json()["must_change_password"] is True

        changed = client.post(
            "/auth/change-password",
            headers=auth_headers(research_token),
            json={"new_password": "Research@12345."},
        )
        assert changed.status_code == 204, changed.text

        research_login = client.post(
            "/auth/login",
            json={
                "username_or_email": "research-admin",
                "password": "Research@12345.",
            },
        )
        assert research_login.status_code == 200, research_login.text
        research_token = research_login.json()["access_token"]

        users_denied = client.get("/users", headers=auth_headers(research_token))
        assert users_denied.status_code == 403, users_denied.text

        users_patch_denied = client.patch(
            f"/users/{admin_user_id}",
            headers=auth_headers(research_token),
            json={"name": "Blocked"},
        )
        assert users_patch_denied.status_code == 403, users_patch_denied.text

        denied = client.get(
            "/teams",
            headers=auth_headers(research_token, default_workspace_id),
        )
        assert denied.status_code == 403, denied.text

        empty_teams = client.get(
            "/teams",
            headers=auth_headers(research_token, research_workspace_id),
        )
        assert empty_teams.status_code == 200, empty_teams.text
        assert empty_teams.json() == []

        team = client.post(
            "/teams",
            headers=auth_headers(research_token, research_workspace_id),
            json={"name": "Applied AI", "slug": "applied-ai"},
        )
        assert team.status_code == 201, team.text
        assert team.json()["workspace_id"] == research_workspace_id
        research_team_id = team.json()["id"]

        create_user_denied = client.post(
            "/users",
            headers=auth_headers(research_token),
            json={
                "username": "blocked-user",
                "email": "blocked-user@example.com",
                "name": "Blocked User",
            },
        )
        assert create_user_denied.status_code == 403, create_user_denied.text

        mismatched_team_user = client.post(
            "/users",
            headers=auth_headers(admin_token),
            json={
                "username": "wrong-team-user",
                "email": "wrong-team-user@example.com",
                "name": "Wrong Team User",
                "workspace_id": research_workspace_id,
                "team_ids": [default_team_id],
            },
        )
        assert mismatched_team_user.status_code == 422, mismatched_team_user.text

        created_user = client.post(
            "/users",
            headers=auth_headers(admin_token),
            json={
                "username": "analyst",
                "email": "analyst@example.com",
                "name": "Analyst",
                "workspace_id": research_workspace_id,
                "team_ids": [research_team_id],
            },
        )
        assert created_user.status_code == 201, created_user.text
        assert created_user.json()["initial_password"]
        assert created_user.json()["user"]["workspaces"] == [
            {
                "id": research_workspace_id,
                "name": "Research Workspace",
                "slug": "research",
                "is_default": False,
                "role": "member",
            }
        ]
        assert created_user.json()["user"]["teams"] == [
            {
                "id": research_team_id,
                "workspace_id": research_workspace_id,
                "name": "Applied AI",
                "slug": "applied-ai",
                "is_default": False,
                "role": "member",
            }
        ]

        users = client.get("/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        research_user = next(
            item for item in users.json() if item["username"] == "research-admin"
        )
        research_user_id = research_user["id"]
        assert research_user["workspaces"] == [
            {
                "id": research_workspace_id,
                "name": "Research Workspace",
                "slug": "research",
                "is_default": False,
                "role": "owner",
            }
        ]
        assert research_user["teams"] == []

        updated_user = client.patch(
            f"/users/{research_user_id}",
            headers=auth_headers(admin_token),
            json={"name": "Research Owner", "is_active": True},
        )
        assert updated_user.status_code == 200, updated_user.text
        assert updated_user.json()["name"] == "Research Owner"
        assert updated_user.json()["workspaces"][0]["id"] == research_workspace_id
        assert updated_user.json()["teams"] == []

        reset_password = client.post(
            f"/users/{research_user_id}/reset-password",
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
            f"/users/{research_user_id}",
            headers=auth_headers(admin_token),
        )
        assert deleted_user.status_code == 204, deleted_user.text

        users = client.get("/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        research_user = next(
            item for item in users.json() if item["id"] == research_user_id
        )
        assert research_user["is_active"] is False


if __name__ == "__main__":
    main()

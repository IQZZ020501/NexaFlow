import asyncio

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from nexaflow.db.session import get_session_factory
from nexaflow.identity.models import User
from nexaflow.teams.models import TeamMembership
from nexaflow.testing import (
    RESEARCH_PASSWORD,
    activate_admin,
    activate_user,
    auth_headers,
    test_client,
)


def teams_url(workspace_id: str, suffix: str = "") -> str:
    return f"/workspaces/{workspace_id}/teams{suffix}"


async def assert_cross_workspace_team_membership_denied(
    default_workspace_id: str,
    team_id: str,
) -> None:
    async with get_session_factory()() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        user = await db.scalar(select(User).where(User.username == "research-admin"))
        assert user is not None

        db.add(
            TeamMembership(
                workspace_id=default_workspace_id,
                team_id=team_id,
                user_id=user.id,
                role="member",
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return

    raise AssertionError("Cross-workspace team membership was allowed.")


def main() -> None:
    with test_client() as client:
        admin_token, default_workspace_id = activate_admin(client)

        default_teams = client.get(
            teams_url(default_workspace_id),
            headers=auth_headers(admin_token),
        )
        assert default_teams.status_code == 200, default_teams.text
        assert [item["slug"] for item in default_teams.json()] == ["default"]
        default_team_id = default_teams.json()[0]["id"]

        created_workspace = client.post(
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
        assert created_workspace.status_code == 201, created_workspace.text
        research_workspace_id = created_workspace.json()["workspace"]["id"]
        temp_password = created_workspace.json()["admin_initial_password"]
        assert temp_password

        admin_research_teams = client.get(
            teams_url(research_workspace_id),
            headers=auth_headers(admin_token),
        )
        assert admin_research_teams.status_code == 403, admin_research_teams.text

        research_token = activate_user(
            client,
            "research-admin",
            temp_password,
            RESEARCH_PASSWORD,
        )

        denied = client.get(
            teams_url(default_workspace_id),
            headers=auth_headers(research_token),
        )
        assert denied.status_code == 403, denied.text

        empty_teams = client.get(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
        )
        assert empty_teams.status_code == 200, empty_teams.text
        assert empty_teams.json() == []

        team = client.post(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"name": "Applied AI", "slug": "applied-ai"},
        )
        assert team.status_code == 201, team.text
        assert team.json()["workspace_id"] == research_workspace_id
        team_id = team.json()["id"]
        asyncio.run(assert_cross_workspace_team_membership_denied(default_workspace_id, team_id))

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

        updated = client.patch(
            teams_url(research_workspace_id, f"/{team_id}"),
            headers=auth_headers(research_token),
            json={"name": "Applied Research", "slug": "applied-research"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["slug"] == "applied-research"

        archived = client.patch(
            teams_url(research_workspace_id, f"/{team_id}"),
            headers=auth_headers(research_token),
            json={"status": "archived"},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"

        restored = client.patch(
            teams_url(research_workspace_id, f"/{team_id}"),
            headers=auth_headers(research_token),
            json={"status": "active"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"

        delete_default = client.delete(
            teams_url(default_workspace_id, f"/{default_team_id}"),
            headers=auth_headers(admin_token),
        )
        assert delete_default.status_code == 400, delete_default.text

        deleted = client.delete(
            teams_url(research_workspace_id, f"/{team_id}"),
            headers=auth_headers(research_token),
        )
        assert deleted.status_code == 204, deleted.text

        teams = client.get(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
        )
        assert teams.status_code == 200, teams.text
        assert teams.json() == []

        audit_logs = client.get("/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        logs = audit_logs.json()
        actions = [item["action"] for item in logs]
        assert "team.archive" in actions
        assert "team.delete" in actions
        assert all(
            item["workspace_id"] == research_workspace_id
            for item in logs
            if item["resource_type"] == "team" and item["resource_id"] == team_id
        )


if __name__ == "__main__":
    main()

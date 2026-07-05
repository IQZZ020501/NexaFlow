from nexaflow.testing import (
    RESEARCH_PASSWORD,
    activate_admin,
    activate_user,
    auth_headers,
    test_client,
)


def main() -> None:
    with test_client() as client:
        admin_token, default_workspace_id = activate_admin(client)

        default_teams = client.get(
            "/teams",
            headers=auth_headers(admin_token, default_workspace_id),
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

        research_token = activate_user(
            client,
            "research-admin",
            temp_password,
            RESEARCH_PASSWORD,
        )

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
        team_id = team.json()["id"]

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
            f"/teams/{team_id}",
            headers=auth_headers(research_token, research_workspace_id),
            json={"name": "Applied Research", "slug": "applied-research"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["slug"] == "applied-research"

        archived = client.patch(
            f"/teams/{team_id}",
            headers=auth_headers(research_token, research_workspace_id),
            json={"status": "archived"},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"

        restored = client.patch(
            f"/teams/{team_id}",
            headers=auth_headers(research_token, research_workspace_id),
            json={"status": "active"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"

        delete_default = client.delete(
            f"/teams/{default_team_id}",
            headers=auth_headers(admin_token, default_workspace_id),
        )
        assert delete_default.status_code == 400, delete_default.text

        deleted = client.delete(
            f"/teams/{team_id}",
            headers=auth_headers(research_token, research_workspace_id),
        )
        assert deleted.status_code == 204, deleted.text

        teams = client.get(
            "/teams",
            headers=auth_headers(research_token, research_workspace_id),
        )
        assert teams.status_code == 200, teams.text
        assert teams.json() == []

        audit_logs = client.get("/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "team.archive" in actions
        assert "team.delete" in actions


if __name__ == "__main__":
    main()

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

        workspaces = client.get("/workspaces", headers=auth_headers(admin_token))
        assert workspaces.status_code == 200, workspaces.text
        assert [item["slug"] for item in workspaces.json()] == ["default"]

        default_workspace = client.get(
            f"/workspaces/{default_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert default_workspace.status_code == 200, default_workspace.text
        assert default_workspace.json()["is_default"] is True

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

        research_token = activate_user(
            client,
            "research-admin",
            temp_password,
            RESEARCH_PASSWORD,
        )

        denied_default = client.get(
            f"/workspaces/{default_workspace_id}",
            headers=auth_headers(research_token),
        )
        assert denied_default.status_code == 403, denied_default.text

        research_workspace = client.get(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(research_token),
        )
        assert research_workspace.status_code == 200, research_workspace.text
        assert research_workspace.json()["slug"] == "research"

        updated = client.patch(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(research_token),
            json={"name": "Research Lab", "slug": "research-lab"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["slug"] == "research-lab"

        delete_default = client.delete(
            f"/workspaces/{default_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert delete_default.status_code == 400, delete_default.text


if __name__ == "__main__":
    main()

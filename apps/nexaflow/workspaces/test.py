from nexaflow.testing import (
    RESEARCH_PASSWORD,
    activate_admin,
    activate_user,
    auth_headers,
    test_client,
)


def members_url(workspace_id: str, suffix: str = "") -> str:
    return f"/workspaces/{workspace_id}/members{suffix}"


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

        members_denied = client.get(
            members_url(research_workspace_id),
            headers=auth_headers(admin_token),
        )
        assert members_denied.status_code == 403, members_denied.text

        members = client.get(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
        )
        assert members.status_code == 200, members.text
        assert [(item["user"]["username"], item["role"]) for item in members.json()] == [
            ("research-admin", "admin")
        ]
        research_admin_id = members.json()[0]["user"]["id"]

        global_users_denied = client.get("/users", headers=auth_headers(research_token))
        assert global_users_denied.status_code == 403, global_users_denied.text

        created_workspace_user = client.post(
            members_url(research_workspace_id, "/users"),
            headers=auth_headers(research_token),
            json={
                "username": "research-member",
                "email": "research-member@example.com",
                "name": "Research Member",
            },
        )
        assert created_workspace_user.status_code == 201, created_workspace_user.text
        workspace_user_payload = created_workspace_user.json()
        assert workspace_user_payload["user"]["is_global_admin"] is False
        assert workspace_user_payload["user"]["workspaces"] == [
            {
                "id": research_workspace_id,
                "name": "Research Workspace",
                "slug": "research",
                "is_default": False,
                "role": "member",
            }
        ]

        disable_last_admin = client.patch(
            f"/users/{research_admin_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert disable_last_admin.status_code == 400, disable_last_admin.text

        delete_last_admin_user = client.delete(
            f"/users/{research_admin_id}",
            headers=auth_headers(admin_token),
        )
        assert delete_last_admin_user.status_code == 400, delete_last_admin_user.text

        created_member_user = client.post(
            "/users",
            headers=auth_headers(admin_token),
            json={
                "username": "workspace-member",
                "email": "workspace-member@example.com",
                "name": "Workspace Member",
            },
        )
        assert created_member_user.status_code == 201, created_member_user.text
        member_user_id = created_member_user.json()["user"]["id"]

        invalid_owner_role = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "owner"},
        )
        assert invalid_owner_role.status_code == 422, invalid_owner_role.text

        added_member = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "admin"},
        )
        assert added_member.status_code == 201, added_member.text
        assert added_member.json()["role"] == "admin"

        duplicate_member = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "member"},
        )
        assert duplicate_member.status_code == 409, duplicate_member.text

        updated_member = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(research_token),
            json={"role": "member"},
        )
        assert updated_member.status_code == 200, updated_member.text
        assert updated_member.json()["role"] == "member"

        demote_last_admin = client.patch(
            members_url(research_workspace_id, f"/{research_admin_id}"),
            headers=auth_headers(research_token),
            json={"role": "member"},
        )
        assert demote_last_admin.status_code == 400, demote_last_admin.text

        removed_member = client.delete(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(research_token),
        )
        assert removed_member.status_code == 204, removed_member.text

        remove_last_admin = client.delete(
            members_url(research_workspace_id, f"/{research_admin_id}"),
            headers=auth_headers(research_token),
        )
        assert remove_last_admin.status_code == 400, remove_last_admin.text

        workspace_admin_update_denied = client.patch(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(research_token),
            json={"name": "Research Lab", "slug": "research-lab"},
        )
        assert workspace_admin_update_denied.status_code == 403, workspace_admin_update_denied.text

        updated = client.patch(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"name": "Research Lab", "slug": "research-lab"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["slug"] == "research-lab"

        archived = client.patch(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "archived"},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"

        restored = client.patch(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "active"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"

        workspace_audit_denied = client.get(
            f"/workspaces/{research_workspace_id}/audit-logs",
            headers=auth_headers(admin_token),
        )
        assert workspace_audit_denied.status_code == 403, workspace_audit_denied.text

        workspace_audit = client.get(
            f"/workspaces/{research_workspace_id}/audit-logs",
            headers=auth_headers(research_token),
        )
        assert workspace_audit.status_code == 200, workspace_audit.text
        workspace_audit_logs = workspace_audit.json()
        assert workspace_audit_logs
        assert all(
            item["workspace_id"] == research_workspace_id
            for item in workspace_audit_logs
        )

        delete_default = client.delete(
            f"/workspaces/{default_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert delete_default.status_code == 400, delete_default.text

        deleted = client.delete(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert deleted.status_code == 204, deleted.text

        missing = client.get(
            f"/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert missing.status_code == 404, missing.text

        audit_logs = client.get("/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        logs = audit_logs.json()
        actions = [item["action"] for item in logs]
        assert "workspace.archive" in actions
        assert "workspace.delete" in actions
        assert "workspace.member.add" in actions
        assert "workspace.member.update" in actions
        assert "workspace.member.remove" in actions
        assert all(
            item["workspace_id"] == research_workspace_id
            for item in logs
            if item["resource_type"] == "workspace"
            and item["resource_id"] == research_workspace_id
        )


if __name__ == "__main__":
    main()

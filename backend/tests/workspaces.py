from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    test_client,
)


def members_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/members{suffix}"


def main() -> None:
    with test_client() as client:
        admin_token, default_workspace_id = activate_admin(client)

        workspaces = client.get("/api/v1/workspaces", headers=auth_headers(admin_token))
        assert workspaces.status_code == 200, workspaces.text
        assert [item["name"] for item in workspaces.json()] == ["Default Workspace"]

        default_workspace = client.get(
            f"/api/v1/workspaces/{default_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert default_workspace.status_code == 200, default_workspace.text
        assert default_workspace.json()["is_default"] is True

        missing_admin = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Missing Admin Workspace",
                "admin_user_id": "missing-user",
            },
        )
        assert missing_admin.status_code == 404, missing_admin.text

        inactive_admin_id, _ = create_active_user(
            client,
            admin_token,
            "inactive-admin",
        )
        disabled_admin = client.patch(
            f"/api/v1/admin/users/{inactive_admin_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert disabled_admin.status_code == 200, disabled_admin.text
        inactive_admin = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Inactive Admin Workspace",
                "admin_user_id": inactive_admin_id,
            },
        )
        assert inactive_admin.status_code == 400, inactive_admin.text

        research_admin_id, research_token = create_active_user(
            client,
            admin_token,
            "research-admin",
        )
        users_before = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
        ).json()

        created = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "description": "研究工作空间",
                "admin_user_id": research_admin_id,
            },
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        research_workspace_id = payload["workspace"]["id"]
        assert payload["admin_user"]["id"] == research_admin_id
        assert payload["workspace"]["description"] == "研究工作空间"
        users_after = client.get(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
        ).json()
        assert [user["id"] for user in users_after] == [
            user["id"] for user in users_before
        ]

        denied_default = client.get(
            f"/api/v1/workspaces/{default_workspace_id}",
            headers=auth_headers(research_token),
        )
        assert denied_default.status_code == 403, denied_default.text

        research_workspace = client.get(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(research_token),
        )
        assert research_workspace.status_code == 200, research_workspace.text
        assert research_workspace.json()["description"] == "研究工作空间"

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
        assert members.json()[0]["user"]["id"] == research_admin_id

        global_users_denied = client.get("/api/v1/admin/users", headers=auth_headers(research_token))
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
        user_workspace = workspace_user_payload["user"]["workspaces"][0]
        assert user_workspace["id"] == research_workspace_id
        assert user_workspace["name"] == "Research Workspace"
        assert user_workspace["is_default"] is False
        assert user_workspace["role"] == "member"

        disable_last_admin = client.patch(
            f"/api/v1/admin/users/{research_admin_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert disable_last_admin.status_code == 400, disable_last_admin.text

        delete_last_admin_user = client.delete(
            f"/api/v1/admin/users/{research_admin_id}",
            headers=auth_headers(admin_token),
        )
        assert delete_last_admin_user.status_code == 400, delete_last_admin_user.text

        created_member_user = client.post(
            "/api/v1/admin/users",
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
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(research_token),
            json={"name": "Research Lab", "description": "研究实验室"},
        )
        assert workspace_admin_update_denied.status_code == 403, workspace_admin_update_denied.text

        updated = client.patch(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"name": "Research Lab", "description": "研究实验室"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["description"] == "研究实验室"

        archived = client.patch(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "archived"},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"

        restored = client.patch(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "active"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"

        workspace_audit_denied = client.get(
            f"/api/v1/workspaces/{research_workspace_id}/audit-logs",
            headers=auth_headers(admin_token),
        )
        assert workspace_audit_denied.status_code == 403, workspace_audit_denied.text

        workspace_audit = client.get(
            f"/api/v1/workspaces/{research_workspace_id}/audit-logs",
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
            f"/api/v1/workspaces/{default_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert delete_default.status_code == 400, delete_default.text

        deleted = client.delete(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert deleted.status_code == 204, deleted.text

        missing = client.get(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert missing.status_code == 404, missing.text

        audit_logs = client.get("/api/v1/admin/audit-logs", headers=auth_headers(admin_token))
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

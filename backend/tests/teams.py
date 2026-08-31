import asyncio

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.session import get_session_factory
from app.shareddomain.platform.models import User
from app.shareddomain.platform.models import TeamMembership
from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    test_client,
)


def teams_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/teams{suffix}"


def members_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/members{suffix}"


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

        admin_me = client.get(
            "/api/v1/auth/me",
            headers=auth_headers(admin_token),
        )
        assert admin_me.status_code == 200, admin_me.text
        workspace_team = client.post(
            teams_url(default_workspace_id),
            headers=auth_headers(admin_token),
            json={
                "name": "Workspace Team",
                "admin_user_id": admin_me.json()["user"]["id"],
            },
        )
        assert workspace_team.status_code == 201, workspace_team.text
        default_team_id = workspace_team.json()["id"]

        research_admin_id, research_token = create_active_user(
            client,
            admin_token,
            "research-admin",
        )
        created_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "description": "研究工作空间",
                "admin_user_id": research_admin_id,
            },
        )
        assert created_workspace.status_code == 201, created_workspace.text
        research_workspace_id = created_workspace.json()["workspace"]["id"]

        admin_research_teams = client.get(
            teams_url(research_workspace_id),
            headers=auth_headers(admin_token),
        )
        assert admin_research_teams.status_code == 200, admin_research_teams.text
        assert admin_research_teams.json() == []

        denied = client.get(
            teams_url(default_workspace_id),
            headers=auth_headers(research_token),
        )
        assert denied.status_code == 404, denied.text

        empty_teams = client.get(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
        )
        assert empty_teams.status_code == 200, empty_teams.text
        assert empty_teams.json() == []

        missing_admin = client.post(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"name": "No Admin Team", "description": "缺少管理员"},
        )
        assert missing_admin.status_code == 422, missing_admin.text

        outsider_id, _ = create_active_user(client, admin_token, "team-outsider")
        outsider_admin = client.post(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={
                "name": "Outsider Team",
                "description": "非成员管理员",
                "admin_user_id": outsider_id,
            },
        )
        assert outsider_admin.status_code == 404, outsider_admin.text

        team = client.post(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={
                "name": "Applied AI",
                "description": "应用智能团队",
                "admin_user_id": research_admin_id,
            },
        )
        assert team.status_code == 201, team.text
        assert team.json()["workspace_id"] == research_workspace_id
        assert team.json()["description"] == "应用智能团队"
        team_id = team.json()["id"]
        research_me = client.get(
            "/api/v1/auth/me",
            headers=auth_headers(research_token),
        )
        assert research_me.status_code == 200, research_me.text
        assert any(
            item["id"] == team_id and item["role"] == "admin"
            for item in research_me.json()["user"]["teams"]
        )
        asyncio.run(assert_cross_workspace_team_membership_denied(default_workspace_id, team_id))

        mismatched_team_user = client.post(
            "/api/v1/admin/users",
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
            json={"name": "Applied Research", "description": "应用研究团队"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["description"] == "应用研究团队"

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

        # Team member management: add/list/update/remove.
        team_member_id, team_member_token = create_active_user(
            client,
            admin_token,
            "team-member",
        )
        added_workspace_member = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": team_member_id, "role": "member"},
        )
        assert added_workspace_member.status_code == 201, added_workspace_member.text

        empty_team_members = client.get(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
        )
        assert empty_team_members.status_code == 200, empty_team_members.text
        assert [(item["user"]["username"], item["role"]) for item in empty_team_members.json()] == [
            ("research-admin", "admin")
        ]

        not_a_workspace_member = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
            json={"user_id": outsider_id, "role": "member"},
        )
        assert not_a_workspace_member.status_code == 404, not_a_workspace_member.text

        added_team_member = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
            json={"user_id": team_member_id, "role": "member"},
        )
        assert added_team_member.status_code == 201, added_team_member.text
        assert added_team_member.json()["role"] == "member"

        team_members_denied_member = client.get(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(team_member_token),
        )
        assert team_members_denied_member.status_code == 403, team_members_denied_member.text

        duplicate_team_member = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
            json={"user_id": team_member_id, "role": "admin"},
        )
        assert duplicate_team_member.status_code == 409, duplicate_team_member.text

        invalid_team_role = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
            json={"user_id": team_member_id, "role": "owner"},
        )
        assert invalid_team_role.status_code == 422, invalid_team_role.text

        team_members_super = client.get(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(admin_token),
        )
        assert team_members_super.status_code == 200, team_members_super.text
        assert [(item["user"]["username"], item["role"]) for item in team_members_super.json()] == [
            ("team-member", "member"),
            ("research-admin", "admin"),
        ]

        member_manage_denied = client.patch(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_id}"),
            headers=auth_headers(team_member_token),
            json={"role": "admin"},
        )
        assert member_manage_denied.status_code == 403, member_manage_denied.text

        updated_team_member = client.patch(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_id}"),
            headers=auth_headers(research_token),
            json={"role": "admin"},
        )
        assert updated_team_member.status_code == 200, updated_team_member.text
        assert updated_team_member.json()["role"] == "admin"

        team_members = client.get(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
        )
        assert team_members.status_code == 200, team_members.text
        assert [(item["user"]["username"], item["role"]) for item in team_members.json()] == [
            ("team-member", "admin"),
            ("research-admin", "admin"),
        ]

        # Team admins manage team members; workspace admins manage team admins.
        team_member_2_id, _ = create_active_user(client, admin_token, "team-member-2")
        added_ws_member_2 = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": team_member_2_id, "role": "member"},
        )
        assert added_ws_member_2.status_code == 201, added_ws_member_2.text

        team_admin_list = client.get(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(team_member_token),
        )
        assert team_admin_list.status_code == 200, team_admin_list.text
        assert [item["user"]["username"] for item in team_admin_list.json()] == [
            "team-member",
            "research-admin",
        ]

        added_by_team_admin = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(team_member_token),
            json={"user_id": team_member_2_id, "role": "member"},
        )
        assert added_by_team_admin.status_code == 201, added_by_team_admin.text
        assert added_by_team_admin.json()["role"] == "member"

        promote_denied = client.patch(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_2_id}"),
            headers=auth_headers(team_member_token),
            json={"role": "admin"},
        )
        assert promote_denied.status_code == 403, promote_denied.text

        remove_member_by_team_admin = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_2_id}"),
            headers=auth_headers(team_member_token),
        )
        assert remove_member_by_team_admin.status_code == 204, remove_member_by_team_admin.text

        team_member_3_id, _ = create_active_user(client, admin_token, "team-member-3")
        added_ws_member_3 = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": team_member_3_id, "role": "member"},
        )
        assert added_ws_member_3.status_code == 201, added_ws_member_3.text

        add_admin_denied = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(team_member_token),
            json={"user_id": team_member_3_id, "role": "admin"},
        )
        assert add_admin_denied.status_code == 403, add_admin_denied.text

        added_team_admin = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
            json={"user_id": team_member_3_id, "role": "admin"},
        )
        assert added_team_admin.status_code == 201, added_team_admin.text
        assert added_team_admin.json()["role"] == "admin"

        remove_admin_denied = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_3_id}"),
            headers=auth_headers(team_member_token),
        )
        assert remove_admin_denied.status_code == 403, remove_admin_denied.text

        demote_admin_denied = client.patch(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_3_id}"),
            headers=auth_headers(team_member_token),
            json={"role": "member"},
        )
        assert demote_admin_denied.status_code == 403, demote_admin_denied.text

        # Super admin manages teams of every workspace, including team admins.
        super_add_member = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(admin_token),
            json={"user_id": team_member_2_id, "role": "member"},
        )
        assert super_add_member.status_code == 201, super_add_member.text

        demoted_team_admin = client.patch(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_3_id}"),
            headers=auth_headers(research_token),
            json={"role": "member"},
        )
        assert demoted_team_admin.status_code == 200, demoted_team_admin.text
        assert demoted_team_admin.json()["role"] == "member"

        removed_team_admin = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_3_id}"),
            headers=auth_headers(research_token),
        )
        assert removed_team_admin.status_code == 204, removed_team_admin.text

        removed_member_2 = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_2_id}"),
            headers=auth_headers(research_token),
        )
        assert removed_member_2.status_code == 204, removed_member_2.text

        removed_team_member = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_id}"),
            headers=auth_headers(research_token),
        )
        assert removed_team_member.status_code == 204, removed_team_member.text

        remove_team_member_again = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{team_member_id}"),
            headers=auth_headers(research_token),
        )
        assert remove_team_member_again.status_code == 404, remove_team_member_again.text

        demote_last_team_admin = client.patch(
            teams_url(research_workspace_id, f"/{team_id}/members/{research_admin_id}"),
            headers=auth_headers(research_token),
            json={"role": "member"},
        )
        assert demote_last_team_admin.status_code == 400, demote_last_team_admin.text

        remove_last_team_admin = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{research_admin_id}"),
            headers=auth_headers(research_token),
        )
        assert remove_last_team_admin.status_code == 400, remove_last_team_admin.text

        delete_workspace_team = client.delete(
            teams_url(default_workspace_id, f"/{default_team_id}"),
            headers=auth_headers(admin_token),
        )
        assert delete_workspace_team.status_code == 204, delete_workspace_team.text

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

        audit_logs = client.get("/api/v1/admin/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        logs = audit_logs.json()
        actions = [item["action"] for item in logs]
        assert "team.archive" in actions
        assert "team.delete" in actions
        assert "team.member.add" in actions
        assert "team.member.update" in actions
        assert "team.member.remove" in actions
        assert all(
            item["workspace_id"] == research_workspace_id
            for item in logs
            if item["resource_type"] == "team" and item["resource_id"] == team_id
        )


if __name__ == "__main__":
    main()

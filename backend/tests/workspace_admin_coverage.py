"""Coverage suite for the workspace / identity / team / admin domains.

Pure-script test suite (no pytest): run from backend/ with

    uv run python -m tests.workspace_admin_coverage

Every failed assertion or raised exception fails the suite; a successful run
prints an OK summary. Each ``test_client()`` block gets a fresh in-memory
database, so blocks are independent of each other.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import select, update as sa_update
from sqlalchemy.exc import IntegrityError

# MUST come before any app module import: configures test environment.
from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    login,
    settings,
    test_client,
)

from app.api.v1.endpoints.auth import REFRESH_TOKEN_COOKIE
from app.application import workspace as workspace_service
from app.entities.user import User
from app.entities.workspace import Workspace
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import team as team_repo
from app.infrastructure.repositories import user as user_repo
from app.infrastructure.repositories import workspace as workspace_repo
from app.infrastructure.security import hash_refresh_token
from app.infrastructure.session import get_session_factory
from app.shareddomain.knowledge.models import KnowledgeTask


def members_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/members{suffix}"


def teams_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/teams{suffix}"


def knowledge_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge-bases{suffix}"


# --------------------------------------------------------------------------
# Async helpers (direct DB / service access).
# --------------------------------------------------------------------------

async def seed_open_knowledge_task(
    workspace_id: str,
    knowledge_base_id: str,
    actor_id: str,
) -> str:
    async with get_session_factory()() as db:
        task = KnowledgeTask(
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            task_type="rebuild_index",
            status="queued",
            options={},
            created_by_user_id=actor_id,
        )
        db.add(task)
        await db.commit()
        return task.id


async def fail_knowledge_task(task_id: str) -> None:
    async with get_session_factory()() as db:
        task = await db.get(KnowledgeTask, task_id)
        assert task is not None
        task.status = "failed"
        task.last_error = "Stopped by test."
        await db.commit()


async def expire_refresh_session(token: str) -> None:
    token_hash = hash_refresh_token(token)
    from app.domain.user import RefreshSession as RefreshSessionOrm

    async with get_session_factory()() as db:
        await db.execute(
            sa_update(RefreshSessionOrm)
            .where(RefreshSessionOrm.token_hash == token_hash)
            .values(expires_at=utc_now() - timedelta(hours=1))
        )
        await db.commit()


async def exercise_direct_workspace_service_404() -> None:
    """update_workspace / delete_workspace_permanently with a missing id."""
    from fastapi import HTTPException

    from app.application.workspace import (
        delete_workspace_permanently,
        update_workspace,
    )
    from app.schemas.workspace import WorkspaceUpdateRequest

    missing = Workspace(id="no-such-workspace-id", name="Ghost", status="active")
    async with get_session_factory()() as db:
        try:
            await update_workspace(
                db,
                missing,
                WorkspaceUpdateRequest(name="Renamed"),
                None,
            )
        except HTTPException as exc:
            assert exc.status_code == 404, exc.status_code
        else:
            raise AssertionError("update_workspace on missing workspace did not 404")

        try:
            await delete_workspace_permanently(
                db,
                missing,
                None,
                settings(),
            )
        except HTTPException as exc:
            assert exc.status_code == 404, exc.status_code
        else:
            raise AssertionError("delete_workspace_permanently on missing workspace did not 404")


async def exercise_direct_identity_edges() -> None:
    """Direct service/repository branches not reachable through the API."""
    from fastapi import HTTPException

    from app.application.identity import (
        delete_user_permanently,
        find_user_by_identity,
        user_teams_by_user_id,
        user_workspaces_by_user_id,
    )

    async with get_session_factory()() as db:
        # Empty user lists short-circuit the scope queries.
        assert await user_workspaces_by_user_id(db, []) == {}
        assert await user_teams_by_user_id(db, []) == {}

        # find_user_by_identity: no match -> None.
        assert (
            await find_user_by_identity(db, "ghost-user", "ghost@example.com")
            is None
        )
        # Exact username+email match -> user.
        admin = await user_repo.list_users(db, 1)
        assert admin
        matched = await find_user_by_identity(db, admin[0].username, admin[0].email)
        assert matched is not None and matched.id == admin[0].id
        # Username matches nobody but email matches someone -> 409 conflict.
        try:
            await find_user_by_identity(db, "ghost-user", admin[0].email)
        except HTTPException as exc:
            assert exc.status_code == 409, exc.status_code
        else:
            raise AssertionError("ambiguous identity did not conflict")

        # delete_user_permanently with an id that no longer exists -> 404.
        try:
            await delete_user_permanently(
                db,
                User(id="no-such-user-id", username="ghost"),
                User(id="actor-id", username="actor"),
            )
        except HTTPException as exc:
            assert exc.status_code == 404, exc.status_code
        else:
            raise AssertionError("deleting a missing user did not 404")


async def exercise_repository_edges(
    workspace_id: str,
    admin_user_id: str,
    member_user_id: str,
    team_id: str,
) -> None:
    """Direct repository calls for branches not hit by the API flows."""
    async with get_session_factory()() as db:
        # Pagination beyond the result set returns empty lists.
        assert await workspace_repo.list_workspaces_for_user(
            db, admin_user_id, 5, 100
        ) == []
        assert await workspace_repo.list_all_workspaces(db, 1, 0)
        assert await workspace_repo.list_all_workspaces(db, 5, 1000) == []

        workspace = await workspace_repo.get_workspace_by_id(db, workspace_id)
        assert workspace is not None
        assert await workspace_repo.get_workspace_by_id(db, "no-such-id") is None
        assert await workspace_repo.lock_workspace(db, workspace_id) is not None
        assert await workspace_repo.lock_workspace(db, "no-such-id") is None
        assert (
            await workspace_repo.get_workspace_membership(db, workspace_id, admin_user_id)
            is not None
        )
        assert (
            await workspace_repo.get_workspace_membership(db, workspace_id, "no-such-user")
            is None
        )
        rows = await workspace_repo.list_workspace_member_rows(db, workspace_id)
        assert rows
        assert (
            await workspace_repo.get_workspace_member_row(db, workspace_id, member_user_id)
            is not None
        )
        assert (
            await workspace_repo.get_workspace_member_row(db, workspace_id, "no-such-user")
            is None
        )

        team = await team_repo.get_team_by_id(db, team_id)
        assert team is not None
        assert await team_repo.get_team_by_id(db, "no-such-id") is None
        assert await team_repo.list_teams(db, workspace_id)
        assert await team_repo.list_teams(db, workspace_id, 1, 0)
        assert await team_repo.list_teams(db, workspace_id, 5, 1000) == []
        assert (
            await team_repo.get_team_membership(db, team_id, admin_user_id) is not None
        )
        assert (
            await team_repo.get_team_membership(db, team_id, "no-such-user") is None
        )
        assert (
            await team_repo.get_active_workspace_user(db, workspace_id, admin_user_id)
            is not None
        )
        assert (
            await team_repo.get_active_workspace_user(db, workspace_id, "no-such-user")
            is None
        )
        assert await team_repo.list_team_member_rows(db, team)

        assert await user_repo.list_users_by_ids(db, []) == []
        assert await user_repo.list_users_by_ids(db, [admin_user_id, member_user_id])
        assert await user_repo.find_users_by_identity(
            db, "ghost-user", "ghost@example.com"
        ) == []
        assert await user_repo.list_admin_workspace_ids_for_user(db, admin_user_id)
        assert await user_repo.list_admin_workspace_ids_for_user(db, "no-such-user") == []
        counts = await user_repo.active_admin_counts_by_workspace(db, [workspace_id])
        assert workspace_id in counts
        assert await user_repo.active_admin_counts_by_workspace(db, ["no-such-id"]) == {}
        memberships = await user_repo.list_workspace_memberships_for_user(db, admin_user_id)
        assert memberships


# --------------------------------------------------------------------------
# Block 1: workspaces, members, teams, permanent deletion.
# --------------------------------------------------------------------------

def run_workspace_block() -> None:
    with test_client() as client:
        admin_token, default_workspace_id = activate_admin(client)

        # A second active user that will administer a separate workspace.
        research_admin_id, research_token = create_active_user(
            client,
            admin_token,
            "research-admin",
        )
        created = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Research Workspace",
                "description": "研究空间",
                "admin_user_id": research_admin_id,
            },
        )
        assert created.status_code == 201, created.text
        research_workspace_id = created.json()["workspace"]["id"]

        # --- build_workspace_context branches -------------------------------
        # Workspace missing -> 404.
        missing_context = client.get(
            teams_url("no-such-workspace"),
            headers=auth_headers(research_token),
        )
        assert missing_context.status_code == 404, missing_context.text

        # Archived workspace -> 403 "not active".
        archived = client.patch(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "archived"},
        )
        assert archived.status_code == 200, archived.text
        inactive_context = client.get(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
        )
        assert inactive_context.status_code == 403, inactive_context.text
        restored = client.patch(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "active"},
        )
        assert restored.status_code == 200, restored.text

        # Global admin without membership -> context role "admin" (200).
        super_members = client.get(
            members_url(research_workspace_id),
            headers=auth_headers(admin_token),
        )
        assert super_members.status_code == 200, super_members.text
        # Non-member, non-admin -> 403 "access denied".
        denied_members = client.get(
            members_url(default_workspace_id),
            headers=auth_headers(research_token),
        )
        assert denied_members.status_code == 403, denied_members.text
        # Workspace member with membership -> context builds (teams list only
        # requires a context, not an admin role).
        member_context = client.get(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
        )
        assert member_context.status_code == 200, member_context.text

        # --- workspace list / get ------------------------------------------
        user_workspaces = client.get(
            "/api/v1/workspaces?limit=5&offset=0",
            headers=auth_headers(research_token),
        )
        assert user_workspaces.status_code == 200, user_workspaces.text
        assert [item["id"] for item in user_workspaces.json()] == [
            research_workspace_id
        ]
        missing_get = client.get(
            f"/api/v1/workspaces/no-such-workspace",
            headers=auth_headers(admin_token),
        )
        assert missing_get.status_code == 404, missing_get.text
        super_get = client.get(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert super_get.status_code == 200, super_get.text
        denied_get = client.get(
            f"/api/v1/workspaces/{default_workspace_id}",
            headers=auth_headers(research_token),
        )
        assert denied_get.status_code == 403, denied_get.text
        member_get = client.get(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(research_token),
        )
        assert member_get.status_code == 200, member_get.text

        # --- create_workspace branches --------------------------------------
        missing_admin = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={"name": "Ghost Admin", "admin_user_id": "no-such-user"},
        )
        assert missing_admin.status_code == 404, missing_admin.text

        inactive_id, _ = create_active_user(client, admin_token, "inactive-owner")
        disabled = client.patch(
            f"/api/v1/admin/users/{inactive_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert disabled.status_code == 200, disabled.text
        inactive_admin = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={"name": "Inactive Owner", "admin_user_id": inactive_id},
        )
        assert inactive_admin.status_code == 400, inactive_admin.text

        extra_admin_id, extra_admin_token = create_active_user(
            client, admin_token, "extra-owner"
        )
        extra_created = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Extra Workspace",
                "description": "额外空间",
                "admin_user_id": extra_admin_id,
            },
        )
        assert extra_created.status_code == 201, extra_created.text
        extra_workspace_id = extra_created.json()["workspace"]["id"]
        assert extra_created.json()["workspace"]["description"] == "额外空间"

        # Duplicate slug (patched new_id) -> IntegrityError -> 409.
        original_new_id = workspace_service.new_id
        workspace_service.new_id = lambda: "fixed-slug-for-409"
        try:
            first = client.post(
                "/api/v1/workspaces",
                headers=auth_headers(admin_token),
                json={"name": "Slug One", "admin_user_id": extra_admin_id},
            )
            assert first.status_code == 201, first.text
            second = client.post(
                "/api/v1/workspaces",
                headers=auth_headers(admin_token),
                json={"name": "Slug Two", "admin_user_id": extra_admin_id},
            )
            assert second.status_code == 409, second.text
        finally:
            workspace_service.new_id = original_new_id

        # --- update_workspace branches --------------------------------------
        updated = client.patch(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"name": "Research Lab", "description": "研究实验室"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["description"] == "研究实验室"

        invalid_status = client.patch(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "frozen"},
        )
        assert invalid_status.status_code == 422, invalid_status.text

        # save_workspace raises IntegrityError -> 409.
        original_save = workspace_service.workspace_repository.save_workspace

        async def failing_save(db, entity):
            raise IntegrityError("stmt", {}, Exception("boom"))

        workspace_service.workspace_repository.save_workspace = failing_save
        try:
            conflict = client.patch(
                f"/api/v1/workspaces/{research_workspace_id}",
                headers=auth_headers(admin_token),
                json={"description": "conflict"},
            )
            assert conflict.status_code == 409, conflict.text
        finally:
            workspace_service.workspace_repository.save_workspace = original_save

        asyncio.run(exercise_direct_workspace_service_404())

        # --- workspace members ----------------------------------------------
        add_missing_user = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": "no-such-user", "role": "member"},
        )
        assert add_missing_user.status_code == 404, add_missing_user.text

        invalid_role = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": extra_admin_id, "role": "owner"},
        )
        assert invalid_role.status_code == 422, invalid_role.text

        add_admin_denied = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": extra_admin_id, "role": "admin"},
        )
        assert add_admin_denied.status_code == 403, add_admin_denied.text

        member_user_id, member_token = create_active_user(
            client, admin_token, "ws-member"
        )
        added_member = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "member"},
        )
        assert added_member.status_code == 201, added_member.text
        assert added_member.json()["role"] == "member"

        duplicate_member = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "member"},
        )
        assert duplicate_member.status_code == 409, duplicate_member.text

        # Member (non-admin) cannot manage members -> 403.
        member_manage_denied = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(member_token),
            json={"user_id": research_admin_id, "role": "member"},
        )
        assert member_manage_denied.status_code == 403, member_manage_denied.text

        # Promote to admin requires global admin.
        promoted = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(admin_token),
            json={"role": "admin"},
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["role"] == "admin"

        # Demote back to member (two admins exist, so it is allowed).
        demoted = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(admin_token),
            json={"role": "member"},
        )
        assert demoted.status_code == 200, demoted.text
        assert demoted.json()["role"] == "member"

        # Updating a non-member -> 404.
        update_missing_member = client.patch(
            members_url(research_workspace_id, "/no-such-user"),
            headers=auth_headers(admin_token),
            json={"role": "member"},
        )
        assert update_missing_member.status_code == 404, update_missing_member.text

        # Demoting the last workspace admin -> 400.
        demote_last_admin = client.patch(
            members_url(research_workspace_id, f"/{research_admin_id}"),
            headers=auth_headers(admin_token),
            json={"role": "member"},
        )
        assert demote_last_admin.status_code == 400, demote_last_admin.text

        # Removing the last admin by super admin -> 400.
        remove_last_admin = client.delete(
            members_url(research_workspace_id, f"/{research_admin_id}"),
            headers=auth_headers(admin_token),
        )
        assert remove_last_admin.status_code == 400, remove_last_admin.text

        # A workspace admin (non-global) cannot remove a fellow admin -> 403.
        promote_member = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(admin_token),
            json={"role": "admin"},
        )
        assert promote_member.status_code == 200, promote_member.text
        remove_admin_denied = client.delete(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(research_token),
        )
        assert remove_admin_denied.status_code == 403, remove_admin_denied.text

        # Removing a plain member (member role) by the workspace admin.
        demote_member = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(admin_token),
            json={"role": "member"},
        )
        assert demote_member.status_code == 200, demote_member.text
        removed_member = client.delete(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(research_token),
        )
        assert removed_member.status_code == 204, removed_member.text
        removed_member_again = client.delete(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(research_token),
        )
        assert removed_member_again.status_code == 404, removed_member_again.text

        # Re-add the member so the team tests below can use them.
        re_added = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "member"},
        )
        assert re_added.status_code == 201, re_added.text

        # --- teams ----------------------------------------------------------
        member_create_denied = client.post(
            teams_url(research_workspace_id),
            headers=auth_headers(member_token),
            json={"name": "Nope", "admin_user_id": research_admin_id},
        )
        assert member_create_denied.status_code == 403, member_create_denied.text

        team_created = client.post(
            teams_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={
                "name": "Applied AI",
                "description": "应用智能",
                "admin_user_id": research_admin_id,
            },
        )
        assert team_created.status_code == 201, team_created.text
        team_id = team_created.json()["id"]

        member_team_admin_denied = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(member_token),
            json={"user_id": member_user_id, "role": "member"},
        )
        assert member_team_admin_denied.status_code == 403, member_team_admin_denied.text

        team_updated = client.patch(
            teams_url(research_workspace_id, f"/{team_id}"),
            headers=auth_headers(research_token),
            json={"name": "Applied Research", "description": "应用研究"},
        )
        assert team_updated.status_code == 200, team_updated.text
        assert team_updated.json()["description"] == "应用研究"

        team_members = client.get(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
        )
        assert team_members.status_code == 200, team_members.text
        assert {item["user"]["username"] for item in team_members.json()} == {
            "research-admin"
        }

        team_member_added = client.post(
            teams_url(research_workspace_id, f"/{team_id}/members"),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "member"},
        )
        assert team_member_added.status_code == 201, team_member_added.text
        assert team_member_added.json()["role"] == "member"

        # Last team admin protection (research-admin is still the only admin).
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

        team_member_updated = client.patch(
            teams_url(research_workspace_id, f"/{team_id}/members/{member_user_id}"),
            headers=auth_headers(research_token),
            json={"role": "admin"},
        )
        assert team_member_updated.status_code == 200, team_member_updated.text
        assert team_member_updated.json()["role"] == "admin"

        team_member_removed = client.delete(
            teams_url(research_workspace_id, f"/{team_id}/members/{member_user_id}"),
            headers=auth_headers(research_token),
        )
        assert team_member_removed.status_code == 204, team_member_removed.text

        # --- workspace audit logs -------------------------------------------
        member_audit_denied = client.get(
            f"/api/v1/workspaces/{research_workspace_id}/audit-logs",
            headers=auth_headers(member_token),
        )
        assert member_audit_denied.status_code == 403, member_audit_denied.text
        workspace_audit = client.get(
            f"/api/v1/workspaces/{research_workspace_id}/audit-logs",
            headers=auth_headers(research_token),
        )
        assert workspace_audit.status_code == 200, workspace_audit.text
        assert workspace_audit.json()

        # --- direct repository edges ----------------------------------------
        asyncio.run(
            exercise_repository_edges(
                research_workspace_id,
                research_admin_id,
                member_user_id,
                team_id,
            )
        )

        # --- permanent deletion ---------------------------------------------
        # Delete a workspace that still owns a team (team rows removed in
        # delete_workspace_graph).
        default_delete = client.delete(
            f"/api/v1/workspaces/{default_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert default_delete.status_code == 204, default_delete.text

        # Knowledge base flow: create a KB, block deletion with a queued task,
        # then finish the task and delete for real.
        kb_created = client.post(
            knowledge_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"name": "Coverage KB"},
        )
        assert kb_created.status_code == 201, kb_created.text
        kb_id = kb_created.json()["id"]

        task_id = asyncio.run(
            seed_open_knowledge_task(
                research_workspace_id,
                kb_id,
                research_admin_id,
            )
        )
        task_blocked = client.delete(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert task_blocked.status_code == 409, task_blocked.text
        still_there = client.get(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert still_there.status_code == 200, still_there.text

        asyncio.run(fail_knowledge_task(task_id))
        kb_delete = client.delete(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert kb_delete.status_code == 204, kb_delete.text
        gone = client.get(
            f"/api/v1/workspaces/{research_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert gone.status_code == 404, gone.text

        # Delete the extra workspace (also exercises the no-KB cleanup path).
        extra_delete = client.delete(
            f"/api/v1/workspaces/{extra_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert extra_delete.status_code == 204, extra_delete.text
        assert extra_admin_token  # keep the token referenced


# --------------------------------------------------------------------------
# Block 2: identity / admin user management.
# --------------------------------------------------------------------------

def run_identity_block() -> None:
    with test_client() as client:
        admin_token, default_workspace_id = activate_admin(client)
        admin_me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
        assert admin_me.status_code == 200, admin_me.text
        admin_user_id = admin_me.json()["user"]["id"]

        # list_users with non-empty scope maps.
        users = client.get("/api/v1/admin/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        assert any(item["id"] == admin_user_id for item in users.json())

        # --- create_user branches -------------------------------------------
        team_without_workspace = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "team-no-ws",
                "email": "team-no-ws@example.com",
                "name": "Team No WS",
                "team_ids": ["some-team"],
            },
        )
        assert team_without_workspace.status_code == 422, team_without_workspace.text

        missing_workspace = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "ws-missing",
                "email": "ws-missing@example.com",
                "name": "WS Missing",
                "workspace_id": "no-such-workspace",
            },
        )
        assert missing_workspace.status_code == 404, missing_workspace.text

        # A workspace to host teams (admin is a member/admin of it).
        owner_id, _ = create_active_user(client, admin_token, "ws-owner")
        hosted = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={"name": "Host Workspace", "admin_user_id": owner_id},
        )
        assert hosted.status_code == 201, hosted.text
        hosted_workspace_id = hosted.json()["workspace"]["id"]

        team_created = client.post(
            teams_url(hosted_workspace_id),
            headers=auth_headers(admin_token),
            json={"name": "Host Team", "admin_user_id": owner_id},
        )
        assert team_created.status_code == 201, team_created.text
        hosted_team_id = team_created.json()["id"]

        # Archived workspace -> create_user 403.
        archived_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={"name": "Archived Host", "admin_user_id": owner_id},
        )
        assert archived_workspace.status_code == 201, archived_workspace.text
        archived_workspace_id = archived_workspace.json()["workspace"]["id"]
        archived_patch = client.patch(
            f"/api/v1/workspaces/{archived_workspace_id}",
            headers=auth_headers(admin_token),
            json={"status": "archived"},
        )
        assert archived_patch.status_code == 200, archived_patch.text
        archived_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "ws-archived",
                "email": "ws-archived@example.com",
                "name": "WS Archived",
                "workspace_id": archived_workspace_id,
            },
        )
        assert archived_user.status_code == 403, archived_user.text

        # Team from a different workspace -> 422.
        other_team = client.post(
            teams_url(hosted_workspace_id),
            headers=auth_headers(admin_token),
            json={"name": "Other Team", "admin_user_id": owner_id},
        )
        assert other_team.status_code == 201, other_team.text
        other_team_id = other_team.json()["id"]
        cross_team_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "cross-team",
                "email": "cross-team@example.com",
                "name": "Cross Team",
                "workspace_id": default_workspace_id,
                "team_ids": [other_team_id],
            },
        )
        assert cross_team_user.status_code == 422, cross_team_user.text

        # Unknown team id in a valid workspace -> 404.
        missing_team_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "missing-team",
                "email": "missing-team@example.com",
                "name": "Missing Team",
                "workspace_id": hosted_workspace_id,
                "team_ids": ["no-such-team"],
            },
        )
        assert missing_team_user.status_code == 404, missing_team_user.text

        # Successful create with workspace membership + team membership.
        scoped_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "scoped-user",
                "email": "scoped-user@example.com",
                "name": "Scoped User",
                "workspace_id": hosted_workspace_id,
                "team_ids": [hosted_team_id],
            },
        )
        assert scoped_user.status_code == 201, scoped_user.text
        scoped_payload = scoped_user.json()
        assert scoped_payload["initial_password"] == "NexaFlow@123"
        assert scoped_payload["user"]["workspaces"][0]["id"] == hosted_workspace_id
        assert scoped_payload["user"]["workspaces"][0]["role"] == "member"
        assert [t["id"] for t in scoped_payload["user"]["teams"]] == [hosted_team_id]
        scoped_user_id = scoped_payload["user"]["id"]

        # Duplicate username -> 409.
        duplicate_username = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "scoped-user",
                "email": "scoped-user-2@example.com",
                "name": "Duplicate Username",
            },
        )
        assert duplicate_username.status_code == 409, duplicate_username.text
        # Duplicate email -> 409.
        duplicate_email = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "scoped-user-2",
                "email": "scoped-user@example.com",
                "name": "Duplicate Email",
            },
        )
        assert duplicate_email.status_code == 409, duplicate_email.text

        # --- update_user branches -------------------------------------------
        renamed = client.patch(
            f"/api/v1/admin/users/{scoped_user_id}",
            headers=auth_headers(admin_token),
            json={
                "username": "scoped-user-renamed",
                "email": "scoped-renamed@example.com",
                "name": "Renamed User",
            },
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["username"] == "scoped-user-renamed"

        promoted_global = client.patch(
            f"/api/v1/admin/users/{scoped_user_id}",
            headers=auth_headers(admin_token),
            json={"is_global_admin": True},
        )
        assert promoted_global.status_code == 200, promoted_global.text
        assert promoted_global.json()["is_global_admin"] is True

        self_demote = client.patch(
            f"/api/v1/admin/users/{admin_user_id}",
            headers=auth_headers(admin_token),
            json={"is_global_admin": False},
        )
        assert self_demote.status_code == 400, self_demote.text

        self_disable = client.patch(
            f"/api/v1/admin/users/{admin_user_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert self_disable.status_code == 400, self_disable.text

        # Disable a user with no workspace admin roles -> 200.
        scoped_login = client.post(
            "/api/v1/auth/login",
            json={"username": "scoped-user-renamed", "password": "NexaFlow@123"},
        )
        assert scoped_login.status_code == 200, scoped_login.text
        disabled_user = client.patch(
            f"/api/v1/admin/users/{scoped_user_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert disabled_user.status_code == 200, disabled_user.text
        assert disabled_user.json()["is_active"] is False
        # Their refresh session was deleted.
        assert client.post("/api/v1/auth/refresh").status_code == 401
        disabled_login = client.post(
            "/api/v1/auth/login",
            json={"username": "scoped-user-renamed", "password": "NexaFlow@123"},
        )
        assert disabled_login.status_code == 401, disabled_login.text
        # Re-enable so the managed-password flow below can log in.
        re_enabled = client.patch(
            f"/api/v1/admin/users/{scoped_user_id}",
            headers=auth_headers(admin_token),
            json={"is_active": True},
        )
        assert re_enabled.status_code == 200, re_enabled.text

        # Disable an admin who is the last active admin -> 400.
        solo_id, solo_token = create_active_user(client, admin_token, "solo-admin")
        solo_ws = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={"name": "Solo Workspace", "admin_user_id": solo_id},
        )
        assert solo_ws.status_code == 201, solo_ws.text
        disable_last_admin = client.patch(
            f"/api/v1/admin/users/{solo_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert disable_last_admin.status_code == 400, disable_last_admin.text

        # Delete the last active admin -> 400.
        delete_last_admin = client.delete(
            f"/api/v1/admin/users/{solo_id}",
            headers=auth_headers(admin_token),
        )
        assert delete_last_admin.status_code == 400, delete_last_admin.text

        # A second admin in the same workspace makes disabling allowed.
        second_id, _ = create_active_user(client, admin_token, "second-admin")
        added_second = client.post(
            members_url(solo_ws.json()["workspace"]["id"]),
            headers=auth_headers(admin_token),
            json={"user_id": second_id, "role": "admin"},
        )
        assert added_second.status_code == 201, added_second.text
        disable_with_peer = client.patch(
            f"/api/v1/admin/users/{solo_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert disable_with_peer.status_code == 200, disable_with_peer.text
        assert solo_token  # keep referenced

        # Update to a duplicate username -> 409.
        duplicate_update = client.patch(
            f"/api/v1/admin/users/{second_id}",
            headers=auth_headers(admin_token),
            json={"username": "admin"},
        )
        assert duplicate_update.status_code == 409, duplicate_update.text

        # Missing user -> 404.
        missing_user_patch = client.patch(
            "/api/v1/admin/users/no-such-user",
            headers=auth_headers(admin_token),
            json={"name": "Ghost"},
        )
        assert missing_user_patch.status_code == 404, missing_user_patch.text

        # --- admin-managed password changes ---------------------------------
        managed_password = "ManagedPass@123"
        changed_managed = client.post(
            f"/api/v1/admin/users/{scoped_user_id}/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": managed_password},
        )
        assert changed_managed.status_code == 200, changed_managed.text
        assert changed_managed.json()["must_change_password"] is False
        # Old password no longer works; new one does.
        old_login = client.post(
            "/api/v1/auth/login",
            json={"username": "scoped-user-renamed", "password": "NexaFlow@123"},
        )
        assert old_login.status_code == 401, old_login.text
        new_login = client.post(
            "/api/v1/auth/login",
            json={"username": "scoped-user-renamed", "password": managed_password},
        )
        assert new_login.status_code == 200, new_login.text

        # Admin changes their own managed password.
        self_managed = client.post(
            f"/api/v1/admin/users/{admin_user_id}/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": "AdminSelfPass@123"},
        )
        assert self_managed.status_code == 200, self_managed.text

        # --- deletion -------------------------------------------------------
        # Delete self -> 400.
        self_delete = client.delete(
            f"/api/v1/admin/users/{admin_user_id}",
            headers=auth_headers(admin_token),
        )
        assert self_delete.status_code == 400, self_delete.text

        # Delete a plain user -> 204 (removes memberships + team memberships).
        delete_target_id, _ = create_active_user(client, admin_token, "delete-me")
        delete_target = client.delete(
            f"/api/v1/admin/users/{delete_target_id}",
            headers=auth_headers(admin_token),
        )
        assert delete_target.status_code == 204, delete_target.text
        deleted_login = client.post(
            "/api/v1/auth/login",
            json={"username": "delete-me", "password": "NexaFlow@12345."},
        )
        assert deleted_login.status_code == 401, deleted_login.text

        asyncio.run(exercise_direct_identity_edges())

        # --- auth flows -----------------------------------------------------
        # Login with an x-forwarded-for header exercises the IP extraction.
        forwarded_login = client.post(
            "/api/v1/auth/login",
            headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"},
            json={"username": "admin", "password": "AdminSelfPass@123"},
        )
        assert forwarded_login.status_code == 200, forwarded_login.text
        assert forwarded_login.json()["must_change_password"] is False

        # Failed login -> 401 (system log + audit path).
        failed_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "WrongPass@123"},
        )
        assert failed_login.status_code == 401, failed_login.text

        # Refresh token flows.
        client.cookies.clear()
        login_before_refresh = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "AdminSelfPass@123"},
        )
        assert login_before_refresh.status_code == 200, login_before_refresh.text
        refresh_token = client.cookies.get(REFRESH_TOKEN_COOKIE)
        assert refresh_token
        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text

        # Invalid refresh token -> 401.
        client.cookies.clear()
        client.cookies.set(REFRESH_TOKEN_COOKIE, "garbage-token", path="/api/v1/auth")
        assert client.post("/api/v1/auth/refresh").status_code == 401
        client.cookies.clear()

        # Expired refresh token -> 401.
        fresh_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "AdminSelfPass@123"},
        )
        assert fresh_login.status_code == 200, fresh_login.text
        fresh_token = client.cookies.get(REFRESH_TOKEN_COOKIE)
        asyncio.run(expire_refresh_session(fresh_token))
        assert client.post("/api/v1/auth/refresh").status_code == 401

        # Logout revokes the session.
        client.cookies.clear()
        logout_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "AdminSelfPass@123"},
        )
        assert logout_login.status_code == 200, logout_login.text
        logged_out = client.post("/api/v1/auth/logout")
        assert logged_out.status_code == 204, logged_out.text
        assert client.post("/api/v1/auth/refresh").status_code == 401

        # Self change-password with current password -> 204 + new cookie.
        changed_self = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": "AdminSelfPass@123",
                "new_password": "RotatedPass@123",
            },
        )
        assert changed_self.status_code == 204, changed_self.text
        assert client.cookies.get(REFRESH_TOKEN_COOKIE)

        # Wrong current password -> 400.
        wrong_current = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": "Wrong@12345.",
                "new_password": "AnotherPass@123",
            },
        )
        assert wrong_current.status_code == 400, wrong_current.text

        # Same password -> 400.
        same_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": "RotatedPass@123",
                "new_password": "RotatedPass@123",
            },
        )
        assert same_password.status_code == 400, same_password.text


def main() -> None:
    run_workspace_block()
    run_identity_block()
    print("workspace_admin_coverage OK: workspace/identity/team/admin coverage suite passed.")


if __name__ == "__main__":
    main()

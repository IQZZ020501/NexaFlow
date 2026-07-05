import asyncio

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from nexaflow.db.session import get_session_factory
from nexaflow.identity.models import User
from nexaflow.knowledge_bases.models import KnowledgeBase
from nexaflow.resource_permissions.models import ResourcePermission
from nexaflow.testing import (
    RESEARCH_PASSWORD,
    activate_admin,
    activate_user,
    auth_headers,
    test_client,
)

MEMBER_PASSWORD = "Member@12345."


def knowledge_bases_url(workspace_id: str, suffix: str = "") -> str:
    return f"/workspaces/{workspace_id}/knowledge-bases{suffix}"


def create_workspace_user(client, token: str, workspace_id: str, username: str) -> tuple[str, str]:
    response = client.post(
        f"/workspaces/{workspace_id}/members/users",
        headers=auth_headers(token),
        json={
            "username": username,
            "email": f"{username}@example.com",
            "name": username.replace("-", " ").title(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], response.json()["initial_password"]


async def assert_cross_workspace_permission_denied(
    default_workspace_id: str,
    knowledge_base_id: str,
) -> None:
    async with get_session_factory()() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        user = await db.scalar(select(User).where(User.username == "research-admin"))
        assert user is not None

        db.add(
            ResourcePermission(
                workspace_id=default_workspace_id,
                resource_type="knowledge_base",
                resource_id=knowledge_base_id,
                user_id=user.id,
                permission="view",
                created_by_user_id=user.id,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return

    raise AssertionError("Cross-workspace resource permission was allowed.")


def main() -> None:
    with test_client() as client:
        admin_token, default_workspace_id = activate_admin(client)

        alice_id, alice_temp_password = create_workspace_user(
            client,
            admin_token,
            default_workspace_id,
            "alice",
        )
        bob_id, bob_temp_password = create_workspace_user(
            client,
            admin_token,
            default_workspace_id,
            "bob",
        )
        alice_token = activate_user(client, "alice", alice_temp_password, MEMBER_PASSWORD)
        bob_token = activate_user(client, "bob", bob_temp_password, MEMBER_PASSWORD)

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
        research_password = created_workspace.json()["admin_initial_password"]
        assert research_password
        research_token = activate_user(
            client,
            "research-admin",
            research_password,
            RESEARCH_PASSWORD,
        )

        knowledge_base = client.post(
            knowledge_bases_url(default_workspace_id),
            headers=auth_headers(alice_token),
            json={"name": "Product Docs", "description": "Internal product answers"},
        )
        assert knowledge_base.status_code == 201, knowledge_base.text
        knowledge_base_id = knowledge_base.json()["id"]
        assert knowledge_base.json()["permission"] == "edit"
        assert knowledge_base.json()["created_by_user_id"] == alice_id

        bob_list = client.get(
            knowledge_bases_url(default_workspace_id),
            headers=auth_headers(bob_token),
        )
        assert bob_list.status_code == 200, bob_list.text
        assert bob_list.json() == []

        denied_cross_workspace = client.get(
            knowledge_bases_url(default_workspace_id),
            headers=auth_headers(research_token),
        )
        assert denied_cross_workspace.status_code == 403, denied_cross_workspace.text

        view_grant = client.put(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{bob_id}"),
            headers=auth_headers(alice_token),
            json={"permission": "view"},
        )
        assert view_grant.status_code == 200, view_grant.text
        assert view_grant.json()["permission"] == "view"
        asyncio.run(assert_cross_workspace_permission_denied(default_workspace_id, knowledge_base_id))

        bob_get = client.get(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert bob_get.status_code == 200, bob_get.text
        assert bob_get.json()["permission"] == "view"

        bob_edit_denied = client.patch(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"description": "Bob edit attempt"},
        )
        assert bob_edit_denied.status_code == 403, bob_edit_denied.text

        edit_grant = client.put(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{bob_id}"),
            headers=auth_headers(alice_token),
            json={"permission": "edit"},
        )
        assert edit_grant.status_code == 200, edit_grant.text

        bob_edit = client.patch(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
            json={"description": "Bob can now edit"},
        )
        assert bob_edit.status_code == 200, bob_edit.text
        assert bob_edit.json()["description"] == "Bob can now edit"

        bob_delete_denied = client.delete(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert bob_delete_denied.status_code == 403, bob_delete_denied.text

        permissions = client.get(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}/permissions"),
            headers=auth_headers(alice_token),
        )
        assert permissions.status_code == 200, permissions.text
        assert [(item["user"]["username"], item["permission"]) for item in permissions.json()] == [
            ("bob", "edit")
        ]

        revoked = client.delete(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}/permissions/{bob_id}"),
            headers=auth_headers(alice_token),
        )
        assert revoked.status_code == 204, revoked.text
        bob_get_denied = client.get(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(bob_token),
        )
        assert bob_get_denied.status_code == 403, bob_get_denied.text

        deleted = client.delete(
            knowledge_bases_url(default_workspace_id, f"/{knowledge_base_id}"),
            headers=auth_headers(alice_token),
        )
        assert deleted.status_code == 204, deleted.text

        async def assert_deleted() -> None:
            async with get_session_factory()() as db:
                assert await db.get(KnowledgeBase, knowledge_base_id) is None

        asyncio.run(assert_deleted())

        audit_logs = client.get("/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "knowledge_base.create" in actions
        assert "resource_permission.grant" in actions
        assert "resource_permission.revoke" in actions
        assert "knowledge_base.delete" in actions


if __name__ == "__main__":
    main()

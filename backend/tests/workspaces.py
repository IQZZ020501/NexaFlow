import asyncio

from sqlalchemy import select

from app.capabilities.llm.models import RegisteredModel
from app.domain.resource_permission import ResourcePermission
from app.infrastructure import object_storage as object_storage_module
from app.infrastructure.session import get_session_factory
from app.shareddomain.agents.models import (
    Agent,
    AgentKnowledgeBase,
    AgentMcpTool,
    AgentRun,
)
from app.shareddomain.knowledge import cleanup as knowledge_cleanup
from app.shareddomain.knowledge.models import (
    KnowledgeBase,
    KnowledgeStorageCleanup,
    KnowledgeTask,
)
from app.shareddomain.knowledge.services import knowledge_object_storage
from app.shareddomain.tools.models import McpServer
from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    settings,
    test_client,
)


def members_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/members{suffix}"


def knowledge_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge-bases{suffix}"


async def assert_workspace_cascade_deleted(
    workspace_id: str,
    knowledge_base_id: str,
    model_id: str,
    agent_id: str,
    agent_run_id: str,
    mcp_server_id: str,
) -> None:
    async with get_session_factory()() as db:
        assert await db.get(KnowledgeBase, knowledge_base_id) is None
        assert await db.get(RegisteredModel, model_id) is None
        assert await db.get(Agent, agent_id) is None
        assert await db.get(AgentRun, agent_run_id) is None
        assert await db.get(McpServer, mcp_server_id) is None
        for model in (AgentKnowledgeBase, AgentMcpTool):
            rows = await db.scalars(
                select(model).where(model.workspace_id == workspace_id)
            )
            assert rows.all() == []
        grants = await db.execute(
            select(ResourcePermission).where(
                ResourcePermission.workspace_id == workspace_id
            )
        )
        assert grants.scalars().all() == []


async def seed_workspace_dependencies(
    workspace_id: str,
    knowledge_base_id: str,
    actor_id: str,
) -> tuple[str, str, str, str, str]:
    async with get_session_factory()() as db:
        model = RegisteredModel(
            workspace_id=workspace_id,
            name="Cascade Model",
            provider="openai",
            provider_type="openai_compatible",
            api_base="https://models.example.com/v1",
            credential_config={},
            credential_secret_hints={},
            model_type="LLM",
            model_name="cascade-model",
            status="active",
            meta={},
            created_by_user_id=actor_id,
        )
        mcp_server = McpServer(
            workspace_id=workspace_id,
            name="Cascade MCP",
            url="https://tools.example.com/mcp",
            tools=[],
            status="active",
            created_by_user_id=actor_id,
        )
        db.add_all([model, mcp_server])
        await db.flush()

        agent = Agent(
            workspace_id=workspace_id,
            name="Cascade Agent",
            description="",
            instructions="Use workspace resources.",
            model_id=model.id,
            status="active",
            created_by_user_id=actor_id,
        )
        db.add(agent)
        await db.flush()

        agent_run = AgentRun(
            workspace_id=workspace_id,
            agent_id=agent.id,
            requested_by_user_id=actor_id,
            goal="Verify cascade",
            instructions=agent.instructions,
            knowledge_base_ids=[knowledge_base_id],
            mcp_tools=[
                {"server_id": mcp_server.id, "tool_name": "lookup"}
            ],
            model_id=model.id,
            model_name=model.name,
            status="succeeded",
        )
        task = KnowledgeTask(
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            task_type="rebuild_index",
            status="queued",
            options={},
            created_by_user_id=actor_id,
        )
        db.add_all(
            [
                AgentKnowledgeBase(
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    knowledge_base_id=knowledge_base_id,
                ),
                AgentMcpTool(
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    mcp_server_id=mcp_server.id,
                    tool_name="lookup",
                ),
                agent_run,
                task,
            ]
        )
        await db.commit()
        return model.id, agent.id, agent_run.id, mcp_server.id, task.id


async def fail_knowledge_task(task_id: str) -> None:
    async with get_session_factory()() as db:
        task = await db.get(KnowledgeTask, task_id)
        assert task is not None
        task.status = "failed"
        task.last_error = "Test task stopped."
        await db.commit()


async def get_storage_cleanup(knowledge_base_id: str) -> KnowledgeStorageCleanup:
    async with get_session_factory()() as db:
        cleanup = await db.scalar(
            select(KnowledgeStorageCleanup).where(
                KnowledgeStorageCleanup.knowledge_base_id == knowledge_base_id
            )
        )
        assert cleanup is not None
        return cleanup


async def assert_storage_cleanup_finished(cleanup_id: str) -> None:
    async with get_session_factory()() as db:
        assert await db.get(KnowledgeStorageCleanup, cleanup_id) is None


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

        members_super = client.get(
            members_url(research_workspace_id),
            headers=auth_headers(admin_token),
        )
        assert members_super.status_code == 200, members_super.text

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

        add_admin_denied = client.post(
            members_url(research_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": member_user_id, "role": "admin"},
        )
        assert add_admin_denied.status_code == 403, add_admin_denied.text

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

        promoted_member = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(admin_token),
            json={"role": "admin"},
        )
        assert promoted_member.status_code == 200, promoted_member.text
        assert promoted_member.json()["role"] == "admin"

        demote_admin_denied = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(research_token),
            json={"role": "member"},
        )
        assert demote_admin_denied.status_code == 403, demote_admin_denied.text

        updated_member = client.patch(
            members_url(research_workspace_id, f"/{member_user_id}"),
            headers=auth_headers(admin_token),
            json={"role": "member"},
        )
        assert updated_member.status_code == 200, updated_member.text
        assert updated_member.json()["role"] == "member"

        demote_last_admin = client.patch(
            members_url(research_workspace_id, f"/{research_admin_id}"),
            headers=auth_headers(admin_token),
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
            headers=auth_headers(admin_token),
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

        workspace_audit_super = client.get(
            f"/api/v1/workspaces/{research_workspace_id}/audit-logs",
            headers=auth_headers(admin_token),
        )
        assert workspace_audit_super.status_code == 200, workspace_audit_super.text

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

        # Regression: removing a member must clean up their resource grants
        # (previously hit a foreign-key violation and returned 500).
        cascade_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={"name": "Cascade Workspace", "admin_user_id": research_admin_id},
        )
        assert cascade_workspace.status_code == 201, cascade_workspace.text
        cascade_workspace_id = cascade_workspace.json()["workspace"]["id"]

        cascade_kb = client.post(
            knowledge_url(cascade_workspace_id),
            headers=auth_headers(research_token),
            json={"name": "Cascade KB"},
        )
        assert cascade_kb.status_code == 201, cascade_kb.text
        cascade_kb_id = cascade_kb.json()["id"]

        cascade_member_id, _ = create_active_user(
            client,
            admin_token,
            "cascade-member",
        )
        added_grant_member = client.post(
            members_url(cascade_workspace_id),
            headers=auth_headers(research_token),
            json={"user_id": cascade_member_id, "role": "member"},
        )
        assert added_grant_member.status_code == 201, added_grant_member.text

        granted = client.put(
            knowledge_url(
                cascade_workspace_id,
                f"/{cascade_kb_id}/permissions/{cascade_member_id}",
            ),
            headers=auth_headers(research_token),
            json={"permission": "view"},
        )
        assert granted.status_code == 200, granted.text

        removed_grant_member = client.delete(
            members_url(cascade_workspace_id, f"/{cascade_member_id}"),
            headers=auth_headers(research_token),
        )
        assert removed_grant_member.status_code == 204, removed_grant_member.text

        permissions = client.get(
            knowledge_url(cascade_workspace_id, f"/{cascade_kb_id}/permissions"),
            headers=auth_headers(research_token),
        )
        assert permissions.status_code == 200, permissions.text
        assert permissions.json() == []

        model_id, agent_id, agent_run_id, mcp_server_id, task_id = asyncio.run(
            seed_workspace_dependencies(
                cascade_workspace_id,
                cascade_kb_id,
                research_admin_id,
            )
        )

        # A queued/running knowledge task must stop the delete before any
        # database or external-storage state is removed.
        task_blocked_delete = client.delete(
            f"/api/v1/workspaces/{cascade_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert task_blocked_delete.status_code == 409, task_blocked_delete.text
        cascade_still_exists = client.get(
            f"/api/v1/workspaces/{cascade_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert cascade_still_exists.status_code == 200, cascade_still_exists.text
        asyncio.run(fail_knowledge_task(task_id))

        storage = knowledge_object_storage(settings())
        retry_object_key = f"{cascade_workspace_id}/{cascade_kb_id}/retry.txt"
        storage.put_bytes(retry_object_key, b"retry cleanup")
        retry_object_path = storage.path(retry_object_key)

        def fail_storage_cleanup(path) -> None:
            raise OSError("storage unavailable")

        original_rmtree = object_storage_module.shutil.rmtree
        object_storage_module.shutil.rmtree = fail_storage_cleanup
        try:
            # Regression: every workspace-owned graph is removed under real
            # FK enforcement, while external cleanup failure remains retryable.
            cascade_delete = client.delete(
                f"/api/v1/workspaces/{cascade_workspace_id}",
                headers=auth_headers(admin_token),
            )
        finally:
            object_storage_module.shutil.rmtree = original_rmtree
        assert cascade_delete.status_code == 204, cascade_delete.text
        cleanup = asyncio.run(get_storage_cleanup(cascade_kb_id))
        assert cleanup.attempts == 1
        assert cleanup.last_error == "OSError: storage unavailable"
        assert retry_object_path.is_file()

        asyncio.run(
            knowledge_cleanup.run_knowledge_storage_cleanup(cleanup.id, settings())
        )
        asyncio.run(assert_storage_cleanup_finished(cleanup.id))
        assert not retry_object_path.exists()

        cascade_missing = client.get(
            f"/api/v1/workspaces/{cascade_workspace_id}",
            headers=auth_headers(admin_token),
        )
        assert cascade_missing.status_code == 404, cascade_missing.text

        cascade_kb_missing = client.get(
            knowledge_url(cascade_workspace_id, f"/{cascade_kb_id}"),
            headers=auth_headers(research_token),
        )
        assert cascade_kb_missing.status_code == 404, cascade_kb_missing.text

        asyncio.run(
            assert_workspace_cascade_deleted(
                cascade_workspace_id,
                cascade_kb_id,
                model_id,
                agent_id,
                agent_run_id,
                mcp_server_id,
            )
        )

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

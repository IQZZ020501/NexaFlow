import asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from tests.support import (
    ADMIN_PASSWORD,
    BOOTSTRAP_ADMIN_PASSWORD,
    MANAGED_USER_INITIAL_PASSWORD,
    auth_headers,
    login,
    settings as test_settings,
    test_client,
)
from app.api.v1.endpoints.auth import REFRESH_TOKEN_COOKIE
from app.entities.user import RefreshSession
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.security import hash_refresh_token
from app.infrastructure import agent_rate_limit
from app.infrastructure.agent_rate_limit import LoginRateLimitExceeded
from app.infrastructure.session import get_session_factory
from app.infrastructure.system_log import SystemLog


async def get_system_log_events() -> list[str]:
    async with get_session_factory()() as db:
        result = await db.scalars(select(SystemLog.event))
        return list(result.all())


async def get_refresh_session(token: str) -> RefreshSession | None:
    async with get_session_factory()() as db:
        return await user_repository.get_active_refresh_session(
            db,
            hash_refresh_token(token),
            utc_now(),
        )


async def check_login_rate_limit() -> None:
    class FakeRedis:
        args: tuple = ()

        async def eval(self, *args):
            self.args = args
            return [11, 1, 42, 42]

    redis = FakeRedis()
    with patch.object(agent_rate_limit, "_rate_limit_redis", return_value=redis):
        try:
            await agent_rate_limit.enforce_login_rate_limit(
                test_settings(),
                "rate-limited-user",
                "203.0.113.10",
            )
            raise AssertionError("expected LoginRateLimitExceeded")
        except LoginRateLimitExceeded as exc:
            assert exc.retry_after == 42
    assert "rate-limited-user" not in repr(redis.args)


async def seed_owned_mcp_source(
    workspace_id: str,
    user_id: str,
) -> tuple[str, str]:
    from app.entities.tools import McpServer, ToolSource
    from app.infrastructure.repositories import mcp as mcp_repository
    from app.infrastructure.repositories import tools as tools_repository

    async with get_session_factory()() as db:
        server = await mcp_repository.create_mcp_server(
            db,
            McpServer(
                workspace_id=workspace_id,
                name="Analyst MCP",
                url="https://analyst.example.com/mcp",
                created_by_user_id=user_id,
            ),
        )
        source = await tools_repository.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=server.id,
                kind="mcp",
                name=server.name,
                created_by_user_id=user_id,
            ),
        )
        await db.commit()
        return server.id, source.id


async def assert_owned_mcp_source_tombstoned(
    workspace_id: str,
    server_id: str,
    source_id: str,
) -> None:
    from app.infrastructure.repositories import mcp as mcp_repository
    from app.infrastructure.repositories import tools as tools_repository

    async with get_session_factory()() as db:
        assert await mcp_repository.get_mcp_server_by_id(db, server_id) is None
        source = await tools_repository.get_tool_source(db, workspace_id, source_id)
        assert source is not None
        assert source.status == "archived"
        assert source.mcp_server_id is None
        assert source.created_by_user_id is None


async def seed_retained_tool_invocation(
    workspace_id: str,
    user_id: str,
    *,
    bound_by_user_id: str | None = None,
) -> None:
    from app.entities.tools import ToolInvocation
    from app.infrastructure.repositories import tools as tools_repository

    async with get_session_factory()() as db:
        tool = next(
            item
            for item in await tools_repository.list_tools(db, workspace_id)
            if item.stable_key == "current_time"
        )
        assert tool.current_version_id is not None
        await tools_repository.save_tool_invocation(
            db,
            ToolInvocation(
                workspace_id=workspace_id,
                origin="test",
                invocation_id=f"identity-{user_id}",
                execution_user_id=user_id,
                access_source="console",
                tool_id=tool.id,
                tool_version_id=tool.current_version_id,
                policy_snapshot={
                    "tool_snapshot": {"bound_by_user_id": bound_by_user_id}
                }
                if bound_by_user_id is not None
                else {},
                arguments={},
                arguments_hash="a" * 64,
                idempotency_key=f"identity-{user_id}",
            ),
        )
        await db.commit()


async def seed_agent_publication_audit(
    workspace_id: str,
    published_by_user_id: str,
    created_by_user_id: str,
    bound_by_user_id: str | None = None,
) -> str:
    from app.capabilities.llm.registry import RegisteredModel
    from app.entities.agents import Agent, AgentPublicationVersion
    from app.infrastructure.repositories import agent as agent_repository

    async with get_session_factory()() as db:
        model_id = await db.scalar(
            select(RegisteredModel.id).where(
                RegisteredModel.workspace_id == workspace_id
            )
        )
        if model_id is None:
            model = RegisteredModel(
                workspace_id=workspace_id,
                name="Publication audit model",
                provider="publication_audit_provider",
                provider_type="openai_compatible",
                api_base="",
                model_type="LLM",
                model_name="publication-audit-model",
                status="active",
                created_by_user_id=created_by_user_id,
            )
            db.add(model)
            await db.flush()
            model_id = model.id
        agent = await agent_repository.create_agent(
            db,
            Agent(
                workspace_id=workspace_id,
                name=f"Publication audit {utc_now().isoformat()}",
                instructions="Keep this publication immutable.",
                model_id=model_id,
                created_by_user_id=created_by_user_id,
            ),
        )
        await agent_repository.create_agent_publication_version(
            db,
            AgentPublicationVersion(
                workspace_id=workspace_id,
                agent_id=agent.id,
                configuration_snapshot={},
                resource_snapshot={
                    "tools": (
                        [{"bound_by_user_id": bound_by_user_id}]
                        if bound_by_user_id is not None
                        else []
                    )
                },
                configuration_hash="a" * 64,
                published_by_user_id=published_by_user_id,
            ),
        )
        await db.commit()
        return agent.id


async def seed_agent_run_binder_audit(
    workspace_id: str,
    bound_by_user_id: str,
    created_by_user_id: str,
) -> None:
    from app.entities.agents import AgentRun
    from app.infrastructure.repositories import agent as agent_repository

    agent_id = await seed_agent_publication_audit(
        workspace_id,
        created_by_user_id,
        created_by_user_id,
    )
    async with get_session_factory()() as db:
        agent = await agent_repository.get_agent_by_id(db, agent_id)
        assert agent is not None and agent.workspace_id == workspace_id
        await agent_repository.create_agent_run(
            db,
            AgentRun(
                workspace_id=workspace_id,
                agent_id=agent.id,
                requested_by_user_id=created_by_user_id,
                execution_user_id=created_by_user_id,
                model_id=agent.model_id,
                configuration_source="legacy",
                tool_snapshots=[{"bound_by_user_id": bound_by_user_id}],
                status="succeeded",
            ),
        )
        await db.commit()


async def seed_tool_grant(workspace_id: str, user_id: str, actor_id: str) -> None:
    from app.entities.resource_permission import ResourcePermission
    from app.infrastructure.repositories import resource_permission as permission_repository
    from app.infrastructure.repositories import tools as tools_repository

    async with get_session_factory()() as db:
        tool = next(
            item
            for item in await tools_repository.list_tools(db, workspace_id)
            if item.stable_key == "current_time"
        )
        await permission_repository.create_resource_permission(
            db,
            ResourcePermission(
                workspace_id=workspace_id,
                resource_type="tool",
                resource_id=tool.id,
                user_id=user_id,
                permission="use",
                created_by_user_id=actor_id,
            ),
        )
        await db.commit()


def main() -> None:
    asyncio.run(check_login_rate_limit())
    with test_client() as client:
        first_login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_ADMIN_PASSWORD},
        )
        assert first_login_response.status_code == 200, first_login_response.text
        first_login = first_login_response.json()
        admin_token = first_login["access_token"]
        assert first_login["expires_in"] == 24 * 60 * 60
        assert first_login["must_change_password"] is True
        assert "refresh_token" not in first_login
        refresh_token = client.cookies.get(REFRESH_TOKEN_COOKIE)
        assert refresh_token
        set_cookie = first_login_response.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "path=/api/v1/auth" in set_cookie
        stored_refresh_session = asyncio.run(get_refresh_session(refresh_token))
        assert stored_refresh_session is not None
        assert stored_refresh_session.token_hash == hash_refresh_token(refresh_token)
        assert stored_refresh_session.token_hash != refresh_token

        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["expires_in"] == 24 * 60 * 60

        logged_out = client.post("/api/v1/auth/logout")
        assert logged_out.status_code == 204, logged_out.text
        assert asyncio.run(get_refresh_session(refresh_token)) is None
        assert client.post("/api/v1/auth/refresh").status_code == 401

        blocked = client.get("/api/v1/workspaces", headers=auth_headers(admin_token))
        assert blocked.status_code == 403, blocked.text

        weak_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": "abcdef"},
        )
        assert weak_password.status_code == 422, weak_password.text

        missing_current_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": ADMIN_PASSWORD},
        )
        assert missing_current_password.status_code == 400, missing_current_password.text

        changed = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": BOOTSTRAP_ADMIN_PASSWORD,
                "new_password": ADMIN_PASSWORD,
            },
        )
        assert changed.status_code == 204, changed.text
        assert client.post("/api/v1/auth/refresh").status_code == 200

        rotated_password = "NexaFlow@123456."
        wrong_current_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": "Wrong@12345.",
                "new_password": rotated_password,
            },
        )
        assert wrong_current_password.status_code == 400, wrong_current_password.text

        repeated_change = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": ADMIN_PASSWORD,
                "new_password": rotated_password,
            },
        )
        assert repeated_change.status_code == 204, repeated_change.text

        same_password = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(admin_token),
            json={
                "current_password": rotated_password,
                "new_password": rotated_password,
            },
        )
        assert same_password.status_code == 400, same_password.text

        second_login = login(client, "admin", rotated_password)
        admin_token = second_login["access_token"]
        assert second_login["must_change_password"] is False

        failed_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Wrong@12345."},
        )
        assert failed_login.status_code == 401, failed_login.text

        with patch(
            "app.application.identity.enforce_login_rate_limit",
            new=AsyncMock(side_effect=LoginRateLimitExceeded(42)),
        ):
            limited_login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": rotated_password},
            )
        assert limited_login.status_code == 429, limited_login.text
        assert limited_login.headers["retry-after"] == "42"

        users = client.get("/api/v1/admin/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        admin_user = users.json()[0]
        assert admin_user["username"] == "admin"
        assert admin_user["is_active"] is True
        assert admin_user["created_at"]
        admin_user_id = admin_user["id"]
        identity_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Identity Tool Lifecycle",
                "admin_user_id": admin_user_id,
            },
        )
        assert identity_workspace.status_code == 201, identity_workspace.text
        identity_workspace_id = identity_workspace.json()["workspace"]["id"]

        created_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "analyst",
                "email": "analyst@example.com",
                "name": "Analyst",
            },
        )
        assert created_user.status_code == 201, created_user.text
        payload = created_user.json()
        assert payload["initial_password"] == MANAGED_USER_INITIAL_PASSWORD
        assert payload["user"]["username"] == "analyst"
        assert payload["user"]["workspaces"] == []
        analyst_id = payload["user"]["id"]
        analyst_login = login(client, "analyst", payload["initial_password"])
        assert analyst_login["must_change_password"] is True
        analyst_token = analyst_login["access_token"]
        analyst_refresh_token = client.cookies.get(REFRESH_TOKEN_COOKIE)
        assert analyst_refresh_token

        analyst_self_password = "AnalystSelf@123"
        analyst_missing_current = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(analyst_token),
            json={"new_password": analyst_self_password},
        )
        assert analyst_missing_current.status_code == 400, analyst_missing_current.text
        analyst_wrong_current = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(analyst_token),
            json={
                "current_password": "Wrong@12345.",
                "new_password": analyst_self_password,
            },
        )
        assert analyst_wrong_current.status_code == 400, analyst_wrong_current.text
        analyst_self_changed = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers(analyst_token),
            json={
                "current_password": payload["initial_password"],
                "new_password": analyst_self_password,
            },
        )
        assert analyst_self_changed.status_code == 204, analyst_self_changed.text

        updated_user = client.patch(
            f"/api/v1/admin/users/{analyst_id}",
            headers=auth_headers(admin_token),
            json={"name": "Data Analyst", "is_active": True},
        )
        assert updated_user.status_code == 200, updated_user.text
        assert updated_user.json()["name"] == "Data Analyst"

        analyst_changed_password = "AnalystPass@123"
        change_managed_password = client.post(
            f"/api/v1/admin/users/{analyst_id}/change-password",
            headers=auth_headers(admin_token),
            json={"new_password": analyst_changed_password},
        )
        assert change_managed_password.status_code == 200, change_managed_password.text
        assert change_managed_password.json()["must_change_password"] is False
        assert client.post("/api/v1/auth/refresh").status_code == 401
        assert asyncio.run(get_refresh_session(analyst_refresh_token)) is None
        analyst_changed_login = login(client, "analyst", analyst_changed_password)
        assert analyst_changed_login["must_change_password"] is False

        self_disable = client.patch(
            f"/api/v1/admin/users/{admin_user_id}",
            headers=auth_headers(admin_token),
            json={"is_active": False},
        )
        assert self_disable.status_code == 400, self_disable.text

        self_delete = client.delete(
            f"/api/v1/admin/users/{admin_user_id}",
            headers=auth_headers(admin_token),
        )
        assert self_delete.status_code == 400, self_delete.text

        server_id, source_id = asyncio.run(
            seed_owned_mcp_source(identity_workspace_id, analyst_id)
        )

        deleted_user = client.delete(
            f"/api/v1/admin/users/{analyst_id}",
            headers=auth_headers(admin_token),
        )
        assert deleted_user.status_code == 204, deleted_user.text
        asyncio.run(
            assert_owned_mcp_source_tombstoned(
                identity_workspace_id,
                server_id,
                source_id,
            )
        )

        retained_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "retained-tool-user",
                "email": "retained-tool-user@example.com",
                "name": "Retained Tool User",
            },
        )
        assert retained_user.status_code == 201, retained_user.text
        retained_user_id = retained_user.json()["user"]["id"]
        asyncio.run(
            seed_retained_tool_invocation(identity_workspace_id, retained_user_id)
        )
        retained_delete = client.delete(
            f"/api/v1/admin/users/{retained_user_id}",
            headers=auth_headers(admin_token),
        )
        assert retained_delete.status_code == 409, retained_delete.text
        assert "Tool binding or invocation" in retained_delete.json()["detail"]

        publication_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "publication-audit-user",
                "email": "publication-audit-user@example.com",
                "name": "Publication Audit User",
            },
        )
        assert publication_user.status_code == 201, publication_user.text
        publication_user_id = publication_user.json()["user"]["id"]
        asyncio.run(
            seed_agent_publication_audit(
                identity_workspace_id,
                publication_user_id,
                admin_user_id,
            )
        )
        publication_delete = client.delete(
            f"/api/v1/admin/users/{publication_user_id}",
            headers=auth_headers(admin_token),
        )
        assert publication_delete.status_code == 409, publication_delete.text
        assert "Agent publication" in publication_delete.json()["detail"]

        publication_binder = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "publication-binder-user",
                "email": "publication-binder-user@example.com",
                "name": "Publication Binder User",
            },
        )
        assert publication_binder.status_code == 201, publication_binder.text
        publication_binder_id = publication_binder.json()["user"]["id"]
        asyncio.run(
            seed_agent_publication_audit(
                identity_workspace_id,
                admin_user_id,
                admin_user_id,
                publication_binder_id,
            )
        )
        binder_delete = client.delete(
            f"/api/v1/admin/users/{publication_binder_id}",
            headers=auth_headers(admin_token),
        )
        assert binder_delete.status_code == 409, binder_delete.text
        assert "Agent publication" in binder_delete.json()["detail"]

        run_binder = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "run-binder-user",
                "email": "run-binder-user@example.com",
                "name": "Run Binder User",
            },
        )
        assert run_binder.status_code == 201, run_binder.text
        run_binder_id = run_binder.json()["user"]["id"]
        asyncio.run(
            seed_agent_run_binder_audit(
                identity_workspace_id,
                run_binder_id,
                admin_user_id,
            )
        )
        run_binder_delete = client.delete(
            f"/api/v1/admin/users/{run_binder_id}",
            headers=auth_headers(admin_token),
        )
        assert run_binder_delete.status_code == 409, run_binder_delete.text
        assert "Agent publication" in run_binder_delete.json()["detail"]

        invocation_binder = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "invocation-binder-user",
                "email": "invocation-binder-user@example.com",
                "name": "Invocation Binder User",
            },
        )
        assert invocation_binder.status_code == 201, invocation_binder.text
        invocation_binder_id = invocation_binder.json()["user"]["id"]
        asyncio.run(
            seed_retained_tool_invocation(
                identity_workspace_id,
                admin_user_id,
                bound_by_user_id=invocation_binder_id,
            )
        )
        invocation_binder_delete = client.delete(
            f"/api/v1/admin/users/{invocation_binder_id}",
            headers=auth_headers(admin_token),
        )
        assert invocation_binder_delete.status_code == 409, invocation_binder_delete.text
        assert (
            "Tool binding or invocation"
            in invocation_binder_delete.json()["detail"]
        )

        grant_only_user = client.post(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token),
            json={
                "username": "grant-only-user",
                "email": "grant-only-user@example.com",
                "name": "Grant Only User",
            },
        )
        assert grant_only_user.status_code == 201, grant_only_user.text
        grant_only_user_id = grant_only_user.json()["user"]["id"]
        membership = client.post(
            f"/api/v1/workspaces/{identity_workspace_id}/members",
            headers=auth_headers(admin_token),
            json={"user_id": grant_only_user_id, "role": "member"},
        )
        assert membership.status_code == 201, membership.text
        asyncio.run(
            seed_tool_grant(
                identity_workspace_id,
                grant_only_user_id,
                admin_user_id,
            )
        )
        grant_only_delete = client.delete(
            f"/api/v1/admin/users/{grant_only_user_id}",
            headers=auth_headers(admin_token),
        )
        assert grant_only_delete.status_code == 204, grant_only_delete.text

        users = client.get("/api/v1/admin/users", headers=auth_headers(admin_token))
        assert users.status_code == 200, users.text
        assert all(item["id"] != analyst_id for item in users.json())
        deleted_login = client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": analyst_changed_password},
        )
        assert deleted_login.status_code == 401, deleted_login.text

        audit_logs = client.get("/api/v1/admin/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "user.create" in actions
        assert "user.update" in actions
        assert "user.change_password" in actions
        assert "user.delete" in actions

        events = asyncio.run(get_system_log_events())
        assert "auth.login_failed" in events


if __name__ == "__main__":
    main()

"""Coverage suite for the agent services / permissions / repository / tasks domain.

Run from backend/:
    uv run python -m tests.agent_services_coverage

Plain Python script suite (no pytest).  Failure = exception or failed assertion.
"""

import asyncio
import dataclasses
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace

from fastapi import HTTPException

# Import support FIRST: it configures the environment (in-memory DB, eager
# Celery, JWT keys) before any app module is imported.
from tests.support import (  # noqa: F401
    activate_admin,
    activate_user,
    auth_headers,
    create_active_user,
    settings as test_settings,
    test_client,
)

from app.capabilities.llm.models import RegisteredModel
from app.capabilities.mcp.client import McpDiscovery
from app.entities.agents import (
    Agent,
    AgentApiCredential,
    AgentRun,
    AgentRunEvent,
    AgentToolCall,
)
from app.entities.user import User
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import knowledge as kb_repository
from app.infrastructure.session import get_session_factory
from app.schemas.agent import (
    AgentCreateRequest,
    AgentInteractionConfig,
    AgentMcpToolRef,
    AgentUpdateRequest,
)
from app.shareddomain.agents import permissions as agent_permissions
from app.shareddomain.agents import services as agent_services
from app.shareddomain.agents.models import AGENT_RUN_UNIFIED_QUEUED_STATUS
from app.shareddomain.tools import services as mcp_services
from app.tasks import agents as agent_tasks
from app.application.agent_executor import RUN_BUSY

MEMBER_PASSWORD = "AgentCoverage@12345."


def agents_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/agents{suffix}"


def knowledge_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge-bases{suffix}"


def mcp_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/mcp-servers{suffix}"


class ModelHandler(BaseHTTPRequestHandler):
    """Minimal chat-completions server used by eager agent run execution."""

    calls: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        ModelHandler.calls.append(body)
        message = {"role": "assistant", "content": "Completed."}
        finish_reason = "stop"

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {
                    "id": "agent-coverage",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": message,
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "agent-coverage",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": finish_reason,
                        }
                    ],
                },
            ]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return

        payload = {
            "id": "agent-coverage",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, format: str, *args) -> None:
        return


@contextmanager
def model_server() -> Iterator[str]:
    ModelHandler.calls = []
    server = HTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def model_payload(api_base: str, name: str = "Coverage LLM") -> dict:
    return {
        "name": name,
        "provider": "model_deepseek_provider",
        "provider_type": "deepseek",
        "model_type": "LLM",
        "model_name": "deepseek-chat",
        "credential": {"api_base": api_base, "api_key": "sk-coverage-1234"},
    }


def create_workspace_user(
    client,
    token: str,
    workspace_id: str,
    username: str,
) -> tuple[str, str]:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members/users",
        headers=auth_headers(token),
        json={
            "username": username,
            "email": f"{username}@example.com",
            "name": username,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], response.json()["initial_password"]


# ---------------------------------------------------------------------------
# Direct (async) DB helpers
# ---------------------------------------------------------------------------

async def insert_registered_model(
    workspace_id: str,
    admin_id: str,
    name: str,
    model_type: str,
    status: str = "active",
) -> str:
    async with get_session_factory()() as db:
        row = RegisteredModel(
            workspace_id=workspace_id,
            name=name,
            provider="model_deepseek_provider",
            provider_type="deepseek",
            api_base="",
            model_type=model_type,
            model_name="coverage-model",
            status=status,
            created_by_user_id=admin_id,
        )
        db.add(row)
        await db.commit()
        return row.id


async def set_knowledge_base_status(kb_id: str, status: str) -> None:
    async with get_session_factory()() as db:
        kb = await kb_repository.get_knowledge_base_by_id(db, kb_id)
        assert kb is not None
        kb.status = status
        await kb_repository.save_knowledge_base(db, kb)
        await db.commit()


async def set_agent_legacy_published(agent_id: str, admin_id: str) -> None:
    """Mark an agent published with a NULL snapshot (legacy publication state)."""
    async with get_session_factory()() as db:
        agent = await agent_repository.get_agent_by_id(db, agent_id)
        assert agent is not None
        agent.published = True
        agent.published_snapshot = None
        agent.published_by_user_id = admin_id
        agent.published_at = utc_now()
        await agent_repository.save_agent(db, agent)
        await db.commit()


# ---------------------------------------------------------------------------
# Direct service-layer tests
# ---------------------------------------------------------------------------

async def exercise_services_http_paths(
    workspace_id: str,
    admin_id: str,
    member_id: str,
    model_id: str,
    embedding_model_id: str,
    disabled_model_id: str,
    kb_id: str,
    mcp_id: str,
) -> None:
    """Exercise service-layer branches that HTTP requests also hit.

    Coverage only traces the portal thread up to the first await, so the
    deep service branches are re-driven synchronously from the main thread.
    """
    actor = User(id=admin_id)
    member = User(id=member_id)

    async with get_session_factory()() as db:
        # get_agent_model error branches
        for bad_model_id, _name in [
            ("ghost-model", None),
            (embedding_model_id, None),
            (disabled_model_id, None),
        ]:
            try:
                await agent_services.get_agent_model(db, workspace_id, bad_model_id)
                raise AssertionError("expected HTTPException")
            except HTTPException as exc:
                assert exc.status_code == 422

        # resolve_agent_knowledge_bases: duplicate ids -> 422
        try:
            await agent_services.resolve_agent_knowledge_bases(
                db, workspace_id, [kb_id, kb_id], actor, "admin"
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 422

        # resolve_agent_knowledge_bases: archived KB -> 422
        await set_knowledge_base_status(kb_id, "archived")
        try:
            try:
                await agent_services.resolve_agent_knowledge_bases(
                    db, workspace_id, [kb_id], actor, "admin"
                )
                raise AssertionError("expected HTTPException")
            except HTTPException as exc:
                assert exc.status_code == 422
        finally:
            await set_knowledge_base_status(kb_id, "active")

        # resolve_agent_knowledge_bases happy path
        resolved = await agent_services.resolve_agent_knowledge_bases(
            db, workspace_id, [kb_id], actor, "admin"
        )
        assert [kb.id for kb in resolved] == [kb_id]

        # accessible_agent_knowledge_bases: active KB appended
        accessible = await agent_services.accessible_agent_knowledge_bases(
            db, workspace_id, [kb_id], actor, "admin"
        )
        assert [kb.id for kb in accessible] == [kb_id]

        # create_agent: full path with KB + MCP binding (incl. workflow graph)
        created = await agent_services.create_agent(
            db,
            workspace_id,
            AgentCreateRequest(
                name="Direct Create",
                description="direct",
                instructions="direct",
                model_id=model_id,
                knowledge_base_ids=[kb_id],
                mcp_tools=[
                    AgentMcpToolRef(
                        server_id=mcp_id, tool_name="lookup_release"
                    )
                ],
            ),
            actor,
            "admin",
        )
        assert created.name == "Direct Create"
        assert created.knowledge_base_ids == [kb_id]
        assert [item.tool_name for item in created.mcp_tools] == [
            "lookup_release"
        ]
        assert [item.server_id for item in created.mcp_tools] == [mcp_id]
        created_agent = await agent_repository.get_agent_by_id(db, created.id)
        assert created_agent is not None

        workflow = await agent_services.create_agent(
            db,
            workspace_id,
            AgentCreateRequest(
                name="Direct Workflow",
                app_type="workflow",
                instructions="w",
                model_id=model_id,
            ),
            actor,
            "admin",
        )
        assert workflow.app_type == "workflow"

        # create_agent: duplicate name -> IntegrityError -> 409
        try:
            await agent_services.create_agent(
                db,
                workspace_id,
                AgentCreateRequest(name="Direct Create", model_id=model_id),
                actor,
                "admin",
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 409

        # get_agent: success path
        fetched_agent = await agent_services.get_agent(
            db, workspace_id, created.id
        )
        assert fetched_agent.id == created.id

        # list_agents + get_agent_response direct
        listed = await agent_services.list_agents(
            db, workspace_id, actor, "admin", limit=10, offset=0
        )
        listed_created = next(item for item in listed if item.id == created.id)
        assert listed_created.created_by_name
        assert listed_created.created_by_username
        response = await agent_services.get_agent_response(
            db, created_agent, actor, "admin"
        )
        assert response.id == created.id

        # member-owned agent: non-admin publish must be forbidden (403)
        member_agent = await agent_services.create_agent(
            db,
            workspace_id,
            AgentCreateRequest(name="Member Owned", model_id=model_id),
            member,
            "member",
        )
        member_agent_entity = await agent_repository.get_agent_by_id(
            db, member_agent.id
        )
        try:
            await agent_services.update_agent(
                db,
                member_agent_entity,
                AgentUpdateRequest(published=True),
                member,
                "member",
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403

        # permissions: list, grant (create + update), revoke
        grants = await agent_permissions.list_agent_permissions(
            db, created_agent
        )
        assert grants == []
        granted = await agent_permissions.upsert_agent_permission(
            db, created_agent, member_id, "view", actor
        )
        assert granted.permission == "view"
        granted_again = await agent_permissions.upsert_agent_permission(
            db, created_agent, member_id, "view", actor
        )
        assert granted_again.permission == "view"
        grants_after = await agent_permissions.list_agent_permissions(
            db, created_agent
        )
        assert len(grants_after) == 1

        # require_agent_view: admin edit / member view / member denied
        assert (
            await agent_permissions.require_agent_view(
                db, created_agent, actor, "admin"
            )
            == "edit"
        )
        assert (
            await agent_permissions.require_agent_view(
                db, created_agent, member, "member"
            )
            == "view"
        )
        denied = await agent_repository.get_agent_by_id(db, created.id)
        denied_agent = Agent(
            id=created.id,
            workspace_id=workspace_id,
            name="denied",
            created_by_user_id=admin_id,
        )
        # revoke the grant first, then a member view must be denied
        await agent_permissions.revoke_agent_permission(
            db, created_agent, member_id, actor
        )
        try:
            await agent_permissions.require_agent_view(
                db, denied_agent, member, "member"
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403

        # upsert to a non-member -> 404
        try:
            await agent_permissions.upsert_agent_permission(
                db, created_agent, "not-a-member", "view", actor
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 404

        # revoke again -> 404
        try:
            await agent_permissions.revoke_agent_permission(
                db, created_agent, member_id, actor
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 404

        # update_agent: full-field change (name/desc/interaction/instructions/
        # model/knowledge mode/status), bindings replacement, mcp replacement
        second_llm_id = await insert_registered_model(
            workspace_id, admin_id, "Direct Second LLM", "LLM"
        )
        updated = await agent_services.update_agent(
            db,
            created_agent,
            AgentUpdateRequest(
                name="Direct Updated",
                description="changed",
                interaction_config=AgentInteractionConfig(prologue="direct hi"),
                instructions="changed instructions",
                model_id=second_llm_id,
                knowledge_query_mode="agentic",
                status="active",
                knowledge_base_ids=[],
                mcp_tools=[],
            ),
            actor,
            "admin",
        )
        assert updated.name == "Direct Updated"
        assert updated.knowledge_base_ids == []
        assert updated.mcp_tools == []
        assert updated.knowledge_query_mode == "agentic"
        assert updated.model_id == second_llm_id

        # app_type conflict -> 409
        try:
            await agent_services.update_agent(
                db,
                created_agent,
                AgentUpdateRequest(app_type="workflow"),
                actor,
                "admin",
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 409

        # invalid status -> 422
        try:
            await agent_services.update_agent(
                db,
                created_agent,
                AgentUpdateRequest(status="bogus"),
                actor,
                "admin",
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 422

        # publish (active) -> snapshot recorded
        published = await agent_services.update_agent(
            db,
            created_agent,
            AgentUpdateRequest(published=True),
            actor,
            "admin",
        )
        assert published.published is True
        assert published.published_by_user_id == admin_id
        assert published.published_at is not None

        # non-admin publish -> 403
        try:
            await agent_services.update_agent(
                db,
                created_agent,
                AgentUpdateRequest(published=False),
                member,
                "member",
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403

        # duplicate-name update -> IntegrityError -> 409
        await agent_services.create_agent(
            db,
            workspace_id,
            AgentCreateRequest(name="Name Collision", model_id=model_id),
            actor,
            "admin",
        )
        try:
            await agent_services.update_agent(
                db,
                created_agent,
                AgentUpdateRequest(name="Name Collision"),
                actor,
                "admin",
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 409

        # legacy publication snapshot preserved across a config change
        await set_agent_legacy_published(created.id, admin_id)
        fresh = await agent_repository.get_agent_by_id(db, created.id)
        legacy_updated = await agent_services.update_agent(
            db,
            fresh,
            AgentUpdateRequest(name="Direct Legacy"),
            actor,
            "admin",
        )
        assert legacy_updated.name == "Direct Legacy"
        assert legacy_updated.published is True

        # delete_agent success path (audit + upload cleanup + graph deletion)
        delete_target = await agent_services.create_agent(
            db,
            workspace_id,
            AgentCreateRequest(name="Delete Target", model_id=model_id),
            actor,
            "admin",
        )
        delete_entity = await agent_repository.get_agent_by_id(
            db, delete_target.id
        )
        await agent_services.delete_agent(db, delete_entity, actor, "admin")
        assert (
            await agent_repository.get_agent_by_id(db, delete_target.id) is None
        )

        # workflow agent publish is rejected through the agent endpoint
        workflow_entity = await agent_repository.get_agent_by_id(db, workflow.id)
        try:
            await agent_services.update_agent(
                db,
                workflow_entity,
                AgentUpdateRequest(published=True),
                actor,
                "admin",
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 409

        # disabled workflow agent resets publication state
        await agent_services.update_agent(
            db,
            workflow_entity,
            AgentUpdateRequest(status="disabled"),
            actor,
            "admin",
        )


async def exercise_services_direct(
    workspace_id: str,
    agent_id: str,
    kb_id: str,
    admin_id: str,
    model_id: str,
) -> None:
    async with get_session_factory()() as db:
        actor = User(id=admin_id)

        # agent_publication_from_snapshot: None branch and snapshot branch
        assert (
            agent_services.agent_publication_from_snapshot(
                Agent(published_snapshot=None)
            )
            is None
        )
        published = agent_services.agent_publication_from_snapshot(
            Agent(
                published_snapshot={
                    "name": "Snap",
                    "description": "d",
                    "instructions": "i",
                    "model_id": "m",
                    "knowledge_query_mode": "required",
                    "knowledge_base_ids": [],
                    "mcp_tools": [],
                    "interaction_config": {"prologue": "hello"},
                }
            )
        )
        assert published is not None
        assert published.name == "Snap"
        assert published.interaction_config["prologue"] == "hello"

        # get_agent -> 404 for a missing agent
        try:
            await agent_services.get_agent(db, workspace_id, "ghost-agent")
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 404

        # delete_agent: lock_agent returns None -> 404
        ghost = Agent(
            id="ghost-agent",
            workspace_id=workspace_id,
            name="ghost",
            created_by_user_id=admin_id,
        )
        try:
            await agent_services.delete_agent(db, ghost, actor, "admin")
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 404

        # accessible_agent_knowledge_bases: HTTPException 403/404 -> skip
        original_get = agent_services.get_knowledge_base
        original_require = agent_services.require_knowledge_base_permission

        async def not_found(*_args, **_kwargs):
            raise HTTPException(404, "nope")

        agent_services.get_knowledge_base = not_found
        try:
            result = await agent_services.accessible_agent_knowledge_bases(
                db, workspace_id, [kb_id], actor, "admin"
            )
            assert result == []
        finally:
            agent_services.get_knowledge_base = original_get

        async def denied(*_args, **_kwargs):
            raise HTTPException(403, "denied")

        agent_services.require_knowledge_base_permission = denied
        try:
            result = await agent_services.accessible_agent_knowledge_bases(
                db, workspace_id, [kb_id], actor, "admin"
            )
            assert result == []
        finally:
            agent_services.require_knowledge_base_permission = original_require

        # accessible_agent_knowledge_bases: non-403/404 HTTPException re-raised
        async def boom(*_args, **_kwargs):
            raise HTTPException(500, "boom")

        agent_services.get_knowledge_base = boom
        try:
            try:
                await agent_services.accessible_agent_knowledge_bases(
                    db, workspace_id, [kb_id], actor, "admin"
                )
                raise AssertionError("expected HTTPException")
            except HTTPException as exc:
                assert exc.status_code == 500
        finally:
            agent_services.get_knowledge_base = original_get

        # upsert_agent_permission with an invalid permission -> 422
        try:
            await agent_permissions.upsert_agent_permission(
                db,
                Agent(
                    id=agent_id,
                    workspace_id=workspace_id,
                    name="Perm Agent",
                    created_by_user_id=admin_id,
                ),
                "some-user",
                "edit",
                actor,
            )
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 422

        # repository primitive round-trips
        saved = await agent_repository.create_agent(
            db,
            Agent(
                workspace_id=workspace_id,
                name="Repo Round Trip",
                description="d",
                instructions="i",
                model_id=model_id,
                created_by_user_id=admin_id,
            ),
        )
        await db.commit()
        assert saved.id
        saved.name = "Repo Round Trip 2"
        resaved = await agent_repository.save_agent(db, saved)
        await db.commit()
        assert resaved.name == "Repo Round Trip 2"
        refreshed = await agent_repository.refresh_agent(db, saved)
        assert refreshed.name == "Repo Round Trip 2"
        locked = await agent_repository.lock_agent(db, saved.id)
        assert locked is not None and locked.name == "Repo Round Trip 2"
        assert await agent_repository.lock_agent(db, "ghost-agent") is None
        await agent_repository.delete_agent_graph(
            db, workspace_id, saved.id, "agent"
        )
        await db.commit()
        assert await agent_repository.get_agent_by_id(db, saved.id) is None

        # list_agents with and without include_all
        all_agents = await agent_repository.list_agents(
            db, workspace_id, admin_id, "agent", True
        )
        assert isinstance(all_agents, list)
        owned = await agent_repository.list_agents(
            db, workspace_id, admin_id, "agent", False, limit=10, offset=0
        )
        assert isinstance(owned, list)


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

def _run_entity(
    workspace_id: str,
    agent_id: str,
    user_id: str,
    conversation_id: str,
    *,
    status: str = "succeeded",
    summary: str = "",
    created_at=None,
    access_source: str = "console",
    consumer_id: str | None = None,
    attempts: int = 0,
    max_attempts: int = 3,
    worker_task_id: str | None = None,
    lease_expires_at=None,
    configuration_source: str = "legacy",
) -> AgentRun:
    return AgentRun(
        workspace_id=workspace_id,
        agent_id=agent_id,
        requested_by_user_id=user_id if access_source == "console" else None,
        execution_user_id=user_id,
        access_source=access_source,
        consumer_id=consumer_id or user_id,
        conversation_id=conversation_id,
        goal="repo goal",
        instructions="repo instructions",
        status=status,
        context_summary=summary,
        model_id="model-1",
        model_name="coverage",
        trace_id=new_id(),
        configuration_source=configuration_source,
        attempts=attempts,
        max_attempts=max_attempts,
        worker_task_id=worker_task_id,
        lease_expires_at=lease_expires_at,
        created_at=created_at or utc_now(),
    )


async def exercise_repository_credentials(
    workspace_id: str,
    agent_id: str,
    admin_id: str,
) -> None:
    async with get_session_factory()() as db:
        cred = AgentApiCredential(
            workspace_id=workspace_id,
            agent_id=agent_id,
            name="ci-token",
            token_hash="hash-original",
            hint="ci-…",
            created_by_user_id=admin_id,
        )
        saved = await agent_repository.create_agent_api_credential(db, cred)
        await db.commit()
        assert saved.id == cred.id

        rows = await agent_repository.list_agent_api_credentials(db, agent_id)
        assert rows[0].id == cred.id  # newest first
        assert cred.id in {row.id for row in rows}

        by_id = await agent_repository.get_agent_api_credential_by_id(db, cred.id)
        assert by_id is not None and by_id.name == "ci-token"

        by_ids = await agent_repository.list_agent_api_credentials_by_ids(
            db, [cred.id]
        )
        assert [row.id for row in by_ids] == [cred.id]
        assert await agent_repository.list_agent_api_credentials_by_ids(db, []) == []

        by_hash = await agent_repository.get_agent_api_credential_by_hash(
            db, "hash-original"
        )
        assert by_hash is not None and by_hash.id == cred.id

        assert (
            await agent_repository.mark_agent_api_credential_used(
                db, cred.id, utc_now()
            )
            is True
        )
        assert (
            await agent_repository.rotate_agent_api_credential(
                db, cred.id, "hash-original", "hash-rotated", "ci-…2"
            )
            is True
        )
        # rotation with a stale hash does not match
        assert (
            await agent_repository.rotate_agent_api_credential(
                db, cred.id, "hash-original", "hash-nope", "ci-…"
            )
            is False
        )
        assert (
            await agent_repository.revoke_agent_api_credential(
                db, cred.id, utc_now()
            )
            is True
        )
        # double revoke / revoked lookup / mark-used-after-revoke all no-op
        assert (
            await agent_repository.revoke_agent_api_credential(
                db, cred.id, utc_now()
            )
            is False
        )
        assert (
            await agent_repository.get_agent_api_credential_by_hash(
                db, "hash-rotated"
            )
            is None
        )
        assert (
            await agent_repository.mark_agent_api_credential_used(
                db, cred.id, utc_now()
            )
            is False
        )


async def exercise_repository_bindings(
    workspace_id: str,
    agent_id: str,
    kb_id: str,
    mcp_server_id: str,
) -> None:
    async with get_session_factory()() as db:
        assert await agent_repository.list_binding_map(db, []) == {}
        assert await agent_repository.list_binding_map(db, [agent_id]) == {
            agent_id: []
        }
        assert await agent_repository.list_mcp_binding_map(db, []) == {}
        assert await agent_repository.list_mcp_binding_map(db, [agent_id]) == {
            agent_id: []
        }

        agent = Agent(id=agent_id, workspace_id=workspace_id)
        await agent_repository.replace_bindings(db, agent, [kb_id])
        await agent_repository.replace_mcp_bindings(
            db,
            agent,
            [{"server_id": mcp_server_id, "tool_name": "lookup_release"}],
        )
        await db.commit()
        assert await agent_repository.list_binding_map(db, [agent_id]) == {
            agent_id: [kb_id]
        }
        assert await agent_repository.list_mcp_binding_map(db, [agent_id]) == {
            agent_id: [{"server_id": mcp_server_id, "tool_name": "lookup_release"}]
        }

        # replace again (delete + re-add path)
        await agent_repository.replace_bindings(db, agent, [])
        await agent_repository.replace_mcp_bindings(db, agent, [])
        await db.commit()
        assert await agent_repository.list_binding_map(db, [agent_id]) == {
            agent_id: []
        }
        assert await agent_repository.list_mcp_binding_map(db, [agent_id]) == {
            agent_id: []
        }


async def exercise_repository_runs(
    workspace_id: str,
    admin_id: str,
    model_id: str,
) -> None:
    now = utc_now()
    t1 = now - timedelta(minutes=30)
    t2 = now - timedelta(minutes=20)
    t3 = now - timedelta(minutes=10)

    async with get_session_factory()() as db:
        # dedicated agent so run counts are deterministic
        agent = await agent_repository.create_agent(
            db,
            Agent(
                workspace_id=workspace_id,
                name="Repo Runs Agent",
                instructions="i",
                model_id=model_id,
                created_by_user_id=admin_id,
            ),
        )
        await db.commit()
        agent_id = agent.id

        r1 = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-1",
                status="succeeded", summary="summary-a", created_at=t1,
            ),
        )
        r1b = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-1",
                status="succeeded", summary="", created_at=t1 + timedelta(minutes=1),
            ),
        )
        r2 = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-1",
                status="failed", created_at=t2,
            ),
        )
        r3 = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-2",
                status="succeeded", created_at=t3,
            ),
        )
        r4 = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-api",
                status="succeeded", access_source="api", consumer_id="consumer-x",
                created_at=t3,
            ),
        )
        await db.commit()

        # list_agent_runs: filters + pagination
        all_runs = await agent_repository.list_agent_runs(
            db, agent_id, "console", admin_id
        )
        assert len(all_runs) == 4
        succeeded = await agent_repository.list_agent_runs(
            db, agent_id, "console", admin_id, status="succeeded"
        )
        assert len(succeeded) == 3  # r1, r1b, r3
        queued_unified = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id,
                agent_id,
                admin_id,
                "conv-filter-unified",
                status="queued_v2",
                configuration_source="draft",
                created_at=t2,
            ),
        )
        await db.commit()
        queued = await agent_repository.list_agent_runs(
            db, agent_id, "console", admin_id, status="queued"
        )
        assert [run.id for run in queued] == [queued_unified.id]
        conv1 = await agent_repository.list_agent_runs(
            db, agent_id, "console", admin_id, conversation_id="conv-1"
        )
        assert len(conv1) == 3
        both = await agent_repository.list_agent_runs(
            db, agent_id, "console", admin_id,
            status="succeeded", conversation_id="conv-1",
        )
        assert len(both) == 2
        paged = await agent_repository.list_agent_runs(
            db, agent_id, "console", admin_id, limit=1, offset=0
        )
        assert len(paged) == 1

        # count_agent_runs: each optional filter
        assert await agent_repository.count_agent_runs(db, agent_id) == 6
        assert (
            await agent_repository.count_agent_runs(
                db, agent_id, access_source="console"
            )
            == 5
        )
        assert (
            await agent_repository.count_agent_runs(
                db, agent_id, consumer_id="consumer-x"
            )
            == 1
        )
        assert (
            await agent_repository.count_agent_runs(
                db, agent_id, conversation_id="conv-2"
            )
            == 1
        )

        # management + consumer stats + monitoring + conversations
        managed = await agent_repository.list_agent_runs_for_management(
            db, workspace_id, agent_id, 10, 0
        )
        assert len(managed) == 6
        stats, total = await agent_repository.list_agent_consumer_stats(
            db, workspace_id, agent_id, 10, 0
        )
        assert total == 2
        assert len(stats) == 2
        monitoring = await agent_repository.list_agent_monitoring_rows(
            db, workspace_id, agent_id, now - timedelta(hours=1)
        )
        assert len(monitoring) == 6
        assert (
            await agent_repository.list_agent_monitoring_rows(
                db, workspace_id, agent_id, now + timedelta(hours=1)
            )
            == []
        )
        conversations = await agent_repository.list_consumer_conversations(
            db, agent_id, "console", admin_id
        )
        assert len(conversations) == 3
        by_conv = {row.conversation_id: row.run_count for row in conversations}
        assert by_conv == {
            "conv-1": 3,
            "conv-2": 1,
            "conv-filter-unified": 1,
        }
        assert (
            await agent_repository.latest_agent_conversation_id(
                db, agent_id, "console", admin_id
            )
            == "conv-2"
        )
        assert (
            await agent_repository.latest_agent_conversation_id(
                db, agent_id, "api", "consumer-x"
            )
            == "conv-api"
        )

        # get_active_agent_run: active queued run found / none for terminal convs
        active = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-active",
                status="queued", created_at=now,
            ),
        )
        await db.commit()
        found = await agent_repository.get_active_agent_run(
            db, agent_id, "console", admin_id, "conv-active"
        )
        assert found is not None and found.id == active.id
        assert (
            await agent_repository.get_active_agent_run(
                db, agent_id, "console", admin_id, "conv-1"
            )
            is None
        )

        # conversation memory: anchor + after-anchor filters
        anchor, memory = await agent_repository.list_conversation_memory_runs(
            db, r2, limit=10
        )
        assert anchor is not None and anchor.id == r1.id
        assert [run.id for run in memory] == [r1b.id]
        anchor2, memory2 = await agent_repository.list_conversation_memory_runs(
            db, r3, limit=10
        )
        assert anchor2 is None
        assert memory2 == []

        # save_conversation_summary: success + failure
        assert (
            await agent_repository.save_conversation_summary(
                db, r1, "rolled-up summary"
            )
            is True
        )
        assert (
            await agent_repository.save_conversation_summary(
                db, _run_entity(workspace_id, agent_id, admin_id, "conv-ghost"),
                "nope",
            )
            is False
        )
        await db.commit()

        # claim / renew / checkpoint / finalize
        claim = await agent_repository.claim_agent_run(
            db, active.id, "worker-claim", now, now + timedelta(seconds=90)
        )
        assert claim is True
        assert (
            await agent_repository.claim_agent_run(
                db, active.id, "worker-claim", now, now + timedelta(seconds=90)
            )
            is False
        )

        # Worker generations are a durable dispatch fence: an old task must
        # never claim a unified run, and the unified task must never claim a
        # legacy run.
        unified = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id,
                agent_id,
                admin_id,
                "conv-unified-fence",
                status=AGENT_RUN_UNIFIED_QUEUED_STATUS,
                configuration_source="draft",
                created_at=now,
            ),
        )
        await db.commit()
        assert (
            await agent_repository.claim_agent_run(
                db, unified.id, "legacy-worker", now, now + timedelta(seconds=90)
            )
            is False
        )
        assert (
            await agent_repository.claim_agent_run(
                db,
                unified.id,
                "unified-worker",
                now,
                now + timedelta(seconds=90),
                generation="unified",
            )
            is True
        )
        assert (
            await agent_repository.claim_agent_run(
                db,
                active.id,
                "unified-worker",
                now,
                now + timedelta(seconds=90),
                generation="unified",
            )
            is False
        )
        assert (
            await agent_repository.renew_agent_run_lease(
                db, active.id, "worker-claim", now + timedelta(seconds=180)
            )
            is True
        )
        assert (
            await agent_repository.renew_agent_run_lease(
                db, active.id, "wrong-worker", now + timedelta(seconds=180)
            )
            is False
        )
        assert (
            await agent_repository.save_agent_run_checkpoint(
                db,
                active.id,
                "worker-claim",
                {"model_usage": {"model_calls": 1}},
                "agent",
            )
            is True
        )
        assert (
            await agent_repository.finalize_agent_run(
                db,
                active.id,
                "worker-claim",
                status="succeeded",
                result="done",
                events=[{"type": "complete"}],
                last_error=None,
                finished_at=now,
                model_usage={"model_calls": 1},
            )
            is True
        )
        # finalize with wrong worker no-ops
        assert (
            await agent_repository.finalize_agent_run(
                db,
                active.id,
                "wrong-worker",
                status="succeeded",
                result="done",
                events=[],
                last_error=None,
                finished_at=now,
            )
            is False
        )

        # pause / requeue / queue-from-input transitions
        pause_me = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-pause",
                status="running", attempts=1, worker_task_id="worker-p",
                created_at=now,
            ),
        )
        await db.commit()
        assert (
            await agent_repository.pause_agent_run(
                db, pause_me.id, "worker-p", "approval required"
            )
            is True
        )
        assert (
            await agent_repository.queue_agent_run(db, pause_me.id) is True
        )
        assert (
            await agent_repository.queue_agent_run(db, pause_me.id) is False
        )

        input_me = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-input",
                status="running", worker_task_id="worker-i", created_at=now,
            ),
        )
        await db.commit()
        assert (
            await agent_repository.pause_agent_run_for_input(
                db, input_me.id, "worker-i"
            )
            is True
        )
        assert (
            await agent_repository.queue_agent_run_from_input(
                db, input_me.id, {"checkpoint": 1}
            )
            is True
        )
        assert (
            await agent_repository.queue_agent_run_from_input(
                db, input_me.id, {"checkpoint": 1}
            )
            is False
        )

        requeue_me = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-requeue",
                status="running", worker_task_id="worker-r", created_at=now,
            ),
        )
        await db.commit()
        assert (
            await agent_repository.requeue_owned_agent_run(
                db, requeue_me.id, "worker-r"
            )
            is True
        )
        assert (
            await agent_repository.requeue_owned_agent_run(
                db, requeue_me.id, "worker-r"
            )
            is False
        )

        # recovery scans
        queued_recoverable = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-recover-q",
                status="queued", created_at=now,
            ),
        )
        running_recoverable = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-recover-r",
                status="running", attempts=1,
                worker_task_id="dead-worker",
                lease_expires_at=now - timedelta(seconds=5),
                created_at=now,
            ),
        )
        exhausted = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-exhausted",
                status="queued", attempts=3, max_attempts=3, created_at=now,
            ),
        )
        await db.commit()
        recoverable = await agent_repository.list_recoverable_agent_run_ids(
            db, now, limit=10
        )
        assert queued_recoverable.id in recoverable
        assert running_recoverable.id in recoverable
        assert exhausted.id not in recoverable

        failed_count = await agent_repository.fail_exhausted_agent_runs(db, now)
        assert failed_count == 1
        assert (
            await agent_repository.fail_exhausted_agent_runs(db, now) == 0
        )
        failed_row = await agent_repository.get_agent_run_by_id(
            db, exhausted.id
        )
        assert failed_row is not None and failed_row.status == "failed"
        assert failed_row.last_error == "Agent run retry limit reached."
        await db.commit()

        # events
        event = await agent_repository.append_agent_run_event(
            db,
            workspace_id,
            r3.id,
            {
                "type": "process",
                "event": {
                    "type": "thought",
                    "status": "succeeded",
                    "turn": 1,
                    "tool_name": "",
                    "summary": "agent.answer_ready",
                },
            },
        )
        assert event.id is not None
        answer_started_at = event.event["event"]["created_at"]
        assert answer_started_at == event.created_at.isoformat()
        await db.commit()
        events = await agent_repository.list_agent_run_events(db, r3.id)
        assert len(events) == 1
        projected = await agent_repository.get_agent_run_by_id(db, r3.id)
        assert projected is not None
        assert projected.events[0]["created_at"] == answer_started_at
        after = await agent_repository.list_agent_run_events(
            db, r3.id, after=events[0].id
        )
        assert after == []
        owned = await agent_repository.append_owned_agent_run_event(
            db, workspace_id, r3.id, "worker-x", {"type": "process"}
        )
        assert owned is None  # run is terminal, no ownership
        live_run = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-events",
                status="running", worker_task_id="worker-e", created_at=now,
            ),
        )
        await db.commit()
        owned = await agent_repository.append_owned_agent_run_event(
            db, workspace_id, live_run.id, "worker-e", {"type": "process"}
        )
        assert owned is not None and owned.id is not None
        await db.commit()


async def exercise_repository_tool_calls(
    workspace_id: str,
    agent_id: str,
    user_id: str,
) -> None:
    now = utc_now()
    async with get_session_factory()() as db:
        run = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, user_id, "conv-tools",
                status="running", worker_task_id="worker-t", created_at=now,
            ),
        )
        await db.commit()

        def tool_entity(status: str = "pending", call_id: str = "call-1") -> AgentToolCall:
            return AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=0,
                call_id=call_id,
                tool_name="lookup_release",
                tool_kind="mcp",
                server_name="Release MCP",
                arguments={"topic": "release"},
                arguments_hash="args-hash",
                definition_hash="def-hash",
                policy_mode="read_only",
                idempotency_key="",
                status=status,
            )

        # create fresh + duplicate (IntegrityError swallowed, current returned)
        first = await agent_repository.create_agent_tool_call(db, tool_entity())
        assert first.call_id == "call-1"
        duplicate = await agent_repository.create_agent_tool_call(
            db, tool_entity(call_id="call-1")
        )
        assert duplicate.id == first.id
        await db.commit()

        second = await agent_repository.create_agent_tool_call(
            db, tool_entity(call_id="call-2")
        )
        await db.commit()

        assert await agent_repository.get_agent_tool_call(
            db, run.id, 0, "call-1"
        ) is not None
        assert (
            await agent_repository.get_agent_tool_call(db, run.id, 0, "call-x")
            is None
        )
        assert (
            await agent_repository.get_agent_tool_call_by_call_id(
                db, run.id, "call-2"
            )
            is not None
        )
        listed = await agent_repository.list_agent_tool_calls(db, run.id)
        assert len(listed) == 2

        # claim pending -> running; double claim no-op
        assert (
            await agent_repository.claim_agent_tool_call(
                db, first.id, "worker-t", now, now + timedelta(seconds=60)
            )
            is True
        )
        assert (
            await agent_repository.claim_agent_tool_call(
                db, first.id, "worker-t", now, now + timedelta(seconds=60)
            )
            is False
        )

        # save result (owned) / wrong worker no-op
        result = tool_entity(call_id="call-1")
        result.status = "succeeded"
        result.result_content = "ok"
        result.result_summary = "done"
        result.result_is_error = False
        result.finished_at = now
        assert (
            await agent_repository.save_agent_tool_call_result(
                db, first.id, "worker-t", result
            )
            is True
        )
        assert (
            await agent_repository.save_agent_tool_call_result(
                db, first.id, "wrong-worker", result
            )
            is False
        )

        # expired tool call marking (approval not required -> approved)
        expired_entity = tool_entity(call_id="call-expired", status="running")
        expired_entity.approval_required = False
        expired_entity.lease_expires_at = now - timedelta(seconds=5)
        await agent_repository.create_agent_tool_call(db, expired_entity)
        await db.commit()
        await agent_repository.mark_expired_agent_tool_calls(db, run.id, now)
        assert (
            await agent_repository.get_agent_tool_call(db, run.id, 0, "call-expired")
        ).status == "approved"

        # approval-required expired -> uncertain
        uncertain_entity = tool_entity(call_id="call-uncertain", status="running")
        uncertain_entity.approval_required = True
        uncertain_entity.lease_expires_at = now - timedelta(seconds=5)
        await agent_repository.create_agent_tool_call(db, uncertain_entity)
        await db.commit()
        await agent_repository.mark_expired_agent_tool_calls(db, run.id, now)
        assert (
            await agent_repository.get_agent_tool_call(db, run.id, 0, "call-uncertain")
        ).status == "uncertain"

        # require approval -> awaiting_approval
        awaiting = await agent_repository.create_agent_tool_call(
            db, tool_entity(call_id="call-awaiting")
        )
        await db.commit()
        assert (
            await agent_repository.require_agent_tool_call_approval(
                db, awaiting.id, "approval_required", now
            )
            is True
        )
        # already awaiting -> no-op
        assert (
            await agent_repository.require_agent_tool_call_approval(
                db, awaiting.id, "approval_required", now
            )
            is False
        )

        # approve
        assert (
            await agent_repository.approve_agent_tool_call(
                db, awaiting.id, user_id, now
            )
            is True
        )
        assert (
            await agent_repository.approve_agent_tool_call(
                db, awaiting.id, user_id, now
            )
            is False
        )

        # reject from awaiting_approval / uncertain
        reject_entity = tool_entity(call_id="call-reject", status="awaiting_approval")
        reject_me = await agent_repository.create_agent_tool_call(db, reject_entity)
        await db.commit()
        assert (
            await agent_repository.reject_agent_tool_call(
                db, reject_me.id, user_id, now
            )
            is True
        )
        assert (
            await agent_repository.reject_agent_tool_call(
                db, reject_me.id, user_id, now
            )
            is False
        )

        # block pending tool call
        block_me = await agent_repository.create_agent_tool_call(
            db, tool_entity(call_id="call-block")
        )
        await db.commit()
        assert (
            await agent_repository.block_agent_tool_call(
                db, block_me.id, "blocked", now, "blocked summary"
            )
            is True
        )
        blocked = await agent_repository.get_agent_tool_call(
            db, run.id, 0, "call-block"
        )
        assert blocked.status == "rejected"
        assert blocked.result_is_error is True


async def exercise_repository_graph_deletion(
    workspace_id: str,
    agent_id: str,
    admin_id: str,
    kb_id: str,
    mcp_id: str,
) -> None:
    """delete_agent_graph cascades runs, credentials, bindings, permissions."""
    now = utc_now()
    async with get_session_factory()() as db:
        run = await agent_repository.create_agent_run(
            db,
            _run_entity(
                workspace_id, agent_id, admin_id, "conv-graph",
                status="failed", created_at=now,
            ),
        )
        await agent_repository.create_agent_api_credential(
            db,
            AgentApiCredential(
                workspace_id=workspace_id,
                agent_id=agent_id,
                name="graph-cred",
                token_hash="graph-hash",
                hint="g",
                created_by_user_id=admin_id,
            ),
        )
        await agent_repository.replace_mcp_bindings(
            db,
            Agent(id=agent_id, workspace_id=workspace_id),
            [{"server_id": mcp_id, "tool_name": "lookup_release"}],
        )
        await agent_repository.replace_bindings(
            db, Agent(id=agent_id, workspace_id=workspace_id), [kb_id]
        )
        await db.commit()

        await agent_repository.delete_agent_graph(
            db, workspace_id, agent_id, "agent"
        )
        await db.commit()
        assert await agent_repository.get_agent_by_id(db, agent_id) is None
        assert await agent_repository.get_agent_run_by_id(db, run.id) is None
        assert (
            await agent_repository.get_agent_api_credential_by_hash(
                db, "graph-hash"
            )
            is None
        )
        assert await agent_repository.list_binding_map(db, [agent_id]) == {
            agent_id: []
        }
        assert await agent_repository.list_mcp_binding_map(db, [agent_id]) == {
            agent_id: []
        }


async def exercise_repository_workspace_deletion(workspace_id: str) -> None:
    async with get_session_factory()() as db:
        await agent_repository.delete_workspace_agent_graph(db, workspace_id)
        await db.commit()
        rows = await agent_repository.list_agents(
            db, workspace_id, "nobody", "agent", True
        )
        assert rows == []


# ---------------------------------------------------------------------------
# Celery task tests
# ---------------------------------------------------------------------------

def exercise_tasks() -> None:
    from celery.exceptions import Retry as CeleryRetry

    original_configure = agent_tasks.configure_task_worker
    original_run_durable = agent_tasks.run_durable_application_run
    original_list_unified = agent_tasks.list_recoverable_unified_agent_run_ids
    original_list_legacy = agent_tasks.list_recoverable_legacy_agent_run_ids
    original_log_error = agent_tasks.log_error
    original_legacy_apply_async = agent_tasks.run_agent_job.apply_async
    original_unified_apply_async = agent_tasks.run_unified_agent_job.apply_async
    original_broker_url = agent_tasks.celery_app.conf.broker_url
    original_eager = agent_tasks.celery_app.conf.task_always_eager
    try:
        agent_tasks.configure_task_worker = lambda _settings: None
        agent_tasks.log_error = lambda *args, **kwargs: None
        # bind=True tasks receive the task instance as `self`; invoke the raw
        # body with a synthetic self carrying a deterministic request id.
        real_task = agent_tasks.run_agent_job._get_current_object()
        legacy_run_body = type(real_task).run
        unified_task = agent_tasks.run_unified_agent_job._get_current_object()
        unified_run_body = type(unified_task).run

        # run_agent_job: happy path
        async def ok_run(_run_id, _settings, **kwargs):
            return None

        agent_tasks.run_durable_application_run = ok_run
        ok_self = SimpleNamespace(
            request=SimpleNamespace(id="worker-task-1"),
            retry=lambda **kwargs: None,
        )
        assert legacy_run_body(ok_self, "run-ok") is None
        assert unified_run_body(ok_self, "run-v2-ok") is None

        # run_agent_job: RUN_BUSY -> self.retry with heartbeat countdown
        async def busy_run(_run_id, _settings, **kwargs):
            return RUN_BUSY

        agent_tasks.run_durable_application_run = busy_run
        retry_kwargs: dict = {}

        class RetrySignal(Exception):
            pass

        def fake_retry(**kwargs):
            retry_kwargs.update(kwargs)
            raise RetrySignal()

        busy_self = SimpleNamespace(
            request=SimpleNamespace(id="worker-task-1"),
            retry=fake_retry,
        )
        try:
            legacy_run_body(busy_self, "run-busy")
            raise AssertionError("expected retry signal")
        except RetrySignal:
            assert retry_kwargs["countdown"] == 30
            assert retry_kwargs["queue"] == "agents-legacy"

        retry_kwargs.clear()
        try:
            unified_run_body(busy_self, "run-v2-busy")
            raise AssertionError("expected retry signal")
        except RetrySignal:
            assert retry_kwargs["countdown"] == 30
            assert retry_kwargs["queue"] == "agents-v2"

        # run_agent_job: crash -> log_error + re-raise
        async def crash_run(_run_id, _settings, **kwargs):
            raise RuntimeError("synthetic crash")

        agent_tasks.run_durable_application_run = crash_run
        try:
            legacy_run_body(ok_self, "run-crash")
            raise AssertionError("expected RuntimeError")
        except RuntimeError:
            pass

        # Each recovery task only sees and dispatches its own generation.
        async def unified_ids(_settings):
            return ["run-unified-1", "run-unified-2"]

        async def legacy_ids(_settings):
            return ["run-legacy-1"]

        agent_tasks.list_recoverable_unified_agent_run_ids = unified_ids
        agent_tasks.list_recoverable_legacy_agent_run_ids = legacy_ids
        unified_dispatched: list[dict] = []
        legacy_dispatched: list[dict] = []
        agent_tasks.run_unified_agent_job.apply_async = (
            lambda **kwargs: unified_dispatched.append(kwargs)
        )
        agent_tasks.run_agent_job.apply_async = (
            lambda **kwargs: legacy_dispatched.append(kwargs)
        )
        agent_tasks.recover_agent_runs_job()
        agent_tasks.recover_legacy_agent_runs_job()
        assert unified_dispatched == [
            {"args": ("run-unified-1",), "queue": "agents-v2"},
            {"args": ("run-unified-2",), "queue": "agents-v2"},
        ]
        assert legacy_dispatched == [
            {"args": ("run-legacy-1",), "queue": "agents-legacy"},
        ]

        # enqueue_agent_run: eager settings execute the run inline
        eager_settings = test_settings()
        eager_calls: list[tuple] = []

        async def eager_run(run_id, settings, **kwargs):
            eager_calls.append((run_id, settings, kwargs))

        agent_tasks.run_durable_application_run = eager_run
        asyncio.run(agent_tasks.enqueue_agent_run("run-eager", eager_settings))
        asyncio.run(
            agent_tasks.enqueue_agent_run(
                "run-v2-eager",
                eager_settings,
                generation="unified",
            )
        )
        assert eager_calls == [
            ("run-eager", eager_settings, {"generation": "legacy"}),
            ("run-v2-eager", eager_settings, {"generation": "unified"}),
        ]

        # enqueue_agent_run: non-eager settings dispatch to the broker queue
        non_eager = dataclasses.replace(
            eager_settings, celery_task_always_eager=False
        )
        legacy_queued: list[dict] = []
        unified_queued: list[dict] = []
        agent_tasks.run_agent_job.apply_async = (
            lambda **kwargs: legacy_queued.append(kwargs)
        )
        agent_tasks.run_unified_agent_job.apply_async = (
            lambda **kwargs: unified_queued.append(kwargs)
        )
        asyncio.run(agent_tasks.enqueue_agent_run("run-queued", non_eager))
        asyncio.run(
            agent_tasks.enqueue_agent_run(
                "run-v2-queued",
                non_eager,
                generation="unified",
            )
        )
        assert legacy_queued == [
            {"args": ("run-queued",), "queue": "agents-legacy"}
        ]
        assert unified_queued == [
            {"args": ("run-v2-queued",), "queue": "agents-v2"}
        ]

        # enqueue_agent_run: dispatch failure is logged, not raised
        def raise_apply(**kwargs):
            raise OSError("broker unavailable")

        agent_tasks.run_agent_job.apply_async = raise_apply
        asyncio.run(agent_tasks.enqueue_agent_run("run-queued", non_eager))
    finally:
        agent_tasks.configure_task_worker = original_configure
        agent_tasks.run_durable_application_run = original_run_durable
        agent_tasks.list_recoverable_unified_agent_run_ids = original_list_unified
        agent_tasks.list_recoverable_legacy_agent_run_ids = original_list_legacy
        agent_tasks.log_error = original_log_error
        agent_tasks.run_agent_job.apply_async = original_legacy_apply_async
        agent_tasks.run_unified_agent_job.apply_async = original_unified_apply_async
        agent_tasks.celery_app.conf.broker_url = original_broker_url
        agent_tasks.celery_app.conf.task_always_eager = original_eager


# ---------------------------------------------------------------------------
# HTTP scenario driver
# ---------------------------------------------------------------------------

def exercise_http(client, admin_token: str, workspace_id: str, model_base_url: str) -> None:
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    assert me.status_code == 200, me.text
    admin_id = me.json()["user"]["id"]

    member_id, member_password = create_workspace_user(
        client, admin_token, workspace_id, "coverage-member"
    )
    member_token = activate_user(
        client, "coverage-member", member_password, MEMBER_PASSWORD
    )

    # --- models ----------------------------------------------------------
    model = client.post(
        f"/api/v1/workspaces/{workspace_id}/models",
        headers=auth_headers(admin_token),
        json=model_payload(model_base_url, "Coverage LLM"),
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]

    second_model = client.post(
        f"/api/v1/workspaces/{workspace_id}/models",
        headers=auth_headers(admin_token),
        json=model_payload(model_base_url, "Coverage LLM 2"),
    )
    assert second_model.status_code == 201, second_model.text
    second_model_id = second_model.json()["id"]

    embedding_model_id = asyncio.run(
        insert_registered_model(workspace_id, admin_id, "Coverage Embed", "EMBEDDING")
    )
    disabled_model_id = asyncio.run(
        insert_registered_model(
            workspace_id, admin_id, "Coverage Disabled", "LLM", status="disabled"
        )
    )

    # --- knowledge bases -------------------------------------------------
    kb = client.post(
        knowledge_url(workspace_id),
        headers=auth_headers(admin_token),
        json={"name": "Coverage Docs", "description": "Agent coverage KB"},
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]
    kb2 = client.post(
        knowledge_url(workspace_id),
        headers=auth_headers(admin_token),
        json={"name": "Coverage Docs 2", "description": "Second KB"},
    )
    assert kb2.status_code == 201, kb2.text
    kb2_id = kb2.json()["id"]

    # --- MCP server ------------------------------------------------------
    mcp = client.post(
        mcp_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Coverage MCP",
            "url": "http://127.0.0.1:9999/mcp",
        },
    )
    assert mcp.status_code == 201, mcp.text
    mcp_id = mcp.json()["id"]

    # --- agent CRUD ------------------------------------------------------
    created = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Planner",
            "description": "Plans coverage work",
            "instructions": "Use workspace evidence.",
            "model_id": model_id,
            "knowledge_base_ids": [kb_id],
        },
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    agent_id = agent["id"]
    assert agent["can_edit"] is True
    assert agent["knowledge_base_ids"] == [kb_id]
    assert agent["knowledge_query_mode"] == "required"
    assert agent["app_type"] == "agent"
    assert agent["published"] is False
    assert agent["has_unpublished_changes"] is False

    workflow_created = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Pipeline",
            "app_type": "workflow",
            "instructions": "Follow the pipeline.",
            "model_id": model_id,
        },
    )
    assert workflow_created.status_code == 201, workflow_created.text
    workflow_id = workflow_created.json()["id"]
    assert workflow_created.json()["app_type"] == "workflow"

    run_agent = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Run Agent",
            "instructions": "Plain agent for runs.",
            "model_id": model_id,
        },
    )
    assert run_agent.status_code == 201, run_agent.text
    run_agent_id = run_agent.json()["id"]

    update_agent = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Update Target",
            "instructions": "Target for update coverage.",
            "model_id": model_id,
            "knowledge_base_ids": [kb_id],
        },
    )
    assert update_agent.status_code == 201, update_agent.text
    update_agent_id = update_agent.json()["id"]

    # GET single agent -> 200
    fetched = client.get(
        agents_url(workspace_id, f"/{agent_id}"),
        headers=auth_headers(admin_token),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == agent_id

    # GET missing agent -> 404
    missing = client.get(
        agents_url(workspace_id, "/ghost-agent"),
        headers=auth_headers(admin_token),
    )
    assert missing.status_code == 404, missing.text

    # model validation errors on create
    bad_model = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={"name": "Bad Model", "model_id": "ghost-model"},
    )
    assert bad_model.status_code == 422, bad_model.text
    non_llm = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={"name": "Non LLM", "model_id": embedding_model_id},
    )
    assert non_llm.status_code == 422, non_llm.text
    disabled = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={"name": "Disabled Model", "model_id": disabled_model_id},
    )
    assert disabled.status_code == 422, disabled.text

    # duplicate knowledge base ids -> 422
    dup_kb = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Dup KB",
            "model_id": model_id,
            "knowledge_base_ids": [kb_id, kb_id],
        },
    )
    assert dup_kb.status_code == 422, dup_kb.text

    # archived knowledge base -> 422
    asyncio.run(set_knowledge_base_status(kb2_id, "archived"))
    try:
        archived_kb = client.post(
            agents_url(workspace_id),
            headers=auth_headers(admin_token),
            json={
                "name": "Archived KB Agent",
                "model_id": model_id,
                "knowledge_base_ids": [kb2_id],
            },
        )
        assert archived_kb.status_code == 422, archived_kb.text
    finally:
        asyncio.run(set_knowledge_base_status(kb2_id, "active"))

    # member cannot bind a knowledge base they cannot access -> 403
    member_kb = client.post(
        agents_url(workspace_id),
        headers=auth_headers(member_token),
        json={
            "name": "Member KB Agent",
            "model_id": model_id,
            "knowledge_base_ids": [kb_id],
        },
    )
    assert member_kb.status_code == 403, member_kb.text

    # duplicate agent name -> 409 (IntegrityError path in create)
    duplicate = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={"name": "Planner", "instructions": "dup", "model_id": model_id},
    )
    assert duplicate.status_code == 409, duplicate.text

    # MCP tool binding on create
    mcp_agent = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Tool Agent",
            "model_id": model_id,
            "mcp_tools": [
                {"server_id": mcp_id, "tool_name": "lookup_release"}
            ],
        },
    )
    assert mcp_agent.status_code == 201, mcp_agent.text
    mcp_agent_id = mcp_agent.json()["id"]
    assert mcp_agent.json()["mcp_tools"][0]["tool_name"] == "lookup_release"

    # unavailable MCP tool -> 422
    bad_tool = client.post(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
        json={
            "name": "Bad Tool Agent",
            "model_id": model_id,
            "mcp_tools": [{"server_id": mcp_id, "tool_name": "nope"}],
        },
    )
    assert bad_tool.status_code == 422, bad_tool.text

    # list agents (admin include-all + member filtered)
    admin_list = client.get(
        agents_url(workspace_id),
        headers=auth_headers(admin_token),
    )
    assert admin_list.status_code == 200, admin_list.text
    admin_ids = {item["id"] for item in admin_list.json()}
    assert agent_id in admin_ids
    assert workflow_id in admin_ids

    member_list = client.get(
        agents_url(workspace_id),
        headers=auth_headers(member_token),
    )
    assert member_list.status_code == 200, member_list.text
    member_ids = {item["id"] for item in member_list.json()}
    assert agent_id not in member_ids  # no grant yet

    # --- permissions -----------------------------------------------------
    permissions = client.get(
        agents_url(workspace_id, f"/{agent_id}/permissions"),
        headers=auth_headers(admin_token),
    )
    assert permissions.status_code == 200, permissions.text
    assert permissions.json() == []

    grant = client.put(
        agents_url(workspace_id, f"/{agent_id}/permissions/{member_id}"),
        headers=auth_headers(admin_token),
        json={"permission": "view"},
    )
    assert grant.status_code == 200, grant.text
    assert grant.json()["user"]["id"] == member_id
    assert grant.json()["permission"] == "view"

    # re-grant updates the existing row
    regrant = client.put(
        agents_url(workspace_id, f"/{agent_id}/permissions/{member_id}"),
        headers=auth_headers(admin_token),
        json={"permission": "view"},
    )
    assert regrant.status_code == 200, regrant.text

    # grant to a non-member -> 404
    stranger = client.put(
        agents_url(workspace_id, f"/{agent_id}/permissions/not-a-member"),
        headers=auth_headers(admin_token),
        json={"permission": "view"},
    )
    assert stranger.status_code == 404, stranger.text

    # member now sees the agent (view grant) but not the KB
    member_get = client.get(
        agents_url(workspace_id, f"/{agent_id}"),
        headers=auth_headers(member_token),
    )
    assert member_get.status_code == 200, member_get.text
    assert member_get.json()["can_edit"] is False
    assert member_get.json()["knowledge_base_ids"] == []

    member_list_after = client.get(
        agents_url(workspace_id),
        headers=auth_headers(member_token),
    )
    assert member_list_after.status_code == 200, member_list_after.text
    assert agent_id in {item["id"] for item in member_list_after.json()}

    # revoke -> 204, revoke again -> 404, member access dropped
    revoked = client.delete(
        agents_url(workspace_id, f"/{agent_id}/permissions/{member_id}"),
        headers=auth_headers(admin_token),
    )
    assert revoked.status_code == 204, revoked.text
    revoke_again = client.delete(
        agents_url(workspace_id, f"/{agent_id}/permissions/{member_id}"),
        headers=auth_headers(admin_token),
    )
    assert revoke_again.status_code == 404, revoke_again.text
    member_after_revoke = client.get(
        agents_url(workspace_id, f"/{agent_id}"),
        headers=auth_headers(member_token),
    )
    assert member_after_revoke.status_code == 403, member_after_revoke.text

    # --- publication semantics ------------------------------------------
    published = client.patch(
        agents_url(workspace_id, f"/{agent_id}"),
        headers=auth_headers(admin_token),
        json={"published": True},
    )
    assert published.status_code == 200, published.text
    published_body = published.json()
    assert published_body["published"] is True
    assert published_body["has_unpublished_changes"] is False
    assert published_body["published_by_user_id"] == admin_id
    assert published_body["published_at"] is not None

    unpublished = client.patch(
        agents_url(workspace_id, f"/{agent_id}"),
        headers=auth_headers(admin_token),
        json={"published": False},
    )
    assert unpublished.status_code == 200, unpublished.text
    assert unpublished.json()["published"] is False
    assert unpublished.json()["published_by_user_id"] is None

    # workflow agents cannot be published through the agent endpoint
    workflow_publish = client.patch(
        agents_url(workspace_id, f"/{workflow_id}"),
        headers=auth_headers(admin_token),
        json={"published": True},
    )
    assert workflow_publish.status_code == 409, workflow_publish.text

    # disabling a workflow agent resets any publication state
    workflow_disable = client.patch(
        agents_url(workspace_id, f"/{workflow_id}"),
        headers=auth_headers(admin_token),
        json={"status": "disabled"},
    )
    assert workflow_disable.status_code == 200, workflow_disable.text

    # disabled agents cannot be (re)published
    agent_disable = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={"status": "disabled"},
    )
    assert agent_disable.status_code == 200, agent_disable.text
    publish_disabled = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={"published": True},
    )
    assert publish_disabled.status_code == 409, publish_disabled.text
    # re-enable for later update coverage
    agent_enable = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={"status": "active"},
    )
    assert agent_enable.status_code == 200, agent_enable.text

    # invalid status -> 422
    invalid_status = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={"status": "bogus"},
    )
    assert invalid_status.status_code == 422, invalid_status.text

    # app_type cannot change after creation -> 409
    app_type_change = client.patch(
        agents_url(workspace_id, f"/{workflow_id}"),
        headers=auth_headers(admin_token),
        json={"app_type": "agent"},
    )
    assert app_type_change.status_code == 409, app_type_change.text

    # full-field update
    updated = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={
            "name": "Update Target Renamed",
            "description": "Renamed for coverage",
            "interaction_config": {
                "prologue": "Hello from coverage",
                "tts_type": "BROWSER",
                "file_upload": False,
                "file_upload_setting": {"file_upload_type": ["document"]},
                "user_input_title": "Ask",
            },
            "instructions": "New instructions.",
            "model_id": second_model_id,
            "knowledge_query_mode": "agentic",
            "status": "active",
        },
    )
    assert updated.status_code == 200, updated.text
    updated_body = updated.json()
    assert updated_body["name"] == "Update Target Renamed"
    assert updated_body["model_id"] == second_model_id
    assert updated_body["knowledge_query_mode"] == "agentic"
    assert updated_body["interaction_config"]["prologue"] == "Hello from coverage"

    # knowledge base binding replacement
    rebound = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={"knowledge_base_ids": []},
    )
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["knowledge_base_ids"] == []

    # MCP tool binding via update
    mcp_update = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={
            "mcp_tools": [
                {"server_id": mcp_id, "tool_name": "lookup_release"}
            ]
        },
    )
    assert mcp_update.status_code == 200, mcp_update.text
    assert mcp_update.json()["mcp_tools"][0]["tool_name"] == "lookup_release"

    # duplicate name update -> 409 (IntegrityError path in update)
    dup_update = client.patch(
        agents_url(workspace_id, f"/{update_agent_id}"),
        headers=auth_headers(admin_token),
        json={"name": "Planner"},
    )
    assert dup_update.status_code == 409, dup_update.text

    # member cannot update another owner's agent
    member_update = client.patch(
        agents_url(workspace_id, f"/{agent_id}"),
        headers=auth_headers(member_token),
        json={"name": "Nope"},
    )
    assert member_update.status_code == 403, member_update.text

    # legacy publication (published with NULL snapshot) preserves snapshot
    asyncio.run(set_agent_legacy_published(agent_id, admin_id))
    legacy_update = client.patch(
        agents_url(workspace_id, f"/{agent_id}"),
        headers=auth_headers(admin_token),
        json={"name": "Planner Legacy"},
    )
    assert legacy_update.status_code == 200, legacy_update.text
    legacy_body = legacy_update.json()
    assert legacy_body["name"] == "Planner Legacy"
    assert legacy_body["published"] is True
    # the pre-update snapshot is preserved, so the rename shows as unpublished
    assert legacy_body["has_unpublished_changes"] is True

    # --- api credentials -------------------------------------------------
    credential = client.post(
        agents_url(workspace_id, f"/{agent_id}/api-credentials"),
        headers=auth_headers(admin_token),
        json={"name": "ci"},
    )
    assert credential.status_code == 201, credential.text
    credential_id = credential.json()["credential"]["id"]
    assert credential.json()["token"]

    credential_list = client.get(
        agents_url(workspace_id, f"/{agent_id}/api-credentials"),
        headers=auth_headers(admin_token),
    )
    assert credential_list.status_code == 200, credential_list.text
    assert credential_list.json()["items"][0]["id"] == credential_id

    credential_deleted = client.delete(
        agents_url(workspace_id, f"/{agent_id}/api-credentials/{credential_id}"),
        headers=auth_headers(admin_token),
    )
    assert credential_deleted.status_code == 204, credential_deleted.text

    # --- runs & streaming ------------------------------------------------
    run_created = client.post(
        agents_url(workspace_id, f"/{run_agent_id}/runs"),
        headers=auth_headers(admin_token),
        json={"goal": "Prepare the coverage summary"},
    )
    assert run_created.status_code == 201, run_created.text
    run_body = run_created.json()
    assert run_body["status"] == "succeeded", run_body
    assert run_body["result"] == "Completed."
    run_id = run_body["id"]

    # reconnect stream replays the durable run
    reconnected = client.get(
        agents_url(workspace_id, f"/{run_agent_id}/runs/{run_id}/stream"),
        headers=auth_headers(admin_token),
    )
    assert reconnected.status_code == 200, reconnected.text
    reconnected_events = [
        json.loads(line)
        for line in reconnected.text.splitlines()
        if line.strip()
    ]
    assert reconnected_events[0]["type"] == "run"
    assert any(event["type"] in {"complete", "error"} for event in reconnected_events)

    # live streaming POST replays the freshly executed run
    streamed = client.post(
        agents_url(workspace_id, f"/{run_agent_id}/runs/stream"),
        headers=auth_headers(admin_token),
        json={"goal": "Stream the coverage plan"},
    )
    assert streamed.status_code == 200, streamed.text
    streamed_events = [
        json.loads(line)
        for line in streamed.text.splitlines()
        if line.strip()
    ]
    assert streamed_events[0]["type"] == "run"
    assert any(event["type"] in {"complete", "error"} for event in streamed_events)

    # --- agent deletion --------------------------------------------------
    deleted = client.delete(
        agents_url(workspace_id, f"/{mcp_agent_id}"),
        headers=auth_headers(admin_token),
    )
    assert deleted.status_code == 204, deleted.text
    gone = client.get(
        agents_url(workspace_id, f"/{mcp_agent_id}"),
        headers=auth_headers(admin_token),
    )
    assert gone.status_code == 404, gone.text

    return {
        "admin_id": admin_id,
        "member_id": member_id,
        "model_id": model_id,
        "embedding_model_id": embedding_model_id,
        "disabled_model_id": disabled_model_id,
        "agent_id": agent_id,
        "run_agent_id": run_agent_id,
        "update_agent_id": update_agent_id,
        "kb_id": kb_id,
        "kb2_id": kb2_id,
        "mcp_id": mcp_id,
    }


def main() -> None:
    original_discover = mcp_services.discover_mcp_tools

    async def fake_discover_mcp_tools(connection, _settings) -> McpDiscovery:
        return McpDiscovery(
            tools=[
                {
                    "name": "lookup_release",
                    "description": "Look up a release record.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"topic": {"type": "string"}},
                        "required": ["topic"],
                    },
                    "annotations": {
                        "readOnlyHint": True,
                        "destructiveHint": False,
                    },
                }
            ]
        )

    mcp_services.discover_mcp_tools = fake_discover_mcp_tools
    try:
        with test_client() as client, model_server() as model_base_url:
            admin_token, workspace_id = activate_admin(client)
            ids = exercise_http(
                client, admin_token, workspace_id, model_base_url
            )

            exercise_tasks()

            asyncio.run(
                exercise_services_http_paths(
                    workspace_id,
                    ids["admin_id"],
                    ids["member_id"],
                    ids["model_id"],
                    ids["embedding_model_id"],
                    ids["disabled_model_id"],
                    ids["kb_id"],
                    ids["mcp_id"],
                )
            )
            asyncio.run(
                exercise_services_direct(
                    workspace_id,
                    ids["agent_id"],
                    ids["kb_id"],
                    ids["admin_id"],
                    ids["model_id"],
                )
            )
            asyncio.run(
                exercise_repository_credentials(
                    workspace_id, ids["agent_id"], ids["admin_id"]
                )
            )
            asyncio.run(
                exercise_repository_bindings(
                    workspace_id,
                    ids["run_agent_id"],
                    ids["kb_id"],
                    ids["mcp_id"],
                )
            )
            asyncio.run(
                exercise_repository_runs(
                    workspace_id, ids["admin_id"], ids["model_id"]
                )
            )
            asyncio.run(
                exercise_repository_tool_calls(
                    workspace_id, ids["run_agent_id"], ids["admin_id"]
                )
            )
            asyncio.run(
                exercise_repository_graph_deletion(
                    workspace_id,
                    ids["update_agent_id"],
                    ids["admin_id"],
                    ids["kb_id"],
                    ids["mcp_id"],
                )
            )
            asyncio.run(exercise_repository_workspace_deletion(workspace_id))
    finally:
        mcp_services.discover_mcp_tools = original_discover

    print("agent_services_coverage: OK")


if __name__ == "__main__":
    main()

import asyncio
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace

from app.application import agents as agent_application
from app.capabilities.mcp import client as mcp_client_module
from app.capabilities.mcp.client import (
    MAX_MCP_TOOL_PAGES,
    McpClientError,
    discover_mcp_tools,
    normalize_mcp_url,
)
from app.schemas.knowledge import KnowledgeQueryHitResponse
from tests.agent_orchestration import main as orchestration_main
from app.shareddomain.tools import services as mcp_services
from tests.support import (
    RESEARCH_PASSWORD,
    activate_admin,
    activate_user,
    auth_headers,
    test_client,
)

MEMBER_PASSWORD = "AgentMember@12345."


class AgentModelHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []
    fail_next_decision = False

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        AgentModelHandler.calls.append(body)

        tool_names = {
            tool["function"]["name"]
            for tool in body.get("tools", [])
            if tool.get("type") == "function"
        }
        if (
            AgentModelHandler.fail_next_decision
            and "agent_submit_plan" not in tool_names
            and not body.get("stream")
        ):
            AgentModelHandler.fail_next_decision = False
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": {"message": "temporary model failure"}}).encode()
            )
            return
        knowledge_tool_name = next(
            (name for name in tool_names if name.startswith("knowledge_")),
            None,
        )
        mcp_tool_name = next((name for name in tool_names if name.startswith("mcp_")), None)
        has_tool_result = any(item.get("role") == "tool" for item in body.get("messages", []))
        if body.get("stream"):
            message = {"role": "assistant", "content": "Completed."}
            finish_reason = "stop"
        elif "agent_submit_plan" in tool_names:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-plan",
                        "type": "function",
                        "function": {
                            "name": "agent_submit_plan",
                            "arguments": json.dumps(
                                {
                                    "steps": [
                                        {
                                            "title": "Gather evidence",
                                            "description": "Gather evidence and prepare an answer",
                                        }
                                    ]
                                }
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif knowledge_tool_name and not has_tool_result:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-search",
                        "type": "function",
                        "function": {
                            "name": knowledge_tool_name,
                            "arguments": json.dumps({"query": "release process"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif mcp_tool_name and not has_tool_result:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-mcp",
                        "type": "function",
                        "function": {
                            "name": mcp_tool_name,
                            "arguments": json.dumps({"topic": "release"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif "agent_complete_step" in tool_names:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-complete",
                        "type": "function",
                        "function": {
                            "name": "agent_complete_step",
                            "arguments": json.dumps({"summary": "Evidence gathered"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "Completed."}
            finish_reason = "stop"

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            delta = {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": [
                    {
                        "index": index,
                        **tool_call,
                    }
                    for index, tool_call in enumerate(message.get("tool_calls", []))
                ],
            }
            chunks = [
                {
                    "id": "agent-test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "agent-test",
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
            "id": "agent-test",
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
def agent_model_server() -> Iterator[str]:
    AgentModelHandler.calls = []
    AgentModelHandler.fail_next_decision = False
    server = HTTPServer(("127.0.0.1", 0), AgentModelHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def model_payload(api_base: str, name: str = "Agent Model") -> dict:
    return {
        "name": name,
        "provider": "model_deepseek_provider",
        "provider_type": "openai_compatible",
        "model_type": "LLM",
        "model_name": "deepseek-chat",
        "credential": {"api_base": api_base, "api_key": "sk-agent-test-1234"},
    }


def agents_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/agents{suffix}"


def knowledge_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge-bases{suffix}"


def mcp_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/mcp-servers{suffix}"


def stream_payloads(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def create_workspace_user(client, token: str, workspace_id: str) -> tuple[str, str]:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members/users",
        headers=auth_headers(token),
        json={
            "username": "agent-member",
            "email": "agent-member@example.com",
            "name": "Agent Member",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], response.json()["initial_password"]


def assert_mcp_url_validation() -> None:
    assert normalize_mcp_url("https://tools.example.com/mcp/") == (
        "https://tools.example.com/mcp"
    )
    for invalid_url in (
        "file:///tmp/mcp.sock",
        "https://tools.example.com/mcp?token=secret",
        "https://tools.example.com:invalid/mcp",
    ):
        try:
            normalize_mcp_url(invalid_url)
        except McpClientError:
            continue
        raise AssertionError(f"Invalid MCP URL was accepted: {invalid_url}")


async def assert_mcp_discovery_rejects_untrusted_metadata() -> None:
    original_client = mcp_client_module.mcp_client

    class FakeClient:
        def __init__(self, schema: dict, next_cursor: str | None) -> None:
            self.schema = schema
            self.next_cursor = next_cursor
            self.calls = 0

        async def list_tools(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="unsafe_tool",
                        description=None,
                        input_schema=self.schema,
                    )
                ],
                next_cursor=self.next_cursor,
            )

    async def run_discovery(client: FakeClient) -> None:
        @asynccontextmanager
        async def fake_client(*_args, **_kwargs):
            yield client

        mcp_client_module.mcp_client = fake_client  # type: ignore[assignment]
        try:
            await discover_mcp_tools("https://tools.example.com", None, False, 1)
        except McpClientError:
            return
        raise AssertionError("Invalid MCP tool metadata was accepted.")

    try:
        await run_discovery(FakeClient({"type": "string"}, None))
        paginated_client = FakeClient({"type": "object"}, "same-cursor")
        await run_discovery(paginated_client)
        assert paginated_client.calls == MAX_MCP_TOOL_PAGES
    finally:
        mcp_client_module.mcp_client = original_client


async def assert_knowledge_reranking() -> None:
    original_query = agent_application.query_knowledge_base
    original_get_model = agent_application.get_knowledge_model
    original_build_provider = agent_application.build_registered_model_provider

    class FakeClient:
        def close(self) -> None:
            pass

    class FakeAsyncClient:
        async def close(self) -> None:
            pass

    class FakeReranker:
        client = FakeClient()
        async_client = FakeAsyncClient()

        def rerank(self, _query: str, _documents: list[str]) -> list[dict]:
            return [
                {"index": 4, "relevance_score": 0.9},
                {"index": 1, "relevance_score": 0.8},
            ]

    async def fake_query(_db, _knowledge_base, payload, _settings):
        assert payload.limit == agent_application.MAX_RERANK_HITS_PER_BASE
        return [
            KnowledgeQueryHitResponse(
                chunk_id=f"chunk-{index}",
                document_id=f"document-{index}",
                document_filename=f"doc-{index}.md",
                chunk_index=index,
                content=f"content-{index}",
                distance=index / 10,
            )
            for index in range(6)
        ]

    async def fake_get_model(*_args, **_kwargs):
        return SimpleNamespace()

    agent_application.query_knowledge_base = fake_query
    agent_application.get_knowledge_model = fake_get_model
    agent_application.build_registered_model_provider = lambda *_args: FakeReranker()
    try:
        tool = agent_application.build_knowledge_search_tool(
            None,
            SimpleNamespace(
                id="knowledge-1",
                workspace_id="workspace-1",
                name="Docs",
                reranker_model_id="reranker-1",
            ),
            None,
        )
        result = await tool.execute(json.dumps({"query": "release"}))
        assert not result.is_error
        assert [hit["document"] for hit in result.output["hits"]] == [
            "doc-4.md",
            "doc-1.md",
        ]
        assert result.output["retrieval_stats"] == [
            {
                "knowledge_base_id": "knowledge-1",
                "knowledge_base_name": "Docs",
                "candidates": 6,
                "reranked": True,
                "submitted": 2,
            }
        ]
    finally:
        agent_application.query_knowledge_base = original_query
        agent_application.get_knowledge_model = original_get_model
        agent_application.build_registered_model_provider = original_build_provider


def main() -> None:
    asyncio.run(orchestration_main())
    asyncio.run(assert_mcp_discovery_rejects_untrusted_metadata())
    asyncio.run(assert_knowledge_reranking())
    assert_mcp_url_validation()

    original_query = agent_application.query_knowledge_base
    original_discover = mcp_services.discover_mcp_tools
    original_call_mcp_tool = agent_application.call_mcp_tool
    query_calls: list[tuple[str, str]] = []
    mcp_calls: list[tuple[str, str, dict]] = []

    async def fake_query_knowledge_base(
        _db,
        knowledge_base,
        payload,
        _settings,
    ) -> list[KnowledgeQueryHitResponse]:
        query_calls.append((knowledge_base.id, payload.query))
        return [
            KnowledgeQueryHitResponse(
                chunk_id="chunk-agent-source",
                document_id="document-agent-source",
                document_filename="release.md",
                chunk_index=0,
                content="Deployments require an approved pull request.",
                distance=0.1,
            )
        ]

    async def fake_discover_mcp_tools(
        _url,
        bearer_token,
        _allow_private_networks,
        _timeout_seconds,
    ) -> list[dict]:
        assert bearer_token == "mcp-secret-token"
        return [
            {
                "name": "lookup_release",
                "description": "Look up a release record.",
                "input_schema": {
                    "type": "object",
                    "properties": {"topic": {"type": "string"}},
                    "required": ["topic"],
                },
            }
        ]

    async def fake_call_mcp_tool(
        url,
        bearer_token,
        tool_name,
        arguments,
        _allow_private_networks,
        _timeout_seconds,
    ) -> tuple[str, bool]:
        assert bearer_token == "mcp-secret-token"
        mcp_calls.append((url, tool_name, arguments))
        return json.dumps({"release": "approved"}), False

    agent_application.query_knowledge_base = fake_query_knowledge_base
    mcp_services.discover_mcp_tools = fake_discover_mcp_tools
    agent_application.call_mcp_tool = fake_call_mcp_tool
    try:
        with test_client() as client, agent_model_server() as model_base_url:
            admin_token, workspace_id = activate_admin(client)
            member_id, temporary_password = create_workspace_user(
                client,
                admin_token,
                workspace_id,
            )
            member_token = activate_user(
                client,
                "agent-member",
                temporary_password,
                MEMBER_PASSWORD,
            )

            model = client.post(
                f"/api/v1/workspaces/{workspace_id}/models",
                headers=auth_headers(admin_token),
                json=model_payload(model_base_url),
            )
            assert model.status_code == 201, model.text
            model_id = model.json()["id"]

            knowledge_base = client.post(
                knowledge_url(workspace_id),
                headers=auth_headers(admin_token),
                json={"name": "Release Docs", "description": "Deployment rules"},
            )
            assert knowledge_base.status_code == 201, knowledge_base.text
            knowledge_base_id = knowledge_base.json()["id"]

            created = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release Planner",
                    "description": "Plans release work",
                    "instructions": "Use workspace evidence before answering.",
                    "model_id": model_id,
                    "knowledge_base_ids": [knowledge_base_id],
                },
            )
            assert created.status_code == 201, created.text
            agent = created.json()
            agent_id = agent["id"]
            assert agent["can_edit"] is True
            assert agent["knowledge_base_ids"] == [knowledge_base_id]

            duplicate = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release Planner",
                    "instructions": "Duplicate",
                    "model_id": model_id,
                },
            )
            assert duplicate.status_code == 409, duplicate.text

            member_list = client.get(
                agents_url(workspace_id),
                headers=auth_headers(member_token),
            )
            assert member_list.status_code == 200, member_list.text
            assert member_list.json()[0]["can_edit"] is False
            assert member_list.json()[0]["knowledge_base_ids"] == []


            member_update = client.patch(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=auth_headers(member_token),
                json={"name": "Changed"},
            )
            assert member_update.status_code == 403, member_update.text

            member_question = client.post(
                agents_url(workspace_id, f"/{agent_id}/runs"),
                headers=auth_headers(member_token),
                json={"goal": "Prepare the release"},
            )
            assert member_question.status_code == 201, member_question.text
            member_run = member_question.json()
            assert member_run["status"] == "succeeded"
            assert len(member_run["plan"]) == 1
            assert member_run["plan"][0]["status"] == "completed"
            own_run = client.get(
                agents_url(workspace_id, f"/{agent_id}/runs/{member_run['id']}"),
                headers=auth_headers(member_token),
            )
            assert own_run.status_code == 200, own_run.text
            hidden_run = client.get(
                agents_url(workspace_id, f"/{agent_id}/runs/{member_run['id']}"),
                headers=auth_headers(admin_token),
            )
            assert hidden_run.status_code == 404, hidden_run.text
            plan_calls = [
                call
                for call in AgentModelHandler.calls
                if "agent_submit_plan"
                in {
                    tool["function"]["name"]
                    for tool in call.get("tools", [])
                    if tool.get("type") == "function"
                }
            ]
            assert plan_calls
            assert "citations" not in member_run
            assert member_run["trace_id"]
            assert query_calls == []

            grant = client.put(
                knowledge_url(workspace_id, f"/{knowledge_base_id}/permissions/{member_id}"),
                headers=auth_headers(admin_token),
                json={"permission": "view"},
            )
            assert grant.status_code == 200, grant.text

            permitted_question = client.post(
                agents_url(workspace_id, f"/{agent_id}/runs"),
                headers=auth_headers(member_token),
                json={"goal": "Prepare the release with evidence"},
            )
            assert permitted_question.status_code == 201, permitted_question.text
            executed = permitted_question.json()
            assert executed["status"] == "succeeded"
            assert executed["result"] == "Completed."
            knowledge_event = next(
                event
                for event in executed["events"]
                if event["type"] == "tool" and event["tool_kind"] == "knowledge"
            )
            assert knowledge_event["tool_name"].startswith("knowledge_")
            assert "citations" not in executed
            assert executed["trace_id"]
            assert query_calls == [(knowledge_base_id, "release process")]
            assert knowledge_event["call_id"] == "call-search"
            assert knowledge_event["tool_label"] == "Release Docs"
            assert knowledge_event["tool_kind"] == "knowledge"
            assert knowledge_event["input"] == {"query": "release process"}
            assert "source_id" not in knowledge_event["output"]["hits"][0]
            assert knowledge_event["output"]["hits"][0]["document"] == "release.md"

            streamed_question = client.post(
                agents_url(workspace_id, f"/{agent_id}/runs/stream"),
                headers=auth_headers(member_token),
                json={"goal": "Stream the release evidence"},
            )
            streamed_events = stream_payloads(streamed_question)
            streamed_types = {item["type"] for item in streamed_events}
            assert {"run", "process", "answer_delta", "complete"} <= streamed_types
            assert streamed_events[-1]["run"]["status"] == "succeeded"

            member_mcp_create = client.post(
                mcp_url(workspace_id),
                headers=auth_headers(member_token),
                json={
                    "name": "Release MCP",
                    "url": "http://127.0.0.1:9999/mcp",
                },
            )
            assert member_mcp_create.status_code == 403, member_mcp_create.text

            mcp_server = client.post(
                mcp_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release MCP",
                    "url": "http://127.0.0.1:9999/mcp",
                    "bearer_token": "mcp-secret-token",
                },
            )
            assert mcp_server.status_code == 201, mcp_server.text
            mcp_server_data = mcp_server.json()
            assert mcp_server_data["has_bearer_token"] is True
            assert "bearer_token" not in mcp_server_data

            mcp_agent = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release Tool Agent",
                    "model_id": model_id,
                    "mcp_tools": [
                        {
                            "server_id": mcp_server_data["id"],
                            "tool_name": "lookup_release",
                        }
                    ],
                },
            )
            assert mcp_agent.status_code == 201, mcp_agent.text
            mcp_agent_data = mcp_agent.json()
            assert mcp_agent_data["mcp_tools"][0]["tool_name"] == "lookup_release"

            mcp_question = client.post(
                agents_url(workspace_id, f"/{mcp_agent_data['id']}/runs"),
                headers=auth_headers(admin_token),
                json={"goal": "Check the release"},
            )
            assert mcp_question.status_code == 201, mcp_question.text
            mcp_run = mcp_question.json()
            assert mcp_run["status"] == "awaiting_approval"
            assert mcp_run["pending_approval"]["tool_name"].startswith("mcp_")
            assert mcp_calls == []
            resumed = client.post(
                agents_url(
                    workspace_id,
                    f"/{mcp_agent_data['id']}/runs/{mcp_run['id']}/resume/stream",
                ),
                headers=auth_headers(admin_token),
                json={"decision": "approved"},
            )
            resumed_events = stream_payloads(resumed)
            mcp_run = next(
                item["run"]
                for item in reversed(resumed_events)
                if item["type"] in {"complete", "pause", "error"}
            )
            assert mcp_run["status"] == "succeeded"
            mcp_event = next(
                event
                for event in mcp_run["events"]
                if event["type"] == "tool" and event["tool_kind"] == "mcp"
            )
            assert mcp_event["status"] == "succeeded"
            assert mcp_event["call_id"] == "call-mcp"
            assert mcp_event["tool_label"] == "lookup_release"
            assert mcp_event["tool_kind"] == "mcp"
            assert mcp_event["server_name"] == "Release MCP"
            assert mcp_event["input"] == {"topic": "release"}
            assert mcp_event["output"] == {"release": "approved"}
            assert mcp_calls == [
                (
                    "http://127.0.0.1:9999/mcp",
                    "lookup_release",
                    {"topic": "release"},
                )
            ]

            member_agent = client.post(
                agents_url(workspace_id),
                headers=auth_headers(member_token),
                json={
                    "name": "Member Agent",
                    "instructions": "Use permitted workspace knowledge.",
                    "model_id": model_id,
                    "knowledge_base_ids": [knowledge_base_id],
                },
            )
            assert member_agent.status_code == 201, member_agent.text
            revoked = client.delete(
                knowledge_url(
                    workspace_id,
                    f"/{knowledge_base_id}/permissions/{member_id}",
                ),
                headers=auth_headers(admin_token),
            )
            assert revoked.status_code == 204, revoked.text
            member_agent_update = client.patch(
                agents_url(workspace_id, f"/{member_agent.json()['id']}"),
                headers=auth_headers(member_token),
                json={
                    "description": "Updated without knowledge access",
                    "instructions": "",
                },
            )
            assert member_agent_update.status_code == 200, member_agent_update.text
            assert member_agent_update.json()["knowledge_base_ids"] == []
            assert member_agent_update.json()["instructions"]

            AgentModelHandler.fail_next_decision = True
            failed_question = client.post(
                agents_url(
                    workspace_id,
                    f"/{member_agent.json()['id']}/runs",
                ),
                headers=auth_headers(member_token),
                json={"goal": "Recover this run"},
            )
            assert failed_question.status_code == 201, failed_question.text
            failed_run = failed_question.json()
            assert failed_run["status"] == "failed"
            assert failed_run["resumable"] is True
            recovered_response = client.post(
                agents_url(
                    workspace_id,
                    f"/{member_agent.json()['id']}/runs/{failed_run['id']}/resume/stream",
                ),
                headers=auth_headers(member_token),
                json={"decision": None},
            )
            recovered_events = stream_payloads(recovered_response)
            recovered_run = next(
                item["run"]
                for item in reversed(recovered_events)
                if item["type"] in {"complete", "pause", "error"}
            )
            assert recovered_run["status"] == "succeeded"

            created_workspace = client.post(
                "/api/v1/workspaces",
                headers=auth_headers(admin_token),
                json={
                    "name": "Other Workspace",
                    "admin": {
                        "username": "other-admin",
                        "email": "other-admin@example.com",
                        "name": "Other Admin",
                    },
                },
            )
            assert created_workspace.status_code == 201, created_workspace.text
            other_workspace_id = created_workspace.json()["workspace"]["id"]
            other_password = created_workspace.json()["admin_initial_password"]
            other_token = activate_user(
                client,
                "other-admin",
                other_password,
                RESEARCH_PASSWORD,
            )
            other_model = client.post(
                f"/api/v1/workspaces/{other_workspace_id}/models",
                headers=auth_headers(other_token),
                json=model_payload(model_base_url, "Other Agent Model"),
            )
            assert other_model.status_code == 201, other_model.text

            cross_workspace_model = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Cross Workspace Agent",
                    "instructions": "Invalid",
                    "model_id": other_model.json()["id"],
                },
            )
            assert cross_workspace_model.status_code == 422, cross_workspace_model.text

            disabled_model = client.patch(
                f"/api/v1/workspaces/{workspace_id}/models/{model_id}",
                headers=auth_headers(admin_token),
                json={"status": "disabled"},
            )
            assert disabled_model.status_code == 200, disabled_model.text

            disabled = client.patch(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=auth_headers(admin_token),
                json={"model_id": model_id, "status": "disabled"},
            )
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["status"] == "disabled"

            deleted = client.delete(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=auth_headers(admin_token),
            )
            assert deleted.status_code == 204, deleted.text

            audit_logs = client.get(
                "/api/v1/admin/audit-logs",
                headers=auth_headers(admin_token),
            )
            actions = [item["action"] for item in audit_logs.json()]
            assert "agent.create" in actions
            assert "agent.delete" in actions
    finally:
        agent_application.query_knowledge_base = original_query
        mcp_services.discover_mcp_tools = original_discover
        agent_application.call_mcp_tool = original_call_mcp_tool


if __name__ == "__main__":
    main()

"""Coverage suite for the public/API agent access domain.

Covers app/application/agent_access.py, app/api/v1/endpoints/agent_access.py and
app/infrastructure/agent_rate_limit.py.  Plain-script suite (no pytest): run with

    uv run coverage run --source=app.application.agent_access,app.api.v1.endpoints.agent_access,app.infrastructure.agent_rate_limit \
        --data-file=.coverage.AgentAccessCoverage -m tests.agent_access
    uv run coverage report -m --data-file=.coverage.AgentAccessCoverage

Pure helpers (payload limiting, progress events, stream sanitizing, rate limit
window) are exercised directly; the HTTP surface is driven through a real
TestClient with a local model server, published agent and API credentials.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

# Must be the first app-adjacent import: sets test env before app modules load.
from tests.support import (  # noqa: F401
    activate_admin,
    activate_user,
    auth_headers,
    create_active_user,
    settings as test_settings,
    test_client,
)

from app.application import agent_access
from app.application import agent_runs
from app.application.agent_access import (
    TOOL_INPUT_LIMITS,
    ToolPayloadLimits,
    _bounded_tool_payload,
    _limit_tool_payload,
    create_agent_api_token,
    external_progress_events,
    external_run_to_response,
    hash_agent_access_token,
    sanitize_external_agent_stream,
)
from app.infrastructure import agent_rate_limit as rate_limit_module
from app.infrastructure.agent_rate_limit import (
    AgentRateLimitExceeded,
    AgentRateLimitUnavailable,
    enforce_external_agent_rate_limit,
)
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.session import get_session_factory
from app.shareddomain.agents.models import (
    Agent as AgentOrm,
    AgentApiCredential as AgentApiCredentialOrm,
    AgentRun as AgentRunOrm,
)

MEMBER_PASSWORD = "AgentMember@12345."


# ---------------------------------------------------------------------------
# Local model server
# ---------------------------------------------------------------------------

class AgentModelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            delta = {"role": "assistant", "content": "Completed."}
            chunks = [
                {
                    "id": "access-test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {"index": 0, "delta": delta, "finish_reason": None}
                    ],
                },
                {
                    "id": "access-test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ],
                },
            ]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = {
            "id": "access-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Completed."},
                    "finish_reason": "stop",
                }
            ],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *args) -> None:
        return


@contextmanager
def agent_model_server() -> Iterator[str]:
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
        "provider_type": "deepseek",
        "model_type": "LLM",
        "model_name": "deepseek-chat",
        "credential": {"api_base": api_base, "api_key": "sk-agent-test-1234"},
    }


def agents_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/agents{suffix}"


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
            "name": username.title(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], response.json()["initial_password"]


# ---------------------------------------------------------------------------
# Pure helper coverage
# ---------------------------------------------------------------------------

def assert_token_helpers() -> None:
    token = create_agent_api_token()
    assert token.startswith("nxf_")
    assert len(token) > 40
    assert hash_agent_access_token(token) == hash_agent_access_token(token)
    assert len(hash_agent_access_token(token)) == 64
    assert hash_agent_access_token(token) != hash_agent_access_token(token + "x")


def assert_tool_payload_limits() -> None:
    # 151: budget exhausted at function entry.
    value, truncated = _limit_tool_payload({"a": 1}, 0, [0, 10], TOOL_INPUT_LIMITS)
    assert value == "…" and truncated

    # Depth exhaustion (148-149).
    deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    value, truncated = _limit_tool_payload(
        deep, 0, [200, 8000], TOOL_INPUT_LIMITS
    )
    assert truncated

    # 162-163: dict key longer than max_string is truncated.
    value, truncated = _limit_tool_payload(
        {"k" * 600: "v"}, 0, [200, 8000], TOOL_INPUT_LIMITS
    )
    assert truncated
    (key,) = value.keys()
    assert key == "k" * 500 + "…"

    # 177-178: list budget exhausted mid-loop.
    value, truncated = _limit_tool_payload([1, 2, 3, 4], 0, [1, 8000], TOOL_INPUT_LIMITS)
    assert truncated
    assert len(value) == 1

    # Dict budget exhausted mid-loop (156-158).
    value, truncated = _limit_tool_payload(
        {"a": 1, "b": 2, "c": 3}, 0, [1, 8000], TOOL_INPUT_LIMITS
    )
    assert truncated
    assert len(value) == 1

    # List longer than max_items (185-187).
    value, truncated = _limit_tool_payload(
        list(range(50)), 0, [200, 8000], TOOL_INPUT_LIMITS
    )
    assert truncated
    assert len(value) == 25

    # Long string truncated (188-192).
    value, truncated = _limit_tool_payload("x" * 900, 0, [200, 8000], TOOL_INPUT_LIMITS)
    assert truncated
    assert len(value) == 500 + 1

    # Scalar passthrough (193-195).
    value, truncated = _limit_tool_payload(42, 0, [200, 8000], TOOL_INPUT_LIMITS)
    assert value == 42 and not truncated
    value, truncated = _limit_tool_payload(None, 0, [200, 8000], TOOL_INPUT_LIMITS)
    assert value is None and not truncated
    value, truncated = _limit_tool_payload(True, 0, [200, 8000], TOOL_INPUT_LIMITS)
    assert value is True and not truncated

    # Fallback str() branch: long text truncated (196-199).
    value, truncated = _limit_tool_payload(
        tuple(range(300)), 0, [200, 8000], TOOL_INPUT_LIMITS
    )
    assert isinstance(value, str) and truncated
    # Fallback str() branch: short text returned unchanged (200).
    value, truncated = _limit_tool_payload((1, 2), 0, [200, 8000], TOOL_INPUT_LIMITS)
    assert value == "(1, 2)" and not truncated

    # _bounded_tool_payload: serialized size overflow → {"truncated": True} (211-214).
    wide = ToolPayloadLimits(
        max_string=500,
        max_depth=4,
        max_items=25,
        max_total_items=200,
        max_total_chars=100000,
        max_serialized=1000,
    )
    value, truncated = _bounded_tool_payload(
        {f"k{i}": "x" * 500 for i in range(25)}, wide
    )
    assert value == {"truncated": True} and truncated

    # _bounded_tool_payload happy path keeps structure (208-210, 215).
    value, truncated = _bounded_tool_payload({"q": "short"}, TOOL_INPUT_LIMITS)
    assert value == {"q": "short"} and not truncated


def assert_external_progress_events() -> None:
    events = [
        # 235: status outside the allowed set is skipped.
        {"type": "thought", "status": "queued", "turn": 1, "summary": "agent.answer_ready"},
        # 241-256: answer ready on succeeded run.
        {
            "type": "thought",
            "status": "succeeded",
            "turn": 2,
            "summary": "agent.answer_ready",
            "reasoning": "done reasoning",
        },
        # 257-276: analysis stage.
        {
            "type": "thought",
            "status": "running",
            "turn": 3,
            "summary": "agent.analyzing",
            "reasoning": "analyzing",
        },
        {
            "type": "thought",
            "status": "running",
            "turn": 4,
            "summary": "agent.preparing_tool_call",
            "reasoning": "ready",
        },
        {
            "type": "tool",
            "status": "running",
            "turn": 5,
            "summary": "agent.preparing_tool_call",
            "tool_kind": "unknown",
            "tool_name": "web_search",
            "tool_label": "Web search",
            "input": {"query": "release"},
            "call_id": "call-preparing",
        },
        # 280: non-thought, non-tool event skipped.
        {"type": "message", "status": "succeeded", "turn": 5, "summary": "hello"},
        # 288-295 + 296-310: knowledge tool with count and hits.
        {
            "type": "tool",
            "status": "succeeded",
            "turn": 6,
            "summary": "agent.knowledge_chunks_returned:3",
            "tool_kind": "knowledge",
            "tool_name": "search_knowledge",
            "tool_label": "Search Knowledge",
            "server_name": "",
            "input": {"query": "release"},
            "call_id": "call-knowledge",
            "output": {
                "hits": [
                    {
                        "knowledge_base": "kb-1",
                        "document": "doc-1",
                        "content": "release notes",
                    },
                    "not-a-dict",
                ],
                "graph_revision_id": "revision-secret",
                "entity_id": "entity-secret",
                "claim_id": "claim-secret",
                "evidence_id": "evidence-secret",
                "profile_markdown": "SECRET_GRAPH_PROFILE",
                "quote": "SECRET_GRAPH_QUOTE",
            },
        },
        # 294-295: count parse ValueError keeps count None.
        {
            "type": "tool",
            "status": "running",
            "turn": 7,
            "summary": "agent.knowledge_chunks_returned:abc",
            "tool_kind": "knowledge",
            "input": {},
            "call_id": "call-bad-count",
        },
        # 285-286: unknown tool_kind normalized to "unknown".
        {
            "type": "tool",
            "status": "succeeded",
            "turn": 8,
            "summary": "done",
            "tool_kind": "custom",
            "tool_name": "custom_tool",
            "input": {"q": "v"},
            "call_id": "call-custom",
        },
    ]
    progress = external_progress_events(events, "succeeded")
    assert len(progress) == 7, [item.type for item in progress]

    answer = next(item for item in progress if item.type == "answer")
    assert answer.status == "succeeded"
    assert answer.stage == "succeeded"
    assert answer.turn == 2
    assert answer.reasoning == "done reasoning"

    analysis = next(item for item in progress if item.type == "analysis")
    assert analysis.stage == "analyzing"
    assert analysis.status == "running"

    preparing = next(item for item in progress if item.stage == "running")
    assert preparing.type == "analysis"
    assert preparing.reasoning == "ready"

    tool_preparing = next(item for item in progress if item.stage == "preparing")
    assert tool_preparing.type == "tool"
    assert tool_preparing.tool_name == "web_search"
    assert tool_preparing.input == {"query": "release"}

    knowledge = next(item for item in progress if item.type == "knowledge")
    assert knowledge.count == 3
    assert len(knowledge.hits) == 1
    assert knowledge.hits[0].knowledge_base == "kb-1"
    assert knowledge.hits[0].document == "doc-1"
    assert knowledge.output is None
    serialized_knowledge = json.dumps(knowledge.model_dump(), ensure_ascii=False)
    for marker in (
        "revision-secret",
        "entity-secret",
        "claim-secret",
        "evidence-secret",
        "SECRET_GRAPH_PROFILE",
        "SECRET_GRAPH_QUOTE",
    ):
        assert marker not in serialized_knowledge

    bad_count = next(item for item in progress if item.turn == 7)
    assert bad_count.count is None

    custom = next(item for item in progress if item.turn == 8)
    assert custom.tool_kind == "unknown"

    # 227-228: upsert replaces the previous event with the same id.
    replaced = external_progress_events(
        [
            {
                "type": "thought",
                "status": "running",
                "turn": 9,
                "summary": "agent.analyzing",
                "reasoning": "first",
            },
            {
                "type": "thought",
                "status": "running",
                "turn": 9,
                "summary": "agent.analyzing",
                "reasoning": "second",
            },
        ],
        "running",
    )
    assert len(replaced) == 1
    assert replaced[0].reasoning == "second"

    # 246: failed run → answer status failed.
    failed = external_progress_events(
        [
            {
                "type": "thought",
                "status": "failed",
                "turn": 1,
                "summary": "agent.answer_ready",
            }
        ],
        "failed",
    )
    assert failed[0].status == "failed"


def assert_external_run_to_response() -> None:
    # 342: cancelled run → generic error.
    cancelled = SimpleNamespace(
        id="r-cancelled",
        conversation_id="c-1",
        status="cancelled",
        goal="goal",
        result="",
        events=[],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at=None,
        finished_at=None,
    )
    response = external_run_to_response(cancelled)
    assert response.error == "Agent run was cancelled."

    # 339-340: failed run → generic error.
    failed = SimpleNamespace(
        id="r-failed",
        conversation_id="c-2",
        status="failed",
        goal="goal",
        result="",
        events=[],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at=None,
        finished_at=None,
    )
    response = external_run_to_response(failed)
    assert response.error == "Agent run failed."

    # dict input; "question" fallback (335-336, 346-354).
    as_dict = {
        "id": "r-dict",
        "conversation_id": "c-3",
        "status": "queued",
        "question": "asked",
        "result": "result text",
        "events": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "started_at": None,
        "finished_at": None,
    }
    response = external_run_to_response(as_dict)
    assert response.status == "queued"
    assert response.question == "asked"
    assert response.result == "result text"
    assert response.error is None


async def assert_sanitize_external_agent_stream() -> None:
    def run_payload(run_id: str, status: str) -> dict:
        return {
            "id": run_id,
            "conversation_id": "c-1",
            "status": status,
            "goal": "goal",
            "result": "out",
            "events": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "started_at": None,
            "finished_at": None,
        }

    async def events() -> AsyncIterator[dict]:
        yield {
            "type": "answer_delta",
            "delta": "hello",
            "sequence": 1,
            "stream_epoch": "epoch-1",
        }
        yield {
            "type": "answer_reset",
            "live_sequence": "2-0",
            "stream_epoch": "epoch-1",
        }
        yield {
            "type": "reasoning_delta",
            "turn": -2,
            "delta": "thinking",
            "live_sequence": "3-1",
            "stream_epoch": "epoch-1",
        }
        yield {
            "type": "process",
            "event": {
                "type": "thought",
                "status": "running",
                "turn": 1,
                "summary": "agent.analyzing",
                "reasoning": "step",
            },
            "sequence": 2,
        }
        # 389, 394-395: approval_required sanitized with metadata.
        yield {
            "type": "approval_required",
            "call_id": "call-approve",
            "reason": "sensitive tool",
            "sequence": 3,
        }
        yield {
            "type": "complete",
            "run": run_payload("r-1", "succeeded"),
            "sequence": 4,
        }
        yield {
            "type": "error",
            "run": run_payload("r-2", "cancelled"),
            "sequence": 5,
        }
        yield {"type": "unknown", "sequence": 6}

    sanitized = []
    async for event in sanitize_external_agent_stream(events()):
        sanitized.append(event)

    assert [event["type"] for event in sanitized] == [
        "answer_delta",
        "answer_reset",
        "reasoning_delta",
        "progress",
        "approval_required",
        "complete",
        "error",
    ]
    answer = sanitized[0]
    assert answer["delta"] == "hello"
    assert answer["sequence"] == 1
    # _copy_external_stream_metadata hashes the epoch.
    assert answer["stream_epoch"] != "epoch-1"
    assert len(answer["stream_epoch"]) == 32

    reset = sanitized[1]
    assert reset["live_sequence"] == "2-0"
    assert reset["stream_epoch"] == answer["stream_epoch"]

    reasoning = sanitized[2]
    assert reasoning["turn"] == 0  # negative turn clamped
    assert reasoning["live_sequence"] == "3-1"

    progress_event = sanitized[3]["event"]
    assert progress_event["type"] == "analysis"

    approval = sanitized[4]
    assert approval["call_id"] == "call-approve"
    assert approval["reason"] == "sensitive tool"
    assert approval["sequence"] == 3

    complete = sanitized[5]
    assert complete["run"]["id"] == "r-1"
    error = sanitized[6]
    assert error["run"]["error"] == "Agent run was cancelled."


def assert_usage_total_tokens() -> None:
    assert agent_access._usage_total_tokens(None) == 0
    assert agent_access._usage_total_tokens({}) == 0
    assert agent_access._usage_total_tokens({"total_tokens": 5}) == 5
    assert agent_access._usage_total_tokens({"total_tokens": "x"}) == 0
    assert agent_access._usage_total_tokens({"total_tokens": -1}) == 0
    assert agent_access._usage_total_tokens({"total_tokens": 0}) == 0


async def assert_rate_limit_module() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    original = rate_limit_module._rate_limit_redis

    class FakeRedis:
        def __init__(self, result):
            self.result = result

        async def eval(self, *_args, **_kwargs):
            if self.result is None:
                raise RedisConnectionError("no redis")
            return self.result

    settings = test_settings()
    try:
        # 64-65: redis unavailable → AgentRateLimitUnavailable.
        rate_limit_module._rate_limit_redis = lambda _url: FakeRedis(None)
        try:
            await enforce_external_agent_rate_limit(
                settings, "agent-1", "public", "consumer-1"
            )
            raise AssertionError("expected AgentRateLimitUnavailable")
        except AgentRateLimitUnavailable:
            pass

        # 72: agent window exceeded → AgentRateLimitExceeded with retry-after.
        rate_limit_module._rate_limit_redis = lambda _url: FakeRedis([101, 1, 30, 30])
        try:
            await enforce_external_agent_rate_limit(
                settings, "agent-1", "public", "consumer-1"
            )
            raise AssertionError("expected AgentRateLimitExceeded")
        except AgentRateLimitExceeded as exc:
            assert exc.retry_after == 30

        # Consumer window exceeded.
        rate_limit_module._rate_limit_redis = lambda _url: FakeRedis([1, 11, 59, 5])
        try:
            await enforce_external_agent_rate_limit(
                settings, "agent-1", "public", "consumer-1"
            )
            raise AssertionError("expected AgentRateLimitExceeded")
        except AgentRateLimitExceeded as exc:
            assert exc.retry_after == 59

        # Within limits: no exception (67-71).
        rate_limit_module._rate_limit_redis = lambda _url: FakeRedis([5, 3, 60, 60])
        await enforce_external_agent_rate_limit(
            settings, "agent-1", "public", "consumer-1"
        )

        assert "retry after 5s" in str(AgentRateLimitExceeded(5))

        # Cover _rate_limit_redis itself (24-33) without opening a connection:
        # Redis.from_url is lazy, so constructing the client is side-effect free.
        original_client = rate_limit_module._redis_client
        try:
            redis_client = original("redis://localhost:6379/0")
            assert redis_client is not None
        finally:
            rate_limit_module._redis_client = original_client
    finally:
        rate_limit_module._rate_limit_redis = original


# ---------------------------------------------------------------------------
# Direct application-layer unit coverage (needs the in-memory DB)
# ---------------------------------------------------------------------------

async def _expect_http(status_code: int, awaitable) -> None:
    try:
        await awaitable
    except HTTPException as exc:
        assert exc.status_code == status_code, (
            status_code,
            exc.status_code,
            exc.detail,
        )
        return
    raise AssertionError(f"expected HTTPException {status_code}")


async def assert_direct_access_units(
    workspace_id: str,
    agent_id: str,
    credential_id: str,
    active_token: str,
) -> None:
    settings = test_settings()
    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        agent = await agent_repository.get_agent_by_id(db, agent_id)
        assert agent is not None

        # --- create credential IntegrityError → 409 (599-602) ---
        original_new = agent_access._new_agent_api_credential

        async def broken_new(*_args, **_kwargs):
            raise IntegrityError("stmt", {}, "boom")

        agent_access._new_agent_api_credential = broken_new
        try:
            await _expect_http(
                409,
                agent_access.create_agent_api_credential(
                    db, workspace_id, agent_id, "dup", actor, "admin"
                ),
            )
        finally:
            agent_access._new_agent_api_credential = original_new

        # --- rotate IntegrityError → 409 (687-690) ---
        original_rotate = agent_repository.rotate_agent_api_credential

        async def broken_rotate(*_args, **_kwargs):
            raise IntegrityError("stmt", {}, "boom")

        agent_repository.rotate_agent_api_credential = broken_rotate
        try:
            await _expect_http(
                409,
                agent_access.rotate_agent_api_credential(
                    db, workspace_id, agent_id, credential_id, actor, "admin"
                ),
            )
        finally:
            agent_repository.rotate_agent_api_credential = original_rotate

        # --- rotate reports no active row → 409 (670-671) ---
        async def no_rotate(*_args, **_kwargs):
            return None

        agent_repository.rotate_agent_api_credential = no_rotate
        try:
            await _expect_http(
                409,
                agent_access.rotate_agent_api_credential(
                    db, workspace_id, agent_id, credential_id, actor, "admin"
                ),
            )
        finally:
            agent_repository.rotate_agent_api_credential = original_rotate

        # --- authenticate: naive last_used_at normalized (725-726) + mark used ---
        credential = await agent_repository.get_agent_api_credential_by_id(
            db, credential_id
        )
        assert credential is not None
        await db.execute(
            update(AgentApiCredentialOrm)
            .where(AgentApiCredentialOrm.id == credential_id)
            .values(last_used_at=(utc_now() - timedelta(minutes=5)).replace(tzinfo=None))
        )
        await db.commit()
        context, credential = await agent_access.authenticate_agent_api_credential(
            db, agent_id, active_token
        )
        assert credential.last_used_at is not None
        assert context.agent.id == agent_id

        # Second call within the 60s window skips the mark (727).
        await agent_access.authenticate_agent_api_credential(db, agent_id, active_token)

        # --- mark_agent_api_credential_used returns False → 401 (728-733) ---
        await db.execute(
            update(AgentApiCredentialOrm)
            .where(AgentApiCredentialOrm.id == credential_id)
            .values(last_used_at=None)
        )
        await db.commit()
        original_mark = agent_repository.mark_agent_api_credential_used

        async def fail_mark(*_args, **_kwargs):
            return False

        agent_repository.mark_agent_api_credential_used = fail_mark
        try:
            await _expect_http(
                401,
                agent_access.authenticate_agent_api_credential(
                    db, agent_id, active_token
                ),
            )
        finally:
            agent_repository.mark_agent_api_credential_used = original_mark

        # --- create_external_agent_run: publication None → 404 (773-774) ---
        bare_context = agent_access.PublishedAgentContext(
            agent=SimpleNamespace(id=agent_id, workspace_id=workspace_id),
            publisher=SimpleNamespace(),
            workspace=SimpleNamespace(),
            publication=None,
        )
        await _expect_http(
            404,
            agent_access.create_external_agent_run(
                db, bare_context, "public", "consumer", "goal", settings
            ),
        )

        # --- create_external_agent_run: api + file_ids → 422 (776-781) ---
        publication_context = agent_access.PublishedAgentContext(
            agent=SimpleNamespace(id=agent_id, workspace_id=workspace_id),
            publisher=SimpleNamespace(),
            workspace=SimpleNamespace(),
            publication=SimpleNamespace(),
        )
        await _expect_http(
            422,
            agent_access.create_external_agent_run(
                db,
                publication_context,
                "api",
                "consumer",
                "goal",
                settings,
                file_ids=["f1"],
            ),
        )

        # --- get_published_application_context: wrong app_type → 404 (441-449) ---
        await _expect_http(
            404,
            agent_access.get_published_application_context(db, agent_id, "workflow"),
        )
        # Unknown agent → 404.
        await _expect_http(
            404,
            agent_access.get_published_application_context(db, "missing-agent", "agent"),
        )

        # --- publisher lookup returns None → 404 (453-457) ---
        original_get_user = agent_access.user_repository.get_user_by_id

        async def missing_user(*_args, **_kwargs):
            return None

        agent_access.user_repository.get_user_by_id = missing_user
        try:
            await _expect_http(
                404,
                agent_access.get_published_application_context(db, agent_id, "agent"),
            )
        finally:
            agent_access.user_repository.get_user_by_id = original_get_user

        # --- build_workspace_context failure → 404 (459-465) ---
        original_build = agent_access.build_workspace_context

        async def broken_build(*_args, **_kwargs):
            raise HTTPException(status_code=403, detail="no access")

        agent_access.build_workspace_context = broken_build
        try:
            await _expect_http(
                404,
                agent_access.get_published_application_context(db, agent_id, "agent"),
            )
        finally:
            agent_access.build_workspace_context = original_build

        # --- publication rebuilt from bindings when snapshot missing (466-475) ---
        row = await db.get(AgentOrm, agent_id)
        assert row is not None
        original_snapshot = row.published_snapshot
        await db.execute(
            update(AgentOrm).where(AgentOrm.id == agent_id).values(
                published_snapshot=None
            )
        )
        await db.commit()
        rebuilt = await agent_access.get_published_application_context(
            db, agent_id, "agent"
        )
        assert rebuilt.publication is not None
        assert rebuilt.publication.name == agent.name
        await db.execute(
            update(AgentOrm).where(AgentOrm.id == agent_id).values(
                published_snapshot=original_snapshot
            )
        )
        await db.commit()

        # --- get_workspace_published_application_context re-raises other
        #     HTTPExceptions (519) ---
        calls = {"n": 0}

        async def selective_build(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return await original_build(*_args, **_kwargs)
            raise HTTPException(status_code=400, detail="boom")

        agent_access.build_workspace_context = selective_build
        try:
            await _expect_http(
                400,
                agent_access.get_workspace_published_application_context(
                    db, agent_id, actor, "agent"
                ),
            )
        finally:
            agent_access.build_workspace_context = original_build

        # --- get_public_agent_profile: publication None → 404 (529-530) ---
        original_workspace_ctx = (
            agent_access.get_workspace_published_agent_context
        )

        async def none_publication(*_args, **_kwargs):
            return agent_access.PublishedAgentContext(
                agent=SimpleNamespace(id=agent_id),
                publisher=SimpleNamespace(),
                workspace=SimpleNamespace(),
                publication=None,
            )

        agent_access.get_workspace_published_agent_context = none_publication
        try:
            await _expect_http(
                404, agent_access.get_public_agent_profile(db, agent_id, actor)
            )
        finally:
            agent_access.get_workspace_published_agent_context = (
                original_workspace_ctx
            )

        # --- get_agent_monitoring: invalid days → 422 (1083-1087) ---
        await _expect_http(
            422,
            agent_access.get_agent_monitoring(
                db, workspace_id, agent_id, actor, "admin", 1
            ),
        )

        # --- workflow-context delegators (432, 496) ---
        await _expect_http(
            404, agent_access.get_published_workflow_context(db, agent_id)
        )
        await _expect_http(
            404,
            agent_access.get_workspace_published_workflow_context(
                db, agent_id, actor
            ),
        )

        # --- list_agent_api_credentials: admin success + member 403 (547-548) ---
        listed = await agent_access.list_agent_api_credentials(
            db, workspace_id, agent_id, actor, "admin"
        )
        assert isinstance(listed.items, list)
        await _expect_http(
            403,
            agent_access.list_agent_api_credentials(
                db, workspace_id, agent_id, actor, "member"
            ),
        )

        # --- create_agent_api_credential success path (589-599, 606) ---
        created_response = await agent_access.create_agent_api_credential(
            db, workspace_id, agent_id, "Direct Key", actor, "admin"
        )
        assert created_response.token.startswith("nxf_")
        direct_credential_id = created_response.credential.id

        # --- revoke_agent_api_credential success path (620-640) ---
        await agent_access.revoke_agent_api_credential(
            db, workspace_id, agent_id, direct_credential_id, actor, "admin"
        )
        # Revoking again is a no-op (626).
        await agent_access.revoke_agent_api_credential(
            db, workspace_id, agent_id, direct_credential_id, actor, "admin"
        )
        # Revoking an unknown credential → 404 (624-625).
        await _expect_http(
            404,
            agent_access.revoke_agent_api_credential(
                db, workspace_id, agent_id, "missing-credential", actor, "admin"
            ),
        )
        # Member revoke → 403 (620).
        await _expect_http(
            403,
            agent_access.revoke_agent_api_credential(
                db, workspace_id, agent_id, "missing-credential", actor, "member"
            ),
        )

        # --- rotate_agent_api_credential: revoked → 409 (659) ---
        await _expect_http(
            409,
            agent_access.rotate_agent_api_credential(
                db, workspace_id, agent_id, direct_credential_id, actor, "admin"
            ),
        )
        # Rotating an unknown credential → 404 (657).
        await _expect_http(
            404,
            agent_access.rotate_agent_api_credential(
                db, workspace_id, agent_id, "missing-credential", actor, "admin"
            ),
        )
        # Rotate success path (675-687).
        rotated_response = await agent_access.create_agent_api_credential(
            db, workspace_id, agent_id, "Rotate Key", actor, "admin"
        )
        rotated_key_id = rotated_response.credential.id
        rotated_again = await agent_access.rotate_agent_api_credential(
            db, workspace_id, agent_id, rotated_key_id, actor, "admin"
        )
        assert rotated_again.credential.id == rotated_key_id
        assert rotated_again.token.startswith("nxf_")
        assert rotated_again.token != rotated_response.token

        # --- authenticate_agent_api_credential: unknown hash → 401 (710-711) ---
        await _expect_http(
            401,
            agent_access.authenticate_agent_api_credential(
                db, agent_id, "nxf_" + "z" * 40
            ),
        )

        # --- authenticate_agent_api_credential: publication failure → 404 (716-717) ---
        original_pub_context = agent_access.get_published_application_context

        async def unpublished_context(*_args, **_kwargs):
            raise HTTPException(status_code=404, detail="unpublished")

        agent_access.get_published_application_context = unpublished_context
        try:
            await _expect_http(
                404,
                agent_access.authenticate_agent_api_credential(
                    db, agent_id, active_token
                ),
            )
        finally:
            agent_access.get_published_application_context = original_pub_context

        # --- create_external_agent_run success path (802-804) ---
        # The eager run execution inside enqueue_prepared_agent_run disrupts
        # coverage tracing of the caller frame, so the direct calls use a no-op
        # enqueue; the real eager path is covered by the HTTP flow above.
        original_enqueue_access = agent_access.enqueue_prepared_agent_run
        original_enqueue_runs = agent_runs.enqueue_prepared_agent_run

        async def noop_enqueue(*_args, **_kwargs):
            return None

        agent_access.enqueue_prepared_agent_run = noop_enqueue
        agent_runs.enqueue_prepared_agent_run = noop_enqueue
        try:
            live_context = await agent_access.get_published_application_context(
                db, agent_id, "agent"
            )
            locked_agent = await agent_repository.lock_agent(db, agent_id)
            assert locked_agent is not None
            current_publication_id = locked_agent.current_published_version_id
            assert current_publication_id is not None
            try:
                locked_agent.current_published_version_id = None
                await agent_repository.save_agent(db, locked_agent)
                await db.commit()
                await _expect_http(
                    409,
                    agent_access.create_external_agent_run(
                        db,
                        live_context,
                        "public",
                        "stale-publication-consumer",
                        "Stale publication question",
                        settings,
                    ),
                )
            finally:
                locked_agent = await agent_repository.lock_agent(db, agent_id)
                assert locked_agent is not None
                locked_agent.current_published_version_id = current_publication_id
                await agent_repository.save_agent(db, locked_agent)
                await db.commit()
            direct_run_response = await agent_access.create_external_agent_run(
                db, live_context, "public", "direct-consumer", "Direct question",
                settings,
            )
            assert direct_run_response.id
            direct_run_id = direct_run_response.id

            # --- get_external_agent_run: success (815-816, 823) + wrong consumer (822) ---
            run = await agent_access.get_external_agent_run(
                db, agent_id, direct_run_id, "public", "direct-consumer"
            )
            assert run.id == direct_run_id
            await _expect_http(
                404,
                agent_access.get_external_agent_run(
                    db, agent_id, direct_run_id, "public", "other-consumer"
                ),
            )

            # --- resolve_external_agent_tool_approval: approve + reject (852-860) ---
            from app.entities.agents import AgentToolCall

            approve_run, _ = await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "Direct approve",
                actor,
                "admin",
                access_source="public",
                consumer_id=actor.id,
            )
            approve_run.configuration_source = "legacy"
            approve_run.agent_publication_version_id = None
            await db.execute(
                update(AgentRunOrm)
                .where(AgentRunOrm.id == approve_run.id)
                .values(
                    status="awaiting_approval",
                    configuration_source="legacy",
                    agent_publication_version_id=None,
                )
            )
            await agent_repository.create_agent_tool_call(
                db,
                AgentToolCall(
                    workspace_id=workspace_id,
                    run_id=approve_run.id,
                    turn=1,
                    call_id="call-direct-approve",
                    tool_name="lookup_release",
                    tool_kind="mcp",
                    arguments_hash="h",
                    idempotency_key="idem-direct-approve",
                    status="awaiting_approval",
                    approval_required=True,
                ),
            )
            await db.commit()
            approved_run = await agent_access.resolve_external_agent_tool_approval(
                db, agent_id, approve_run.id, "call-direct-approve", "public",
                actor, settings, approve=True,
            )
            assert approved_run.id == approve_run.id

            reject_run, _ = await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "Direct reject",
                actor,
                "admin",
                access_source="public",
                consumer_id=actor.id,
            )
            reject_run.configuration_source = "legacy"
            reject_run.agent_publication_version_id = None
            await db.execute(
                update(AgentRunOrm)
                .where(AgentRunOrm.id == reject_run.id)
                .values(
                    status="awaiting_approval",
                    configuration_source="legacy",
                    agent_publication_version_id=None,
                )
            )
            await agent_repository.create_agent_tool_call(
                db,
                AgentToolCall(
                    workspace_id=workspace_id,
                    run_id=reject_run.id,
                    turn=1,
                    call_id="call-direct-reject",
                    tool_name="lookup_release",
                    tool_kind="mcp",
                    arguments_hash="h",
                    idempotency_key="idem-direct-reject",
                    status="awaiting_approval",
                    approval_required=True,
                ),
            )
            await db.commit()
            rejected_run = await agent_access.resolve_external_agent_tool_approval(
                db, agent_id, reject_run.id, "call-direct-reject", "public",
                actor, settings, approve=False,
            )
            assert rejected_run.id == reject_run.id
        finally:
            agent_access.enqueue_prepared_agent_run = original_enqueue_access
            agent_runs.enqueue_prepared_agent_run = original_enqueue_runs

        # --- list_external_agent_runs (873-882) ---
        listed_runs = await agent_access.list_external_agent_runs(
            db, agent_id, "public", "direct-consumer", 10, 0
        )
        assert listed_runs.total >= 1
        assert listed_runs.items

        # --- list_public_agent_conversations (902-906) ---
        conversations = await agent_access.list_public_agent_conversations(
            db, agent_id, "direct-consumer"
        )
        assert conversations.items

        # --- _consumer_display_names (966-981) ---
        all_rows = (await db.execute(select(AgentRunOrm))).scalars().all()
        pairs = list(
            dict.fromkeys(
                (row.access_source, row.consumer_id) for row in all_rows
            )
        )
        names = await agent_access._consumer_display_names(db, pairs)
        assert len(names) == len(pairs)

        # --- list_agent_logs (994-1029) ---
        logs = await agent_access.list_agent_logs(
            db, workspace_id, agent_id, actor, "admin", 50, 0
        )
        assert logs.total >= 1
        assert logs.items
        assert all(item.display_name for item in logs.items)

        # --- list_agent_conversation_users (1042-1065) ---
        users = await agent_access.list_agent_conversation_users(
            db, workspace_id, agent_id, actor, "admin", 50, 0
        )
        assert users.total >= 1
        assert users.items

        # --- get_agent_monitoring success path (1089-1143) ---
        monitoring = await agent_access.get_agent_monitoring(
            db, workspace_id, agent_id, actor, "admin", 7
        )
        assert monitoring.summary.runs >= 1
        assert len(monitoring.daily) == 7

        # --- get_workspace_published_application_context normal return (520) ---
        context = await agent_access.get_workspace_published_application_context(
            db, agent_id, actor, "agent"
        )
        assert context.agent.id == agent_id

        # --- get_workspace_published_application_context: build 403 → 404 (515-518) ---
        forbidden_calls = {"n": 0}

        async def forbidden_build(*_args, **_kwargs):
            forbidden_calls["n"] += 1
            if forbidden_calls["n"] == 1:
                return await original_build(*_args, **_kwargs)
            raise HTTPException(status_code=403, detail="no access")

        agent_access.build_workspace_context = forbidden_build
        try:
            await _expect_http(
                404,
                agent_access.get_workspace_published_application_context(
                    db, agent_id, actor, "agent"
                ),
            )
        finally:
            agent_access.build_workspace_context = original_build

        # --- get_public_agent_profile success return (531) ---
        profile = await agent_access.get_public_agent_profile(db, agent_id, actor)
        assert profile.id == agent_id
        assert profile.name == agent.name


async def assert_documentation_404_direct(agent_id: str) -> None:
    import app.api.v1.endpoints.agent_access as endpoints_module

    async def fake_auth(*_args, **_kwargs):
        return (
            SimpleNamespace(agent=SimpleNamespace(id=agent_id), publication=None),
            SimpleNamespace(),
        )

    original = endpoints_module.authenticate_agent_api_credential
    endpoints_module.authenticate_agent_api_credential = fake_auth
    try:
        async with get_session_factory()() as db:
            await _expect_http(
                404,
                endpoints_module.get_api_agent_documentation(
                    agent_id, db, SimpleNamespace(scheme="bearer", credentials="x")
                ),
            )
    finally:
        endpoints_module.authenticate_agent_api_credential = original


async def assert_direct_endpoint_calls(
    workspace_id: str,
    agent_id: str,
    active_token: str,
    public_run_id: str,
    api_run_id: str,
) -> None:
    """Drive the endpoint functions directly from the main thread so the
    coverage tracer records every line (the TestClient worker thread drops
    trace events for a subset of lines)."""
    import io

    from fastapi.security import HTTPAuthorizationCredentials
    from starlette.datastructures import UploadFile

    import app.api.v1.endpoints.agent_access as endpoints_module

    from app.entities.agents import AgentToolCall

    settings = test_settings()
    async with get_session_factory()() as db:
        user = await user_repository.get_active_user_by_username(db, "admin")
        assert user is not None
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=active_token
        )

        # 87: conversations list.
        conversations = await endpoints_module.public_agent_conversations(
            agent_id, db, user
        )
        assert conversations.items

        # 103: public uploads.
        upload = UploadFile(
            filename="direct.txt",
            file=io.BytesIO(b"direct attachment"),
            headers={"content-type": "text/plain"},
        )
        uploads = await endpoints_module.upload_public_agent_attachments(
            agent_id, [upload], settings, db, user
        )
        assert uploads

        # 118: public runs list.
        runs = await endpoints_module.list_public_agent_runs(agent_id, db, user)
        assert runs.total >= 1

        # 183-184: public run stream.
        stream = await endpoints_module.stream_public_agent_run(
            agent_id, public_run_id, settings, db, user
        )
        chunks = [chunk async for chunk in stream.body_iterator]
        assert chunks
        assert any(b'"type": "run"' in chunk for chunk in chunks)
        assert any(b'"type": "complete"' in chunk for chunk in chunks)

        # 230: approve tool call.
        approve_run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "Direct endpoint approve",
            user,
            "admin",
            access_source="public",
            consumer_id=user.id,
        )
        approve_run.configuration_source = "legacy"
        approve_run.agent_publication_version_id = None
        await db.execute(
            update(AgentRunOrm)
            .where(AgentRunOrm.id == approve_run.id)
            .values(
                status="awaiting_approval",
                configuration_source="legacy",
                agent_publication_version_id=None,
            )
        )
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=approve_run.id,
                turn=1,
                call_id="call-ep-approve",
                tool_name="lookup_release",
                tool_kind="mcp",
                arguments_hash="h",
                idempotency_key="idem-ep-approve",
                status="awaiting_approval",
                approval_required=True,
            ),
        )
        await db.commit()
        approved = await endpoints_module.approve_public_agent_run_tool_call(
            agent_id, approve_run.id, "call-ep-approve", settings, db, user
        )
        assert approved.id == approve_run.id

        # 255: reject tool call.
        reject_run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "Direct endpoint reject",
            user,
            "admin",
            access_source="public",
            consumer_id=user.id,
        )
        reject_run.configuration_source = "legacy"
        reject_run.agent_publication_version_id = None
        await db.execute(
            update(AgentRunOrm)
            .where(AgentRunOrm.id == reject_run.id)
            .values(
                status="awaiting_approval",
                configuration_source="legacy",
                agent_publication_version_id=None,
            )
        )
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=reject_run.id,
                turn=1,
                call_id="call-ep-reject",
                tool_name="lookup_release",
                tool_kind="mcp",
                arguments_hash="h",
                idempotency_key="idem-ep-reject",
                status="awaiting_approval",
                approval_required=True,
            ),
        )
        await db.commit()
        rejected = await endpoints_module.reject_public_agent_run_tool_call(
            agent_id, reject_run.id, "call-ep-reject", settings, db, user
        )
        assert rejected.id == reject_run.id

        # 290: API documentation response.
        docs = await endpoints_module.get_api_agent_documentation(
            agent_id, db, credentials
        )
        assert docs.agent_id == agent_id
        assert docs.agent_name == "Access Coverage Agent"

        # 333-336: API run lookup.
        api_run = await endpoints_module.get_api_agent_run(
            agent_id, api_run_id, db, credentials
        )
        assert api_run.id == api_run_id

        # 352-354: API run stream.
        api_stream = await endpoints_module.stream_api_agent_run(
            agent_id, api_run_id, settings, db, credentials
        )
        api_chunks = [chunk async for chunk in api_stream.body_iterator]
        assert any(b'"type": "complete"' in chunk for chunk in api_chunks)


# ---------------------------------------------------------------------------
# DB seeding helpers used by the HTTP flow
# ---------------------------------------------------------------------------

async def seed_approval(workspace_id: str, run_id: str, call_id: str) -> None:
    from app.entities.agents import AgentToolCall
    from app.shareddomain.agents.models import AgentRun as AgentRunOrm

    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        assert run is not None
        await db.execute(
            update(AgentRunOrm)
            .where(AgentRunOrm.id == run_id)
            .values(
                status="awaiting_approval",
                configuration_source="legacy",
                agent_publication_version_id=None,
            )
        )
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=run_id,
                turn=1,
                call_id=call_id,
                tool_name="lookup_release",
                tool_kind="mcp",
                arguments_hash="h",
                idempotency_key=f"idem-{call_id}",
                status="awaiting_approval",
                approval_required=True,
            ),
        )
        await db.commit()


async def seed_runs_for_logs_and_monitoring(
    workspace_id: str,
    agent_id: str,
) -> None:
    """
    Seed succeeded, failed, and historical agent runs for log and monitoring tests.
    
    Parameters:
        workspace_id (str): Workspace containing the runs.
        agent_id (str): Agent associated with the runs.
    """
    from app.shareddomain.agents.models import AgentRun as AgentRunOrm

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        succeeded, _ = await agent_runs.prepare_agent_run(
            db, workspace_id, agent_id, "Monitor success", actor, "admin"
        )
        failed, _ = await agent_runs.prepare_agent_run(
            db, workspace_id, agent_id, "Monitor failure", actor, "admin"
        )
        old, _ = await agent_runs.prepare_agent_run(
            db, workspace_id, agent_id, "Old console run", actor, "admin"
        )
        await db.execute(
            update(AgentRunOrm)
            .where(AgentRunOrm.id == succeeded.id)
            .values(
                status="succeeded",
                result="Monitor answer",
                model_usage={"total_tokens": 120},
                feedback="positive",
                feedback_updated_at=utc_now(),
            )
        )
        await db.execute(
            update(AgentRunOrm)
            .where(AgentRunOrm.id == failed.id)
            .values(status="failed", model_usage={"total_tokens": 7})
        )
        await db.execute(
            update(AgentRunOrm)
            .where(AgentRunOrm.id == old.id)
            .values(status="succeeded", created_at=utc_now() - timedelta(days=100))
        )
        await db.commit()


async def hard_delete_credential(credential_id: str) -> None:
    async with get_session_factory()() as db:
        await db.execute(
            delete(AgentApiCredentialOrm).where(
                AgentApiCredentialOrm.id == credential_id
            )
        )
        await db.commit()


# ---------------------------------------------------------------------------
# HTTP integration flow
# ---------------------------------------------------------------------------

def assert_http_external_access() -> None:
    """Exercise end-to-end external agent access through public and API interfaces.
    
    Verifies authentication, publication visibility, credential management, run creation and retrieval, streaming, tool approvals, access isolation, audit logs, monitoring, and rate-limit responses.
    """
    original_rate_limit = agent_access.enforce_external_agent_rate_limit
    original_run_agent = None

    async def allow_rate_limit(*_args, **_kwargs) -> None:
        return None

    agent_access.enforce_external_agent_rate_limit = allow_rate_limit
    try:
        with test_client() as client, agent_model_server() as model_base_url:
            admin_token, workspace_id = activate_admin(client)
            admin_user_id = client.get(
                "/api/v1/auth/me",
                headers=auth_headers(admin_token),
            ).json()["user"]["id"]

            model_resp = client.post(
                f"/api/v1/workspaces/{workspace_id}/models",
                headers=auth_headers(admin_token),
                json=model_payload(model_base_url, "Access Agent Model"),
            )
            assert model_resp.status_code == 201, model_resp.text
            model_id = model_resp.json()["id"]

            created = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Access Coverage Agent",
                    "description": "Coverage target agent",
                    "instructions": "Answer directly.",
                    "interaction_config": {
                        "prologue": "How can I help?",
                        "tts_type": "BROWSER",
                        "file_upload": True,
                        "file_upload_setting": {
                            "file_upload_type": ["document"],
                        },
                    },
                    "model_id": model_id,
                },
            )
            assert created.status_code == 201, created.text
            agent_id = created.json()["id"]
            management_base = agents_url(workspace_id, f"/{agent_id}")
            public_base = f"/api/v1/public/agents/{agent_id}"
            api_base = f"/api/v1/agent-api/{agent_id}"

            # ---- publish + profile ----
            assert client.get(f"{public_base}/profile").status_code == 401
            unpublished = client.get(
                f"{public_base}/profile",
                headers=auth_headers(admin_token),
            )
            assert unpublished.status_code == 404, unpublished.text
            published = client.patch(
                management_base,
                headers=auth_headers(admin_token),
                json={"published": True},
            )
            assert published.status_code == 200, published.text
            profile = client.get(
                f"{public_base}/profile",
                headers=auth_headers(admin_token),
            )
            assert profile.status_code == 200, profile.text
            assert profile.json()["name"] == "Access Coverage Agent"
            # Unknown agent → 404 (449).
            missing_profile = client.get(
                "/api/v1/public/agents/does-not-exist/profile",
                headers=auth_headers(admin_token),
            )
            assert missing_profile.status_code == 404

            # ---- member: credential management and logs are admin-only ----
            member_user_id, temporary = create_workspace_user(
                client, admin_token, workspace_id, "access-member"
            )
            member_token = activate_user(
                client, "access-member", temporary, MEMBER_PASSWORD
            )
            member_create = client.post(
                f"{management_base}/api-credentials",
                headers=auth_headers(member_token),
                json={"name": "Member key"},
            )
            assert member_create.status_code == 403, member_create.text
            member_list = client.get(
                f"{management_base}/api-credentials",
                headers=auth_headers(member_token),
            )
            assert member_list.status_code == 403, member_list.text
            member_logs = client.get(
                f"{management_base}/logs",
                headers=auth_headers(member_token),
            )
            assert member_logs.status_code == 403, member_logs.text

            # ---- credentials: create/list ----
            key_a = client.post(
                f"{management_base}/api-credentials",
                headers=auth_headers(admin_token),
                json={"name": "Integration Key"},
            )
            assert key_a.status_code == 201, key_a.text
            token_a = key_a.json()["token"]
            credential_a_id = key_a.json()["credential"]["id"]
            assert token_a.startswith("nxf_")
            listed = client.get(
                f"{management_base}/api-credentials",
                headers=auth_headers(admin_token),
            )
            assert listed.status_code == 200, listed.text
            assert any(
                item["id"] == credential_a_id for item in listed.json()["items"]
            )

            # ---- api authentication / documentation ----
            assert client.get(f"{api_base}/documentation").status_code == 401
            # Token without nxf_ prefix → 401 (705-706).
            assert (
                client.get(
                    f"{api_base}/documentation",
                    headers={"Authorization": "Bearer bad-token"},
                ).status_code
                == 401
            )
            docs = client.get(
                f"{api_base}/documentation",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert docs.status_code == 200, docs.text
            assert docs.json()["agent_name"] == "Access Coverage Agent"

            # ---- public uploads (103) ----
            uploaded = client.post(
                f"{public_base}/uploads",
                headers=auth_headers(admin_token),
                files=[("files", ("ctx.txt", b"attachment data", "text/plain"))],
            )
            assert uploaded.status_code == 201, uploaded.text
            upload_id = uploaded.json()[0]["id"]

            # ---- public run with attachment + list + get + stream ----
            public_run = client.post(
                f"{public_base}/runs",
                headers=auth_headers(admin_token),
                json={"goal": "Public question", "file_ids": [upload_id]},
            )
            assert public_run.status_code == 201, public_run.text
            public_run_id = public_run.json()["id"]
            assert public_run.json()["question"] == "Public question"

            public_list = client.get(
                f"{public_base}/runs",
                headers=auth_headers(admin_token),
            )
            assert public_list.status_code == 200, public_list.text
            assert public_list.json()["total"] >= 1

            public_get = client.get(
                f"{public_base}/runs/{public_run_id}",
                headers=auth_headers(admin_token),
            )
            assert public_get.status_code == 200, public_get.text
            assert public_get.json()["id"] == public_run_id

            # stream public run (182-184)
            public_stream = client.get(
                f"{public_base}/runs/{public_run_id}/stream",
                headers=auth_headers(admin_token),
            )
            assert public_stream.status_code == 200, public_stream.text
            assert public_stream.headers["content-type"].startswith(
                "application/x-ndjson"
            )
            stream_events = [
                json.loads(line) for line in public_stream.text.splitlines()
            ]
            assert stream_events
            assert stream_events[0]["type"] == "run"
            assert any(
                event["type"] == "complete" for event in stream_events
            ), stream_events

            # conversations (86-87)
            conversations = client.get(
                f"{public_base}/conversations",
                headers=auth_headers(admin_token),
            )
            assert conversations.status_code == 200, conversations.text
            assert any(
                item["conversation_id"]
                == public_run.json()["conversation_id"]
                for item in conversations.json()["items"]
            )

            # ---- approve / reject tool calls (230, 254-255) ----
            approve_run = client.post(
                f"{public_base}/runs",
                headers=auth_headers(admin_token),
                json={"goal": "Approval flow"},
            )
            assert approve_run.status_code == 201, approve_run.text
            approve_run_id = approve_run.json()["id"]
            asyncio.run(seed_approval(workspace_id, approve_run_id, "call-approve"))
            tool_calls = client.get(
                f"{public_base}/runs/{approve_run_id}/tool-calls",
                headers=auth_headers(admin_token),
            )
            assert tool_calls.status_code == 200, tool_calls.text
            assert any(
                item["call_id"] == "call-approve"
                and item["status"] == "awaiting_approval"
                for item in tool_calls.json()
            )
            approved = client.post(
                f"{public_base}/runs/{approve_run_id}/tool-calls/call-approve/approve",
                headers=auth_headers(admin_token),
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["id"] == approve_run_id

            reject_run = client.post(
                f"{public_base}/runs",
                headers=auth_headers(admin_token),
                json={"goal": "Reject flow"},
            )
            assert reject_run.status_code == 201, reject_run.text
            reject_run_id = reject_run.json()["id"]
            asyncio.run(seed_approval(workspace_id, reject_run_id, "call-reject"))
            rejected = client.post(
                f"{public_base}/runs/{reject_run_id}/tool-calls/call-reject/reject",
                headers=auth_headers(admin_token),
            )
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["id"] == reject_run_id

            # ---- cross-user isolation (822) ----
            outsider_id, outsider_token = create_active_user(
                client, admin_token, "access-outsider"
            )
            outsider_membership = client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=auth_headers(admin_token),
                json={"user_id": outsider_id, "role": "member"},
            )
            assert outsider_membership.status_code == 201, outsider_membership.text
            cross_user_read = client.get(
                f"{public_base}/runs/{public_run_id}",
                headers=auth_headers(outsider_token),
            )
            assert cross_user_read.status_code == 404, cross_user_read.text

            # ---- user outside the workspace → 404 (510-518) ----
            second_ws = client.post(
                "/api/v1/workspaces",
                headers=auth_headers(admin_token),
                json={"name": "Second Space", "admin_user_id": admin_user_id},
            )
            assert second_ws.status_code == 201, second_ws.text
            second_ws_id = second_ws.json()["workspace"]["id"]
            foreign_id, foreign_token = create_active_user(
                client, admin_token, "access-foreign"
            )
            foreign_membership = client.post(
                f"/api/v1/workspaces/{second_ws_id}/members",
                headers=auth_headers(admin_token),
                json={"user_id": foreign_id, "role": "member"},
            )
            assert foreign_membership.status_code == 201, foreign_membership.text
            foreign_profile = client.get(
                f"{public_base}/profile",
                headers=auth_headers(foreign_token),
            )
            assert foreign_profile.status_code == 404, foreign_profile.text

            # ---- API runs: create / get / stream ----
            api_run = client.post(
                f"{api_base}/runs",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"goal": "API question"},
            )
            assert api_run.status_code == 201, api_run.text
            api_run_id = api_run.json()["id"]

            api_get = client.get(
                f"{api_base}/runs/{api_run_id}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert api_get.status_code == 200, api_get.text
            assert api_get.json()["id"] == api_run_id

            api_stream = client.get(
                f"{api_base}/runs/{api_run_id}/stream",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert api_stream.status_code == 200, api_stream.text
            assert api_stream.headers["content-type"].startswith(
                "application/x-ndjson"
            )
            api_events = [
                json.loads(line) for line in api_stream.text.splitlines()
            ]
            assert any(event["type"] == "complete" for event in api_events)

            # second key for cross-key tests
            key_b = client.post(
                f"{management_base}/api-credentials",
                headers=auth_headers(admin_token),
                json={"name": "Second Key"},
            )
            assert key_b.status_code == 201, key_b.text
            token_b = key_b.json()["token"]
            credential_b_id = key_b.json()["credential"]["id"]
            api_run_b = client.post(
                f"{api_base}/runs",
                headers={"Authorization": f"Bearer {token_b}"},
                json={"goal": "API question B"},
            )
            assert api_run_b.status_code == 201, api_run_b.text
            api_run_b_id = api_run_b.json()["id"]
            # Cross-key read → 404 (816-822).
            cross_key_read = client.get(
                f"{api_base}/runs/{api_run_b_id}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert cross_key_read.status_code == 404, cross_key_read.text

            # ---- rotate (652-663, 675-677) ----
            rotated = client.post(
                f"{management_base}/api-credentials/{credential_a_id}/rotate",
                headers=auth_headers(admin_token),
            )
            assert rotated.status_code == 201, rotated.text
            rotated_token = rotated.json()["token"]
            assert rotated_token != token_a
            old_token_read = client.get(
                f"{api_base}/runs/{api_run_id}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert old_token_read.status_code == 401, old_token_read.text
            rotated_read = client.get(
                f"{api_base}/runs/{api_run_id}",
                headers={"Authorization": f"Bearer {rotated_token}"},
            )
            assert rotated_read.status_code == 200, rotated_read.text
            # Rotate unknown credential → 404 (656-657).
            rotate_missing = client.post(
                f"{management_base}/api-credentials/does-not-exist/rotate",
                headers=auth_headers(admin_token),
            )
            assert rotate_missing.status_code == 404, rotate_missing.text

            # ---- revoke (620-640) ----
            revoke_b = client.delete(
                f"{management_base}/api-credentials/{credential_b_id}",
                headers=auth_headers(admin_token),
            )
            assert revoke_b.status_code == 204, revoke_b.text
            # Second revoke is a no-op (626).
            assert (
                client.delete(
                    f"{management_base}/api-credentials/{credential_b_id}",
                    headers=auth_headers(admin_token),
                ).status_code
                == 204
            )
            revoke_missing = client.delete(
                f"{management_base}/api-credentials/does-not-exist",
                headers=auth_headers(admin_token),
            )
            assert revoke_missing.status_code == 404, revoke_missing.text
            # Revoked credential is rejected by auth.
            revoked_docs = client.get(
                f"{api_base}/documentation",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert revoked_docs.status_code == 401, revoked_docs.text
            # Rotating a revoked credential → 409 (658-659).
            rotate_revoked = client.post(
                f"{management_base}/api-credentials/{credential_b_id}/rotate",
                headers=auth_headers(admin_token),
            )
            assert rotate_revoked.status_code == 409, rotate_revoked.text

            # ---- audit logs ----
            audit_logs = client.get(
                f"/api/v1/workspaces/{workspace_id}/audit-logs",
                headers=auth_headers(admin_token),
            )
            assert audit_logs.status_code == 200, audit_logs.text
            actions = [item["action"] for item in audit_logs.json()]
            assert "agent.api_credential.create" in actions
            assert "agent.api_credential.rotate" in actions
            assert "agent.api_credential.revoke" in actions

            # Hard-delete credential B so its run shows bare "API Key" (974-977).
            asyncio.run(hard_delete_credential(credential_b_id))

            # ---- visitor run + delete visitor → "Visitor …" (968-970) ----
            visitor_id, visitor_token = create_active_user(
                client, admin_token, "access-visitor"
            )
            visitor_membership = client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=auth_headers(admin_token),
                json={"user_id": visitor_id, "role": "member"},
            )
            assert visitor_membership.status_code == 201, visitor_membership.text
            visitor_run = client.post(
                f"{public_base}/runs",
                headers=auth_headers(visitor_token),
                json={"goal": "Visitor question"},
            )
            assert visitor_run.status_code == 201, visitor_run.text
            visitor_delete = client.delete(
                f"/api/v1/admin/users/{visitor_id}",
                headers=auth_headers(admin_token),
            )
            assert visitor_delete.status_code == 204, visitor_delete.text

            # ---- console + monitoring rows seeded directly ----
            asyncio.run(seed_runs_for_logs_and_monitoring(workspace_id, agent_id))

            # ---- logs (994-1009, 1029) ----
            logs = client.get(
                f"{management_base}/logs",
                headers=auth_headers(admin_token),
            )
            assert logs.status_code == 200, logs.text
            assert logs.json()["total"] >= 4
            display_names = [item["display_name"] for item in logs.json()["items"]]
            assert any(name.startswith("Visitor ") for name in display_names)
            assert "API Key: Integration Key" in display_names
            assert "API Key" in display_names
            assert any(
                name and not name.startswith(("Visitor ", "API Key"))
                for name in display_names
            )
            assert any(item["feedback"] == "positive" for item in logs.json()["items"])
            assert any(
                item["feedback_updated_at"]
                for item in logs.json()["items"]
                if item["feedback"] == "positive"
            )

            # ---- conversation-users (1042-1043, 1065) ----
            users = client.get(
                f"{management_base}/conversation-users",
                headers=auth_headers(admin_token),
            )
            assert users.status_code == 200, users.text
            assert users.json()["total"] >= 4
            assert all(
                item["display_name"] for item in users.json()["items"]
            )

            # ---- monitoring (1089-1093, 1107-1130, 1143) ----
            monitoring = client.get(
                f"{management_base}/monitoring?days=7",
                headers=auth_headers(admin_token),
            )
            assert monitoring.status_code == 200, monitoring.text
            summary = monitoring.json()["summary"]
            assert summary["succeeded"] >= 1
            assert summary["failed"] >= 1
            assert summary["total_tokens"] >= 100
            assert len(monitoring.json()["daily"]) == 7

            # ---- unpublish → 404 for public + api; republish ----
            unpublished = client.patch(
                management_base,
                headers=auth_headers(admin_token),
                json={"published": False},
            )
            assert unpublished.status_code == 200, unpublished.text
            public_while_unpublished = client.post(
                f"{public_base}/runs",
                headers=auth_headers(admin_token),
                json={"goal": "Unavailable"},
            )
            assert public_while_unpublished.status_code == 404
            api_while_unpublished = client.post(
                f"{api_base}/runs",
                headers={"Authorization": f"Bearer {rotated_token}"},
                json={"goal": "Unavailable"},
            )
            assert api_while_unpublished.status_code == 404
            api_history_while_unpublished = client.get(
                f"{api_base}/runs/{api_run_id}",
                headers={"Authorization": f"Bearer {rotated_token}"},
            )
            assert api_history_while_unpublished.status_code == 404
            republished = client.patch(
                management_base,
                headers=auth_headers(admin_token),
                json={"published": True},
            )
            assert republished.status_code == 200, republished.text

            # ---- rate limit mapping in _enforce_rate_limit (749-759) ----
            from app.infrastructure.agent_rate_limit import (
                AgentRateLimitExceeded,
                AgentRateLimitUnavailable,
            )

            async def exceed_rate_limit(*_args, **_kwargs) -> None:
                raise AgentRateLimitExceeded(42)

            agent_access.enforce_external_agent_rate_limit = exceed_rate_limit
            limited = client.post(
                f"{api_base}/runs",
                headers={"Authorization": f"Bearer {rotated_token}"},
                json={"goal": "Limited"},
            )
            assert limited.status_code == 429, limited.text
            assert limited.headers["retry-after"] == "42"

            async def unavailable_rate_limit(*_args, **_kwargs) -> None:
                raise AgentRateLimitUnavailable

            agent_access.enforce_external_agent_rate_limit = unavailable_rate_limit
            unavailable_run = client.post(
                f"{api_base}/runs",
                headers={"Authorization": f"Bearer {rotated_token}"},
                json={"goal": "Unavailable"},
            )
            assert unavailable_run.status_code == 503, unavailable_run.text
            agent_access.enforce_external_agent_rate_limit = allow_rate_limit

            # ---- direct unit coverage ----
            asyncio.run(
                assert_direct_access_units(
                    workspace_id, agent_id, credential_a_id, rotated_token
                )
            )
            asyncio.run(assert_documentation_404_direct(agent_id))
            asyncio.run(
                assert_direct_endpoint_calls(
                    workspace_id,
                    agent_id,
                    rotated_token,
                    public_run_id,
                    api_run_id,
                )
            )
    finally:
        agent_access.enforce_external_agent_rate_limit = original_rate_limit
        if original_run_agent is not None:
            from app.application import agent_executor

            agent_executor.run_agent = original_run_agent


# ---------------------------------------------------------------------------

def main() -> None:
    assert_token_helpers()
    assert_tool_payload_limits()
    assert_external_progress_events()
    assert_external_run_to_response()
    asyncio.run(assert_sanitize_external_agent_stream())
    assert_usage_total_tokens()
    asyncio.run(assert_rate_limit_module())
    assert_http_external_access()
    print("OK: agent_access coverage suite passed")


if __name__ == "__main__":
    main()

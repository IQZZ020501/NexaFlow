import hashlib
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.llm.runtime import (
    ModelProviderError,
    ModelProviderStatusError,
    build_registered_model_provider,
)
from app.capabilities.mcp.client import McpClientError, call_mcp_tool
from app.capabilities.rag.retrieval import query_knowledge_base
from app.domain.user import User
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.schemas.agent import AgentRunResponse
from app.schemas.knowledge import KnowledgeQueryRequest
from app.shareddomain.agents.models import AgentRun
from app.shareddomain.agents.runner import (
    AgentRunnerError,
    AgentGraphState,
    AgentOrchestrator,
    AgentRuntimeContext,
    AgentTool,
    AgentToolResult,
    initial_agent_state,
)
from app.shareddomain.agents.services import (
    ACTIVE_STATUS,
    accessible_agent_knowledge_bases,
    can_edit_agent,
    get_agent,
    get_agent_model,
)
from app.shareddomain.knowledge.models import KnowledgeBase
from app.shareddomain.tools.services import (
    ResolvedMcpTool,
    bearer_token,
    resolve_mcp_tools,
)

MAX_KNOWLEDGE_HITS_PER_BASE = 3
MAX_KNOWLEDGE_CONTENT_CHARS = 2000
MAX_CITATION_EXCERPT_CHARS = 500
MAX_AGENT_TURNS = 12
MAX_AGENT_TOOL_CALLS = 16
MAX_AGENT_RETRIEVAL_CALLS = 6
AGENT_RUN_TIMEOUT_SECONDS = 600
STALE_AGENT_RUN_SECONDS = 120


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def run_to_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        workspace_id=run.workspace_id,
        agent_id=run.agent_id,
        requested_by_user_id=run.requested_by_user_id,
        goal=run.goal,
        model_id=run.model_id,
        model_name=run.model_name,
        status=run.status,
        plan=run.plan,
        plan_revision=run.plan_revision,
        events=run.events,
        citations=run.citations,
        pending_approval=run.pending_approval,
        budget=run.budget,
        usage=run.usage,
        result=run.result,
        last_error=run.last_error,
        stop_reason=run.stop_reason,
        resumable=run.resumable or is_stale_run(run),
        planned_at=run.planned_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def is_stale_run(run: AgentRun) -> bool:
    return run.status == "running" and aware_utc(run.updated_at) <= (
        datetime.now(timezone.utc) - timedelta(seconds=STALE_AGENT_RUN_SECONDS)
    )


def agent_run_budget() -> dict[str, Any]:
    return {
        "max_turns": MAX_AGENT_TURNS,
        "max_tool_calls": MAX_AGENT_TOOL_CALLS,
        "max_retrieval_calls": MAX_AGENT_RETRIEVAL_CALLS,
        "deadline_at": (
            datetime.now(timezone.utc) + timedelta(seconds=AGENT_RUN_TIMEOUT_SECONDS)
        ).isoformat(),
    }


async def list_agent_runs(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    limit: int = 20,
) -> list[AgentRunResponse]:
    await get_agent(db, workspace_id, agent_id)
    return [
        run_to_response(run)
        for run in await agent_repository.list_agent_runs(
            db,
            agent_id,
            actor.id,
            limit,
        )
    ]


def safe_agent_error(exc: Exception) -> str:
    if isinstance(exc, ModelProviderStatusError):
        return f"Agent model returned provider status {exc.status_code}."
    if isinstance(exc, AgentRunnerError):
        return str(exc)
    if isinstance(exc, ModelProviderError):
        return "Agent model request failed."
    return "Agent execution failed."


def build_knowledge_search_tool(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    settings: Settings,
    citations: list[dict[str, Any]],
) -> AgentTool:
    citation_ids = {
        f"{citation['knowledge_base_id']}:{citation['chunk_id']}": citation["source_id"]
        for citation in citations
    }

    async def execute(arguments: str) -> AgentToolResult:
        try:
            payload = KnowledgeSearchInput.model_validate_json(arguments)
        except ValidationError:
            return AgentToolResult(
                content="Knowledge search parameters are invalid.",
                summary="Invalid search parameters.",
                is_error=True,
            )

        try:
            selected_hits = await query_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(
                    query=payload.query,
                    limit=MAX_KNOWLEDGE_HITS_PER_BASE,
                ),
                settings,
            )
        except HTTPException:
            return AgentToolResult(
                content="Knowledge search failed for this source.",
                summary="agent.knowledge_search_failed",
                is_error=True,
            )

        tool_hits = []
        for hit in selected_hits:
            citation_key = f"{knowledge_base.id}:{hit.chunk_id}"
            source_id = citation_ids.get(citation_key)
            if source_id is None:
                source_id = f"S{len(citations) + 1}"
                citation_ids[citation_key] = source_id
                citations.append(
                    {
                        "source_id": source_id,
                        "knowledge_base_id": knowledge_base.id,
                        "knowledge_base_name": knowledge_base.name,
                        "document_id": hit.document_id,
                        "document_filename": hit.document_filename,
                        "chunk_id": hit.chunk_id,
                        "chunk_index": hit.chunk_index,
                        "excerpt": hit.content[:MAX_CITATION_EXCERPT_CHARS],
                    }
                )
            tool_hits.append(
                {
                    "source_id": source_id,
                    "knowledge_base_id": knowledge_base.id,
                    "knowledge_base": knowledge_base.name,
                    "document": hit.document_filename,
                    "content": hit.content[:MAX_KNOWLEDGE_CONTENT_CHARS],
                }
            )

        output = {"query": payload.query, "hits": tool_hits}
        return AgentToolResult(
            content=json.dumps({"hits": tool_hits}, ensure_ascii=False),
            summary=f"agent.knowledge_chunks_returned:{len(tool_hits)}",
            output=output,
        )

    return AgentTool(
        name=knowledge_function_name(knowledge_base),
        description=(
            f"Search the knowledge base '{knowledge_base.name}'. "
            "Use returned source IDs as citations in the final answer."
        ),
        parameters=KnowledgeSearchInput.model_json_schema(),
        execute=execute,
        display_name=knowledge_base.name,
        kind="knowledge",
    )


def knowledge_function_name(knowledge_base: KnowledgeBase) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", knowledge_base.name).strip("_")[:32]
    digest = hashlib.sha256(knowledge_base.id.encode()).hexdigest()[:8]
    return f"knowledge_{stem or 'source'}_{digest}"


def mcp_function_name(tool: ResolvedMcpTool) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", tool.name).strip("_")[:40] or "tool"
    digest = hashlib.sha256(
        f"{tool.server.id}:{tool.name}".encode()
    ).hexdigest()[:8]
    return f"mcp_{stem}_{digest}"


def build_mcp_agent_tool(tool: ResolvedMcpTool, settings: Settings) -> AgentTool:
    async def execute(arguments: str) -> AgentToolResult:
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError:
            return AgentToolResult(
                content="MCP tool parameters are invalid JSON.",
                summary=f"{tool.server.name}: {tool.name} received invalid parameters.",
                is_error=True,
            )
        if not isinstance(payload, dict):
            return AgentToolResult(
                content="MCP tool parameters must be an object.",
                summary=f"{tool.server.name}: {tool.name} received invalid parameters.",
                is_error=True,
            )
        try:
            content, is_error = await call_mcp_tool(
                tool.server.url,
                bearer_token(tool.server, settings),
                tool.name,
                payload,
                settings.mcp_allow_private_networks,
                settings.mcp_request_timeout_seconds,
            )
        except McpClientError:
            return AgentToolResult(
                content="MCP tool request failed.",
                summary=f"{tool.server.name}: {tool.name} request failed.",
                is_error=True,
            )
        safe_output: Any
        try:
            safe_output = json.loads(content)
        except json.JSONDecodeError:
            safe_output = content[:4000]
        return AgentToolResult(
            content=content,
            summary=f"{tool.server.name}: {tool.name} completed.",
            output=safe_output,
            is_error=is_error,
        )

    return AgentTool(
        name=mcp_function_name(tool),
        description=(
            f"MCP tool {tool.server.name}/{tool.name}. {tool.description}"
        )[:1000],
        parameters=tool.input_schema,
        execute=execute,
        display_name=tool.name,
        kind="mcp",
        server_name=tool.server.name,
        requires_approval=True,
    )


async def prepare_agent_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    goal: str,
    actor: User,
    workspace_role: str | None,
) -> tuple[AgentRun, Any]:
    agent = await get_agent(db, workspace_id, agent_id)
    if agent.status != ACTIVE_STATUS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Agent is disabled.")
    model = await get_agent_model(db, workspace_id, agent.model_id)
    knowledge_bindings = await agent_repository.list_binding_map(db, [agent.id])
    mcp_bindings = await agent_repository.list_mcp_binding_map(db, [agent.id])
    selected_mcp_tools = (
        mcp_bindings[agent.id]
        if can_edit_agent(agent, actor, workspace_role)
        else []
    )
    run = AgentRun(
        workspace_id=workspace_id,
        agent_id=agent.id,
        requested_by_user_id=actor.id,
        goal=goal.strip(),
        instructions=agent.instructions,
        knowledge_base_ids=knowledge_bindings[agent.id],
        mcp_tools=selected_mcp_tools,
        model_id=model.id,
        model_name=model.name,
        status="planning",
        plan=[],
        plan_revision=0,
        events=[],
        citations=[],
        pending_approval=None,
        budget=agent_run_budget(),
        usage={"turns": 0, "tool_calls": 0, "retrieval_calls": 0},
        result="",
        stop_reason=None,
        resumable=False,
        started_at=utc_now(),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run, model


async def get_agent_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    actor: User,
    *,
    for_update: bool = False,
) -> AgentRun:
    await get_agent(db, workspace_id, agent_id)
    run = (
        await agent_repository.get_agent_run_by_id_for_update(db, run_id)
        if for_update
        else await agent_repository.get_agent_run_by_id(db, run_id)
    )
    if (
        run is None
        or run.workspace_id != workspace_id
        or run.agent_id != agent_id
        or run.requested_by_user_id != actor.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found.")
    return run


async def build_agent_runtime(
    db: AsyncSession,
    run: AgentRun,
    model: Any,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> tuple[AgentRuntimeContext, list[dict[str, Any]]]:
    citations = list(run.citations or [])
    knowledge_bases = await accessible_agent_knowledge_bases(
        db,
        run.workspace_id,
        run.knowledge_base_ids,
        actor,
        workspace_role,
    )
    mcp_tools = await resolve_mcp_tools(
        db,
        run.workspace_id,
        run.mcp_tools,
        strict=False,
    )
    provider = build_registered_model_provider(model, settings)
    tools = [
        build_knowledge_search_tool(db, knowledge_base, settings, citations)
        for knowledge_base in knowledge_bases
    ]
    tools.extend(build_mcp_agent_tool(tool, settings) for tool in mcp_tools)
    return AgentRuntimeContext(provider, tools), citations


async def project_agent_state(
    db: AsyncSession,
    run: AgentRun,
    state: AgentGraphState,
    citations: list[dict[str, Any]],
    *,
    interrupted: bool,
) -> AgentRunResponse:
    run.plan = list(state.get("plan", []))
    run.plan_revision = state.get("plan_revision", 0)
    run.events = list(state.get("events", []))
    run.citations = list(citations)
    run.pending_approval = state.get("pending_approval")
    run.budget = dict(state.get("budget", run.budget))
    run.usage = dict(state.get("usage", run.usage))
    run.result = state.get("result", "")
    run.stop_reason = state.get("stop_reason") or None
    run.last_error = None
    run.resumable = False
    if run.plan and run.planned_at is None:
        run.planned_at = utc_now()
    run.status = "awaiting_approval" if interrupted else state.get("status", run.status)
    if run.status == "succeeded":
        run.finished_at = utc_now()
    await db.commit()
    await db.refresh(run)
    return run_to_response(run)


async def fail_agent_run(
    db: AsyncSession,
    run: AgentRun,
    orchestrator: AgentOrchestrator,
    exc: Exception,
) -> AgentRunResponse:
    run_id = run.id
    await db.rollback()
    persisted_run = await agent_repository.get_agent_run_by_id(db, run_id)
    if persisted_run is None:
        raise AgentRunnerError("Agent run disappeared during failure recovery.") from exc
    run = persisted_run
    try:
        run.resumable = await orchestrator.has_checkpoint(run_id)
    except Exception:
        run.resumable = False
    run.status = "failed"
    run.last_error = safe_agent_error(exc)
    run.stop_reason = "execution_failed"
    run.finished_at = utc_now()
    await db.commit()
    await db.refresh(run)
    return run_to_response(run)


async def execute_agent_graph(
    db: AsyncSession,
    run: AgentRun,
    model: Any,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
    orchestrator: AgentOrchestrator,
    *,
    state: AgentGraphState | None = None,
    approval_decision: str | None = None,
    recover: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    context: AgentRuntimeContext | None = None
    try:
        context, citations = await build_agent_runtime(
            db,
            run,
            model,
            actor,
            workspace_role,
            settings,
        )
        async for item in orchestrator.stream(
            run.id,
            context,
            state=state,
            approval_decision=approval_decision,
            recover=recover,
        ):
            if item["type"] == "custom":
                yield item["data"]
                continue
            if item["type"] != "values":
                continue
            response = await project_agent_state(
                db,
                run,
                item["data"],
                citations,
                interrupted=bool(item.get("interrupts")),
            )
            yield {"type": "run", "run": response.model_dump(mode="json")}
        response = run_to_response(run)
        yield {
            "type": "pause" if run.status == "awaiting_approval" else "complete",
            "run": response.model_dump(mode="json"),
        }
    except Exception as exc:
        response = await fail_agent_run(db, run, orchestrator, exc)
        yield {"type": "error", "run": response.model_dump(mode="json")}
    finally:
        if context is not None:
            context.provider.client.close()
            await context.provider.async_client.close()


async def stream_agent_run(
    db: AsyncSession,
    run: AgentRun,
    model: Any,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
    orchestrator: AgentOrchestrator,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "run", "run": run_to_response(run).model_dump(mode="json")}
    state = initial_agent_state(run.id, run.goal, run.instructions, run.budget)
    async for event in execute_agent_graph(
        db,
        run,
        model,
        actor,
        workspace_role,
        settings,
        orchestrator,
        state=state,
    ):
        yield event


async def create_agent_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    goal: str,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
    orchestrator: AgentOrchestrator,
) -> AgentRunResponse:
    run, model = await prepare_agent_run(
        db,
        workspace_id,
        agent_id,
        goal,
        actor,
        workspace_role,
    )
    async for _ in execute_agent_graph(
        db,
        run,
        model,
        actor,
        workspace_role,
        settings,
        orchestrator,
        state=initial_agent_state(run.id, run.goal, run.instructions, run.budget),
    ):
        pass
    return run_to_response(run)


async def prepare_agent_run_resume(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    decision: str | None,
    actor: User,
) -> tuple[AgentRun, Any, str | None, bool]:
    run = await get_agent_run(
        db,
        workspace_id,
        agent_id,
        run_id,
        actor,
        for_update=True,
    )
    model = await get_agent_model(db, workspace_id, run.model_id)
    recover = False
    if run.status == "awaiting_approval":
        if decision is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "An approval decision is required.",
            )
    elif run.status == "failed" and run.resumable:
        if decision is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Approval decision is not valid for this run.",
            )
        recover = True
    elif is_stale_run(run):
        if decision is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Approval decision is not valid for this run.",
            )
        recover = True
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "Agent run cannot be resumed.")

    run.status = "running"
    run.resumable = False
    run.last_error = None
    run.finished_at = None
    run.updated_at = utc_now()
    await db.commit()
    await db.refresh(run)
    return run, model, decision, recover


async def stream_agent_run_resume(
    db: AsyncSession,
    run: AgentRun,
    model: Any,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
    orchestrator: AgentOrchestrator,
    *,
    decision: str | None,
    recover: bool,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "run", "run": run_to_response(run).model_dump(mode="json")}
    async for event in execute_agent_graph(
        db,
        run,
        model,
        actor,
        workspace_role,
        settings,
        orchestrator,
        approval_decision=decision,
        recover=recover,
    ):
        yield event

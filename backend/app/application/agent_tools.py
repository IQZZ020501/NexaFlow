"""Agent tool construction and pure mapping helpers.

Sibling module of ``app.application.agents`` (which re-exports the public
surface): everything about building the agent's tools and converting runs to
responses lives here, separate from run orchestration.
"""

import asyncio
import hashlib
import json
import re
from typing import Any

from fastapi import HTTPException
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledge import query_knowledge_base
from app.entities.agents import AgentRun
from app.entities.knowledge import KnowledgeBase
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.session import get_session_factory
from app.ports.llm import (
    ModelProviderError,
    ModelProviderStatusError,
    build_reranker,
)
from app.ports.mcp import McpClientError, call_mcp_tool
from app.schemas.agent import AgentRunResponse
from app.schemas.knowledge import KnowledgeQueryRequest
from app.shareddomain.agents.runtime import (
    AgentRunnerError,
    AgentToolResult,
    create_agent_tool,
)
from app.shareddomain.agents.services import accessible_agent_knowledge_bases
from app.shareddomain.knowledge.services import get_knowledge_model
from app.shareddomain.tools.services import (
    ResolvedMcpTool,
    bearer_token,
    resolve_mcp_tools,
)

MAX_KNOWLEDGE_HITS_PER_BASE = 3
MAX_RERANK_HITS_PER_BASE = 10
MAX_RERANK_CONTEXT_HITS = 5
MAX_KNOWLEDGE_HITS_PER_CALL = 8
MAX_KNOWLEDGE_CONTENT_CHARS = 2000


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def run_to_response(run: AgentRun, *, trace_id: str = "") -> AgentRunResponse:
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
        events=run.events,
        result=run.result,
        last_error=run.last_error,
        planned_at=run.planned_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        trace_id=trace_id,
    )


def safe_agent_error(exc: Exception) -> str:
    if isinstance(exc, ModelProviderStatusError):
        return str(exc)
    if isinstance(exc, AgentRunnerError):
        return str(exc)
    if isinstance(exc, ModelProviderError):
        return "Agent model request failed."
    return "Agent execution failed."


def build_knowledge_search_tool(
    knowledge_bases: list[KnowledgeBase],
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> StructuredTool:
    knowledge_base_ids = [knowledge_base.id for knowledge_base in knowledge_bases]

    async def execute(arguments: str) -> AgentToolResult:
        try:
            payload = KnowledgeSearchInput.model_validate_json(arguments)
        except ValidationError:
            return AgentToolResult(
                content="Knowledge search parameters are invalid.",
                summary="Invalid search parameters.",
                is_error=True,
            )

        async with get_session_factory()() as tool_db:
            available_knowledge_bases = await accessible_agent_knowledge_bases(
                tool_db,
                workspace_id,
                knowledge_base_ids,
                actor,
                workspace_role,
            )
            if not available_knowledge_bases:
                return AgentToolResult(
                    content="Knowledge search failed for the configured sources.",
                    summary="Knowledge search failed.",
                    is_error=True,
                )

            retrieval_stats = []
            for knowledge_base in available_knowledge_bases:
                stats_entry = {
                    "knowledge_base_id": knowledge_base.id,
                    "knowledge_base_name": knowledge_base.name,
                    "candidates": 0,
                    "reranked": False,
                    "submitted": 0,
                }
                retrieval_stats.append(stats_entry)
                if knowledge_base.reranker_model_id is not None:
                    stats_entry["reranked"] = True
            hit_groups = []
            failed_sources = 0
            for knowledge_base in available_knowledge_bases:
                try:
                    hits = await query_knowledge_base(
                        tool_db,
                        knowledge_base,
                        KnowledgeQueryRequest(
                            query=payload.query,
                            limit=MAX_KNOWLEDGE_HITS_PER_BASE,
                        ),
                        settings,
                    )
                except HTTPException:
                    failed_sources += 1
                    continue
                hit_groups.append((knowledge_base, hits))

            reranked_groups: list[tuple[KnowledgeBase, list[Any]]] = []
            for knowledge_base, hits in hit_groups:
                stats_entry = next(
                    entry
                    for entry in retrieval_stats
                    if entry["knowledge_base_id"] == knowledge_base.id
                )
                stats_entry["candidates"] = len(hits)
                if (
                    knowledge_base.reranker_model_id is not None
                    and len(hits) > 0
                    and all(hit.parent_id is None for hit in hits)
                ):
                    try:
                        reranker_model = await get_knowledge_model(
                            tool_db,
                            knowledge_base.workspace_id,
                            knowledge_base.reranker_model_id,
                            "RERANKER",
                        )
                    except HTTPException:
                        reranked_groups.append((knowledge_base, hits))
                        continue
                    if reranker_model is not None:
                        docs = [hit.content for hit in hits[:MAX_RERANK_HITS_PER_BASE]]
                        try:
                            rerank_results = await asyncio.to_thread(
                                build_reranker(
                                    settings, reranker_model
                                ).rerank,
                                payload.query,
                                docs,
                            )
                        except ModelProviderError:
                            reranked_groups.append((knowledge_base, hits))
                            continue
                        scored = sorted(
                            [
                                (
                                    result.get("index", idx),
                                    result.get("relevance_score", 0),
                                )
                                for idx, result in enumerate(rerank_results)
                            ],
                            key=lambda item: item[1],
                            reverse=True,
                        )
                        reranked = [
                            hits[idx]
                            for idx, _ in scored[:MAX_RERANK_CONTEXT_HITS]
                            if idx < len(hits)
                        ]
                        reranked_groups.append((knowledge_base, reranked))
                        continue
                reranked_groups.append((knowledge_base, hits))

            selected_hits: list[tuple[KnowledgeBase, Any]] = []
            for index in range(MAX_KNOWLEDGE_HITS_PER_BASE):
                for knowledge_base, hits in reranked_groups:
                    if index < len(hits):
                        selected_hits.append((knowledge_base, hits[index]))
                        if len(selected_hits) == MAX_KNOWLEDGE_HITS_PER_CALL:
                            break
                if len(selected_hits) == MAX_KNOWLEDGE_HITS_PER_CALL:
                    break

            for knowledge_base, _ in selected_hits:
                entry = next(
                    entry
                    for entry in retrieval_stats
                    if entry["knowledge_base_id"] == knowledge_base.id
                )
                entry["submitted"] += 1

            tool_hits = []
            for knowledge_base, hit in selected_hits:
                tool_hits.append(
                    {
                        "knowledge_base": knowledge_base.name,
                        "document": hit.document_filename,
                        "content": hit.content[:MAX_KNOWLEDGE_CONTENT_CHARS],
                    }
                )

            if not tool_hits and failed_sources == len(available_knowledge_bases):
                return AgentToolResult(
                    content="Knowledge search failed for the configured sources.",
                    summary="Knowledge search failed.",
                    is_error=True,
                )
            output = {
                "query": payload.query,
                "hits": tool_hits,
                "retrieval_stats": retrieval_stats,
            }
            return AgentToolResult(
                content=json.dumps({"hits": tool_hits}, ensure_ascii=False),
                summary=f"agent.knowledge_chunks_returned:{len(tool_hits)}",
                output=output,
                evidence_ids=frozenset(hit.chunk_id for _, hit in selected_hits),
            )

    return create_agent_tool(
        name="search_knowledge",
        description="Search the knowledge bases available to this run.",
        parameters=KnowledgeSearchInput.model_json_schema(),
        execute=execute,
        display_name="知识库检索",
        kind="knowledge",
        parallel_safe=True,
    )


def mcp_function_name(tool: ResolvedMcpTool) -> str:
    name = tool.definition.name
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_")[:40] or "tool"
    digest = hashlib.sha256(f"{tool.server.id}:{name}".encode()).hexdigest()[:8]
    return f"mcp_{stem}_{digest}"


def build_mcp_agent_tool(
    tool: ResolvedMcpTool,
    settings: Settings,
) -> StructuredTool:
    definition = tool.definition
    reference = {"server_id": tool.server.id, "tool_name": definition.name}

    async def execute(arguments: str) -> AgentToolResult:
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError:
            return AgentToolResult(
                content="MCP tool parameters are invalid JSON.",
                summary=(
                    f"{tool.server.name}: {definition.name} received invalid parameters."
                ),
                is_error=True,
            )
        if not isinstance(payload, dict):
            return AgentToolResult(
                content="MCP tool parameters must be an object.",
                summary=(
                    f"{tool.server.name}: {definition.name} received invalid parameters."
                ),
                is_error=True,
            )
        async with get_session_factory()() as tool_db:
            current_tools = await resolve_mcp_tools(
                tool_db,
                tool.server.workspace_id,
                [reference],
                strict=False,
            )
            if not current_tools:
                return AgentToolResult(
                    content="MCP tool is no longer available.",
                    summary=f"{tool.server.name}: {definition.name} is unavailable.",
                    is_error=True,
                )
            current_tool = current_tools[0]
            try:
                content, is_error = await call_mcp_tool(
                    current_tool.server.url,
                    bearer_token(current_tool.server, settings),
                    current_tool.definition.name,
                    payload,
                    settings.mcp_allow_private_networks,
                    settings.mcp_request_timeout_seconds,
                )
            except McpClientError:
                return AgentToolResult(
                    content="MCP tool request failed.",
                    summary=f"{tool.server.name}: {definition.name} request failed.",
                    is_error=True,
                )
        safe_output: Any
        try:
            safe_output = json.loads(content)
        except json.JSONDecodeError:
            safe_output = content[:4000]
        return AgentToolResult(
            content=content,
            summary=f"{tool.server.name}: {definition.name} completed.",
            output=safe_output,
            is_error=is_error,
        )

    return create_agent_tool(
        name=mcp_function_name(tool),
        description=(
            f"MCP tool {tool.server.name}/{definition.name}. "
            f"{definition.description or ''}"
        )[:1000],
        parameters=definition.input_schema,
        execute=execute,
        display_name=definition.name,
        kind="mcp",
        server_name=tool.server.name,
    )

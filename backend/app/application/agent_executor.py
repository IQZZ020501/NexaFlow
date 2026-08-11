import asyncio
import hashlib
import json
import logging
import time
import traceback
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from langchain_core.tools import StructuredTool

from app.application.agent_memory import (
    PreparedConversationMemory,
    prepare_conversation_memory,
)
from app.application.agent_tools import (
    build_knowledge_search_tool,
    build_mcp_agent_tool,
    describe_knowledge_sources,
    safe_agent_error,
    set_agent_tool_idempotency_key,
)
from app.application.workspace import build_workspace_context
from app.entities.agents import AgentRun, AgentToolCall
from app.entities.knowledge import KnowledgeBase
from app.entities.tools import McpToolPolicy
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.agent_live_stream import AgentLiveStreamPublisher
from app.infrastructure.errors import classify_error, log_error
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.session import get_session_factory
from app.infrastructure.system_log import record_system_log
from app.ports.llm import RegisteredModel, build_chat_model
from app.shareddomain.agents.models import (
    AGENT_RUN_FAILED_STATUS,
    AGENT_RUN_RUNNING_STATUS,
    AGENT_RUN_SUCCEEDED_STATUS,
)
from app.shareddomain.agents.runtime import (
    AgentExecutionPaused,
    AgentRunnerError,
    AgentToolBusy,
    AgentToolResult,
    AgentToolUncertain,
    empty_usage,
    run_agent,
    safe_event_value,
)
from app.shareddomain.agents.runtime.state import PendingToolCall
from app.shareddomain.agents.services import (
    accessible_agent_knowledge_bases,
    get_agent_model,
)
from app.shareddomain.tools.services import (
    ResolvedMcpTool,
    effective_mcp_tool_policy_mode,
    get_mcp_tool_policy,
    mcp_tool_definition_hash,
    resolve_mcp_tools,
)

logger = get_logger(__name__)

RUN_FINISHED = "finished"
RUN_BUSY = "busy"
RUN_AWAITING_APPROVAL = "awaiting_approval"
AGENT_EVENT_REPLAY_PAGE_SIZE = 500


@dataclass(frozen=True)
class ExecutionScope:
    run: AgentRun
    actor: User
    workspace_role: str | None
    model: RegisteredModel
    knowledge_bases: list[KnowledgeBase]
    mcp_tools: list[tuple[ResolvedMcpTool, str]]


def _upsert_process_event(
    events: list[dict[str, Any]], event: dict[str, Any]
) -> None:
    call_id = event.get("call_id")
    for index, current in enumerate(events):
        same_event = (
            current.get("call_id") == call_id
            if call_id
            else current.get("type") == event.get("type")
            and current.get("turn") == event.get("turn")
            and current.get("tool_name") == event.get("tool_name")
        )
        if same_event:
            events[index] = event
            return
    events.append(event)


def _completed_process_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [event for event in events if event.get("status") != "running"]


async def _list_all_agent_run_events(db: Any, run_id: str) -> list[Any]:
    rows: list[Any] = []
    cursor = 0
    while True:
        page = await agent_repository.list_agent_run_events(
            db,
            run_id,
            after=cursor,
            limit=AGENT_EVENT_REPLAY_PAGE_SIZE,
        )
        rows.extend(page)
        if len(page) < AGENT_EVENT_REPLAY_PAGE_SIZE:
            return rows
        last_id = page[-1].id
        if last_id is None or last_id <= cursor:
            raise AgentRunnerError("Agent event replay cursor did not advance.")
        cursor = last_id


def _arguments_hash(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _stored_tool_result(call: AgentToolCall) -> AgentToolResult:
    if call.status == "rejected":
        return AgentToolResult(
            content=call.result_content or "Tool call was rejected by the user.",
            summary=call.result_summary or "Tool call rejected.",
            is_error=True,
        )
    return AgentToolResult(
        content=call.result_content,
        summary=call.result_summary,
        output=call.result_output,
        is_error=call.result_is_error,
        evidence_ids=frozenset(call.result_evidence_ids),
    )


def current_mcp_policy_mode(
    access_source: str,
    metadata: dict[str, str],
    policy: McpToolPolicy | None,
    current_definition_hash: str | None = None,
) -> str:
    """Reconcile a durable MCP call with the policy currently in the database."""
    if access_source == "api":
        # API consumers are machine-to-machine: only verified read-only tools
        # are allowed; anything else is disabled.
        snapshot_definition_hash = metadata.get("definition_hash", "")
        if (
            policy is not None
            and policy.mode == "read_only"
            and current_definition_hash == snapshot_definition_hash
            and policy.definition_hash == current_definition_hash
        ):
            return "read_only"
        return "disabled"
    if policy is None:
        return metadata.get("policy_mode", "")
    if policy.definition_hash != metadata.get("definition_hash", ""):
        return "approval_required"
    return policy.mode


async def _invoke_required_knowledge(
    tool: StructuredTool,
    query: str,
    timeout_seconds: float,
) -> AgentToolResult:
    try:
        async with asyncio.timeout(timeout_seconds):
            return await tool.ainvoke({"query": query})
    except Exception:
        return AgentToolResult(
            content=json.dumps(
                {"hits": [], "evidence_status": "unavailable"},
                ensure_ascii=False,
            ),
            summary="Knowledge search unavailable.",
            output={
                "query": query,
                "hits": [],
                "evidence_status": "unavailable",
            },
            is_error=True,
        )


class DurableToolLedger:
    def __init__(
        self,
        run: AgentRun,
        worker_task_id: str,
        settings: Settings,
        lease_lost: asyncio.Event,
    ) -> None:
        self.run = run
        self.worker_task_id = worker_task_id
        self.settings = settings
        self.lease_lost = lease_lost

    async def before(
        self,
        turn: int,
        call: PendingToolCall,
        metadata: dict[str, str],
        arguments: dict[str, Any],
    ) -> AgentToolResult | None:
        if self.lease_lost.is_set():
            raise AgentToolBusy(call["id"], "Agent run lease was lost.")
        arguments_hash = _arguments_hash(arguments)
        approval_required = (
            metadata["kind"] == "mcp" and metadata.get("policy_mode") != "read_only"
        )
        idempotency_key = hashlib.sha256(
            f"{self.run.id}:{turn}:{call['id']}:{arguments_hash}".encode()
        ).hexdigest()
        now = utc_now()
        async with get_session_factory()() as db:
            policy_mode = metadata.get("policy_mode", "")
            if metadata["kind"] == "mcp":
                policy = await get_mcp_tool_policy(
                    db,
                    self.run.workspace_id,
                    metadata.get("server_id", ""),
                    metadata.get("source_tool_name", ""),
                )
                current_definition_hash = None
                if self.run.access_source in {"public", "api"}:
                    resolved_tools = await resolve_mcp_tools(
                        db,
                        self.run.workspace_id,
                        [
                            {
                                "server_id": metadata.get("server_id", ""),
                                "tool_name": metadata.get("source_tool_name", ""),
                            }
                        ],
                        strict=False,
                    )
                    if resolved_tools:
                        current_definition_hash = mcp_tool_definition_hash(
                            resolved_tools[0].definition
                        )
                policy_mode = current_mcp_policy_mode(
                    self.run.access_source,
                    metadata,
                    policy,
                    current_definition_hash,
                )
                approval_required = (
                    metadata["kind"] == "mcp"
                    and policy_mode != "read_only"
                    and self.run.access_source != "api"
                )
            existing = await agent_repository.get_agent_tool_call(
                db,
                self.run.id,
                turn,
                call["id"],
            )
            if existing is None:
                existing = await agent_repository.create_agent_tool_call(
                    db,
                    AgentToolCall(
                        workspace_id=self.run.workspace_id,
                        run_id=self.run.id,
                        turn=turn,
                        call_id=call["id"],
                        tool_name=call["name"],
                        tool_kind=metadata["kind"],
                        server_name=metadata["server_name"],
                        arguments=safe_event_value(arguments),
                        arguments_hash=arguments_hash,
                        definition_hash=metadata.get("definition_hash", ""),
                        policy_mode=policy_mode,
                        idempotency_key=idempotency_key,
                        status=(
                            "awaiting_approval" if approval_required else "approved"
                        ),
                        approval_required=approval_required,
                    ),
                )
                await db.commit()
            if (
                existing.tool_name != call["name"]
                or existing.arguments_hash != arguments_hash
            ):
                raise AgentToolUncertain(
                    call["id"],
                    "Tool call identity changed while resuming; manual review is required.",
                )
            if existing.definition_hash != metadata.get("definition_hash", ""):
                await agent_repository.block_agent_tool_call(
                    db,
                    existing.id,
                    "MCP tool definition changed after this call was created; start a new run.",
                    now,
                    "MCP tool definition changed.",
                )
                await db.commit()
                blocked = await agent_repository.get_agent_tool_call(
                    db,
                    self.run.id,
                    turn,
                    call["id"],
                )
                assert blocked is not None
                return _stored_tool_result(blocked)
            if policy_mode == "disabled":
                await agent_repository.block_agent_tool_call(
                    db,
                    existing.id,
                    "MCP tool is disabled by workspace policy.",
                    now,
                    "Tool disabled by workspace policy.",
                )
                await db.commit()
                blocked = await agent_repository.get_agent_tool_call(
                    db,
                    self.run.id,
                    turn,
                    call["id"],
                )
                assert blocked is not None
                return _stored_tool_result(blocked)
            if (
                approval_required
                and not existing.approval_required
                and existing.approved_by_user_id is None
            ):
                await agent_repository.require_agent_tool_call_approval(
                    db,
                    existing.id,
                    policy_mode,
                    now,
                )
                await db.commit()
                existing = await agent_repository.get_agent_tool_call(
                    db,
                    self.run.id,
                    turn,
                    call["id"],
                )
                assert existing is not None
            if existing.status in {"succeeded", "failed", "rejected"}:
                return _stored_tool_result(existing)
            if existing.status == "awaiting_approval":
                raise AgentExecutionPaused(
                    call["id"],
                    "Tool call requires user approval.",
                )
            if existing.status == "uncertain":
                raise AgentToolUncertain(
                    call["id"],
                    existing.last_error or "Tool outcome is uncertain.",
                )
            if existing.status == "running":
                raise AgentToolBusy(call["id"], "Tool call is owned by another worker.")
            claimed = await agent_repository.claim_agent_tool_call(
                db,
                existing.id,
                self.worker_task_id,
                now,
                now + timedelta(seconds=self.settings.agent_executor_lease_seconds),
            )
            await db.commit()
            if not claimed:
                raise AgentToolBusy(call["id"], "Tool call could not be claimed.")
        set_agent_tool_idempotency_key(idempotency_key)
        return None

    async def after(
        self,
        turn: int,
        call: PendingToolCall,
        metadata: dict[str, str],
        arguments: dict[str, Any],
        result: AgentToolResult,
    ) -> None:
        del metadata, arguments
        async with get_session_factory()() as db:
            stored = await agent_repository.get_agent_tool_call(
                db,
                self.run.id,
                turn,
                call["id"],
            )
            if stored is None:
                raise AgentRunnerError("Tool ledger entry is missing.")
            stored.status = (
                "uncertain"
                if result.outcome_uncertain
                else "failed" if result.is_error else "succeeded"
            )
            stored.result_content = result.content
            stored.result_summary = result.summary
            stored.result_output = safe_event_value(result.output)
            stored.result_is_error = result.is_error
            stored.result_evidence_ids = sorted(result.evidence_ids)
            stored.last_error = result.summary if result.is_error else None
            stored.finished_at = utc_now()
            stored.updated_at = stored.finished_at
            saved = await agent_repository.save_agent_tool_call_result(
                db,
                stored.id,
                self.worker_task_id,
                stored,
            )
            await db.commit()
            if not saved:
                raise AgentToolUncertain(
                    call["id"],
                    "Tool result could not be durably recorded; confirm the external state.",
                )
            if result.outcome_uncertain:
                raise AgentToolUncertain(
                    call["id"],
                    "Tool execution may have reached the external system; confirm its state before continuing.",
                )


async def _load_execution_scope(run_id: str) -> ExecutionScope:
    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        if run is None or run.status != AGENT_RUN_RUNNING_STATUS:
            raise AgentRunnerError("Agent run is not executable.")
        actor = await user_repository.get_user_by_id(db, run.execution_user_id)
        if actor is None or not actor.is_active:
            raise AgentRunnerError("Agent run user is unavailable.")
        context = await build_workspace_context(db, actor, run.workspace_id)
        model = await get_agent_model(db, run.workspace_id, run.model_id)
        knowledge_bases = await accessible_agent_knowledge_bases(
            db,
            run.workspace_id,
            run.knowledge_base_ids,
            actor,
            context.membership_role,
        )
        resolved_mcp_tools = await resolve_mcp_tools(
            db,
            run.workspace_id,
            run.mcp_tools,
            strict=False,
        )
        mcp_tools: list[tuple[ResolvedMcpTool, str]] = []
        for tool in resolved_mcp_tools:
            policy = await get_mcp_tool_policy(
                db,
                run.workspace_id,
                tool.server.id,
                tool.definition.name,
            )
            policy_mode = effective_mcp_tool_policy_mode(tool.definition, policy)
            allowed = (
                policy_mode == "read_only"
                if run.access_source == "api"
                else policy_mode != "disabled"
            )
            if allowed:
                mcp_tools.append((tool, policy_mode))
        event_rows = await _list_all_agent_run_events(db, run.id)
    process_events: list[dict[str, Any]] = []
    for row in event_rows:
        event = row.event.get("event", {})
        if row.event.get("type") == "process":
            _upsert_process_event(process_events, event)
    run.events = _completed_process_events(process_events)
    return ExecutionScope(
        run=run,
        actor=actor,
        workspace_role=context.membership_role,
        model=model,
        knowledge_bases=knowledge_bases,
        mcp_tools=mcp_tools,
    )


async def _append_event(
    run: AgentRun,
    event: dict[str, Any],
    *,
    worker_task_id: str | None = None,
) -> int:
    async with get_session_factory()() as db:
        if worker_task_id is None:
            stored = await agent_repository.append_agent_run_event(
                db,
                run.workspace_id,
                run.id,
                event,
            )
        else:
            stored = await agent_repository.append_owned_agent_run_event(
                db,
                run.workspace_id,
                run.id,
                worker_task_id,
                event,
            )
            if stored is None:
                raise AgentToolBusy("", "Agent run lease was lost.")
        await db.commit()
    assert stored.id is not None
    return stored.id


async def _pause_agent_run_for_tool(
    run_id: str,
    worker_task_id: str,
    call_id: str,
    reason: str,
) -> tuple[bool, bool]:
    async with get_session_factory()() as db:
        paused = await agent_repository.pause_agent_run(
            db,
            run_id,
            worker_task_id,
            reason,
        )
        requeued = False
        if paused:
            call = await agent_repository.get_agent_tool_call_by_call_id(
                db,
                run_id,
                call_id,
            )
            if call is not None and call.status in {"approved", "rejected"}:
                requeued = await agent_repository.queue_agent_run(db, run_id)
            if not requeued:
                run = await agent_repository.get_agent_run_by_id(db, run_id)
                assert run is not None
                await agent_repository.append_agent_run_event(
                    db,
                    run.workspace_id,
                    run_id,
                    {
                        "type": "approval_required",
                        "call_id": call_id,
                        "reason": reason,
                    },
                )
        await db.commit()
    return paused, requeued


async def maintain_agent_run_lease(
    run_id: str,
    worker_task_id: str,
    settings: Settings,
    lease_lost: asyncio.Event,
) -> None:
    while True:
        await asyncio.sleep(settings.agent_executor_heartbeat_seconds)
        try:
            async with get_session_factory()() as db:
                renewed = await agent_repository.renew_agent_run_lease(
                    db,
                    run_id,
                    worker_task_id,
                    utc_now()
                    + timedelta(seconds=settings.agent_executor_lease_seconds),
                )
                await db.commit()
            if not renewed:
                lease_lost.set()
                return
        except Exception:
            lease_lost.set()
            return


async def _execute_claimed_agent_run(
    run_id: str,
    worker_task_id: str,
    settings: Settings,
    lease_lost: asyncio.Event,
) -> str:
    scope = await _load_execution_scope(run_id)
    run = scope.run
    process_events = list(run.events)
    started_at = time.perf_counter()
    knowledge_tool = (
        build_knowledge_search_tool(
            scope.knowledge_bases,
            run.workspace_id,
            scope.actor,
            scope.workspace_role,
            settings,
        )
        if scope.knowledge_bases
        else None
    )
    knowledge_context = ""
    if not run.checkpoint and knowledge_tool is not None and run.knowledge_query_mode == "required":
        eager_call_id = f"eager-knowledge-{run.id}"
        eager_event = next(
            (event for event in process_events if event.get("call_id") == eager_call_id),
            None,
        )
        if eager_event is None:
            eager_started_at = time.perf_counter()
            eager_result = await _invoke_required_knowledge(
                knowledge_tool,
                run.goal,
                settings.agent_tool_timeout_seconds,
            )
            eager_event = {
                "type": "tool",
                "turn": 0,
                "tool_name": "search_knowledge",
                "status": "failed" if eager_result.is_error else "succeeded",
                "summary": eager_result.summary,
                "call_id": eager_call_id,
                "tool_label": "knowledge",
                "tool_kind": "knowledge",
                "server_name": "",
                "input": {"query": run.goal},
                "output": safe_event_value(eager_result.output),
                "duration_ms": round(
                    (time.perf_counter() - eager_started_at) * 1000
                ),
            }
            _upsert_process_event(process_events, eager_event)
            await _append_event(
                run,
                {"type": "process", "event": eager_event},
                worker_task_id=worker_task_id,
            )
        knowledge_context = json.dumps(
            eager_event.get("output")
            or {
                "query": run.goal,
                "hits": [],
                "evidence_status": (
                    "unavailable"
                    if eager_event.get("status") == "failed"
                    else "not_found"
                ),
            },
            ensure_ascii=False,
        )[:12000]

    tools: list[StructuredTool] = []
    if knowledge_tool is not None and run.knowledge_query_mode == "agentic":
        tools.append(knowledge_tool)
    tools.extend(
        build_mcp_agent_tool(tool, settings, policy_mode)
        for tool, policy_mode in scope.mcp_tools
    )
    from app.application.agent_runs import execution_messages

    chat_model = build_chat_model(settings, scope.model)
    base_messages = execution_messages(
        run,
        knowledge_tool is not None and run.knowledge_query_mode == "agentic",
        bool(scope.mcp_tools),
        knowledge_scope=(
            describe_knowledge_sources(scope.knowledge_bases)
            if scope.knowledge_bases
            else ""
        ),
        knowledge_query_mode=run.knowledge_query_mode,
        knowledge_context=knowledge_context,
    )
    memory = PreparedConversationMemory(messages=[], model_usage=empty_usage())
    if not run.checkpoint:
        try:
            async with get_session_factory()() as memory_db:
                memory = await prepare_conversation_memory(
                    memory_db,
                    run,
                    scope.model,
                    chat_model,
                    base_messages,
                    tools,
                    timeout_seconds=min(
                        60.0,
                        float(settings.agent_run_timeout_seconds),
                    ),
                )
                await memory_db.commit()
        except Exception as exc:
            # A summary is an optimization; a failed compaction must not lose the
            # current request. The durable transcript remains available for retry.
            log_error(
                logger,
                "Conversation compaction was skipped.",
                exc,
                agent_run_id=run.id,
                trace_id=run.trace_id,
            )
            memory = PreparedConversationMemory(messages=[], model_usage=empty_usage())
    messages = execution_messages(
        run,
        knowledge_tool is not None and run.knowledge_query_mode == "agentic",
        bool(scope.mcp_tools),
        knowledge_scope=(
            describe_knowledge_sources(scope.knowledge_bases)
            if scope.knowledge_bases
            else ""
        ),
        knowledge_query_mode=run.knowledge_query_mode,
        knowledge_context=knowledge_context,
        context_messages=memory.messages,
    )
    ledger = DurableToolLedger(run, worker_task_id, settings, lease_lost)
    live_stream = AgentLiveStreamPublisher(settings, run.id)

    async def record_event(event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type in {"answer_delta", "reasoning_delta"}:
            await live_stream.publish({**event, "stream_epoch": worker_task_id})
            return
        if event_type != "process":
            return
        process_event = event.get("event", {})
        await _append_event(run, event, worker_task_id=worker_task_id)
        _upsert_process_event(process_events, process_event)

    async def save_checkpoint(checkpoint: dict[str, Any], phase: str) -> None:
        if lease_lost.is_set():
            raise AgentToolBusy("", "Agent run lease was lost.")
        async with get_session_factory()() as db:
            saved = await agent_repository.save_agent_run_checkpoint(
                db,
                run.id,
                worker_task_id,
                checkpoint,
                phase,
            )
            await db.commit()
        if not saved:
            lease_lost.set()
            raise AgentToolBusy("", "Agent run checkpoint lease was lost.")

    try:
        try:
            async with asyncio.timeout(settings.agent_run_timeout_seconds):
                result = await run_agent(
                    chat_model,
                    messages,
                    tools,
                    on_event=record_event,
                    tool_timeout_seconds=settings.agent_tool_timeout_seconds,
                    checkpoint=run.checkpoint or None,
                    on_checkpoint=save_checkpoint,
                    before_tool_call=ledger.before,
                    after_tool_call=ledger.after,
                    initial_usage=memory.model_usage,
                )
        except TimeoutError as exc:
            raise AgentRunnerError("Agent run timed out.") from exc
        async with get_session_factory()() as db:
            finalized = await agent_repository.finalize_agent_run(
                db,
                run.id,
                worker_task_id,
                status=AGENT_RUN_SUCCEEDED_STATUS,
                result=result.content,
                events=_completed_process_events(process_events),
                last_error=None,
                finished_at=utc_now(),
                model_usage=result.model_usage,
            )
            await db.commit()
        if not finalized:
            raise AgentToolBusy("", "Agent run finalization lease was lost.")
        current = await _current_run(run.id)
        await _append_event(
            run,
            {"type": "complete", "run": _run_payload(current)},
        )
        log_event(
            logger,
            logging.INFO,
            "Durable agent run succeeded.",
            agent_run_id=run.id,
            trace_id=run.trace_id,
            duration_ms=round((time.perf_counter() - started_at) * 1000),
        )
        return RUN_FINISHED
    except AgentToolBusy:
        async with get_session_factory()() as db:
            await agent_repository.requeue_owned_agent_run(db, run.id, worker_task_id)
            await db.commit()
        return RUN_BUSY
    except (AgentExecutionPaused, AgentToolUncertain) as exc:
        paused, requeued = await _pause_agent_run_for_tool(
            run.id,
            worker_task_id,
            exc.call_id,
            exc.reason,
        )
        if requeued:
            return RUN_BUSY
        if not paused:
            return RUN_BUSY
        return RUN_AWAITING_APPROVAL
    except Exception as exc:
        error = safe_agent_error(exc)
        log_error(
            logger,
            "Durable agent run failed.",
            exc,
            agent_run_id=run.id,
            trace_id=run.trace_id,
            workspace_id=run.workspace_id,
        )
        async with get_session_factory()() as db:
            finalized = await agent_repository.finalize_agent_run(
                db,
                run.id,
                worker_task_id,
                status=AGENT_RUN_FAILED_STATUS,
                result="",
                events=_completed_process_events(process_events),
                last_error=error,
                finished_at=utc_now(),
            )
            await db.commit()
        try:
            async with get_session_factory()() as log_db:
                record_system_log(
                    log_db,
                    level="error",
                    event="agent.execution_failed",
                    message=error,
                    status_code=500,
                    user_id=scope.actor.id,
                    username=scope.actor.username,
                    details={
                        "agent_id": run.agent_id,
                        "agent_run_id": run.id,
                        "exception_type": exc.__class__.__name__,
                        "source": classify_error(exc),
                        "trace_id": run.trace_id,
                        "workspace_id": run.workspace_id,
                    },
                    stack_trace="".join(traceback.format_exception(exc)),
                )
                await log_db.commit()
        except Exception as log_exc:
            log_error(logger, "Failed to record agent execution error.", log_exc)
        if finalized:
            current = await _current_run(run.id)
            await _append_event(
                run,
                {"type": "error", "run": _run_payload(current)},
            )
        return RUN_FINISHED
    finally:
        await live_stream.close()


async def _current_run(run_id: str) -> AgentRun:
    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
    if run is None:
        raise AgentRunnerError("Agent run no longer exists.")
    return run


def _run_payload(run: AgentRun) -> dict[str, Any]:
    from app.application.agent_tools import run_to_response

    return run_to_response(run, trace_id=run.trace_id).model_dump(mode="json")


async def _fail_unhandled_claimed_run(
    run_id: str,
    worker_task_id: str,
    exc: Exception,
) -> str:
    error = safe_agent_error(exc)
    log_error(
        logger,
        "Durable agent run crashed outside the execution loop.",
        exc,
        agent_run_id=run_id,
    )
    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        if run is None:
            return RUN_FINISHED
        event_rows = await _list_all_agent_run_events(db, run_id)
        process_events: list[dict[str, Any]] = []
        for row in event_rows:
            if row.event.get("type") == "process":
                _upsert_process_event(process_events, row.event.get("event", {}))
        finalized = await agent_repository.finalize_agent_run(
            db,
            run_id,
            worker_task_id,
            status=AGENT_RUN_FAILED_STATUS,
            result="",
            events=_completed_process_events(process_events),
            last_error=error,
            finished_at=utc_now(),
        )
        if finalized:
            record_system_log(
                db,
                level="error",
                event="agent.execution_failed",
                message=error,
                status_code=500,
                user_id=run.execution_user_id,
                details={
                    "agent_id": run.agent_id,
                    "agent_run_id": run.id,
                    "exception_type": exc.__class__.__name__,
                    "source": classify_error(exc),
                    "trace_id": run.trace_id,
                    "workspace_id": run.workspace_id,
                },
                stack_trace="".join(traceback.format_exception(exc)),
            )
        await db.commit()
    if not finalized:
        current = await _current_run(run_id)
        return (
            RUN_BUSY
            if current.status in {"queued", AGENT_RUN_RUNNING_STATUS}
            else RUN_FINISHED
        )
    current = await _current_run(run_id)
    await _append_event(
        run,
        {"type": "error", "run": _run_payload(current)},
    )
    return RUN_FINISHED


async def run_durable_agent_run(
    run_id: str,
    settings: Settings,
    worker_task_id: str | None = None,
) -> str:
    worker_task_id = worker_task_id or new_id()
    now = utc_now()
    async with get_session_factory()() as db:
        claimed = await agent_repository.claim_agent_run(
            db,
            run_id,
            worker_task_id,
            now,
            now + timedelta(seconds=settings.agent_executor_lease_seconds),
        )
        if claimed:
            await agent_repository.mark_expired_agent_tool_calls(db, run_id, now)
        else:
            await agent_repository.fail_exhausted_agent_runs(db, now)
        await db.commit()
    if not claimed:
        current = await _current_run(run_id)
        return RUN_BUSY if current.status == AGENT_RUN_RUNNING_STATUS else RUN_FINISHED

    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        maintain_agent_run_lease(
            run_id,
            worker_task_id,
            settings,
            lease_lost,
        )
    )
    try:
        try:
            return await _execute_claimed_agent_run(
                run_id,
                worker_task_id,
                settings,
                lease_lost,
            )
        except Exception as exc:
            return await _fail_unhandled_claimed_run(
                run_id,
                worker_task_id,
                exc,
            )
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


async def list_recoverable_agent_run_ids(settings: Settings) -> list[str]:
    del settings
    async with get_session_factory()() as db:
        now = utc_now()
        await agent_repository.fail_exhausted_agent_runs(db, now)
        run_ids = await agent_repository.list_recoverable_agent_run_ids(db, now)
        await db.commit()
    return run_ids

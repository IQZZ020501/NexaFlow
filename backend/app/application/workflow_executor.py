import asyncio
from contextlib import suppress
from dataclasses import dataclass, replace as dataclass_replace
from datetime import UTC, datetime, timedelta
import json
import traceback
from typing import Any

from app.application.agent_executor import (
    RUN_BUSY,
    RUN_FINISHED,
    maintain_agent_run_lease,
)
from app.application.agent_child_runs import (
    ensure_workflow_agent_child,
    preflight_workflow_agent_snapshots,
)
from app.application.workflow_nodes import WorkflowNodeScope, execute_workflow_node
from app.application.workflow_tool_runtime import WorkflowToolRuntime
from app.application.workspace import build_workspace_context
from app.entities.agents import AgentRun
from app.entities.knowledge import KnowledgeBase
from app.entities.tools import ToolSnapshot
from app.entities.user import User
from app.entities.workflows import WorkflowNodeExecution, WorkflowRunDetail
from app.infrastructure.agent_live_stream import AgentLiveStreamPublisher
from app.infrastructure.config import Settings
from app.infrastructure.errors import classify_error
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.infrastructure.session import get_session_factory
from app.infrastructure.system_log import record_system_log
from app.ports.llm import (
    ModelProviderError,
    ModelProviderTimeoutError,
    RegisteredModel,
)
from app.ports.model_registry import get_registered_model_by_id
from app.schemas.workflow import LlmNodeConfig, RerankerNodeConfig, WorkflowGraph
from app.shareddomain.agents.models import (
    AGENT_RUN_FAILED_STATUS,
    AGENT_RUN_RUNNING_STATUS,
    AGENT_RUN_RUNNING_STATUSES,
    AGENT_RUN_SUCCEEDED_STATUS,
    AGENT_RUN_UNIFIED_RUNNING_STATUS,
)
from app.shareddomain.agents.runtime import (
    empty_usage,
    merge_usage,
    safe_event_value,
)
from app.shareddomain.agents.services import (
    accessible_agent_knowledge_bases,
    get_agent_model,
)
from app.shareddomain.tools.runtime import tool_snapshot_payload
from app.shareddomain.workflows.engine import (
    NodeTransition,
    WorkflowEngine,
    WorkflowEngineError,
    WorkflowEngineState,
    WorkflowInputRequired,
    WorkflowChildRequired,
)
from app.shareddomain.workflows.resources import (
    load_workflow_agent_snapshots,
    load_workflow_resource_snapshot,
)

MAX_WORKFLOW_OUTPUT_BYTES = 256 * 1024
WORKFLOW_HISTORY_LIMIT = 20


def _history_answer(result: str) -> Any:
    try:
        return json.loads(result)
    except (TypeError, ValueError):
        return result


async def _workflow_context(
    run: AgentRun,
    graph: WorkflowGraph,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """
    Builds conversation context and per-node dialogue histories for a workflow run.
    
    Parameters:
    	run (AgentRun): The current run whose conversation and agent scope determine the history.
    	graph (WorkflowGraph): The workflow graph used to identify LLM nodes with node-level dialogue.
    
    Returns:
    	context (dict[str, Any]): Global workflow context containing timestamps, conversation ID, and prior run history.
    	histories (dict[str, list[dict[str, Any]]]): Successful prior answers grouped by node-level dialogue node ID.
    """
    node_ids = [
        node.id
        for node in graph.nodes
        if node.data.type == "llm"
        and LlmNodeConfig.model_validate(node.data.config).dialogue_type == "NODE"
    ]
    histories: dict[str, list[dict[str, Any]]] = {
        node_id: [] for node_id in node_ids
    }
    prior: list[AgentRun] = []
    executions_by_run: dict[str, list[WorkflowNodeExecution]] = {}
    if run.conversation_id:
        async with get_session_factory()() as db:
            prior = await agent_repository.list_agent_runs(
                db,
                run.agent_id,
                run.access_source,
                run.consumer_id,
                limit=WORKFLOW_HISTORY_LIMIT,
                status=AGENT_RUN_SUCCEEDED_STATUS,
                conversation_id=run.conversation_id,
                latest_versions_only=True,
            )
            executions = await workflow_repository.list_node_executions_for_runs(
                db,
                [item.id for item in prior] if node_ids else [],
            )
        for execution in executions:
            executions_by_run.setdefault(execution.run_id, []).append(execution)

    history = [
        {"question": item.goal, "answer": _history_answer(item.result)}
        for item in reversed(prior)
    ]
    if node_ids:
        node_id_set = set(node_ids)
        for item in reversed(prior):
            for execution in executions_by_run.get(item.id, []):
                if execution.node_id not in node_id_set:
                    continue
                if execution.status != "succeeded":
                    continue
                answer = (execution.outputs or {}).get("text")
                if answer is None:
                    continue
                histories[execution.node_id].append(
                    {"question": item.goal, "answer": answer}
                )
    now = utc_now()
    return (
        {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "history_context": history,
            "chat_id": run.conversation_id,
            "start_time": now.isoformat(),
        },
        histories,
    )


@dataclass(frozen=True)
class WorkflowExecutionScope:
    run: AgentRun
    detail: WorkflowRunDetail
    actor: User
    workspace_role: str | None
    models: dict[str, RegisteredModel]
    knowledge_bases: dict[str, KnowledgeBase]
    tool_snapshots: list[ToolSnapshot]
    agent_snapshots: list[dict[str, Any]]
    child_runs: dict[str, AgentRun]


async def _load_scope(run_id: str) -> WorkflowExecutionScope:
    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        detail = await workflow_repository.get_run_detail(db, run_id)
        if run is None or detail is None or run.status not in AGENT_RUN_RUNNING_STATUSES:
            raise WorkflowEngineError("Workflow run is not executable.")
        agent = await agent_repository.get_agent_by_id(db, run.agent_id)
        if agent is None or agent.app_type != "workflow" or agent.status != "active":
            raise WorkflowEngineError("Workflow application is unavailable.")
        actor = await user_repository.get_user_by_id(db, run.execution_user_id)
        if actor is None or not actor.is_active:
            raise WorkflowEngineError("Workflow run user is unavailable.")
        context = await build_workspace_context(db, actor, run.workspace_id)
        graph = WorkflowGraph.model_validate(detail.graph_snapshot)
        try:
            knowledge_base_ids, tool_snapshots = load_workflow_resource_snapshot(
                graph,
                detail.resource_snapshot,
                detail.resource_hash,
            )
            agent_snapshots = load_workflow_agent_snapshots(
                graph,
                detail.resource_snapshot,
                detail.resource_hash,
            )
            await preflight_workflow_agent_snapshots(
                db,
                run.workspace_id,
                agent_snapshots,
                execution_user_id=run.execution_user_id,
                access_source=run.access_source,
            )
        except ValueError as exc:
            raise WorkflowEngineError(
                "Workflow resource snapshot is invalid."
            ) from exc
        if (
            knowledge_base_ids != run.knowledge_base_ids
            or [tool_snapshot_payload(item) for item in tool_snapshots]
            != run.tool_snapshots
        ):
            raise WorkflowEngineError("Workflow run snapshot is inconsistent.")
        model_ids = {run.model_id}
        model_ids.update(
            str(node.data.config["model_id"])
            for node in graph.nodes
            if node.data.type in {"llm", "classifier"}
            and node.data.config.get("model_id")
        )
        models = {
            model_id: await get_agent_model(db, run.workspace_id, model_id)
            for model_id in model_ids
        }
        for node in graph.nodes:
            if node.data.type != "reranker-node":
                continue
            model_id = RerankerNodeConfig.model_validate(
                node.data.config
            ).reranker_model_id
            model = await get_registered_model_by_id(db, model_id)
            if (
                model is None
                or model.workspace_id != run.workspace_id
                or model.model_type != "RERANKER"
                or model.status != "active"
            ):
                raise WorkflowEngineError("Workflow reranker model is unavailable.")
            models[model_id] = model
        knowledge_bases = await accessible_agent_knowledge_bases(
            db,
            run.workspace_id,
            knowledge_base_ids,
            actor,
            context.membership_role,
        )
        child_runs = {}
        if agent_snapshots:
            child_runs = {
                child.parent_node_id: child
                for child in await agent_repository.list_agent_child_runs(
                    db,
                    run.workspace_id,
                    run.id,
                )
                if child.parent_node_id is not None
            }
    return WorkflowExecutionScope(
        run=run,
        detail=detail,
        actor=actor,
        workspace_role=context.membership_role,
        models=models,
        knowledge_bases={item.id: item for item in knowledge_bases},
        tool_snapshots=tool_snapshots,
        agent_snapshots=agent_snapshots,
        child_runs=child_runs,
    )


def _safe_node_error(exc: Exception) -> str:
    if isinstance(exc, ModelProviderTimeoutError):
        return "Workflow model request timed out."
    if isinstance(exc, ModelProviderError):
        return "Workflow model request failed."
    if isinstance(exc, (ValueError, RuntimeError)):
        return str(exc)[:1000]
    return "Workflow node execution failed."


def _safe_run_error(exc: Exception) -> str:
    if isinstance(exc, WorkflowEngineError):
        return str(exc)[:1000]
    return "Workflow execution failed."


async def _execute_claimed_workflow_run(
    run_id: str,
    worker_task_id: str,
    settings: Settings,
    lease_lost: asyncio.Event,
) -> str:
    scope = await _load_scope(run_id)
    run, detail = scope.run, scope.detail
    graph = WorkflowGraph.model_validate(detail.graph_snapshot)
    workflow_globals, node_histories = await _workflow_context(run, graph)
    tool_runtime = WorkflowToolRuntime(
        run,
        detail,
        scope.tool_snapshots,
        worker_task_id,
        settings,
        lease_lost,
    )
    live_stream = AgentLiveStreamPublisher(settings, run.id)

    async def output_delta(node_id: str, delta: str) -> None:
        await live_stream.publish(
            {
                "type": "answer_delta",
                "node_id": node_id,
                "delta": delta,
                "stream_epoch": worker_task_id,
            }
        )

    node_scope = WorkflowNodeScope(
        run=run,
        actor=scope.actor,
        workspace_role=scope.workspace_role,
        settings=settings,
        models=scope.models,
        knowledge_bases=scope.knowledge_bases,
        tool_runtime=tool_runtime,
        node_histories=node_histories,
        child_runs=scope.child_runs,
        output_delta=output_delta,
    )
    engine = WorkflowEngine(
        graph,
        max_steps=detail.max_steps,
        max_model_tokens=detail.max_model_tokens,
        deadline_at=detail.deadline_at,
    )
    checkpoint = run.checkpoint or {}
    engine_checkpoint = checkpoint.get("workflow_engine")
    state = WorkflowEngineState.from_dict(engine_checkpoint) if engine_checkpoint else None
    node_executions = {
        item.node_id: item
        for item in await _list_node_executions(run.id)
    }
    started_at: dict[str, datetime] = {}
    persistence_lock = asyncio.Lock()
    usage_total = merge_usage(
        empty_usage(),
        checkpoint.get("model_usage", run.model_usage),
    )
    form_submissions = {
        str(key): dict(value)
        for key, value in checkpoint.get("workflow_form_submissions", {}).items()
        if isinstance(value, dict)
    }
    node_scope = dataclass_replace(
        node_scope,
        form_submissions=form_submissions,
    )
    node_errors: dict[str, Exception] = {}
    pending_child_ids: dict[str, str] = {}

    async def execute(node, context):
        if lease_lost.is_set():
            raise WorkflowEngineError("Workflow run lease was lost.")
        try:
            result = await execute_workflow_node(node_scope, node, context)
            encoded = json.dumps(
                result.outputs,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(encoded.encode()) > MAX_WORKFLOW_OUTPUT_BYTES:
                raise WorkflowEngineError(
                    "Workflow node output exceeds 256 KiB.",
                    node_id=node.id,
                )
            return result
        except Exception as exc:
            node_errors[node.id] = exc
            raise RuntimeError(_safe_node_error(exc)) from exc

    async def on_started(node, sequence):
        async with persistence_lock:
            now = utc_now()
            started_at[node.id] = now
            async with get_session_factory()() as db:
                item = await workflow_repository.start_node_execution(
                    db,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    worker_task_id=worker_task_id,
                    node_id=node.id,
                    node_type=node.data.type,
                    sequence=sequence,
                    started_at=now,
                )
                if item is None:
                    lease_lost.set()
                    raise WorkflowEngineError("Workflow run lease was lost.")
                node_executions[node.id] = item
                event = await agent_repository.append_owned_agent_run_event(
                    db,
                    run.workspace_id,
                    run.id,
                    worker_task_id,
                    {
                        "type": "workflow_node_started",
                        "node_id": node.id,
                        "node_type": node.data.type,
                        "sequence": sequence,
                    },
                )
                if event is None:
                    lease_lost.set()
                    raise WorkflowEngineError("Workflow run lease was lost.")
                await db.commit()

    async def on_finished(transition: NodeTransition, current: WorkflowEngineState):
        nonlocal usage_total
        async with persistence_lock:
            now = utc_now()
            async with get_session_factory()() as db:
                item = node_executions.get(transition.node.id)
                if item is None:
                    item = await workflow_repository.start_node_execution(
                        db,
                        workspace_id=run.workspace_id,
                        run_id=run.id,
                        worker_task_id=worker_task_id,
                        node_id=transition.node.id,
                        node_type=transition.node.data.type,
                        sequence=transition.sequence,
                        started_at=now,
                    )
                if item is None:
                    lease_lost.set()
                    raise WorkflowEngineError("Workflow run lease was lost.")
                start = started_at.get(transition.node.id) or item.started_at or now
                item.status = transition.status.value
                item.sequence = transition.sequence
                item.inputs = transition.result.inputs
                item.outputs = transition.result.outputs
                item.model_usage = transition.result.model_usage
                item.error = transition.error
                item.started_at = start
                item.finished_at = now
                item.duration_ms = max(0, round((now - start).total_seconds() * 1000))
                item.updated_at = now
                usage_total = merge_usage(usage_total, transition.result.model_usage)
                detail.step_count = current.step_count
                detail.token_usage = current.model_tokens
                checkpoint_payload = {
                    "workflow_engine": current.to_dict(),
                    "model_usage": usage_total,
                }
                if (
                    transition.node.data.type == "form-node"
                    and transition.status.value == "succeeded"
                ):
                    form_submissions.pop(transition.node.id, None)
                if form_submissions:
                    checkpoint_payload["workflow_form_submissions"] = form_submissions
                if transition.result.interrupt is not None:
                    checkpoint_payload["workflow_form"] = transition.result.interrupt
                if transition.result.child_request is not None:
                    request = transition.result.child_request
                    agent_id = request.get("agent_id")
                    version_id = request.get("agent_version_id")
                    agent_snapshot = next(
                        (
                            item
                            for item in scope.agent_snapshots
                            if item.get("agent_id") == agent_id
                            and item.get("version_id") == version_id
                        ),
                        None,
                    )
                    if agent_snapshot is None:
                        raise WorkflowEngineError(
                            "Workflow Agent snapshot is missing.",
                            node_id=transition.node.id,
                        )
                    child = await ensure_workflow_agent_child(
                        db,
                        run,
                        transition.node.id,
                        request.get("input"),
                        agent_snapshot,
                        scope.actor,
                        scope.workspace_role,
                        deadline_at=(
                            detail.deadline_at
                            if detail.deadline_at.tzinfo is not None
                            else detail.deadline_at.replace(tzinfo=UTC)
                        ).isoformat(),
                        remaining_model_tokens=int(
                            request.get("remaining_model_tokens") or 0
                        ),
                    )
                    pending_child_ids[transition.node.id] = child.id
                    checkpoint_payload["workflow_child"] = {
                        "runtime_node_id": transition.node.id,
                        "child_run_id": child.id,
                    }
                saved = await workflow_repository.finish_node_execution(
                    db, item, worker_task_id
                )
                checkpoint_saved = await agent_repository.save_agent_run_checkpoint(
                    db,
                    run.id,
                    worker_task_id,
                    checkpoint_payload,
                    "workflow",
                )
                detail_saved = await workflow_repository.save_owned_run_detail(
                    db, detail, worker_task_id
                )
                event = await agent_repository.append_owned_agent_run_event(
                    db,
                    run.workspace_id,
                    run.id,
                    worker_task_id,
                    {
                        "type": "workflow_node",
                        "node_id": transition.node.id,
                        "node_type": transition.node.data.type,
                        "status": transition.status.value,
                        "execution_sequence": transition.sequence,
                        "inputs": safe_event_value(transition.result.inputs),
                        "outputs": safe_event_value(transition.result.outputs),
                        "model_usage": transition.result.model_usage,
                        "error": transition.error,
                        "duration_ms": item.duration_ms,
                    },
                )
                if not (saved and checkpoint_saved and detail_saved) or event is None:
                    lease_lost.set()
                    raise WorkflowEngineError("Workflow run lease was lost.")
                if transition.result.child_request is not None:
                    paused = await agent_repository.pause_agent_run_for_child(
                        db,
                        run.id,
                        worker_task_id,
                    )
                    if not paused:
                        lease_lost.set()
                        raise WorkflowEngineError("Workflow run lease was lost.")
                node_executions[transition.node.id] = item
                await db.commit()

    try:
        result = await engine.run(
            detail.inputs,
            execute,
            state=state,
            on_node_started=on_started,
            on_node_finished=on_finished,
            workflow_globals=workflow_globals,
        )
    except WorkflowInputRequired:
        async with get_session_factory()() as db:
            paused = await agent_repository.pause_agent_run_for_input(
                db,
                run.id,
                worker_task_id,
            )
            if paused:
                current_run = await agent_repository.get_agent_run_by_id(db, run.id)
                current_detail = await workflow_repository.get_run_detail(db, run.id)
                if current_run is None or current_detail is None:
                    raise WorkflowEngineError("Paused workflow run state is missing.")
                await agent_repository.append_agent_run_event(
                    db,
                    run.workspace_id,
                    run.id,
                    {
                        "type": "workflow_input_required",
                        "run": _run_payload(current_run, current_detail),
                    },
                )
            await db.commit()
        return RUN_FINISHED if paused else RUN_BUSY
    except WorkflowChildRequired as exc:
        node_id = str(exc.request.get("runtime_node_id") or "")
        child_id = pending_child_ids.get(node_id)
        if child_id is None:
            async with get_session_factory()() as db:
                child = await agent_repository.get_agent_child_run(
                    db,
                    run.workspace_id,
                    run.id,
                    node_id,
                )
            child_id = child.id if child is not None else None
        if child_id is None:
            raise WorkflowEngineError("Workflow Agent child was not persisted.")
        from app.application.agent_runs import enqueue_prepared_agent_run

        await enqueue_prepared_agent_run(child_id, settings, unified=True)
        return RUN_FINISHED
    except WorkflowEngineError as exc:
        original = node_errors.get(exc.node_id or "")
        if original is not None:
            raise exc from original
        raise
    finally:
        await live_stream.close()
    encoded_output = json.dumps(
        result.outputs,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(encoded_output.encode()) > MAX_WORKFLOW_OUTPUT_BYTES:
        raise WorkflowEngineError("Workflow output exceeds 256 KiB.")
    finished = utc_now()
    detail.outputs = result.outputs
    detail.step_count = result.state.step_count
    detail.token_usage = result.state.model_tokens
    async with get_session_factory()() as db:
        saved_detail = await workflow_repository.save_owned_run_detail(
            db, detail, worker_task_id
        )
        finalized = await agent_repository.finalize_agent_run(
            db,
            run.id,
            worker_task_id,
            status=AGENT_RUN_SUCCEEDED_STATUS,
            result=encoded_output,
            events=[],
            last_error=None,
            finished_at=finished,
            model_usage=usage_total,
        )
        if finalized and saved_detail:
            current_run = await agent_repository.get_agent_run_by_id(db, run.id)
            current_detail = await workflow_repository.get_run_detail(db, run.id)
            if current_run is None or current_detail is None:
                raise WorkflowEngineError("Finalized workflow run state is missing.")
            await agent_repository.append_agent_run_event(
                db,
                run.workspace_id,
                run.id,
                {
                    "type": "complete",
                    "run": _run_payload(current_run, current_detail),
                },
            )
        await db.commit()
    return RUN_FINISHED if finalized and saved_detail else RUN_BUSY


async def _list_node_executions(run_id: str) -> list[WorkflowNodeExecution]:
    async with get_session_factory()() as db:
        return await workflow_repository.list_node_executions(db, run_id)


def _run_payload(run: AgentRun, detail: WorkflowRunDetail) -> dict:
    from app.application.workflow_runs import workflow_run_to_response

    return workflow_run_to_response(run, detail).model_dump(mode="json")


async def _fail_claimed_workflow_run(
    run_id: str,
    worker_task_id: str,
    exc: Exception,
) -> str:
    error = _safe_run_error(exc)
    finished = utc_now()
    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        detail = await workflow_repository.get_run_detail(db, run_id)
        if run is None or detail is None:
            return RUN_FINISHED
        finalized = await agent_repository.finalize_agent_run(
            db,
            run_id,
            worker_task_id,
            status=AGENT_RUN_FAILED_STATUS,
            result="",
            events=[],
            last_error=error,
            finished_at=finished,
            model_usage=(run.checkpoint or {}).get("model_usage", run.model_usage),
        )
        if finalized:
            current = await agent_repository.get_agent_run_by_id(db, run_id)
            if current is None:
                raise WorkflowEngineError("Finalized workflow run state is missing.")
            await agent_repository.append_agent_run_event(
                db,
                run.workspace_id,
                run.id,
                {"type": "error", "run": _run_payload(current, detail)},
            )
            record_system_log(
                db,
                level="error",
                event="workflow.execution_failed",
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
    return RUN_FINISHED if finalized else RUN_BUSY


async def run_durable_workflow_run(
    run_id: str,
    settings: Settings,
    worker_task_id: str | None = None,
    *,
    generation: str = "legacy",
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
            generation=generation,
        )
        if claimed:
            await workflow_repository.set_first_run_deadline(
                db,
                run_id,
                worker_task_id,
                now + timedelta(seconds=settings.agent_run_timeout_seconds),
            )
            if generation == "legacy":
                await agent_repository.mark_expired_agent_tool_calls(db, run_id, now)
        await db.commit()
    if not claimed:
        async with get_session_factory()() as db:
            current = await agent_repository.get_agent_run_by_id(db, run_id)
        return (
            RUN_BUSY
            if current is not None
            and current.status
            == (
                AGENT_RUN_UNIFIED_RUNNING_STATUS
                if generation == "unified"
                else AGENT_RUN_RUNNING_STATUS
            )
            else RUN_FINISHED
        )

    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        maintain_agent_run_lease(run_id, worker_task_id, settings, lease_lost)
    )
    try:
        try:
            return await _execute_claimed_workflow_run(
                run_id, worker_task_id, settings, lease_lost
            )
        except Exception as exc:
            return await _fail_claimed_workflow_run(run_id, worker_task_id, exc)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat

"""Durable, provider-neutral Tool execution."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.tool_adapters import build_tool_adapter
from app.entities.tools import ToolInvocation, ToolSnapshot
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import mcp as mcp_repository
from app.infrastructure.repositories import resource_permission as permission_repository
from app.infrastructure.repositories import tools as tool_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.infrastructure.session import get_session_factory
from app.ports.tool_runtime import (
    ToolAdapter,
    ToolAdapterBusy,
    ToolInvocationContext,
    ToolRuntimeResult,
)
from app.shareddomain.tools.permissions import evaluate_tool_authorization
from app.shareddomain.tools.runtime import (
    TOOL_APPROVAL_AUTO,
    TOOL_APPROVAL_DISABLED,
    TOOL_APPROVAL_EACH_CALL,
    TOOL_INVOCATION_AWAITING_APPROVAL,
    TOOL_INVOCATION_CLAIMABLE_STATUSES,
    TOOL_INVOCATION_FAILED,
    TOOL_INVOCATION_QUEUED,
    TOOL_INVOCATION_RUNNING,
    TOOL_INVOCATION_SUCCEEDED,
    TOOL_INVOCATION_TERMINAL_STATUSES,
    TOOL_INVOCATION_UNCERTAIN,
    TOOL_SAFE_EXTERNAL_EFFECTS,
    TOOL_UNCERTAIN_EFFECTS,
    tool_arguments_hash,
    normalize_tool_arguments,
    tool_snapshot_from_payload,
    tool_snapshot_payload,
    validate_tool_arguments,
    validate_tool_output,
)


class ToolInvocationBusy(RuntimeError):
    pass


class ToolInvocationConflict(ValueError):
    pass


async def queue_tool_invocation(
    db: AsyncSession,
    snapshot: ToolSnapshot,
    arguments: dict[str, Any],
    context: ToolInvocationContext,
) -> ToolInvocation:
    _validate_context(context)
    arguments = normalize_tool_arguments(
        snapshot.function_name,
        snapshot.input_schema,
        arguments,
    )
    validate_tool_arguments(snapshot, arguments)
    arguments_hash = tool_arguments_hash(arguments)
    payload = {
        "tool_snapshot": tool_snapshot_payload(snapshot),
        "deadline_at": context.deadline_at.isoformat(),
    }
    candidate = ToolInvocation(
        workspace_id=context.workspace_id,
        origin=context.origin,
        root_run_id=context.root_run_id,
        run_id=context.run_id,
        invocation_id=context.invocation_id,
        execution_user_id=context.execution_user_id,
        access_source=context.access_source,
        tool_id=snapshot.tool_id,
        tool_version_id=snapshot.version_id,
        policy_snapshot=payload,
        arguments=arguments,
        arguments_hash=arguments_hash,
        idempotency_key=context.idempotency_key,
        status=(
            TOOL_INVOCATION_AWAITING_APPROVAL
            if snapshot.approval == TOOL_APPROVAL_EACH_CALL
            else TOOL_INVOCATION_QUEUED
        ),
    )
    invocation = await tool_repository.create_or_get_tool_invocation(db, candidate)
    if not _same_invocation(invocation, candidate):
        raise ToolInvocationConflict(
            "Tool invocation idempotency key was reused with different data."
        )
    if invocation.status in TOOL_INVOCATION_CLAIMABLE_STATUSES:
        refreshed = await tool_repository.refresh_tool_invocation_deadline(
            db,
            invocation.workspace_id,
            invocation.id,
            context.deadline_at,
        )
        if refreshed is not None:
            invocation = refreshed
    return invocation


async def execute_tool_invocation(
    invocation_id: str,
    settings: Settings,
    worker_task_id: str,
    *,
    adapter: ToolAdapter | None = None,
) -> ToolRuntimeResult:
    async with get_session_factory()() as db:
        invocation = await tool_repository.get_tool_invocation_by_id(db, invocation_id)
        if invocation is None:
            raise ValueError("Tool invocation not found.")
        if invocation.status in TOOL_INVOCATION_TERMINAL_STATUSES:
            return _stored_result(invocation)
        if invocation.status == TOOL_INVOCATION_AWAITING_APPROVAL:
            return _failure("approval_required", "Tool invocation requires approval.")

        try:
            snapshot, context = _load_invocation_contract(invocation)
        except ValueError:
            return await _fail_pending(
                db,
                invocation,
                _failure("invalid_tool_snapshot", "Tool invocation snapshot is invalid."),
            )
        now = utc_now()
        if invocation.status == TOOL_INVOCATION_RUNNING:
            lease_expires_at = invocation.lease_expires_at
            if lease_expires_at is not None and lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
            if lease_expires_at is not None and lease_expires_at >= now:
                raise ToolInvocationBusy("Tool invocation is owned by another worker.")
            if snapshot.effect in TOOL_UNCERTAIN_EFFECTS:
                return await _fail_pending(
                    db,
                    invocation,
                    _failure(
                        "tool_outcome_uncertain",
                        "Tool invocation outcome is uncertain after worker recovery.",
                        uncertain=True,
                    ),
                )
            if invocation.attempts >= invocation.max_attempts:
                return await _fail_pending(
                    db,
                    invocation,
                    _failure(
                        "tool_attempts_exhausted",
                        "Tool invocation attempts were exhausted.",
                    ),
                )
        live_error, mcp_server = await _validate_live_state(db, invocation, snapshot)
        if live_error is not None:
            return await _fail_pending(db, invocation, live_error)
        try:
            validate_tool_arguments(snapshot, invocation.arguments)
        except ValueError:
            return await _fail_pending(
                db,
                invocation,
                _failure("invalid_tool_arguments", "Tool arguments are invalid."),
            )

        if context.deadline_at <= now:
            return await _fail_pending(
                db,
                invocation,
                _failure("tool_deadline_exceeded", "Tool invocation deadline expired."),
            )
        claimed = await tool_repository.claim_tool_invocation(
            db,
            invocation.workspace_id,
            invocation.id,
            worker_task_id,
            now,
            now + timedelta(seconds=settings.agent_executor_lease_seconds),
        )
        await db.commit()
        if not claimed:
            current = await tool_repository.get_tool_invocation(
                db,
                invocation.workspace_id,
                invocation.id,
            )
            if (
                current is not None
                and current.status in TOOL_INVOCATION_TERMINAL_STATUSES
            ):
                return _stored_result(current)
            raise ToolInvocationBusy("Tool invocation is owned by another worker.")
        selected_adapter = adapter or build_tool_adapter(snapshot, settings, mcp_server)

    if selected_adapter.kind != snapshot.kind:
        result = _failure("tool_adapter_mismatch", "Tool provider is unavailable.")
    else:
        remaining = max(0.001, (context.deadline_at - utc_now()).total_seconds())
        try:
            async with asyncio.timeout(remaining):
                result = await selected_adapter.invoke(
                    snapshot,
                    invocation.arguments,
                    context,
                )
        except ToolAdapterBusy:
            if invocation.attempts + 1 < invocation.max_attempts:
                async with get_session_factory()() as db:
                    await tool_repository.requeue_tool_invocation(
                        db,
                        invocation.workspace_id,
                        invocation.id,
                        worker_task_id,
                        "tool_provider_busy",
                        "Tool provider is busy.",
                        utc_now(),
                    )
                    await db.commit()
                raise ToolInvocationBusy("Tool provider is busy.")
            result = _failure(
                "tool_attempts_exhausted",
                "Tool invocation attempts were exhausted.",
            )
        except TimeoutError:
            result = _failure(
                "tool_deadline_exceeded",
                "Tool invocation deadline expired.",
                uncertain=snapshot.effect in TOOL_UNCERTAIN_EFFECTS,
            )
        except Exception:
            result = _failure(
                "tool_execution_failed",
                "Tool execution failed.",
                uncertain=snapshot.effect in TOOL_UNCERTAIN_EFFECTS,
            )

    if result.ok:
        try:
            validate_tool_output(snapshot, result.data)
        except ValueError:
            result = _failure("invalid_tool_output", "Tool output is invalid.")

    async with get_session_factory()() as db:
        stored = await tool_repository.get_tool_invocation(
            db,
            invocation.workspace_id,
            invocation.id,
        )
        if stored is None:
            return _failure(
                "tool_result_not_persisted",
                "Tool result could not be persisted.",
                uncertain=snapshot.effect in TOOL_UNCERTAIN_EFFECTS,
            )
        _apply_result(stored, result)
        saved = await tool_repository.finalize_tool_invocation(
            db,
            stored.workspace_id,
            stored.id,
            worker_task_id,
            stored,
        )
        await db.commit()
        if not saved:
            return _failure(
                "tool_result_not_persisted",
                "Tool result could not be persisted.",
                uncertain=snapshot.effect in TOOL_UNCERTAIN_EFFECTS,
            )
    return result


async def _validate_live_state(
    db: AsyncSession,
    invocation: ToolInvocation,
    snapshot: ToolSnapshot,
) -> tuple[ToolRuntimeResult | None, Any]:
    tool = await tool_repository.get_tool(db, invocation.workspace_id, snapshot.tool_id)
    if tool is None or tool.status != "active":
        return _failure("tool_disabled", "Tool is disabled."), None
    source = await tool_repository.get_tool_source(
        db,
        invocation.workspace_id,
        snapshot.source_id,
    )
    if source is None or source.status != "active" or tool.availability != "available":
        return _failure("tool_unavailable", "Tool is unavailable."), None
    version = await tool_repository.get_tool_version(
        db,
        invocation.workspace_id,
        snapshot.version_id,
    )
    is_python_test = invocation.origin == "test" and snapshot.kind == "python"
    if (
        version is None
        or tool.source_id != source.id
        or tool.kind != snapshot.kind
        or tool.function_name != snapshot.function_name
        or (not is_python_test and tool.current_version_id != version.id)
        or version.tool_id != tool.id
        or version.definition_hash != snapshot.definition_hash
        or version.display_name != snapshot.display_name
        or version.description != snapshot.description
        or version.input_schema != snapshot.input_schema
        or version.output_schema != snapshot.output_schema
        or version.execution_spec != snapshot.execution_spec
    ):
        return _failure("tool_definition_changed", "Tool definition changed."), None
    policy = await tool_repository.get_tool_policy(db, invocation.workspace_id, tool.id)
    if is_python_test:
        policy_matches = (
            snapshot.approval == TOOL_APPROVAL_AUTO
            and snapshot.effect == "pure"
            and snapshot.allowed_access_sources == ("console",)
            and snapshot.workflow_callable
            and not snapshot.parallel_safe
        )
    else:
        policy_matches = (
            policy is not None
            and policy.id == snapshot.policy_id
            and policy.revision == snapshot.policy_revision
            and policy.tool_version_id == snapshot.version_id
            and policy.definition_hash == snapshot.definition_hash
            and policy.approval == snapshot.approval
            and policy.effect == snapshot.effect
            and tuple(policy.allowed_access_sources) == snapshot.allowed_access_sources
            and policy.workflow_callable == snapshot.workflow_callable
            and policy.parallel_safe == snapshot.parallel_safe
        )
    if not policy_matches:
        return _failure("tool_policy_changed", "Tool policy changed."), None
    if snapshot.approval == TOOL_APPROVAL_DISABLED:
        return _failure("tool_disabled", "Tool is disabled."), None
    if invocation.access_source not in snapshot.allowed_access_sources:
        return _failure("tool_access_source_denied", "Tool access source is denied."), None
    if invocation.access_source in {"public", "api"} and (
        snapshot.approval != TOOL_APPROVAL_AUTO
        or snapshot.effect not in TOOL_SAFE_EXTERNAL_EFFECTS
    ):
        return _failure("tool_access_source_denied", "Tool access source is denied."), None
    if invocation.origin == "workflow" and not snapshot.workflow_callable:
        return _failure("tool_not_workflow_callable", "Tool cannot run in a Workflow."), None
    if snapshot.execution_spec.get("workflow_only") is True and invocation.origin != "workflow":
        return _failure("tool_not_agent_callable", "Tool cannot run in an Agent."), None

    actor = await user_repository.get_user_by_id(db, snapshot.bound_by_user_id)
    membership = (
        await workspace_repository.get_workspace_membership(
            db,
            invocation.workspace_id,
            snapshot.bound_by_user_id,
        )
        if actor is not None
        else None
    )
    grant = (
        await permission_repository.get_user_grant(
            db,
            invocation.workspace_id,
            "tool",
            tool.id,
            snapshot.bound_by_user_id,
        )
        if actor is not None
        else None
    )
    authorization = (
        evaluate_tool_authorization(
            tool,
            actor,
            membership.role if membership is not None else None,
            grant,
        )
        if actor is not None
        else None
    )
    allowed = (
        authorization is not None
        and (
            authorization.access.can_manage
            if invocation.origin == "test"
            else authorization.access.can_use
        )
    )
    if not allowed:
        return _failure("tool_access_revoked", "Tool access was revoked."), None

    execution_user = (
        actor
        if actor is not None and actor.id == invocation.execution_user_id
        else await user_repository.get_user_by_id(db, invocation.execution_user_id)
    )
    execution_membership = (
        membership
        if execution_user is not None and execution_user.id == snapshot.bound_by_user_id
        else await workspace_repository.get_workspace_membership(
            db,
            invocation.workspace_id,
            invocation.execution_user_id,
        )
        if execution_user is not None
        else None
    )
    if execution_user is None or not execution_user.is_active or (
        not execution_user.is_global_admin and execution_membership is None
    ):
        return _failure(
            "tool_execution_access_revoked",
            "Tool execution access was revoked.",
        ), None

    server = None
    if snapshot.kind == "mcp":
        server = (
            await mcp_repository.get_mcp_server_by_id(db, source.mcp_server_id)
            if source.mcp_server_id is not None
            else None
        )
        if (
            server is None
            or server.workspace_id != invocation.workspace_id
            or server.status != "active"
        ):
            return _failure("tool_unavailable", "Tool is unavailable."), None
    return None, server


async def list_recoverable_tool_test_invocation_ids() -> list[str]:
    async with get_session_factory()() as db:
        now = utc_now()
        invocation_ids = await tool_repository.list_recoverable_tool_test_invocation_ids(
            db,
            now,
        )
        await db.commit()
        return invocation_ids


async def preflight_tool_snapshot(
    db: AsyncSession,
    snapshot: ToolSnapshot,
    *,
    origin: str,
    workspace_id: str,
    execution_user_id: str,
    access_source: str,
) -> ToolRuntimeResult | None:
    invocation = ToolInvocation(
        workspace_id=workspace_id,
        origin=origin,
        execution_user_id=execution_user_id,
        access_source=access_source,
        tool_id=snapshot.tool_id,
        tool_version_id=snapshot.version_id,
    )
    failure, _server = await _validate_live_state(db, invocation, snapshot)
    return failure


async def _fail_pending(
    db: AsyncSession,
    invocation: ToolInvocation,
    result: ToolRuntimeResult,
) -> ToolRuntimeResult:
    _apply_result(invocation, result)
    now = utc_now()
    invocation.finished_at = now
    invocation.updated_at = now
    await tool_repository.fail_pending_tool_invocation(
        db,
        invocation.workspace_id,
        invocation.id,
        invocation,
        now,
    )
    await db.commit()
    return result


def _load_invocation_contract(
    invocation: ToolInvocation,
) -> tuple[ToolSnapshot, ToolInvocationContext]:
    snapshot = tool_snapshot_from_payload(invocation.policy_snapshot.get("tool_snapshot"))
    deadline_value = invocation.policy_snapshot.get("deadline_at")
    if not isinstance(deadline_value, str):
        raise ValueError("Tool invocation deadline is invalid.")
    deadline = datetime.fromisoformat(deadline_value)
    if deadline.tzinfo is None:
        raise ValueError("Tool invocation deadline is invalid.")
    context = ToolInvocationContext(
        workspace_id=invocation.workspace_id,
        origin=invocation.origin,
        root_run_id=invocation.root_run_id,
        run_id=invocation.run_id,
        invocation_id=invocation.invocation_id,
        execution_user_id=invocation.execution_user_id,
        access_source=invocation.access_source,
        deadline_at=deadline,
        idempotency_key=invocation.idempotency_key,
    )
    _validate_context(context)
    return snapshot, context


def _validate_context(context: ToolInvocationContext) -> None:
    if context.origin == "test":
        if context.root_run_id is not None or context.run_id is not None:
            raise ValueError("Tool tests cannot belong to a Run.")
    elif not context.root_run_id or not context.run_id:
        raise ValueError("Application Tool invocations require Run IDs.")
    if context.access_source not in {"console", "public", "api"}:
        raise ValueError("Tool invocation access source is invalid.")
    if not context.idempotency_key or not context.invocation_id:
        raise ValueError("Tool invocation identity is invalid.")


def _same_invocation(existing: ToolInvocation, candidate: ToolInvocation) -> bool:
    return existing.policy_snapshot.get(
        "tool_snapshot"
    ) == candidate.policy_snapshot.get("tool_snapshot") and all(
        getattr(existing, field) == getattr(candidate, field)
        for field in (
            "workspace_id",
            "origin",
            "root_run_id",
            "run_id",
            "invocation_id",
            "execution_user_id",
            "access_source",
            "tool_id",
            "tool_version_id",
            "arguments_hash",
        )
    )


def _apply_result(invocation: ToolInvocation, result: ToolRuntimeResult) -> None:
    invocation.status = (
        TOOL_INVOCATION_UNCERTAIN
        if result.outcome == "uncertain"
        else TOOL_INVOCATION_SUCCEEDED
        if result.ok
        else TOOL_INVOCATION_FAILED
    )
    invocation.result_data = result.data
    invocation.result_summary = result.summary[:1000]
    invocation.outcome = result.outcome
    invocation.error_code = result.error_code
    invocation.error_message = result.error_message[:1000] if result.error_message else None
    invocation.usage = result.usage
    invocation.finished_at = utc_now()
    invocation.updated_at = invocation.finished_at


def _stored_result(invocation: ToolInvocation) -> ToolRuntimeResult:
    return ToolRuntimeResult(
        ok=invocation.status == TOOL_INVOCATION_SUCCEEDED,
        data=invocation.result_data,
        summary=invocation.result_summary,
        error_code=invocation.error_code,
        error_message=invocation.error_message,
        outcome=(
            "uncertain"
            if invocation.status == TOOL_INVOCATION_UNCERTAIN
            else "confirmed"
        ),
        usage=invocation.usage,
    )


def _failure(
    code: str,
    message: str,
    *,
    uncertain: bool = False,
) -> ToolRuntimeResult:
    return ToolRuntimeResult(
        ok=False,
        data=None,
        summary=message,
        error_code=code,
        error_message=message,
        outcome="uncertain" if uncertain else "confirmed",
        usage={},
    )


__all__ = [
    "ToolInvocationBusy",
    "ToolInvocationConflict",
    "execute_tool_invocation",
    "list_recoverable_tool_test_invocation_ids",
    "preflight_tool_snapshot",
    "queue_tool_invocation",
]

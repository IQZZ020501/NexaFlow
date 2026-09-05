from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
import hashlib
import json
from itertools import islice
import secrets
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent_runs import (
    cancel_run_tree,
    enqueue_prepared_agent_run,
    list_canonical_agent_run_tool_calls,
    prepare_agent_run,
    regenerate_agent_run_from_source,
    resolve_agent_run_tool_approval,
    stream_agent_run,
    tool_call_to_response,
    update_run_feedback,
)
from app.application.workspace import WorkspaceContext, build_workspace_context
from app.entities.agents import (
    Agent,
    AgentApiCredential,
    AgentPublicationVersion,
    AgentRun,
)
from app.entities.user import User
from app.infrastructure.agent_rate_limit import (
    AgentRateLimitExceeded,
    AgentRateLimitUnavailable,
    enforce_external_agent_rate_limit,
)
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import APP_TIMEZONE, utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.validation import normalize_name
from app.schemas.agent import (
    AgentApiCredentialCreateResponse,
    AgentApiCredentialListResponse,
    AgentApiCredentialResponse,
    AgentConversationUserListResponse,
    AgentConversationUserResponse,
    AgentLogListResponse,
    AgentLogResponse,
    AgentMonitoringDailyResponse,
    AgentMonitoringResponse,
    AgentMonitoringValues,
    AgentToolCallResponse,
    ExternalAgentKnowledgeHitResponse,
    ExternalAgentProgressEventResponse,
    ExternalAgentRunListResponse,
    ExternalAgentRunResponse,
    PublicAgentConversationListResponse,
    PublicAgentConversationResponse,
    PublicAgentProfileResponse,
)
from app.application.workflow_uploads import resolve_public_agent_files
from app.shareddomain.agents.services import (
    ACTIVE_STATUS,
    AgentPublication,
    agent_publication_from_version,
    agent_publication_from_snapshot,
    get_agent,
    require_agent_edit,
)
from app.shareddomain.agents.models import agent_run_display_status
from app.shareddomain.agents.runtime.graph import ModelTextStreamFilter, clean_model_text
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.agents.runtime.callbacks import safe_event_value

ExternalAccessSource = Literal["public", "api"]


@dataclass(frozen=True)
class PublishedAgentContext:
    agent: Agent
    publisher: User
    workspace: WorkspaceContext
    publication: AgentPublication | None = None
    publication_version: AgentPublicationVersion | None = None


def hash_agent_access_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_agent_api_token() -> str:
    return f"nxf_{secrets.token_urlsafe(36)}"


def _credential_to_response(
    credential: AgentApiCredential,
) -> AgentApiCredentialResponse:
    return AgentApiCredentialResponse(
        id=credential.id,
        workspace_id=credential.workspace_id,
        agent_id=credential.agent_id,
        name=credential.name,
        hint=credential.hint,
        created_by_user_id=credential.created_by_user_id,
        last_used_at=credential.last_used_at,
        revoked_at=credential.revoked_at,
        created_at=credential.created_at,
    )


def _external_progress_id(event: dict[str, Any], suffix: str = "") -> str:
    identity = ":".join(
        (
            str(event.get("type") or ""),
            str(event.get("turn") or 0),
            str(event.get("call_id") or event.get("tool_name") or ""),
            suffix,
        )
    )
    return hashlib.sha256(f"external-progress:{identity}".encode()).hexdigest()[:16]


TOOL_PAYLOAD_ELLIPSIS = "…"


@dataclass(frozen=True)
class ToolPayloadLimits:
    max_string: int
    max_depth: int
    max_items: int
    max_total_items: int
    max_total_chars: int
    max_serialized: int


# 调用输入由运行时保留完整内容；敏感字段仍在事件生成时脱敏。
# 调用结果（output）完整透传，不做截断。
TOOL_INPUT_LIMITS = ToolPayloadLimits(
    max_string=500,
    max_depth=4,
    max_items=25,
    max_total_items=200,
    max_total_chars=4000,
    max_serialized=4000,
)


def _limit_tool_payload(
    value: object,
    depth: int,
    budget: list[int],
    limits: ToolPayloadLimits,
) -> tuple[object, bool]:
    """递归限制工具载荷，返回 (受限副本, 是否截断)。

    budget = [剩余元素数, 剩余字符数]，遍历途中耗尽即截断，
    避免 materialize 超大容器或保留超限结构。
    """
    if depth >= limits.max_depth:
        return TOOL_PAYLOAD_ELLIPSIS, True
    if budget[0] <= 0 or budget[1] <= 0:
        return TOOL_PAYLOAD_ELLIPSIS, True
    if isinstance(value, dict):
        limited: dict[str, object] = {}
        truncated = False
        for key, item in islice(value.items(), limits.max_items):
            if budget[0] <= 0 or budget[1] <= 0:
                truncated = True
                break
            budget[0] -= 1
            safe_key = key if isinstance(key, str) else str(key)
            if len(safe_key) > limits.max_string:
                safe_key = safe_key[: limits.max_string] + TOOL_PAYLOAD_ELLIPSIS
                truncated = True
            budget[1] -= len(safe_key)
            limited[safe_key], item_truncated = _limit_tool_payload(
                item, depth + 1, budget, limits
            )
            truncated = truncated or item_truncated
        if len(value) > len(limited):
            truncated = True
        return limited, truncated
    if isinstance(value, list):
        limited: list[object] = []
        truncated = False
        for item in islice(value, limits.max_items):
            if budget[0] <= 0 or budget[1] <= 0:
                truncated = True
                break
            budget[0] -= 1
            limited_item, item_truncated = _limit_tool_payload(
                item, depth + 1, budget, limits
            )
            limited.append(limited_item)
            truncated = truncated or item_truncated
        if len(value) > len(limited):
            truncated = True
        return limited, truncated
    if isinstance(value, str):
        budget[1] -= min(len(value), limits.max_string)
        if len(value) > limits.max_string:
            return value[: limits.max_string] + TOOL_PAYLOAD_ELLIPSIS, True
        return value, False
    if value is None or isinstance(value, (bool, int, float)):
        budget[1] -= len(str(value))
        return value, False
    text = str(value)
    budget[1] -= min(len(text), limits.max_string)
    if len(text) > limits.max_string:
        return text[: limits.max_string] + TOOL_PAYLOAD_ELLIPSIS, True
    return text, False


def _bounded_tool_payload(
    value: object,
    limits: ToolPayloadLimits,
) -> tuple[object, bool]:
    """按给定限制约束工具载荷，保证元素数与序列化大小都有界。"""
    budget = [limits.max_total_items, limits.max_total_chars]
    limited, truncated = _limit_tool_payload(value, 0, budget, limits)
    serialized = json.dumps(limited, ensure_ascii=False, default=str)
    if len(serialized) > limits.max_serialized:
        # 结构截断后仍超限：整体替换为截断标记，避免嵌入原始序列化文本
        # 导致再序列化时引号转义膨胀。
        return {"truncated": True}, True
    return limited, truncated


def external_progress_events(
    events: list[dict[str, Any]],
    run_status: str,
) -> list[ExternalAgentProgressEventResponse]:
    progress: list[ExternalAgentProgressEventResponse] = []

    def upsert(item: ExternalAgentProgressEventResponse) -> None:
        for index, current in enumerate(progress):
            if current.id == item.id:
                progress[index] = item
                return
        progress.append(item)

    for event in events:
        event_type = event.get("type")
        status_value = event.get("status")
        if status_value not in {"running", "succeeded", "failed"}:
            continue
        event_status: Literal["running", "succeeded", "failed"] = status_value
        if run_status == "cancelled" and event_status == "running":
            event_status = "failed"
        turn = max(0, int(event.get("turn") or 0))
        summary = str(event.get("summary") or "")

        if event_type == "thought":
            if summary == "agent.answer_ready":
                answer_status: Literal["running", "succeeded", "failed"] = (
                    "succeeded"
                    if run_status == "succeeded"
                    else "failed"
                    if run_status in {"failed", "cancelled"}
                    else "running"
                )
                upsert(
                    ExternalAgentProgressEventResponse(
                        id=_external_progress_id(event, "answer"),
                        type="answer",
                        status=answer_status,
                        stage=answer_status,
                        turn=turn,
                        reasoning=str(event.get("reasoning") or ""),
                        created_at=event.get("created_at"),
                    )
                )
            elif summary in {
                "agent.analyzing",
                "agent.preparing_tool_call",
                "agent.reviewing_tool_results",
                "agent.tools_selected",
            }:
                stage = {
                    "agent.analyzing": "analyzing",
                    "agent.preparing_tool_call": "preparing",
                    "agent.reviewing_tool_results": "reviewing",
                    "agent.tools_selected": "completed",
                }[summary]
                upsert(
                    ExternalAgentProgressEventResponse(
                        id=_external_progress_id(event, "analysis"),
                        type="analysis",
                        status=event_status,
                        stage=stage,
                        turn=turn,
                        reasoning=str(event.get("reasoning") or ""),
                    )
                )
            elif summary in {
                "agent.grounding_check",
                "agent.grounding_verified",
                "agent.grounding_revised",
                "agent.grounding_insufficient",
                "agent.grounding_unavailable",
            }:
                grounding_stage = (
                    "reviewing"
                    if summary == "agent.grounding_check"
                    else "completed"
                    if summary in {"agent.grounding_verified", "agent.grounding_revised"}
                    else "failed"
                )
                upsert(
                    ExternalAgentProgressEventResponse(
                        id=_external_progress_id(event, "grounding"),
                        type="analysis",
                        status=event_status,
                        stage=grounding_stage,
                        turn=turn,
                        reasoning=str(event.get("reasoning") or ""),
                    )
                )
            continue

        if event_type != "tool":
            continue
        progress_type: Literal["knowledge", "tool"] = (
            "knowledge" if event.get("tool_kind") == "knowledge" else "tool"
        )
        tool_kind = str(event.get("tool_kind") or "unknown")
        if tool_kind not in {"knowledge", "mcp", "unknown"}:
            tool_kind = "unknown"
        raw_input = event.get("input")
        count = None
        if progress_type == "knowledge" and summary.startswith(
            "agent.knowledge_chunks_returned:"
        ):
            try:
                count = max(0, int(summary.rsplit(":", 1)[1]))
            except ValueError:
                count = None
        hits: list[ExternalAgentKnowledgeHitResponse] = []
        if progress_type == "knowledge":
            output = event.get("output")
            if isinstance(output, dict) and isinstance(output.get("hits"), list):
                for raw_hit in output["hits"]:
                    if not isinstance(raw_hit, dict):
                        continue
                    hits.append(
                        ExternalAgentKnowledgeHitResponse(
                            knowledge_base=str(raw_hit.get("knowledge_base") or ""),
                            document=str(raw_hit.get("document") or ""),
                            content=str(raw_hit.get("content") or ""),
                        )
                    )
        bounded_input = (
            safe_event_value(raw_input, max_string_chars=None, max_list_items=None)
            if isinstance(raw_input, dict)
            else {}
        )
        upsert(
            ExternalAgentProgressEventResponse(
                id=_external_progress_id(event, "tool"),
                type=progress_type,
                status=event_status,
                stage=(
                    "preparing"
                    if summary == "agent.preparing_tool_call"
                    else event_status
                ),
                turn=turn,
                count=count,
                tool_name=str(event.get("tool_name") or ""),
                tool_label=str(event.get("tool_label") or ""),
                tool_kind=tool_kind,
                server_name=str(event.get("server_name") or ""),
                input=bounded_input,
                output=None if progress_type == "knowledge" else event.get("output"),
                input_truncated=False,
                hits=hits,
            )
        )
    return progress


def external_run_to_response(run: AgentRun | dict[str, Any]) -> ExternalAgentRunResponse:
    """
    Convert an agent run into its external response representation.
    
    Parameters:
    	run (AgentRun | dict[str, Any]): The agent run entity or mapping to convert.
    
    Returns:
    	ExternalAgentRunResponse: The external run response, including status, result, progress, timestamps, feedback, and regeneration information.
    """
    value = run if isinstance(run, dict) else vars(run)
    snapshot = value.get("application_snapshot")
    attachments = value.get("attachments")
    if attachments is None and isinstance(snapshot, dict):
        attachments = snapshot.get("attachments")
    run_status = agent_run_display_status(str(value.get("status") or ""))
    generic_error = None
    if run_status == "failed":
        generic_error = "Agent run failed."
    elif run_status == "cancelled":
        generic_error = "Agent run was cancelled."
    return ExternalAgentRunResponse(
        id=str(value["id"]),
        conversation_id=str(value["conversation_id"]),
        regenerated_from_run_id=(
            str(value["regenerated_from_run_id"])
            if value.get("regenerated_from_run_id")
            else None
        ),
        question=str(value.get("goal") or value.get("question") or ""),
        attachments=attachments or [],
        status=run_status,
        result=clean_model_text(str(value.get("result") or "")),
        error=generic_error,
        progress=external_progress_events(value.get("events") or [], run_status),
        created_at=value["created_at"],
        started_at=value.get("started_at"),
        finished_at=value.get("finished_at"),
        updated_at=value["updated_at"],
        feedback=value.get("feedback"),
        feedback_updated_at=value.get("feedback_updated_at"),
    )


async def sanitize_external_agent_stream(
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    streamed_tool_inputs: dict[str, dict[str, str]] = {}
    text_filter = ModelTextStreamFilter()
    async for event in events:
        event_type = event.get("type")
        if event_type == "answer_delta":
            delta = text_filter.push(str(event.get("delta") or ""))
            if not delta:
                continue
            sanitized = {
                "type": "answer_delta",
                "delta": delta,
            }
            _copy_external_stream_metadata(event, sanitized)
            yield sanitized
        elif event_type == "answer_reset":
            text_filter = ModelTextStreamFilter()
            sanitized = {"type": "answer_reset"}
            _copy_external_stream_metadata(event, sanitized)
            yield sanitized
        elif event_type == "reasoning_delta":
            sanitized = {
                "type": "reasoning_delta",
                "turn": max(0, int(event.get("turn") or 0)),
                "delta": str(event.get("delta") or ""),
            }
            _copy_external_stream_metadata(event, sanitized)
            yield sanitized
        elif event_type == "tool_input_delta":
            progress_id = _external_progress_id(
                {
                    "type": "tool",
                    "turn": event.get("turn"),
                    "call_id": event.get("call_id"),
                },
                "tool",
            )
            field = str(event.get("field") or "")
            if not field:
                continue
            inputs = streamed_tool_inputs.setdefault(progress_id, {})
            previous = inputs.get(field, "")
            raw_delta = str(event.get("delta") or "")
            candidate = raw_delta if event.get("replace") else previous + raw_delta
            safe_candidate = safe_event_value(
                {field: candidate}, max_string_chars=None, max_list_items=None
            )[field]
            candidate = (
                safe_candidate
                if isinstance(safe_candidate, str)
                else str(safe_candidate)
            )
            inputs[field] = candidate
            replace = not candidate.startswith(previous)
            delta = candidate if replace else candidate[len(previous) :]
            sanitized = {
                "type": "tool_input_delta",
                "id": progress_id,
                "turn": max(0, int(event.get("turn") or 0)),
                "tool_name": str(event.get("tool_name") or "")[:200],
                "field": field,
                "delta": delta,
                "replace": replace,
                "input_truncated": False,
            }
            _copy_external_stream_metadata(event, sanitized)
            yield sanitized
        elif event_type == "process" and isinstance(event.get("event"), dict):
            for progress_event in external_progress_events(
                [event["event"]], "running"
            ):
                sanitized = {
                    "type": "progress",
                    "event": progress_event.model_dump(
                        mode="json", exclude={"created_at"}
                    ),
                }
                _copy_external_stream_metadata(event, sanitized)
                yield sanitized
        elif event_type == "approval_required":
            sanitized = {
                "type": "approval_required",
                "call_id": str(event.get("call_id") or ""),
                "reason": str(event.get("reason") or ""),
            }
            _copy_external_stream_metadata(event, sanitized)
            yield sanitized
        elif event_type in {"run", "complete", "error"} and isinstance(
            event.get("run"), dict
        ):
            if event_type in {"complete", "error"}:
                trailing = text_filter.finish()
                if trailing:
                    trailing_event = {"type": "answer_delta", "delta": trailing}
                    _copy_external_stream_metadata(event, trailing_event)
                    yield trailing_event
            sanitized = {
                "type": event_type,
                "run": external_run_to_response(event["run"]).model_dump(mode="json"),
            }
            _copy_external_stream_metadata(event, sanitized)
            yield sanitized


def _copy_external_stream_metadata(
    event: dict[str, Any],
    sanitized: dict[str, Any],
) -> None:
    for key in ("sequence", "live_sequence"):
        if key in event:
            sanitized[key] = event[key]
    raw_epoch = event.get("stream_epoch")
    if isinstance(raw_epoch, str) and raw_epoch:
        sanitized["stream_epoch"] = hashlib.sha256(
            f"external-stream:{raw_epoch}".encode("utf-8")
        ).hexdigest()[:32]


async def get_published_agent_context(
    db: AsyncSession,
    agent_id: str,
) -> PublishedAgentContext:
    return await get_published_application_context(db, agent_id, "agent")


async def get_published_workflow_context(
    db: AsyncSession,
    workflow_id: str,
) -> PublishedAgentContext:
    return await get_published_application_context(db, workflow_id, "workflow")


async def get_published_application_context(
    db: AsyncSession,
    agent_id: str,
    application_type: Literal["agent", "workflow"],
) -> PublishedAgentContext:
    agent = await agent_repository.get_agent_by_id(db, agent_id)
    if (
        agent is None
        or agent.app_type != application_type
        or agent.status != ACTIVE_STATUS
        or not agent.published
        or not agent.published_by_user_id
        or agent.published_at is None
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Published {application_type} not found.",
        )
    publication_version = None
    publication = None
    publisher_id = agent.published_by_user_id
    if application_type == "agent":
        if agent.current_published_version_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
        publication_version = await agent_repository.get_agent_publication_version(
            db,
            agent.workspace_id,
            agent.current_published_version_id,
        )
        if publication_version is None or publication_version.agent_id != agent.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
        try:
            publication = agent_publication_from_version(publication_version)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Published agent not found.",
            ) from exc
        publisher_id = publication_version.published_by_user_id
    else:
        publication = agent_publication_from_snapshot(agent)
    publisher = await user_repository.get_user_by_id(db, publisher_id)
    if publisher is None or not publisher.is_active:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Published {application_type} not found.",
        )
    try:
        workspace = await build_workspace_context(db, publisher, agent.workspace_id)
    except HTTPException as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Published {application_type} not found.",
        ) from exc
    return PublishedAgentContext(
        agent=agent,
        publisher=publisher,
        workspace=workspace,
        publication=publication,
        publication_version=publication_version,
    )


async def get_workspace_published_agent_context(
    db: AsyncSession,
    agent_id: str,
    user: User,
) -> PublishedAgentContext:
    return await get_workspace_published_application_context(db, agent_id, user, "agent")


async def get_workspace_published_workflow_context(
    db: AsyncSession,
    workflow_id: str,
    user: User,
) -> PublishedAgentContext:
    return await get_workspace_published_application_context(
        db, workflow_id, user, "workflow"
    )


async def get_workspace_published_application_context(
    db: AsyncSession,
    agent_id: str,
    user: User,
    application_type: Literal["agent", "workflow"],
) -> PublishedAgentContext:
    context = await get_published_application_context(db, agent_id, application_type)
    try:
        await build_workspace_context(db, user, context.agent.workspace_id)
    except HTTPException as exc:
        if exc.status_code in {
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        }:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Published {application_type} not found.",
            ) from exc
        raise
    return context


async def get_public_agent_profile(
    db: AsyncSession,
    agent_id: str,
    user: User,
) -> PublicAgentProfileResponse:
    context = await get_workspace_published_agent_context(db, agent_id, user)
    if context.publication is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
    return PublicAgentProfileResponse(
        id=context.agent.id,
        name=context.publication.name,
        description=context.publication.description,
        interaction_config=context.publication.interaction_config,
    )


async def list_agent_api_credentials(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
) -> AgentApiCredentialListResponse:
    agent = await get_agent(db, workspace_id, agent_id)
    _require_workspace_admin(workspace_role)
    credentials = await agent_repository.list_agent_api_credentials(db, agent.id)
    return AgentApiCredentialListResponse(
        items=[_credential_to_response(item) for item in credentials]
    )


def _require_workspace_admin(workspace_role: str | None) -> None:
    if workspace_role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace admin required.")


async def _new_agent_api_credential(
    db: AsyncSession,
    agent: Agent,
    name: str,
    actor: User,
) -> tuple[AgentApiCredential, str]:
    token = create_agent_api_token()
    credential = AgentApiCredential(
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        name=normalize_name(name),
        token_hash=hash_agent_access_token(token),
        hint=f"{token[:8]}...{token[-4:]}",
        created_by_user_id=actor.id,
    )
    return await agent_repository.create_agent_api_credential(db, credential), token


async def create_agent_api_credential(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    name: str,
    actor: User,
    workspace_role: str | None,
) -> AgentApiCredentialCreateResponse:
    agent = await get_agent(db, workspace_id, agent_id)
    _require_workspace_admin(workspace_role)
    try:
        credential, token = await _new_agent_api_credential(db, agent, name, actor)
        record_audit_log(
            db,
            actor,
            "agent.api_credential.create",
            "agent_api_credential",
            credential.id,
            credential.name,
            {"agent_id": agent.id},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "API credential could not be created.",
        ) from exc
    return AgentApiCredentialCreateResponse(
        credential=_credential_to_response(credential), token=token
    )


async def revoke_agent_api_credential(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    credential_id: str,
    actor: User,
    workspace_role: str | None,
) -> None:
    agent = await get_agent(db, workspace_id, agent_id)
    _require_workspace_admin(workspace_role)
    credential = await agent_repository.get_agent_api_credential_by_id(
        db, credential_id
    )
    if credential is None or credential.agent_id != agent.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API credential not found.")
    if credential.revoked_at is None:
        await agent_repository.revoke_agent_api_credential(
            db, credential.id, utc_now()
        )
        record_audit_log(
            db,
            actor,
            "agent.api_credential.revoke",
            "agent_api_credential",
            credential.id,
            credential.name,
            {"agent_id": agent.id},
            workspace_id=workspace_id,
        )
        await db.commit()


async def rotate_agent_api_credential(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    credential_id: str,
    actor: User,
    workspace_role: str | None,
) -> AgentApiCredentialCreateResponse:
    agent = await get_agent(db, workspace_id, agent_id)
    _require_workspace_admin(workspace_role)
    previous = await agent_repository.get_agent_api_credential_by_id(
        db, credential_id
    )
    if previous is None or previous.agent_id != agent.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API credential not found.")
    if previous.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "API credential is revoked.")
    try:
        token = create_agent_api_token()
        hint = f"{token[:8]}...{token[-4:]}"
        rotated = await agent_repository.rotate_agent_api_credential(
            db,
            previous.id,
            previous.token_hash,
            hash_agent_access_token(token),
            hint,
        )
        if not rotated:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "API credential is no longer active.",
            )
        previous.token_hash = hash_agent_access_token(token)
        previous.hint = hint
        record_audit_log(
            db,
            actor,
            "agent.api_credential.rotate",
            "agent_api_credential",
            previous.id,
            previous.name,
            {"agent_id": agent.id},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "API credential could not be rotated.",
        ) from exc
    return AgentApiCredentialCreateResponse(
        credential=_credential_to_response(previous), token=token
    )


async def authenticate_agent_api_credential(
    db: AsyncSession,
    agent_id: str,
    token: str,
    application_type: Literal["agent", "workflow"] = "agent",
) -> tuple[PublishedAgentContext, AgentApiCredential]:
    if not token.startswith("nxf_"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API credential.")
    credential = await agent_repository.get_agent_api_credential_by_hash(
        db, hash_agent_access_token(token)
    )
    if credential is None or credential.agent_id != agent_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API credential.")
    try:
        context = await get_published_application_context(
            db, agent_id, application_type
        )
    except HTTPException as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Published {application_type} not found.",
        ) from exc
    if credential.workspace_id != context.agent.workspace_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API credential.")
    now = utc_now()
    last_used_at = credential.last_used_at
    if last_used_at is not None and last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=UTC)
    if last_used_at is None or (now - last_used_at).total_seconds() >= 60:
        if not await agent_repository.mark_agent_api_credential_used(
            db, credential.id, now
        ):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Invalid API credential."
            )
        await db.commit()
        credential.last_used_at = now
    return context, credential


async def _enforce_rate_limit(
    settings: Settings,
    agent_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
) -> None:
    try:
        await enforce_external_agent_rate_limit(
            settings, agent_id, access_source, consumer_id
        )
    except AgentRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Agent run rate limit exceeded.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except AgentRateLimitUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Agent run service is temporarily unavailable.",
        ) from exc


async def create_external_agent_run(
    db: AsyncSession,
    context: PublishedAgentContext,
    access_source: ExternalAccessSource,
    consumer_id: str,
    goal: str,
    settings: Settings,
    conversation_id: str | None = None,
    file_ids: list[str] | None = None,
) -> ExternalAgentRunResponse:
    await _enforce_rate_limit(settings, context.agent.id, access_source, consumer_id)
    if context.publication is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
    attachment_context = ""
    attachments: list[dict[str, Any]] = []
    if file_ids:
        if access_source != "public":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Agent API runs do not accept public upload ids.",
            )
        attachment_context, attachments = await resolve_public_agent_files(
            db,
            context,
            consumer_id,
            file_ids,
            settings,
        )
    run, _ = await prepare_agent_run(
        db,
        context.agent.workspace_id,
        context.agent.id,
        goal,
        context.publisher,
        context.workspace.membership_role,
        conversation_id=conversation_id,
        access_source=access_source,
        consumer_id=consumer_id,
        publication=context.publication,
        publication_version=context.publication_version,
        attachment_context=attachment_context,
        attachments=attachments,
    )
    await enqueue_prepared_agent_run(
        run.id,
        settings,
        unified=run.configuration_source in {"draft", "published"},
    )
    current = await agent_repository.refresh_agent_run(db, run)
    return external_run_to_response(current)


async def get_external_agent_run(
    db: AsyncSession,
    agent_id: str,
    run_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
) -> AgentRun:
    """
    Retrieve an externally accessible agent run for the specified consumer.
    
    Parameters:
        agent_id (str): Identifier of the agent associated with the run.
        run_id (str): Identifier of the run to retrieve.
        access_source (ExternalAccessSource): Source through which the run was accessed.
        consumer_id (str): Identifier of the consumer who owns the run.
    
    Returns:
        AgentRun: The matching agent run.
    
    Raises:
        HTTPException: If the run does not exist or does not match the agent, access source, or consumer.
    """
    await get_published_agent_context(db, agent_id)
    run = await agent_repository.get_agent_run_by_id(db, run_id)
    if (
        run is None
        or run.agent_id != agent_id
        or run.access_source != access_source
        or run.consumer_id != consumer_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found.")
    return run


async def cancel_external_agent_run(
    db: AsyncSession,
    agent_id: str,
    run_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
) -> ExternalAgentRunResponse:
    """Cancel an externally accessible public run owned by the consumer."""
    if access_source != "public":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found.")
    run = await get_external_agent_run(
        db,
        agent_id,
        run_id,
        access_source,
        consumer_id,
    )
    if not await cancel_run_tree(db, run.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Agent run is already finished.")
    await db.commit()
    current = await agent_repository.get_agent_run_by_id(db, run.id)
    assert current is not None
    return external_run_to_response(current)


async def regenerate_external_agent_run(
    db: AsyncSession,
    context: PublishedAgentContext,
    run_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
    settings: Settings,
    goal: str | None = None,
) -> ExternalAgentRunResponse:
    """
    Regenerate a publicly accessible agent run from its source run.
    
    Parameters:
        context (PublishedAgentContext): The published agent context used to authorize regeneration.
        run_id (str): The identifier of the source run.
        access_source (ExternalAccessSource): The access channel for the run.
        consumer_id (str): The external consumer requesting regeneration.
        settings (Settings): Application settings required for run regeneration.
    
    Returns:
        ExternalAgentRunResponse: The regenerated run represented for external access.
    """
    if access_source != "public":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found.")
    source = await get_external_agent_run(
        db,
        context.agent.id,
        run_id,
        access_source,
        consumer_id,
    )
    regenerated = await regenerate_agent_run_from_source(
        db,
        source,
        context.publisher,
        settings,
        goal=goal,
    )
    return external_run_to_response(regenerated)


async def set_external_agent_run_feedback(
    db: AsyncSession,
    agent_id: str,
    run_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
    value: str | None,
) -> ExternalAgentRunResponse:
    """
    Update feedback for an externally accessible agent run.
    
    Parameters:
        agent_id (str): Identifier of the agent that owns the run.
        run_id (str): Identifier of the run.
        access_source (ExternalAccessSource): Source through which the run was accessed.
        consumer_id (str): Identifier of the external consumer.
        value (str | None): Feedback value, or `None` to clear the feedback.
    
    Returns:
        ExternalAgentRunResponse: The updated external run.
    
    Raises:
        HTTPException: If the run was not accessed publicly or cannot be found.
    """
    if access_source != "public":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found.")
    source = await get_external_agent_run(
        db,
        agent_id,
        run_id,
        access_source,
        consumer_id,
    )
    updated = await update_run_feedback(db, source, value)
    return external_run_to_response(updated)


async def list_external_agent_run_tool_calls(
    db: AsyncSession,
    agent_id: str,
    run_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
) -> list[AgentToolCallResponse]:
    """
    List tool calls associated with an externally accessible agent run.
    
    Parameters:
        access_source (ExternalAccessSource): The source through which the run was accessed.
        consumer_id (str): The consumer identity authorized to access the run.
    
    Returns:
        list[AgentToolCallResponse]: Tool calls for the run.
    """
    run = await get_external_agent_run(db, agent_id, run_id, access_source, consumer_id)
    if run.configuration_source in {"draft", "published"}:
        return await list_canonical_agent_run_tool_calls(db, run)
    return [
        tool_call_to_response(call)
        for call in await agent_repository.list_agent_tool_calls(db, run_id)
    ]


async def resolve_external_agent_tool_approval(
    db: AsyncSession,
    agent_id: str,
    run_id: str,
    call_id: str,
    access_source: ExternalAccessSource,
    user: User,
    settings: Settings,
    *,
    approve: bool,
) -> ExternalAgentRunResponse:
    run = await get_external_agent_run(db, agent_id, run_id, access_source, user.id)
    run = await resolve_agent_run_tool_approval(
        db,
        run,
        call_id,
        user,
        settings,
        approve=approve,
    )
    return external_run_to_response(run)


async def list_external_agent_runs(
    db: AsyncSession,
    agent_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
    limit: int,
    offset: int,
    conversation_id: str | None = None,
) -> ExternalAgentRunListResponse:
    """
    List the latest external runs for a published agent.
    
    Parameters:
        access_source (ExternalAccessSource): Source through which the runs were accessed.
        consumer_id (str): Consumer identity whose runs should be listed.
        conversation_id (str | None): Optional conversation used to filter the runs.
    
    Returns:
        ExternalAgentRunListResponse: Paginated external runs and their total count.
    """
    await get_published_agent_context(db, agent_id)
    runs = await agent_repository.list_agent_runs(
        db,
        agent_id,
        access_source,
        consumer_id,
        limit,
        offset,
        conversation_id=conversation_id,
        latest_versions_only=True,
    )
    total = await agent_repository.count_agent_runs(
        db,
        agent_id,
        access_source=access_source,
        consumer_id=consumer_id,
        conversation_id=conversation_id,
        latest_versions_only=True,
    )
    return ExternalAgentRunListResponse(
        items=[external_run_to_response(run) for run in runs],
        total=total,
        offset=offset,
        limit=limit,
    )


async def list_public_agent_conversations(
    db: AsyncSession,
    agent_id: str,
    consumer_id: str,
) -> PublicAgentConversationListResponse:
    await get_published_agent_context(db, agent_id)
    rows = await agent_repository.list_consumer_conversations(
        db, agent_id, "public", consumer_id
    )
    return PublicAgentConversationListResponse(
        items=[
            PublicAgentConversationResponse(
                conversation_id=row.conversation_id,
                question=row.goal,
                status=row.status,
                result=clean_model_text(str(row.result or "")),
                run_count=row.run_count,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
    )


async def delete_public_agent_conversation(
    db: AsyncSession,
    agent_id: str,
    consumer_id: str,
    conversation_id: str,
) -> None:
    await get_published_agent_context(db, agent_id)
    deleted, active = await agent_repository.delete_consumer_conversation(
        db, agent_id, "public", consumer_id, conversation_id
    )
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete a conversation while it is running.",
        )
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    await db.commit()


async def stream_external_agent_run(
    db: AsyncSession,
    context: PublishedAgentContext,
    run: AgentRun,
    settings: Settings,
    *,
    after: int = 0,
    live_after: str = "0-0",
) -> AsyncIterator[dict[str, Any]]:
    async for event in sanitize_external_agent_stream(
        stream_agent_run(
            db,
            run,
            None,
            context.publisher,
            context.workspace.membership_role,
            settings,
            after=after,
            live_after=live_after,
        )
    ):
        yield event


async def _consumer_display_names(
    db: AsyncSession,
    rows: list[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    api_ids = [consumer_id for source, consumer_id in rows if source == "api"]
    user_ids = [
        consumer_id
        for source, consumer_id in rows
        if source in {"console", "public"}
    ]
    api_names = {
        credential.id: credential.name
        for credential in await agent_repository.list_agent_api_credentials_by_ids(
            db, api_ids
        )
    }
    user_names = {
        user.id: (user.name or user.username)
        for user in await user_repository.list_users_by_ids(db, user_ids)
    }
    names: dict[tuple[str, str], str] = {}
    for source, consumer_id in rows:
        if source == "public":
            user_name = user_names.get(consumer_id)
            names[(source, consumer_id)] = user_name or f"Visitor {consumer_id[:8]}"
        elif source == "api":
            credential_name = api_names.get(consumer_id)
            names[(source, consumer_id)] = (
                f"API Key: {credential_name}"
                if credential_name is not None
                else "API Key"
            )
        else:
            user_name = user_names.get(consumer_id)
            names[(source, consumer_id)] = user_name or "Former user"
    return names


async def list_agent_logs(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int,
    offset: int,
) -> AgentLogListResponse:
    """
    List paginated execution logs for an agent.
    
    Parameters:
        workspace_id (str): Workspace containing the agent.
        agent_id (str): Agent whose logs are requested.
        actor (User): User requesting the logs.
        workspace_role (str | None): Actor's role in the workspace.
    
    Returns:
        AgentLogListResponse: Paginated agent logs with execution details, consumer display names, feedback, and total count.
    """
    agent = await get_agent(db, workspace_id, agent_id)
    require_agent_edit(agent, actor, workspace_role)
    runs = await agent_repository.list_agent_runs_for_management(
        db, workspace_id, agent_id, limit, offset
    )
    total = await agent_repository.count_agent_runs(db, agent_id)
    display_names = await _consumer_display_names(
        db,
        [
            (run.access_source, run.consumer_id)
            for run in runs
        ],
    )
    items = []
    for run in runs:
        display_name = display_names[(run.access_source, run.consumer_id)]
        items.append(
            AgentLogResponse(
                id=run.id,
                conversation_id=run.conversation_id,
                access_source=run.access_source,
                consumer_id=run.consumer_id,
                display_name=display_name,
                requested_by_user_id=run.requested_by_user_id,
                execution_user_id=run.execution_user_id,
                question=run.goal,
                status=run.status,
                result=clean_model_text(str(run.result or "")),
                last_error=run.last_error,
                model_usage=run.model_usage,
                feedback=run.feedback,
                feedback_updated_at=run.feedback_updated_at,
                created_at=run.created_at,
                started_at=run.started_at,
                finished_at=run.finished_at,
                updated_at=run.updated_at,
            )
        )
    return AgentLogListResponse(items=items, total=total, offset=offset, limit=limit)


async def list_agent_conversation_users(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int,
    offset: int,
) -> AgentConversationUserListResponse:
    agent = await get_agent(db, workspace_id, agent_id)
    require_agent_edit(agent, actor, workspace_role)
    rows, total = await agent_repository.list_agent_consumer_stats(
        db, workspace_id, agent_id, limit, offset
    )
    display_names = await _consumer_display_names(
        db,
        [
            (row.access_source, row.consumer_id)
            for row in rows
        ],
    )
    items = [
        AgentConversationUserResponse(
            consumer_id=row.consumer_id,
            access_source=row.access_source,
            display_name=display_names[(row.access_source, row.consumer_id)],
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            conversation_count=row.conversation_count,
            run_count=row.run_count,
        )
        for row in rows
    ]
    return AgentConversationUserListResponse(
        items=items, total=total, offset=offset, limit=limit
    )


def _usage_total_tokens(usage: dict[str, Any] | None) -> int:
    value = (usage or {}).get("total_tokens", 0)
    return value if isinstance(value, int) and value > 0 else 0


async def get_agent_monitoring(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    days: int,
) -> AgentMonitoringResponse:
    if days not in {7, 30, 90}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Monitoring days must be 7, 30, or 90.",
        )
    agent = await get_agent(db, workspace_id, agent_id)
    require_agent_edit(agent, actor, workspace_role)
    today = utc_now().astimezone(APP_TIMEZONE).date()
    first_day = today - timedelta(days=days - 1)
    since = datetime.combine(
        first_day, time.min, tzinfo=APP_TIMEZONE
    ).astimezone(UTC)
    rows = await agent_repository.list_agent_monitoring_rows(
        db, workspace_id, agent_id, since
    )
    daily_values: dict[Any, dict[str, Any]] = {
        first_day + timedelta(days=index): {
            "users": set(),
            "conversations": set(),
            "runs": 0,
            "succeeded": 0,
            "failed": 0,
            "total_tokens": 0,
        }
        for index in range(days)
    }
    all_users: set[tuple[str, str]] = set()
    all_conversations: set[tuple[str, str, str]] = set()
    succeeded = failed = total_tokens = 0
    for row in rows:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        day = created_at.astimezone(APP_TIMEZONE).date()
        if day not in daily_values:
            continue
        user_key = (row.access_source, row.consumer_id)
        conversation_key = (*user_key, row.conversation_id)
        values = daily_values[day]
        values["users"].add(user_key)
        values["conversations"].add(conversation_key)
        values["runs"] += 1
        all_users.add(user_key)
        all_conversations.add(conversation_key)
        if row.status == "succeeded":
            succeeded += 1
            values["succeeded"] += 1
        elif row.status == "failed":
            failed += 1
            values["failed"] += 1
        tokens = _usage_total_tokens(row.model_usage)
        total_tokens += tokens
        values["total_tokens"] += tokens
    daily = [
        AgentMonitoringDailyResponse(
            date=day,
            active_users=len(values["users"]),
            conversations=len(values["conversations"]),
            runs=values["runs"],
            succeeded=values["succeeded"],
            failed=values["failed"],
            total_tokens=values["total_tokens"],
        )
        for day, values in daily_values.items()
    ]
    return AgentMonitoringResponse(
        days=days,
        summary=AgentMonitoringValues(
            active_users=len(all_users),
            conversations=len(all_conversations),
            runs=len(rows),
            succeeded=succeeded,
            failed=failed,
            total_tokens=total_tokens,
        ),
        daily=daily,
    )

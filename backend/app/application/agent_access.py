from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
import hashlib
import json
import secrets
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent_runs import (
    enqueue_prepared_agent_run,
    prepare_agent_run,
    stream_agent_run,
)
from app.application.workspace import WorkspaceContext, build_workspace_context
from app.entities.agents import Agent, AgentApiCredential, AgentRun
from app.entities.user import User
from app.infrastructure.agent_rate_limit import (
    AgentRateLimitExceeded,
    AgentRateLimitUnavailable,
    enforce_external_agent_rate_limit,
)
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
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
    ExternalAgentKnowledgeHitResponse,
    ExternalAgentProgressEventResponse,
    ExternalAgentRunListResponse,
    ExternalAgentRunResponse,
    PublicAgentConversationListResponse,
    PublicAgentConversationResponse,
    PublicAgentProfileResponse,
)
from app.shareddomain.agents.services import (
    ACTIVE_STATUS,
    get_agent,
    require_agent_edit,
)
from app.shareddomain.audit.services import record_audit_log

ExternalAccessSource = Literal["public", "api"]


@dataclass(frozen=True)
class PublishedAgentContext:
    agent: Agent
    publisher: User
    workspace: WorkspaceContext


def hash_agent_access_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_agent_consumer_id(agent_id: str, session_token: str) -> str:
    return hash_agent_access_token(f"{agent_id}:{session_token}")


def create_public_agent_session_token() -> str:
    return secrets.token_urlsafe(48)


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


TOOL_PAYLOAD_MAX_STRING = 500
TOOL_PAYLOAD_MAX_DEPTH = 4
TOOL_PAYLOAD_MAX_ITEMS = 25
TOOL_PAYLOAD_MAX_SERIALIZED = 4000
TOOL_PAYLOAD_ELLIPSIS = "…"


def _limit_tool_payload(value: object, depth: int) -> tuple[object, bool]:
    """递归限制工具载荷，返回 (受限副本, 是否截断)。"""
    if depth >= TOOL_PAYLOAD_MAX_DEPTH:
        return TOOL_PAYLOAD_ELLIPSIS, True
    if isinstance(value, dict):
        truncated = False
        items = list(value.items())
        if len(items) > TOOL_PAYLOAD_MAX_ITEMS:
            items = items[:TOOL_PAYLOAD_MAX_ITEMS]
            truncated = True
        limited: dict[str, object] = {}
        for key, item in items:
            safe_key = key if isinstance(key, str) else str(key)
            if len(safe_key) > TOOL_PAYLOAD_MAX_STRING:
                safe_key = safe_key[:TOOL_PAYLOAD_MAX_STRING] + TOOL_PAYLOAD_ELLIPSIS
                truncated = True
            limited[safe_key], item_truncated = _limit_tool_payload(
                item, depth + 1
            )
            truncated = truncated or item_truncated
        return limited, truncated
    if isinstance(value, list):
        truncated = len(value) > TOOL_PAYLOAD_MAX_ITEMS
        items = value[:TOOL_PAYLOAD_MAX_ITEMS]
        limited: list[object] = []
        for item in items:
            limited_item, item_truncated = _limit_tool_payload(item, depth + 1)
            limited.append(limited_item)
            truncated = truncated or item_truncated
        return limited, truncated
    if isinstance(value, str):
        if len(value) > TOOL_PAYLOAD_MAX_STRING:
            return value[:TOOL_PAYLOAD_MAX_STRING] + TOOL_PAYLOAD_ELLIPSIS, True
        return value, False
    if value is None or isinstance(value, (bool, int, float)):
        return value, False
    text = str(value)
    if len(text) > TOOL_PAYLOAD_MAX_STRING:
        return text[:TOOL_PAYLOAD_MAX_STRING] + TOOL_PAYLOAD_ELLIPSIS, True
    return text, False


def _bounded_tool_payload(value: object) -> tuple[object, bool]:
    """限制工具 input/output 载荷，保证序列化大小有界。"""
    limited, truncated = _limit_tool_payload(value, 0)
    serialized = json.dumps(limited, ensure_ascii=False, default=str)
    if len(serialized) > TOOL_PAYLOAD_MAX_SERIALIZED:
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
        turn = max(0, int(event.get("turn") or 0))
        summary = str(event.get("summary") or "")

        if event_type == "thought":
            if summary == "agent.answer_ready":
                answer_status: Literal["running", "succeeded", "failed"] = (
                    "succeeded" if run_status == "succeeded" else "running"
                )
                if run_status == "failed":
                    answer_status = "failed"
                upsert(
                    ExternalAgentProgressEventResponse(
                        id=_external_progress_id(event, "answer"),
                        type="answer",
                        status=answer_status,
                        stage=answer_status,
                        turn=turn,
                        reasoning=str(event.get("reasoning") or ""),
                    )
                )
            elif summary in {
                "agent.analyzing",
                "agent.reviewing_tool_results",
                "agent.tools_selected",
            }:
                stage = {
                    "agent.analyzing": "analyzing",
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
        bounded_input, input_truncated = _bounded_tool_payload(
            raw_input if isinstance(raw_input, dict) else {}
        )
        bounded_output, output_truncated = _bounded_tool_payload(
            event.get("output")
        )
        upsert(
            ExternalAgentProgressEventResponse(
                id=_external_progress_id(event, "tool"),
                type=progress_type,
                status=event_status,
                stage=event_status,
                turn=turn,
                count=count,
                tool_name=str(event.get("tool_name") or ""),
                tool_label=str(event.get("tool_label") or ""),
                tool_kind=tool_kind,
                server_name=str(event.get("server_name") or ""),
                input=bounded_input,
                output=bounded_output,
                input_truncated=input_truncated,
                output_truncated=output_truncated,
                hits=hits,
            )
        )
    return progress


def external_run_to_response(run: AgentRun | dict[str, Any]) -> ExternalAgentRunResponse:
    value = run if isinstance(run, dict) else vars(run)
    run_status = str(value.get("status") or "")
    generic_error = None
    if run_status == "failed":
        generic_error = "Agent run failed."
    elif run_status == "cancelled":
        generic_error = "Agent run was cancelled."
    return ExternalAgentRunResponse(
        id=str(value["id"]),
        conversation_id=str(value["conversation_id"]),
        question=str(value.get("goal") or value.get("question") or ""),
        status=run_status,
        result=str(value.get("result") or ""),
        error=generic_error,
        progress=external_progress_events(value.get("events") or [], run_status),
        created_at=value["created_at"],
        started_at=value.get("started_at"),
        finished_at=value.get("finished_at"),
        updated_at=value["updated_at"],
    )


async def sanitize_external_agent_stream(
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    async for event in events:
        event_type = event.get("type")
        if event_type == "answer_delta":
            sanitized = {
                "type": "answer_delta",
                "delta": str(event.get("delta") or ""),
            }
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
        elif event_type == "process" and isinstance(event.get("event"), dict):
            for progress_event in external_progress_events(
                [event["event"]], "running"
            ):
                sanitized = {
                    "type": "progress",
                    "event": progress_event.model_dump(mode="json"),
                }
                _copy_external_stream_metadata(event, sanitized)
                yield sanitized
        elif event_type in {"run", "complete", "error"} and isinstance(
            event.get("run"), dict
        ):
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
    agent = await agent_repository.get_agent_by_id(db, agent_id)
    if (
        agent is None
        or agent.status != ACTIVE_STATUS
        or not agent.published
        or not agent.published_by_user_id
        or agent.published_at is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
    publisher = await user_repository.get_user_by_id(db, agent.published_by_user_id)
    if publisher is None or not publisher.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
    try:
        workspace = await build_workspace_context(db, publisher, agent.workspace_id)
    except HTTPException as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Published agent not found.",
        ) from exc
    return PublishedAgentContext(agent=agent, publisher=publisher, workspace=workspace)


async def get_public_agent_profile(
    db: AsyncSession,
    agent_id: str,
) -> PublicAgentProfileResponse:
    context = await get_published_agent_context(db, agent_id)
    return PublicAgentProfileResponse(
        id=context.agent.id,
        name=context.agent.name,
        description=context.agent.description,
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
) -> tuple[PublishedAgentContext, AgentApiCredential]:
    if not token.startswith("nxf_"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API credential.")
    credential = await agent_repository.get_agent_api_credential_by_hash(
        db, hash_agent_access_token(token)
    )
    if credential is None or credential.agent_id != agent_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API credential.")
    try:
        context = await get_published_agent_context(db, agent_id)
    except HTTPException as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.") from exc
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
) -> ExternalAgentRunResponse:
    await _enforce_rate_limit(settings, context.agent.id, access_source, consumer_id)
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
    )
    await enqueue_prepared_agent_run(run.id, settings)
    current = await agent_repository.refresh_agent_run(db, run)
    return external_run_to_response(current)


async def get_external_agent_run(
    db: AsyncSession,
    agent_id: str,
    run_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
) -> AgentRun:
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


async def list_external_agent_runs(
    db: AsyncSession,
    agent_id: str,
    access_source: ExternalAccessSource,
    consumer_id: str,
    limit: int,
    offset: int,
    conversation_id: str | None = None,
) -> ExternalAgentRunListResponse:
    await get_published_agent_context(db, agent_id)
    runs = await agent_repository.list_agent_runs(
        db,
        agent_id,
        access_source,
        consumer_id,
        limit,
        offset,
        conversation_id=conversation_id,
    )
    total = await agent_repository.count_agent_runs(
        db,
        agent_id,
        access_source=access_source,
        consumer_id=consumer_id,
        conversation_id=conversation_id,
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
                result=row.result,
                run_count=row.run_count,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
    )


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
    user_ids = [consumer_id for source, consumer_id in rows if source == "user"]
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
            names[(source, consumer_id)] = f"Visitor {consumer_id[:8]}"
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
            if run.access_source != "public"
        ],
    )
    items = []
    for run in runs:
        display_name = (
            f"Visitor {run.consumer_id[:8]}"
            if run.access_source == "public"
            else display_names[(run.access_source, run.consumer_id)]
        )
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
                result=run.result,
                last_error=run.last_error,
                model_usage=run.model_usage,
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
            if row.access_source != "public"
        ],
    )
    items = [
        AgentConversationUserResponse(
            consumer_id=row.consumer_id,
            access_source=row.access_source,
            display_name=(
                f"Visitor {row.consumer_id[:8]}"
                if row.access_source == "public"
                else display_names[(row.access_source, row.consumer_id)]
            ),
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
    today = utc_now().date()
    first_day = today - timedelta(days=days - 1)
    since = datetime.combine(first_day, time.min, tzinfo=UTC)
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
        day = row.created_at.date()
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

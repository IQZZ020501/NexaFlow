"""Application use cases for automations, webhooks, and execution control."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agents import (
    ACTIVE_STATUS,
    cancel_agent_run,
    enqueue_prepared_agent_run,
    get_agent,
    get_agent_model,
    get_agent_run_entity,
    list_agent_run_tool_calls,
    prepare_agent_run,
    run_to_response,
)
from app.application.agents import (
    resolve_agent_tool_approval as resolve_workspace_agent_tool_approval,
)
from app.application.artifacts.service import list_authorized_run_artifacts
from app.application.workflows.definitions.service import (
    cancel_workflow_run,
    prepare_workflow_run,
    resolve_workflow_tool_approval,
    submit_workflow_form,
    workflow_run_response,
)
from app.application.workspaces.service import build_workspace_context
from app.domain.agents.access.permissions import require_agent_view
from app.domain.agents.models import agent_run_display_status
from app.domain.agents.service import agent_publication_from_version
from app.domain.audit.services import record_audit_log
from app.domain.automations import (
    AUTOMATION_STATUS_ACTIVE,
    AUTOMATION_STATUS_COMPLETED,
    AUTOMATION_STATUS_PAUSED,
    DEFAULT_WEBHOOK_MAX_PENDING,
    EXECUTION_DISPATCH_DISPATCHED,
    EXECUTION_DISPATCH_PENDING,
    EXECUTION_DISPATCH_QUEUED,
    EXECUTION_DISPATCH_REJECTED,
    EXECUTION_DISPATCH_SKIPPED,
    MAX_WEBHOOK_PAYLOAD_BYTES,
    build_execution_input_snapshot,
    canonical_payload_hash,
    compute_next_schedule_at,
    extract_run_goal_and_extra_inputs,
    generate_webhook_secret,
    validate_input_config,
    validate_trigger_config,
    verify_webhook_signature,
)
from app.entities.automations import Automation, AutomationExecution
from app.entities.defaults import new_id, utc_now
from app.entities.identity.user import User
from app.infra.config.settings import Settings
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.repositories.automations import repository as automation_repository
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.repositories.workflows import repository as workflow_repository
from app.infra.db.repositories.workspaces import repository as workspace_repository
from app.infra.db.session import get_session_factory
from app.infra.security.agent_rate_limit import (
    WebhookRateLimitExceeded,
    WebhookRateLimitUnavailable,
    enforce_webhook_rate_limit,
)
from app.infra.security.keyring import application_secret_key
from app.infra.security.secrets import decrypt_secret, encrypt_secret
from app.schemas.automations import (
    AutomationArtifactLinkResponse,
    AutomationCreateRequest,
    AutomationCreateResponse,
    AutomationExecutionDetailResponse,
    AutomationExecutionListResponse,
    AutomationExecutionSummaryResponse,
    AutomationInputConfig,
    AutomationListResponse,
    AutomationNotificationPreferences,
    AutomationResponse,
    AutomationUpdateRequest,
    AutomationWebhookReceiptResponse,
    AutomationWebhookSecretRotateResponse,
)
from app.schemas.workflows.contracts import (
    WorkflowFormSubmitRequest,
    WorkflowRunCreateRequest,
)

logger = logging.getLogger(__name__)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _webhook_url(hook_id: str | None) -> str | None:
    return f"/api/v1/hooks/automations/{hook_id}" if hook_id else None


def _secret_hint(secret: str) -> str:
    return f"{secret[:10]}...{secret[-4:]}"


def _execution_to_summary(
    execution: AutomationExecution,
    *,
    run: Any | None = None,
) -> AutomationExecutionSummaryResponse:
    run_status = (
        agent_run_display_status(run.status)
        if run is not None
        else (
            "cancelled" if execution.last_reconciled_run_status == "cancelled" else None
        )
    )
    return AutomationExecutionSummaryResponse(
        id=execution.id,
        automation_id=execution.automation_id,
        workspace_id=execution.workspace_id,
        trigger_source=execution.trigger_source,  # type: ignore[arg-type]
        dedup_key=execution.dedup_key,
        config_revision=execution.config_revision,
        scheduled_at=execution.scheduled_at,
        received_at=execution.received_at,
        dispatched_at=execution.dispatched_at,
        dispatch_status=execution.dispatch_status,  # type: ignore[arg-type]
        skip_reason=execution.skip_reason,
        run_id=execution.run_id,
        run_status=run_status,
        missed_count_before=execution.missed_count_before,
        created_at=execution.created_at,
        updated_at=execution.updated_at,
    )


def _automation_to_response(
    automation: Automation,
    *,
    target_app_name: str,
    latest_execution: AutomationExecutionSummaryResponse | None = None,
) -> AutomationResponse:
    return AutomationResponse(
        id=automation.id,
        workspace_id=automation.workspace_id,
        owner_user_id=automation.owner_user_id,
        name=automation.name,
        description=automation.description,
        target_app_id=automation.target_app_id,
        target_app_name=target_app_name,
        target_app_type=automation.target_app_type,  # type: ignore[arg-type]
        publication_version_id=automation.publication_version_id,
        workflow_version_id=automation.workflow_version_id,
        target_version_number=automation.target_version_number,
        approval_mode=automation.approval_mode,  # type: ignore[arg-type]
        trigger_type=automation.trigger_type,  # type: ignore[arg-type]
        trigger_config=dict(automation.trigger_config or {}),
        input_config=AutomationInputConfig.model_validate(
            automation.input_config or {}
        ),
        notification_config=AutomationNotificationPreferences.model_validate(
            automation.notification_config or {}
        ),
        webhook_hook_id=automation.webhook_hook_id,
        webhook_url=_webhook_url(automation.webhook_hook_id),
        webhook_secret_hint=automation.webhook_secret_hint,
        webhook_secret_updated_at=automation.webhook_secret_updated_at,
        status=automation.status,  # type: ignore[arg-type]
        config_revision=automation.config_revision,
        next_run_at=automation.next_run_at,
        last_triggered_at=automation.last_triggered_at,
        missed_run_count=automation.missed_run_count,
        latest_execution=latest_execution,
        created_at=automation.created_at,
        updated_at=automation.updated_at,
    )


async def _load_owned_automation(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    actor: User,
    *,
    lock: bool = False,
) -> Automation:
    automation = await automation_repository.get_workspace_automation(
        db,
        workspace_id,
        automation_id,
        lock=lock,
    )
    if automation is None or automation.owner_user_id != actor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automation not found.")
    return automation


async def _resolve_published_target_binding(
    db: AsyncSession,
    workspace_id: str,
    target_app_id: str,
    actor: User,
    *,
    publication_version_id: str | None = None,
    workflow_version_id: str | None = None,
) -> tuple[Any, str | None, str | None, int, User, str | None]:
    """Validate and resolve explicit published Agent or Workflow version binding."""
    agent = await get_agent(db, workspace_id, target_app_id)
    await require_agent_view(db, agent, actor)
    if agent.status != ACTIVE_STATUS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Target application must be active.",
        )
    if (
        not agent.published
        or not agent.published_by_user_id
        or agent.published_at is None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Target application must be published before binding an automation.",
        )

    if agent.app_type == "agent":
        if workflow_version_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "workflow_version_id cannot be specified for an Agent target.",
            )
        selected_version_id = (
            publication_version_id or agent.current_published_version_id
        )
        if not selected_version_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Published agent version is missing.",
            )
        pub_version = await agent_repository.get_agent_publication_version(
            db, workspace_id, selected_version_id
        )
        if pub_version is None or pub_version.agent_id != agent.id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Published agent version not found.",
            )
        try:
            publication = agent_publication_from_version(pub_version)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Published agent version snapshot is invalid.",
            ) from exc
        publisher = await user_repository.get_user_by_id(
            db, pub_version.published_by_user_id
        )
        if publisher is None or not publisher.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Application publisher is inactive.",
            )
        pub_ctx = await build_workspace_context(db, publisher, workspace_id)
        await require_agent_view(db, agent, publisher)
        await get_agent_model(
            db,
            workspace_id,
            publication.model_id,
            user_id=None,
        )
        return (
            agent,
            pub_version.id,
            None,
            pub_version.version_number,
            publisher,
            pub_ctx.membership_role,
        )

    if agent.app_type == "workflow":
        if publication_version_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "publication_version_id cannot be specified for a Workflow target.",
            )
        versions = await workflow_repository.list_versions(db, workspace_id, agent.id)
        if not versions:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Workflow must be published before binding an automation.",
            )
        if workflow_version_id is not None:
            wf_version = next(
                (item for item in versions if item.id == workflow_version_id),
                None,
            )
            if wf_version is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    "Published workflow version not found.",
                )
        else:
            wf_version = versions[0]
        publisher = await user_repository.get_user_by_id(db, agent.published_by_user_id)
        if publisher is None or not publisher.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Application publisher is inactive.",
            )
        pub_ctx = await build_workspace_context(db, publisher, workspace_id)
        await require_agent_view(db, agent, publisher)
        model_id = wf_version.default_model_id or agent.model_id
        await get_agent_model(db, workspace_id, model_id, user_id=None)
        return (
            agent,
            None,
            wf_version.id,
            wf_version.version_number,
            publisher,
            pub_ctx.membership_role,
        )

    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Only Agent and Workflow applications support automations.",
    )


def _normalize_configs(
    *,
    trigger_type: str,
    raw_trigger_config: dict[str, Any],
    raw_input_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        trigger_config = validate_trigger_config(trigger_type, raw_trigger_config)
        input_config = validate_input_config(raw_input_config)
        if trigger_type != "webhook":
            build_execution_input_snapshot(input_config)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(exc),
        ) from exc
    return trigger_config, input_config


async def _latest_run_map(
    db: AsyncSession,
    executions: list[AutomationExecution],
) -> dict[str, Any]:
    run_ids = [item.run_id for item in executions if item.run_id is not None]
    if not run_ids:
        return {}
    result: dict[str, Any] = {}
    for run_id in dict.fromkeys(run_ids):
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        if run is not None:
            result[run_id] = run
    return result


async def create_automation(
    db: AsyncSession,
    workspace_id: str,
    payload: AutomationCreateRequest,
    actor: User,
    settings: Settings,
) -> AutomationCreateResponse:
    (
        agent,
        pub_ver_id,
        wf_ver_id,
        version_number,
        _pub,
        _role,
    ) = await _resolve_published_target_binding(
        db,
        workspace_id,
        payload.target_app_id,
        actor,
        publication_version_id=payload.publication_version_id,
        workflow_version_id=payload.workflow_version_id,
    )
    trigger_config, input_config = _normalize_configs(
        trigger_type=payload.trigger_type,
        raw_trigger_config=payload.trigger_config,
        raw_input_config=payload.input_config.model_dump(),
    )
    now = utc_now()
    next_run_at = compute_next_schedule_at(
        payload.trigger_type,
        trigger_config,
        after_utc=now,
        inclusive=True,
    )
    if payload.trigger_type == "once" and next_run_at is None:
        raw_run_at = trigger_config["run_at"]
        parsed = datetime.fromisoformat(raw_run_at)
        next_run_at = _as_utc(parsed)

    webhook_hook_id: str | None = None
    webhook_secret: str | None = None
    webhook_secret_ciphertext: str | None = None
    webhook_secret_hint: str | None = None
    webhook_secret_updated_at: datetime | None = None
    if payload.trigger_type == "webhook":
        webhook_hook_id = new_id()
        webhook_secret = generate_webhook_secret()
        webhook_secret_ciphertext = encrypt_secret(
            webhook_secret, application_secret_key(settings)
        )
        webhook_secret_hint = _secret_hint(webhook_secret)
        webhook_secret_updated_at = now

    automation = Automation(
        workspace_id=workspace_id,
        owner_user_id=actor.id,
        name=payload.name,
        description=payload.description.strip(),
        target_app_id=agent.id,
        target_app_type=agent.app_type,
        publication_version_id=pub_ver_id,
        workflow_version_id=wf_ver_id,
        target_version_number=version_number,
        approval_mode=payload.approval_mode,
        trigger_type=payload.trigger_type,
        trigger_config=trigger_config,
        input_config=input_config,
        notification_config=payload.notification_config.model_dump(),
        webhook_hook_id=webhook_hook_id,
        webhook_secret_ciphertext=webhook_secret_ciphertext,
        webhook_secret_hint=webhook_secret_hint,
        webhook_secret_updated_at=webhook_secret_updated_at,
        status=AUTOMATION_STATUS_ACTIVE,
        config_revision=1,
        next_run_at=next_run_at,
        created_at=now,
        updated_at=now,
    )
    automation = await automation_repository.create_automation(db, automation)
    record_audit_log(
        db,
        actor,
        "automation.create",
        "automation",
        automation.id,
        automation.name,
        {
            "target_app_id": automation.target_app_id,
            "target_app_type": automation.target_app_type,
            "target_version_number": automation.target_version_number,
            "trigger_type": automation.trigger_type,
        },
        workspace_id=workspace_id,
    )
    await db.commit()
    base = _automation_to_response(automation, target_app_name=agent.name)
    return AutomationCreateResponse(
        **base.model_dump(),
        webhook_secret=webhook_secret,
    )


async def list_automations(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    *,
    target_app_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AutomationListResponse:
    items, total = await automation_repository.list_automations_for_owner(
        db,
        workspace_id,
        actor.id,
        target_app_id=target_app_id,
        limit=limit,
        offset=offset,
    )
    latest_map = await automation_repository.list_latest_executions_by_automation_ids(
        db,
        [item.id for item in items],
    )
    runs_map = await _latest_run_map(db, list(latest_map.values()))
    app_names = await agent_repository.list_agent_names_by_ids(
        db, [item.target_app_id for item in items]
    )

    responses: list[AutomationResponse] = []
    for item in items:
        latest = latest_map.get(item.id)
        latest_summary = (
            _execution_to_summary(
                latest,
                run=runs_map.get(latest.run_id) if latest.run_id else None,
            )
            if latest is not None
            else None
        )
        responses.append(
            _automation_to_response(
                item,
                target_app_name=app_names.get(item.target_app_id, item.target_app_id),
                latest_execution=latest_summary,
            )
        )
    return AutomationListResponse(
        items=responses,
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_automation_detail(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    actor: User,
) -> AutomationResponse:
    automation = await _load_owned_automation(db, workspace_id, automation_id, actor)
    agent = await agent_repository.get_agent_by_id(db, automation.target_app_id)
    latest_map = await automation_repository.list_latest_executions_by_automation_ids(
        db,
        [automation.id],
    )
    latest = latest_map.get(automation.id)
    run = (
        await agent_repository.get_agent_run_by_id(db, latest.run_id)
        if latest and latest.run_id
        else None
    )
    return _automation_to_response(
        automation,
        target_app_name=agent.name if agent is not None else automation.target_app_id,
        latest_execution=_execution_to_summary(latest, run=run)
        if latest is not None
        else None,
    )


async def update_automation(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    payload: AutomationUpdateRequest,
    actor: User,
    settings: Settings,
) -> AutomationResponse:
    automation = await _load_owned_automation(
        db, workspace_id, automation_id, actor, lock=True
    )
    now = utc_now()
    revision_bumped = False
    schedule_changed = False

    if payload.name is not None:
        automation.name = payload.name
    if payload.description is not None:
        automation.description = payload.description.strip()
    if (
        payload.approval_mode is not None
        and payload.approval_mode != automation.approval_mode
    ):
        automation.approval_mode = payload.approval_mode
        revision_bumped = True
    if payload.notification_config is not None:
        automation.notification_config = payload.notification_config.model_dump()

    if (
        payload.publication_version_id is not None
        or payload.workflow_version_id is not None
    ):
        (
            agent,
            pub_ver_id,
            wf_ver_id,
            version_number,
            _pub,
            _role,
        ) = await _resolve_published_target_binding(
            db,
            workspace_id,
            automation.target_app_id,
            actor,
            publication_version_id=payload.publication_version_id,
            workflow_version_id=payload.workflow_version_id,
        )
        if (
            pub_ver_id != automation.publication_version_id
            or wf_ver_id != automation.workflow_version_id
        ):
            automation.publication_version_id = pub_ver_id
            automation.workflow_version_id = wf_ver_id
            automation.target_version_number = version_number
            revision_bumped = True
    else:
        agent = await agent_repository.get_agent_by_id(db, automation.target_app_id)

    next_trigger_type = payload.trigger_type or automation.trigger_type
    next_trigger_config = (
        payload.trigger_config
        if payload.trigger_config is not None
        else automation.trigger_config
    )
    next_input_config = (
        payload.input_config.model_dump()
        if payload.input_config is not None
        else automation.input_config
    )
    trigger_config, input_config = _normalize_configs(
        trigger_type=next_trigger_type,
        raw_trigger_config=next_trigger_config,
        raw_input_config=next_input_config,
    )
    schedule_changed = (
        next_trigger_type != automation.trigger_type
        or trigger_config != automation.trigger_config
    )
    if schedule_changed or input_config != automation.input_config:
        revision_bumped = True

    if next_trigger_type == "webhook" and not automation.webhook_hook_id:
        raw_secret = generate_webhook_secret()
        automation.webhook_hook_id = new_id()
        automation.webhook_secret_ciphertext = encrypt_secret(
            raw_secret, application_secret_key(settings)
        )
        automation.webhook_secret_hint = _secret_hint(raw_secret)
        automation.webhook_secret_updated_at = now

    automation.trigger_type = next_trigger_type
    automation.trigger_config = trigger_config
    automation.input_config = input_config
    if revision_bumped:
        automation.config_revision += 1

    if automation.trigger_type == "webhook":
        automation.next_run_at = None
        if automation.status == AUTOMATION_STATUS_COMPLETED:
            automation.status = AUTOMATION_STATUS_ACTIVE
    elif automation.status == AUTOMATION_STATUS_PAUSED:
        automation.next_run_at = None
    elif schedule_changed:
        scheduled = compute_next_schedule_at(
            automation.trigger_type,
            automation.trigger_config,
            after_utc=now,
            inclusive=True,
        )
        if automation.trigger_type == "once" and payload.trigger_config is not None:
            parsed = _as_utc(
                datetime.fromisoformat(automation.trigger_config["run_at"])
            )
            scheduled = parsed
            automation.status = AUTOMATION_STATUS_ACTIVE
        automation.next_run_at = scheduled
        automation.status = AUTOMATION_STATUS_ACTIVE

    automation.updated_at = now
    automation = await automation_repository.save_automation(db, automation)
    record_audit_log(
        db,
        actor,
        "automation.update",
        "automation",
        automation.id,
        automation.name,
        {"config_revision": automation.config_revision},
        workspace_id=workspace_id,
    )
    await db.commit()
    return _automation_to_response(
        automation,
        target_app_name=agent.name if agent is not None else automation.target_app_id,
    )


async def pause_automation(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    actor: User,
) -> AutomationResponse:
    automation = await _load_owned_automation(
        db, workspace_id, automation_id, actor, lock=True
    )
    if automation.status == AUTOMATION_STATUS_COMPLETED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Completed one-time automation cannot be paused.",
        )
    if automation.status != AUTOMATION_STATUS_PAUSED:
        automation.status = AUTOMATION_STATUS_PAUSED
        automation.next_run_at = None
        automation.updated_at = utc_now()
        automation = await automation_repository.save_automation(db, automation)
        record_audit_log(
            db,
            actor,
            "automation.pause",
            "automation",
            automation.id,
            automation.name,
            {},
            workspace_id=workspace_id,
        )
        await db.commit()
    return await get_automation_detail(db, workspace_id, automation_id, actor)


async def resume_automation(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    actor: User,
    settings: Settings,
) -> AutomationResponse:
    automation = await _load_owned_automation(
        db, workspace_id, automation_id, actor, lock=True
    )
    if automation.status == AUTOMATION_STATUS_COMPLETED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Completed one-time automation cannot be resumed without rescheduling.",
        )
    await _resolve_published_target_binding(
        db,
        workspace_id,
        automation.target_app_id,
        actor,
        publication_version_id=automation.publication_version_id,
        workflow_version_id=automation.workflow_version_id,
    )
    now = utc_now()
    if automation.status != AUTOMATION_STATUS_ACTIVE:
        automation.status = AUTOMATION_STATUS_ACTIVE
        automation.next_run_at = compute_next_schedule_at(
            automation.trigger_type,
            automation.trigger_config,
            after_utc=now,
            inclusive=False,
        )
        if automation.trigger_type == "once" and automation.next_run_at is None:
            automation.next_run_at = _as_utc(
                datetime.fromisoformat(automation.trigger_config["run_at"])
            )
        automation.updated_at = now
        automation = await automation_repository.save_automation(db, automation)
        record_audit_log(
            db,
            actor,
            "automation.resume",
            "automation",
            automation.id,
            automation.name,
            {
                "next_run_at": automation.next_run_at.isoformat()
                if automation.next_run_at
                else None
            },
            workspace_id=workspace_id,
        )
        await db.commit()
    await db.rollback()
    queued_id = await automation_repository.get_next_queued_execution_id(
        db, automation.id
    )
    await db.rollback()
    if queued_id is not None:
        await _publish_webhook_dispatch(queued_id, settings)
    return await get_automation_detail(db, workspace_id, automation_id, actor)


async def rotate_automation_webhook_secret(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    actor: User,
    settings: Settings,
) -> AutomationWebhookSecretRotateResponse:
    automation = await _load_owned_automation(
        db, workspace_id, automation_id, actor, lock=True
    )
    if automation.trigger_type != "webhook" or not automation.webhook_hook_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Secret rotation is only supported for webhook automations.",
        )
    now = utc_now()
    raw_secret = generate_webhook_secret()
    automation.webhook_secret_ciphertext = encrypt_secret(
        raw_secret, application_secret_key(settings)
    )
    automation.webhook_secret_hint = _secret_hint(raw_secret)
    automation.webhook_secret_updated_at = now
    automation.updated_at = now
    automation = await automation_repository.save_automation(db, automation)
    record_audit_log(
        db,
        actor,
        "automation.webhook_secret.rotate",
        "automation",
        automation.id,
        automation.name,
        {},
        workspace_id=workspace_id,
    )
    await db.commit()
    return AutomationWebhookSecretRotateResponse(
        automation_id=automation.id,
        webhook_hook_id=automation.webhook_hook_id,
        webhook_url=_webhook_url(automation.webhook_hook_id) or "",
        webhook_secret=raw_secret,
        webhook_secret_hint=automation.webhook_secret_hint or "",
        webhook_secret_updated_at=now,
    )


async def _prepare_run_for_execution(
    db: AsyncSession,
    settings: Settings,
    automation: Automation,
    execution: AutomationExecution,
) -> tuple[Any, Any | None, str]:
    """Re-verify owner, workspace, application publication, and resource permissions."""
    frozen = execution.frozen_config
    if not frozen.get("target_app_id") or not frozen.get("target_app_type"):
        raise ValueError("Automation execution configuration is missing.")
    automation = replace(
        automation,
        **{
            key: frozen[key]
            for key in (
                "target_app_id",
                "target_app_type",
                "publication_version_id",
                "workflow_version_id",
                "target_version_number",
                "approval_mode",
            )
        },
    )
    owner = await user_repository.get_user_by_id(db, execution.owner_user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Automation owner user is inactive or missing.",
        )
    workspace = await workspace_repository.get_workspace_by_id(
        db, automation.workspace_id
    )
    if workspace is None or workspace.status != ACTIVE_STATUS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Workspace is inactive or unavailable.",
        )
    await build_workspace_context(db, owner, automation.workspace_id)
    agent = await agent_repository.get_agent_by_id(db, automation.target_app_id)
    if (
        agent is None
        or agent.workspace_id != automation.workspace_id
        or agent.app_type != automation.target_app_type
        or agent.status != ACTIVE_STATUS
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Target application is unavailable or disabled.",
        )
    await require_agent_view(db, agent, owner)
    if (
        not agent.published
        or not agent.published_by_user_id
        or agent.published_at is None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Target application has been unpublished.",
        )

    goal, extra_inputs = extract_run_goal_and_extra_inputs(execution.frozen_input or {})
    if automation.target_app_type == "agent":
        version = await agent_repository.get_agent_publication_version(
            db,
            automation.workspace_id,
            automation.publication_version_id or "",
        )
        if version is None or version.agent_id != agent.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Pinned agent publication version is missing.",
            )
        publisher = await user_repository.get_user_by_id(
            db, version.published_by_user_id
        )
        if publisher is None or not publisher.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Application publisher is inactive.",
            )
        pub_ctx = await build_workspace_context(db, publisher, automation.workspace_id)
        await require_agent_view(db, agent, publisher)
        run, _model = await prepare_agent_run(
            db,
            automation.workspace_id,
            agent.id,
            goal,
            publisher,
            pub_ctx.membership_role,
            persist=False,
            conversation_id=new_id(),
            access_source="automation",
            consumer_id=owner.id,
            requested_by_user_id=owner.id,
            publication_version=version,
            allow_pinned_publication=True,
            settings=settings,
            approval_mode=automation.approval_mode,  # type: ignore[arg-type]
            request_id=execution.id,
            use_memory=False,
        )
        unified = run.configuration_source in {"draft", "published"}
        return run, None, ("unified" if unified else "legacy")

    versions = await workflow_repository.list_versions(
        db, automation.workspace_id, agent.id
    )
    wf_version = next(
        (item for item in versions if item.id == automation.workflow_version_id),
        None,
    )
    if wf_version is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Pinned workflow published version is missing.",
        )
    publisher = await user_repository.get_user_by_id(db, agent.published_by_user_id)
    if publisher is None or not publisher.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Application publisher is inactive.",
        )
    pub_ctx = await build_workspace_context(db, publisher, automation.workspace_id)
    await require_agent_view(db, agent, publisher)
    run, detail = await prepare_workflow_run(
        db,
        automation.workspace_id,
        agent.id,
        WorkflowRunCreateRequest(
            question=goal,
            source="published",
            version_number=wf_version.version_number,
        ),
        publisher,
        pub_ctx.membership_role,
        settings,
        access_source="automation",
        consumer_id=owner.id,
        requested_by_user_id=owner.id,
        conversation_id=new_id(),
        extra_inputs=extra_inputs,
        workflow_version_id=wf_version.id,
        persist=False,
        approval_mode=automation.approval_mode,
    )
    return run, detail, "unified"


def _frozen_config_snapshot(automation: Automation) -> dict[str, Any]:
    return {
        "target_app_id": automation.target_app_id,
        "target_app_type": automation.target_app_type,
        "publication_version_id": automation.publication_version_id,
        "workflow_version_id": automation.workflow_version_id,
        "target_version_number": automation.target_version_number,
        "approval_mode": automation.approval_mode,
        "config_revision": automation.config_revision,
        "name": automation.name,
        "notification_config": dict(automation.notification_config),
    }


async def dispatch_execution_by_id(
    execution_id: str,
    settings: Settings,
) -> AutomationExecution | None:
    """Atomically bind at most one Run to an execution and publish to the worker queue."""
    run_id_to_enqueue: str | None = None
    enqueue_unified = True

    async with get_session_factory()() as db:
        execution = await automation_repository.get_execution(db, execution_id)
        if execution is None:
            return None
        automation = await automation_repository.get_automation(
            db, execution.automation_id, lock=True
        )
        execution = await automation_repository.get_execution(
            db, execution_id, lock=True
        )
        if execution is None:
            return None
        if automation is None:
            execution.dispatch_status = EXECUTION_DISPATCH_REJECTED
            execution.skip_reason = "Parent automation no longer exists."
            execution.notification_closed = True
            execution.updated_at = utc_now()
            await automation_repository.save_execution(db, execution)
            await db.commit()
            return execution

        if automation.status == AUTOMATION_STATUS_PAUSED:
            await db.rollback()
            return execution

        if execution.dispatch_status == EXECUTION_DISPATCH_PENDING:
            if execution.run_id is None:
                execution.dispatch_status = EXECUTION_DISPATCH_REJECTED
                execution.skip_reason = "Pending dispatch has no linked run."
                execution.notification_closed = True
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()
                return execution
            existing_run = await agent_repository.get_agent_run_by_id(
                db, execution.run_id
            )
            if existing_run is None:
                execution.dispatch_status = EXECUTION_DISPATCH_REJECTED
                execution.skip_reason = "Linked run could not be found."
                execution.notification_closed = True
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()
                return execution
            if existing_run.status not in {"queued", "queued_v2"}:
                execution.dispatch_status = EXECUTION_DISPATCH_DISPATCHED
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()
                return execution
            run_id_to_enqueue = existing_run.id
            enqueue_unified = (
                existing_run.configuration_source in {"draft", "published"}
                if automation.target_app_type == "agent"
                else True
            )

        elif execution.dispatch_status == EXECUTION_DISPATCH_QUEUED:
            if (
                execution.trigger_source != "schedule"
                and (
                    await automation_repository.get_next_queued_execution_id(
                        db, automation.id
                    )
                )
                != execution.id
            ):
                await db.rollback()
                return execution
            if await automation_repository.has_active_execution_or_run(
                db, automation.id, exclude_execution_id=execution.id
            ):
                if execution.trigger_source == "schedule":
                    execution.dispatch_status = EXECUTION_DISPATCH_SKIPPED
                    execution.skip_reason = (
                        "Skipped because a previous run is still active."
                    )
                    execution.notification_closed = True
                    execution.updated_at = utc_now()
                    await automation_repository.save_execution(db, execution)
                    await db.commit()
                    return execution
                await db.rollback()
                return execution

            try:
                (
                    prepared_run,
                    prepared_detail,
                    generation,
                ) = await _prepare_run_for_execution(
                    db, settings, automation, execution
                )
            except (HTTPException, ValueError) as exc:
                reason = exc.detail if isinstance(exc, HTTPException) else str(exc)
                await db.rollback()
                async with get_session_factory()() as err_db:
                    locked = await automation_repository.get_execution(
                        err_db, execution_id, lock=True
                    )
                    if (
                        locked is not None
                        and locked.dispatch_status == EXECUTION_DISPATCH_QUEUED
                    ):
                        locked.dispatch_status = EXECUTION_DISPATCH_REJECTED
                        locked.skip_reason = str(reason)
                        locked.notification_closed = False
                        locked.updated_at = utc_now()
                        locked = await automation_repository.save_execution(
                            err_db, locked
                        )
                        await err_db.commit()
                        return locked
                return execution

            created_run = await agent_repository.create_agent_run(db, prepared_run)
            if prepared_detail is not None:
                prepared_detail.run_id = created_run.id
                await workflow_repository.create_run_detail(db, prepared_detail)
            now = utc_now()
            execution.run_id = created_run.id
            execution.dispatch_status = EXECUTION_DISPATCH_PENDING
            execution.updated_at = now
            await automation_repository.save_execution(db, execution)
            await db.commit()
            run_id_to_enqueue = created_run.id
            enqueue_unified = generation == "unified"
        else:
            await db.rollback()
            return execution

    if run_id_to_enqueue is not None:
        try:
            await enqueue_prepared_agent_run(
                run_id_to_enqueue,
                settings,
                unified=enqueue_unified,
            )
        except Exception as exc:
            logger.warning(
                "Run enqueue deferred for automation execution %s (%s): %s",
                execution_id,
                run_id_to_enqueue,
                type(exc).__name__,
            )
            return None

        async with get_session_factory()() as done_db:
            locked = await automation_repository.get_execution(
                done_db, execution_id, lock=True
            )
            if (
                locked is not None
                and locked.dispatch_status == EXECUTION_DISPATCH_PENDING
            ):
                now = utc_now()
                locked.dispatch_status = EXECUTION_DISPATCH_DISPATCHED
                locked.dispatched_at = now
                locked.updated_at = now
                locked = await automation_repository.save_execution(done_db, locked)
                await done_db.commit()
                return locked
            return locked

    return None


async def _load_execution_after_dispatch(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    execution_id: str,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> AutomationExecutionDetailResponse:
    # Ensure caller's session sees committed dispatch changes made outside its transaction.
    db.expire_all()
    return await get_automation_execution_detail(
        db,
        workspace_id,
        automation_id,
        execution_id,
        actor,
        workspace_role,
        settings,
    )


async def execute_automation_manually(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    request_id: str | None,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> AutomationExecutionDetailResponse:
    req_id = (request_id or "").strip() or new_id()
    dedup_key = f"manual:{req_id}"
    automation = await _load_owned_automation(
        db, workspace_id, automation_id, actor, lock=True
    )
    existing = await automation_repository.get_execution_by_dedup_key(
        db, automation.id, dedup_key
    )
    if existing is not None:
        return await _load_execution_after_dispatch(
            db,
            workspace_id,
            automation_id,
            existing.id,
            actor,
            workspace_role,
            settings,
        )
    if automation.status == AUTOMATION_STATUS_PAUSED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Automation is paused; resume it before manual execution.",
        )
    if await automation_repository.has_active_execution_or_run(
        db, automation.id
    ) or await automation_repository.get_next_queued_execution_id(db, automation.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An active execution is already running for this automation.",
        )
    frozen_input = build_execution_input_snapshot(automation.input_config)
    now = utc_now()
    execution = AutomationExecution(
        workspace_id=workspace_id,
        automation_id=automation.id,
        owner_user_id=actor.id,
        trigger_source="manual",
        dedup_key=dedup_key,
        config_revision=automation.config_revision,
        received_at=now,
        frozen_input=frozen_input,
        frozen_config=_frozen_config_snapshot(automation),
        dispatch_status=EXECUTION_DISPATCH_QUEUED,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            execution = await automation_repository.create_execution(db, execution)
            automation.last_triggered_at = now
            automation.updated_at = now
            await automation_repository.save_automation(db, automation)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await automation_repository.get_execution_by_dedup_key(
            db, automation.id, dedup_key
        )
        if existing is None:
            raise
        execution = existing

    await dispatch_execution_by_id(execution.id, settings)
    return await _load_execution_after_dispatch(
        db, workspace_id, automation_id, execution.id, actor, workspace_role, settings
    )


async def receive_webhook_trigger(
    db: AsyncSession,
    hook_id: str,
    raw_body: bytes,
    *,
    timestamp_header: str | None,
    signature_header: str | None,
    event_id_header: str | None,
    settings: Settings,
    source_ip: str | None = None,
) -> AutomationWebhookReceiptResponse:
    if len(raw_body) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "Webhook payload exceeds maximum allowed size.",
        )

    try:
        await enforce_webhook_rate_limit(settings, hook_id, source_ip)
    except WebhookRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Webhook rate limit exceeded.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except WebhookRateLimitUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Webhook rate limiter is unavailable.",
        ) from exc

    automation = await automation_repository.get_automation_by_hook_id(
        db, hook_id, lock=False
    )
    if (
        automation is None
        or automation.trigger_type != "webhook"
        or not automation.webhook_secret_ciphertext
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook hook not found.")

    pre_lock_secret_ciphertext = automation.webhook_secret_ciphertext
    try:
        secret = decrypt_secret(
            pre_lock_secret_ciphertext,
            application_secret_key(settings),
        )
        event_id, _ts = verify_webhook_signature(
            secret=secret,
            timestamp_header=timestamp_header,
            signature_header=signature_header,
            event_id_header=event_id_header,
            raw_body=raw_body,
            now_utc=utc_now(),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    automation = await automation_repository.get_automation_by_hook_id(
        db, hook_id, lock=True
    )
    if (
        automation is None
        or automation.trigger_type != "webhook"
        or not automation.webhook_secret_ciphertext
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook hook not found.")
    if automation.webhook_secret_ciphertext != pre_lock_secret_ciphertext:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature.")

    try:
        parsed_body = json.loads(
            raw_body.decode("utf-8"), parse_constant=_reject_json_constant
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Webhook payload must be valid UTF-8 JSON.",
        ) from exc
    if not isinstance(parsed_body, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Webhook payload must be a JSON object.",
        )

    try:
        payload_hash = canonical_payload_hash(parsed_body)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(422, "Webhook payload must be valid UTF-8 JSON.") from exc
    dedup_key = f"webhook:{event_id}"
    existing = await automation_repository.get_execution_by_dedup_key(
        db, automation.id, dedup_key
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Webhook event ID already received with different payload.",
            )
        return AutomationWebhookReceiptResponse(
            accepted=True,
            deduplicated=True,
            automation_id=automation.id,
            execution_id=existing.id,
            dispatch_status=existing.dispatch_status,  # type: ignore[arg-type]
            run_id=existing.run_id,
            received_at=existing.received_at,
        )

    if automation.status == AUTOMATION_STATUS_PAUSED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Automation is paused and cannot accept webhook events.",
        )

    try:
        frozen_input = build_execution_input_snapshot(
            automation.input_config,
            webhook_payload=parsed_body,
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(exc),
        ) from exc

    max_pending = int(
        (automation.trigger_config or {}).get(
            "max_pending", DEFAULT_WEBHOOK_MAX_PENDING
        )
    )
    pending_count = await automation_repository.count_pending_webhook_executions(
        db, automation.id
    )
    if pending_count >= max_pending:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Automation webhook pending queue is full.",
        )

    now = utc_now()
    execution = AutomationExecution(
        workspace_id=automation.workspace_id,
        automation_id=automation.id,
        owner_user_id=automation.owner_user_id,
        trigger_source="webhook",
        dedup_key=dedup_key,
        config_revision=automation.config_revision,
        received_at=now,
        payload_hash=payload_hash,
        frozen_input=frozen_input,
        frozen_config=_frozen_config_snapshot(automation),
        dispatch_status=EXECUTION_DISPATCH_QUEUED,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            execution = await automation_repository.create_execution(db, execution)
            automation.last_triggered_at = now
            automation.updated_at = now
            await automation_repository.save_automation(db, automation)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await automation_repository.get_execution_by_dedup_key(
            db, automation.id, dedup_key
        )
        if existing is None:
            raise
        if existing.payload_hash != payload_hash:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Webhook event ID already received with different payload.",
            )
        return AutomationWebhookReceiptResponse(
            accepted=True,
            deduplicated=True,
            automation_id=automation.id,
            execution_id=existing.id,
            dispatch_status=existing.dispatch_status,  # type: ignore[arg-type]
            run_id=existing.run_id,
            received_at=existing.received_at,
        )

    await _publish_webhook_dispatch(execution.id, settings)
    return AutomationWebhookReceiptResponse(
        accepted=True,
        deduplicated=False,
        automation_id=automation.id,
        execution_id=execution.id,
        dispatch_status=execution.dispatch_status,  # type: ignore[arg-type]
        run_id=execution.run_id,
        received_at=execution.received_at,
    )


async def _publish_webhook_dispatch(execution_id: str, settings: Settings) -> None:
    try:
        from app.infra.queue.celery import publish_task

        await publish_task(
            "app.automations.dispatch",
            args=(execution_id,),
            settings=settings,
            queue="celery",
            timeout_seconds=1.5,
        )
    except Exception as exc:
        logger.warning(
            "Immediate webhook dispatch publish deferred (%s): %s",
            execution_id,
            type(exc).__name__,
        )


async def list_automation_executions(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    actor: User,
    *,
    limit: int = 50,
    offset: int = 0,
) -> AutomationExecutionListResponse:
    await _load_owned_automation(db, workspace_id, automation_id, actor)
    items, total = await automation_repository.list_executions_for_automation(
        db,
        workspace_id,
        automation_id,
        limit=limit,
        offset=offset,
    )
    runs_map = await _latest_run_map(db, items)
    return AutomationExecutionListResponse(
        items=[
            _execution_to_summary(
                item,
                run=runs_map.get(item.run_id) if item.run_id else None,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_automation_execution_detail(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    execution_id: str,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> AutomationExecutionDetailResponse:
    automation = await _load_owned_automation(db, workspace_id, automation_id, actor)
    execution = await automation_repository.get_execution_for_automation(
        db, workspace_id, automation.id, execution_id
    )
    if execution is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Automation execution not found.",
        )

    run = (
        await agent_repository.get_agent_run_by_id(db, execution.run_id)
        if execution.run_id is not None
        else None
    )
    if run is not None:
        target = await get_agent(db, workspace_id, run.agent_id)
        await require_agent_view(db, target, actor)
        if run.access_source != "automation" or run.consumer_id != actor.id:
            raise HTTPException(404, "Automation run not found.")
    agent_run_resp = None
    workflow_run_resp = None
    tool_calls = []
    artifacts: list[AutomationArtifactLinkResponse] = []
    if run is not None:
        target_type = str(
            (execution.frozen_config or {}).get(
                "target_app_type", automation.target_app_type
            )
        )
        if target_type == "workflow":
            detail = await workflow_repository.get_run_detail(db, run.id)
            if detail is not None:
                workflow_run_resp = await workflow_run_response(db, run, detail)
                tool_calls = list(workflow_run_resp.tool_calls or [])
        else:
            agent_run_resp = run_to_response(run, trace_id=run.trace_id)
            try:
                tool_calls = await list_agent_run_tool_calls(
                    db,
                    workspace_id,
                    automation.target_app_id,
                    run.id,
                    actor,
                    workspace_role,
                )
            except HTTPException:
                tool_calls = []
        try:
            links = await list_authorized_run_artifacts(
                db, settings, actor, workspace_id, run.id
            )
            artifacts = [
                AutomationArtifactLinkResponse(
                    artifact_id=item.artifact_id,
                    format=item.format,
                    filename=item.filename,
                    media_type=item.media_type,
                    download_url=item.download_url,
                    expires_at=item.expires_at,
                    size_bytes=item.size_bytes,
                    relative_path=item.relative_path,
                )
                for item in links
            ]
        except HTTPException:
            artifacts = []

    summary = _execution_to_summary(execution, run=run)
    return AutomationExecutionDetailResponse(
        **summary.model_dump(),
        frozen_input=dict(execution.frozen_input or {}),
        frozen_config=dict(execution.frozen_config or {}),
        agent_run=agent_run_resp,
        workflow_run=workflow_run_resp,
        tool_calls=tool_calls,
        artifacts=artifacts,
    )


async def cancel_automation_execution(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    execution_id: str,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> AutomationExecutionDetailResponse:
    automation = await _load_owned_automation(
        db, workspace_id, automation_id, actor, lock=True
    )
    execution = await automation_repository.get_execution_for_automation(
        db, workspace_id, automation.id, execution_id, lock=True
    )
    if execution is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Automation execution not found.",
        )
    if execution.run_id is None:
        if execution.dispatch_status == EXECUTION_DISPATCH_QUEUED:
            execution.dispatch_status = EXECUTION_DISPATCH_SKIPPED
            execution.skip_reason = "Cancelled before run creation."
            execution.last_reconciled_run_status = "cancelled"
            execution.notification_closed = False
            execution.updated_at = utc_now()
            await automation_repository.save_execution(db, execution)
            await db.commit()
            return await get_automation_execution_detail(
                db,
                workspace_id,
                automation_id,
                execution_id,
                actor,
                workspace_role,
                settings,
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Execution has no cancellable run.",
        )

    if automation.target_app_type == "workflow":
        await cancel_workflow_run(
            db,
            workspace_id,
            automation.target_app_id,
            execution.run_id,
            actor,
            workspace_role,
        )
    else:
        await cancel_agent_run(
            db,
            workspace_id,
            automation.target_app_id,
            execution.run_id,
            actor,
            workspace_role,
        )
    return await get_automation_execution_detail(
        db, workspace_id, automation_id, execution_id, actor, workspace_role, settings
    )


async def resolve_automation_tool_approval(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    execution_id: str,
    call_id: str,
    approve: bool,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> AutomationExecutionDetailResponse:
    automation = await _load_owned_automation(db, workspace_id, automation_id, actor)
    execution = await automation_repository.get_execution_for_automation(
        db, workspace_id, automation.id, execution_id
    )
    if execution is None or execution.run_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Automation run not found.",
        )
    if automation.target_app_type == "workflow":
        await resolve_workflow_tool_approval(
            db,
            workspace_id,
            automation.target_app_id,
            execution.run_id,
            call_id,
            actor,
            workspace_role,
            settings,
            approve=approve,
        )
    else:
        run = await get_agent_run_entity(
            db,
            workspace_id,
            automation.target_app_id,
            execution.run_id,
            actor,
            workspace_role,
        )
        await resolve_workspace_agent_tool_approval(
            db,
            workspace_id,
            automation.target_app_id,
            run.id,
            call_id,
            actor,
            workspace_role,
            settings,
            approve=approve,
        )
    return await get_automation_execution_detail(
        db, workspace_id, automation_id, execution_id, actor, workspace_role, settings
    )


async def submit_automation_workflow_form(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    execution_id: str,
    payload: WorkflowFormSubmitRequest,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> AutomationExecutionDetailResponse:
    automation = await _load_owned_automation(db, workspace_id, automation_id, actor)
    if automation.target_app_type != "workflow":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only workflow automations support form submissions.",
        )
    execution = await automation_repository.get_execution_for_automation(
        db, workspace_id, automation.id, execution_id
    )
    if execution is None or execution.run_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Automation run not found.",
        )
    await submit_workflow_form(
        db,
        workspace_id,
        automation.target_app_id,
        execution.run_id,
        payload,
        actor,
        workspace_role,
        settings,
    )
    return await get_automation_execution_detail(
        db, workspace_id, automation_id, execution_id, actor, workspace_role, settings
    )

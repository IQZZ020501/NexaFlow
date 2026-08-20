"""Transactional email enqueueing and durable delivery orchestration."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.smtp import build_smtp_transport_config, smtp_identity_ready
from app.entities.email import EmailDelivery
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import email as email_repository
from app.infrastructure.repositories import smtp_settings as smtp_repository
from app.infrastructure.secrets import decrypt_secret, encrypt_secret
from app.infrastructure.session import get_session_factory
from app.infrastructure.smtp import (
    SmtpConfigurationError,
    SmtpTransportConfig,
    send_smtp_message,
)
from app.infrastructure.system_log import record_system_log
from app.infrastructure.validation import normalize_email
from app.shareddomain.email.services import render_email

logger = get_logger(__name__)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def identity_email_is_ready(db: AsyncSession) -> bool:
    return smtp_identity_ready(await smtp_repository.get(db))


async def queue_identity_email(
    db: AsyncSession,
    settings: Settings,
    *,
    kind: str,
    recipient: str,
    payload: dict[str, str],
    expires_at,
    user_id: str | None = None,
    source_type: str,
    source_id: str,
    path: str | None = None,
) -> str | None:
    """Persist an encrypted delivery intent when identity email is configured."""
    smtp = await smtp_repository.get(db)
    if not smtp_identity_ready(smtp):
        return None
    assert smtp is not None
    content = dict(payload)
    content["recipient"] = normalize_email(recipient)
    if path is not None:
        content["url"] = f"{smtp.site_url}{path}"
    ciphertext = encrypt_secret(
        json.dumps(content, ensure_ascii=False, separators=(",", ":")),
        settings.model_secret_key,
    )
    delivery = await email_repository.create_delivery(
        db,
        EmailDelivery(
            kind=kind,
            payload_ciphertext=ciphertext,
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            expires_at=expires_at,
        ),
    )
    return delivery.id


async def cancel_source_emails(
    db: AsyncSession,
    source_type: str,
    source_id: str,
) -> None:
    await email_repository.delete_source_deliveries(db, source_type, source_id)


async def _defer_unconfigured(delivery_id: str) -> None:
    async with get_session_factory()() as db:
        delivery = await email_repository.lock_delivery(db, delivery_id)
        if delivery is None:
            return
        now = utc_now()
        if (
            delivery.status == "sending"
            and delivery.lease_expires_at is not None
            and _utc(delivery.lease_expires_at) > now
        ):
            return
        if _utc(delivery.expires_at) <= now:
            await email_repository.delete_delivery(db, delivery.id)
        else:
            delivery.status = "retry"
            delivery.next_attempt_at = now + timedelta(minutes=5)
            delivery.lease_token = None
            delivery.lease_expires_at = None
            delivery.last_error_code = "EmailServiceUnavailable"
            await email_repository.save_delivery(db, delivery)
        await db.commit()


async def _claim_delivery(
    delivery_id: str,
    settings: Settings,
) -> tuple[EmailDelivery, SmtpTransportConfig] | None:
    async with get_session_factory()() as db:
        smtp = await smtp_repository.get(db)
        if not smtp_identity_ready(smtp):
            await db.rollback()
            await _defer_unconfigured(delivery_id)
            return None
        assert smtp is not None
        try:
            config = build_smtp_transport_config(smtp, settings)
        except SmtpConfigurationError as exc:
            log_error(logger, "Email service configuration is invalid.", exc)
            await db.rollback()
            await _defer_unconfigured(delivery_id)
            return None
        delivery = await email_repository.lock_delivery(db, delivery_id)
        if delivery is None:
            return None
        now = utc_now()
        if _utc(delivery.expires_at) <= now or delivery.attempts >= delivery.max_attempts:
            record_system_log(
                db,
                level="warning",
                event="email.delivery_expired",
                message="Queued email expired before delivery.",
                user_id=delivery.user_id,
                details={"delivery_id": delivery.id, "kind": delivery.kind},
            )
            await email_repository.delete_delivery(db, delivery.id)
            await db.commit()
            return None
        if delivery.status == "sending" and delivery.lease_expires_at:
            if _utc(delivery.lease_expires_at) > now:
                return None
        elif _utc(delivery.next_attempt_at) > now:
            return None

        delivery.status = "sending"
        delivery.attempts += 1
        delivery.lease_token = new_id()
        delivery.lease_expires_at = now + timedelta(
            seconds=max(90, int(config.timeout_seconds) + 60)
        )
        delivery = await email_repository.save_delivery(db, delivery)
        await db.commit()
        return delivery, config


async def _finish_delivery(
    delivery_id: str,
    lease_token: str,
    *,
    error: Exception | None,
) -> None:
    async with get_session_factory()() as db:
        delivery = await email_repository.lock_delivery(db, delivery_id)
        if (
            delivery is None
            or delivery.status != "sending"
            or delivery.lease_token != lease_token
        ):
            return
        if error is None:
            record_system_log(
                db,
                level="info",
                event="email.delivery_succeeded",
                message="Queued email was delivered.",
                user_id=delivery.user_id,
                details={
                    "delivery_id": delivery.id,
                    "kind": delivery.kind,
                    "attempts": delivery.attempts,
                },
            )
            await email_repository.delete_delivery(db, delivery.id)
            await db.commit()
            return

        now = utc_now()
        error_code = type(error).__name__[:120]
        if delivery.attempts >= delivery.max_attempts or _utc(delivery.expires_at) <= now:
            record_system_log(
                db,
                level="error",
                event="email.delivery_failed",
                message="Queued email exhausted its delivery attempts.",
                user_id=delivery.user_id,
                details={
                    "delivery_id": delivery.id,
                    "kind": delivery.kind,
                    "attempts": delivery.attempts,
                    "error_code": error_code,
                },
            )
            await email_repository.delete_delivery(db, delivery.id)
        else:
            retry_seconds = min(3600, 30 * 2 ** min(delivery.attempts - 1, 7))
            delivery.status = "retry"
            delivery.next_attempt_at = now + timedelta(seconds=retry_seconds)
            delivery.lease_token = None
            delivery.lease_expires_at = None
            delivery.last_error_code = error_code
            await email_repository.save_delivery(db, delivery)
        await db.commit()


async def run_email_delivery(delivery_id: str, settings: Settings) -> None:
    claimed = await _claim_delivery(delivery_id, settings)
    if claimed is None:
        return
    delivery, config = claimed
    assert delivery.lease_token is not None
    error: Exception | None = None
    try:
        raw_payload = decrypt_secret(
            delivery.payload_ciphertext,
            settings.model_secret_key,
        )
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            raise ValueError("Invalid email payload.")
        rendered = render_email(delivery.kind, payload)
        await send_smtp_message(
            config,
            rendered.recipient,
            rendered.subject,
            rendered.text_body,
            html_body=rendered.html_body,
            message_id=f"<{delivery.id}@nexaflow.local>",
        )
    except Exception as exc:
        error = exc
        log_error(
            logger,
            "Queued email delivery failed.",
            exc,
            delivery_id=delivery.id,
            kind=delivery.kind,
        )
    await _finish_delivery(delivery.id, delivery.lease_token, error=error)


async def list_due_email_delivery_ids(limit: int = 100) -> list[str]:
    async with get_session_factory()() as db:
        return await email_repository.list_due_delivery_ids(db, utc_now(), limit)


async def dispatch_email_deliveries(
    delivery_ids: list[str],
    settings: Settings,
) -> None:
    if not delivery_ids:
        return
    if settings.celery_task_always_eager:
        for delivery_id in delivery_ids:
            await run_email_delivery(delivery_id, settings)
        return

    from app.tasks.email import run_email_delivery_job

    from app.infrastructure.celery import celery_app

    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=False,
    )
    for delivery_id in delivery_ids:
        try:
            await asyncio.to_thread(
                run_email_delivery_job.apply_async,
                args=(delivery_id,),
            )
        except Exception as exc:
            log_error(
                logger,
                "Email delivery dispatch deferred.",
                exc,
                delivery_id=delivery_id,
            )

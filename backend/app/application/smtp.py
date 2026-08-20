"""System-wide SMTP settings and test-delivery use cases."""

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.smtp_settings import SmtpSettings
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import smtp_settings as smtp_repository
from app.infrastructure.secrets import decrypt_secret, encrypt_secret, secret_hint
from app.infrastructure.smtp import (
    SmtpConfigurationError,
    SmtpDeliveryError,
    SmtpTransportConfig,
    send_smtp_message,
)
from app.infrastructure.validation import normalize_email
from app.schemas.smtp import (
    SmtpSettingsResponse,
    SmtpSettingsUpdateRequest,
    SmtpTestRequest,
    normalize_site_url,
)
from app.shareddomain.audit.services import record_audit_log


def _response(entity: SmtpSettings) -> SmtpSettingsResponse:
    return SmtpSettingsResponse(
        host=entity.host,
        port=entity.port,
        username=entity.username,
        security=entity.security,
        from_email=entity.from_email,
        from_name=entity.from_name,
        site_url=entity.site_url,
        enabled=entity.enabled,
        timeout_seconds=entity.timeout_seconds,
        has_password=entity.password_ciphertext is not None,
        password_hint=entity.password_hint,
        configured=bool(entity.host and entity.from_email),
        identity_configured=smtp_identity_ready(entity),
        updated_at=entity.updated_at,
    )


def _invalid(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _validate_email(value: str, field: str) -> str:
    if (
        "\r" in value
        or "\n" in value
        or any(character.isspace() for character in value)
    ):
        raise _invalid(f"Invalid SMTP {field}.")
    try:
        return normalize_email(value)
    except HTTPException as exc:
        raise _invalid(f"Invalid SMTP {field}.") from exc


def smtp_identity_ready(entity: SmtpSettings | None) -> bool:
    return bool(
        entity
        and entity.enabled
        and entity.host
        and entity.from_email
        and entity.site_url
    )


def _validate_entity(entity: SmtpSettings) -> None:
    entity.host = entity.host.strip()
    entity.username = entity.username.strip()
    entity.from_name = entity.from_name.strip()
    entity.site_url = entity.site_url.strip().rstrip("/")
    if any(
        "\r" in value or "\n" in value
        for value in (entity.host, entity.username, entity.from_name, entity.site_url)
    ):
        raise _invalid("SMTP text fields cannot contain line breaks.")
    if entity.from_email:
        entity.from_email = _validate_email(entity.from_email, "sender address")
    if entity.security not in {"none", "starttls", "ssl"}:
        raise _invalid("Invalid SMTP security mode.")
    if entity.security == "none" and entity.username:
        raise _invalid("SMTP authentication requires TLS.")
    if entity.enabled and (not entity.host or not entity.from_email):
        raise _invalid("SMTP host and sender address are required when enabled.")
    if entity.site_url:
        try:
            entity.site_url = normalize_site_url(entity.site_url)
        except ValueError as exc:
            raise _invalid("Invalid public site URL.") from exc


def _password(entity: SmtpSettings, settings: Settings) -> str | None:
    if entity.password_ciphertext is None:
        return None
    try:
        return decrypt_secret(entity.password_ciphertext, settings.model_secret_key)
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise SmtpConfigurationError("Stored SMTP password is invalid.") from exc


def build_smtp_transport_config(
    entity: SmtpSettings,
    settings: Settings,
) -> SmtpTransportConfig:
    if not entity.host or not entity.from_email:
        raise SmtpConfigurationError("SMTP host and sender address are required.")
    try:
        _validate_entity(entity)
    except HTTPException as exc:
        raise SmtpConfigurationError("Stored SMTP configuration is invalid.") from exc
    return SmtpTransportConfig(
        host=entity.host,
        port=entity.port,
        username=entity.username,
        password=_password(entity, settings),
        security=entity.security,
        from_email=entity.from_email,
        from_name=entity.from_name,
        timeout_seconds=entity.timeout_seconds,
    )


async def get_smtp_settings(db: AsyncSession) -> SmtpSettingsResponse:
    entity = await smtp_repository.get(db) or SmtpSettings()
    return _response(entity)


async def update_smtp_settings(
    db: AsyncSession,
    actor: User,
    payload: SmtpSettingsUpdateRequest,
    settings: Settings,
) -> SmtpSettingsResponse:
    entity = await smtp_repository.get(db) or SmtpSettings()
    supplied = payload.model_fields_set
    details = payload.model_dump(exclude={"password"}, exclude_unset=True)
    password_updated = False

    for field in (
        "host",
        "port",
        "username",
        "security",
        "from_email",
        "from_name",
        "site_url",
        "enabled",
        "timeout_seconds",
    ):
        if field in supplied:
            value = getattr(payload, field)
            if value is None:
                if field in {
                    "host",
                    "username",
                    "from_email",
                    "from_name",
                    "site_url",
                }:
                    value = ""
                else:
                    raise _invalid(f"SMTP {field} cannot be null.")
            setattr(entity, field, value)

    if payload.clear_password and payload.password not in (None, ""):
        raise _invalid("Choose a password or clear_password, not both.")
    if payload.clear_password:
        entity.password_ciphertext = None
        entity.password_hint = None
        password_updated = True
    elif payload.password:
        entity.password_ciphertext = encrypt_secret(
            payload.password,
            settings.model_secret_key,
        )
        entity.password_hint = secret_hint(payload.password)
        password_updated = True

    _validate_entity(entity)
    entity.updated_by_user_id = actor.id
    entity.updated_at = utc_now()
    details["password_updated"] = password_updated

    await smtp_repository.save(db, entity)
    record_audit_log(
        db,
        actor,
        "smtp.settings.update",
        "smtp_settings",
        entity.id,
        "SMTP settings",
        details,
    )
    await db.commit()
    return _response(entity)


async def test_smtp_settings(
    db: AsyncSession,
    actor: User,
    payload: SmtpTestRequest,
    settings: Settings,
) -> dict[str, bool]:
    entity = await smtp_repository.get(db)
    if entity is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "SMTP settings are not configured.",
        )

    try:
        config = build_smtp_transport_config(entity, settings)
        recipient = _validate_email(payload.to_email, "recipient address")
        await send_smtp_message(
            config,
            recipient,
            "NexaFlow SMTP test",
            "This is a test email from NexaFlow. SMTP settings are working.",
        )
    except (SmtpConfigurationError, SmtpDeliveryError, HTTPException) as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SMTP test failed.") from exc

    record_audit_log(
        db,
        actor,
        "smtp.test",
        "smtp_settings",
        entity.id,
        "SMTP settings",
        {"recipient": recipient},
    )
    await db.commit()
    return {"success": True}

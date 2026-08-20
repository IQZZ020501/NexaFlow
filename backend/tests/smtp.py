"""SMTP settings and transport regression checks.

Run from ``backend/`` with ``uv run python -m tests.smtp``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import select

from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    settings as test_settings,
    test_client,
)
from app.application.smtp import (
    _validate_email,
    _validate_entity,
    build_smtp_transport_config,
)
from app.domain.smtp_settings import SmtpSettings as SmtpSettingsOrm
from app.entities.smtp_settings import SmtpSettings
from app.infrastructure.secrets import decrypt_secret
from app.infrastructure.session import get_session_factory
from app.infrastructure.smtp import (
    SmtpConfigurationError,
    SmtpDeliveryError,
    SmtpTransportConfig,
    _authenticate_and_send,
    _send_smtp_message_sync,
    send_smtp_message,
)
from app.shareddomain.audit.models import AuditLog


async def stored_password() -> tuple[str | None, list[dict]]:
    async with get_session_factory()() as db:
        row = await db.get(SmtpSettingsOrm, "default")
        assert row is not None
        audit_details = list(
            await db.scalars(
                select(AuditLog.details).where(AuditLog.action == "smtp.settings.update")
            )
        )
        return row.password_ciphertext, audit_details


def test_transport_modes() -> None:
    config = SmtpTransportConfig(
        host="smtp.example.com",
        port=587,
        username="",
        password=None,
        security="none",
        from_email="noreply@example.com",
        from_name="NexaFlow",
        timeout_seconds=7,
    )
    client = MagicMock()
    client.__enter__.return_value = client
    with patch("app.infrastructure.smtp.smtplib.SMTP", return_value=client) as smtp:
        _send_smtp_message_sync(config, "to@example.com", "subject", "body")
    smtp.assert_called_once_with("smtp.example.com", 587, timeout=7)
    client.login.assert_not_called()
    client.starttls.assert_not_called()
    client.send_message.assert_called_once()

    client.reset_mock()
    with patch("app.infrastructure.smtp.smtplib.SMTP", return_value=client):
        _send_smtp_message_sync(
            config,
            "to@example.com",
            "subject",
            "body",
            html_body="<p>body</p>",
            message_id="<delivery@nexaflow.local>",
        )
    message = client.send_message.call_args.args[0]
    assert message["Message-ID"] == "<delivery@nexaflow.local>"
    assert message.is_multipart()

    try:
        _send_smtp_message_sync(config, "to@example.com\nBcc:x@example.com", "subject", "body")
    except SmtpConfigurationError:
        pass
    else:
        raise AssertionError("SMTP header injection was accepted")

    plaintext_auth = SmtpTransportConfig(
        **{
            **config.__dict__,
            "username": "mailer@example.com",
            "password": "secret",
        }
    )
    client.reset_mock()
    try:
        _authenticate_and_send(client, plaintext_auth, MagicMock())
    except SmtpConfigurationError:
        pass
    else:
        raise AssertionError("SMTP authentication without TLS was accepted")
    client.login.assert_not_called()
    client.send_message.assert_not_called()

    config = SmtpTransportConfig(
        **{
            **config.__dict__,
            "username": "mailer@example.com",
            "password": "secret",
            "security": "starttls",
        }
    )
    client.reset_mock()
    with patch("app.infrastructure.smtp.smtplib.SMTP", return_value=client):
        _send_smtp_message_sync(config, "to@example.com", "subject", "body")
    client.starttls.assert_called_once()
    client.login.assert_called_once_with("mailer@example.com", "secret")

    config = SmtpTransportConfig(**{**config.__dict__, "security": "ssl", "port": 465})
    client.reset_mock()
    with patch("app.infrastructure.smtp.smtplib.SMTP_SSL", return_value=client) as smtp_ssl:
        _send_smtp_message_sync(config, "to@example.com", "subject", "body")
    assert smtp_ssl.call_args.kwargs["timeout"] == 7
    client.send_message.assert_called_once()

    for invalid in (
        SmtpTransportConfig(**{**config.__dict__, "host": ""}),
        SmtpTransportConfig(**{**config.__dict__, "security": "invalid"}),
    ):
        try:
            _send_smtp_message_sync(invalid, "to@example.com", "subject", "body")
        except SmtpConfigurationError:
            pass
        else:
            raise AssertionError("Invalid SMTP transport configuration was accepted")

    with patch("app.infrastructure.smtp.smtplib.SMTP_SSL", side_effect=OSError("down")):
        try:
            _send_smtp_message_sync(config, "to@example.com", "subject", "body")
        except SmtpDeliveryError:
            pass
        else:
            raise AssertionError("SMTP transport failure was not normalized")

    with patch("app.infrastructure.smtp._send_smtp_message_sync") as sync_sender:
        asyncio.run(send_smtp_message(config, "to@example.com", "subject", "body"))
    sync_sender.assert_called_once()


def test_application_validation() -> None:
    settings = test_settings()
    valid = SmtpSettings(
        host="smtp.example.com",
        from_email="noreply@example.com",
        site_url="https://nexaflow.example",
        enabled=True,
    )
    assert build_smtp_transport_config(valid, settings).host == "smtp.example.com"

    invalid_entities = (
        SmtpSettings(from_email="noreply@example.com"),
        SmtpSettings(
            host="smtp.example.com",
            from_email="noreply@example.com",
            security="invalid",
        ),
        SmtpSettings(
            host="smtp.example.com",
            username="mailer@example.com",
            from_email="noreply@example.com",
            security="none",
        ),
        SmtpSettings(
            host="smtp.example.com\ninvalid",
            from_email="noreply@example.com",
        ),
        SmtpSettings(host="smtp.example.com", enabled=True),
        SmtpSettings(
            host="smtp.example.com",
            from_email="noreply@example.com",
            site_url="https://user@example.com",
        ),
        SmtpSettings(
            host="smtp.example.com",
            from_email="noreply@example.com",
            password_ciphertext="not-a-fernet-token",
        ),
    )
    for entity in invalid_entities:
        try:
            build_smtp_transport_config(entity, settings)
        except SmtpConfigurationError:
            pass
        else:
            raise AssertionError("Invalid stored SMTP configuration was accepted")

    for value in ("bad address@example.com", "invalid"):
        try:
            _validate_email(value, "recipient address")
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("Invalid SMTP recipient was accepted")

    try:
        _validate_entity(SmtpSettings(host="smtp.example.com", enabled=True))
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Enabled SMTP without a sender was accepted")


def main() -> None:
    test_transport_modes()
    test_application_validation()
    with test_client() as client:
        admin_token, _ = activate_admin(client)
        headers = auth_headers(admin_token)

        initial = client.get("/api/v1/admin/smtp", headers=headers)
        assert initial.status_code == 200, initial.text
        assert initial.json()["has_password"] is False
        assert "password" not in initial.json()

        missing_test = client.post(
            "/api/v1/admin/smtp/test",
            headers=headers,
            json={"to_email": "admin@example.com"},
        )
        assert missing_test.status_code == 400, missing_test.text

        disabled_empty = client.patch(
            "/api/v1/admin/smtp",
            headers=headers,
            json={"host": "", "from_email": "", "enabled": False},
        )
        assert disabled_empty.status_code == 200, disabled_empty.text

        invalid_null = client.patch(
            "/api/v1/admin/smtp",
            headers=headers,
            json={"port": None},
        )
        assert invalid_null.status_code == 422, invalid_null.text

        cleared_site_url = client.patch(
            "/api/v1/admin/smtp",
            headers=headers,
            json={"site_url": None},
        )
        assert cleared_site_url.status_code == 200, cleared_site_url.text

        updated = client.patch(
            "/api/v1/admin/smtp",
            headers=headers,
            json={
                "host": "smtp.example.com",
                "port": 587,
                "username": "mailer@example.com",
                "password": "smtp-secret",
                "security": "starttls",
                "from_email": "noreply@example.com",
                "from_name": "NexaFlow",
                "enabled": True,
            },
        )
        assert updated.status_code == 200, updated.text
        payload = updated.json()
        assert payload["configured"] is True
        assert payload["has_password"] is True
        assert payload["password_hint"] == "****cret"
        assert "smtp-secret" not in updated.text
        ciphertext, audit_details = asyncio.run(stored_password())
        assert ciphertext and ciphertext != "smtp-secret"
        assert decrypt_secret(ciphertext, test_settings().model_secret_key) == "smtp-secret"
        assert "smtp-secret" not in str(audit_details)

        retained = client.patch(
            "/api/v1/admin/smtp",
            headers=headers,
            json={"from_name": "Updated NexaFlow"},
        )
        assert retained.status_code == 200, retained.text
        assert retained.json()["has_password"] is True

        with patch("app.application.smtp.send_smtp_message", new=AsyncMock()) as sender:
            tested = client.post(
                "/api/v1/admin/smtp/test",
                headers=headers,
                json={"to_email": "admin@example.com"},
            )
        assert tested.status_code == 200, tested.text
        assert tested.json() == {"success": True}
        sender.assert_awaited_once()

        with patch(
            "app.application.smtp.send_smtp_message",
            new=AsyncMock(side_effect=SmtpDeliveryError("down")),
        ):
            failed_test = client.post(
                "/api/v1/admin/smtp/test",
                headers=headers,
                json={"to_email": "admin@example.com"},
            )
        assert failed_test.status_code == 400, failed_test.text

        conflict = client.patch(
            "/api/v1/admin/smtp",
            headers=headers,
            json={"password": "new-secret", "clear_password": True},
        )
        assert conflict.status_code == 422, conflict.text

        cleared = client.patch(
            "/api/v1/admin/smtp",
            headers=headers,
            json={"clear_password": True},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["has_password"] is False

        denied = client.get("/api/v1/admin/smtp")
        assert denied.status_code == 401, denied.text

        _, member_token = create_active_user(client, admin_token, "smtp-member")
        denied_member = client.get(
            "/api/v1/admin/smtp", headers=auth_headers(member_token)
        )
        assert denied_member.status_code == 403, denied_member.text
        for method, path, body in (
            ("patch", "/api/v1/admin/smtp", {"host": "smtp.example.com"}),
            ("post", "/api/v1/admin/smtp/test", {"to_email": "admin@example.com"}),
        ):
            response = getattr(client, method)(
                path,
                headers=auth_headers(member_token),
                json=body,
            )
            assert response.status_code == 403, response.text

    print("smtp tests passed")


if __name__ == "__main__":
    main()

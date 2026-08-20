"""Small stdlib SMTP transport used by the system administration feature."""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.infrastructure.errors import ExternalServiceError


class SmtpConfigurationError(ValueError):
    """The persisted SMTP configuration cannot be used."""


class SmtpDeliveryError(ExternalServiceError):
    """The SMTP server rejected or could not receive a message."""


@dataclass(frozen=True)
class SmtpTransportConfig:
    host: str
    port: int
    username: str
    password: str | None
    security: str
    from_email: str
    from_name: str
    timeout_seconds: float


def _send_smtp_message_sync(
    config: SmtpTransportConfig,
    to_email: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    message_id: str | None = None,
) -> None:
    if not config.host or not config.from_email:
        raise SmtpConfigurationError("SMTP host and sender address are required.")
    if config.security not in {"none", "starttls", "ssl"}:
        raise SmtpConfigurationError("Unsupported SMTP security mode.")
    if not to_email or any(
        "\r" in value or "\n" in value
        for value in (
            to_email,
            subject,
            config.from_email,
            config.from_name,
            message_id or "",
        )
    ):
        raise SmtpConfigurationError("Invalid SMTP message headers.")

    message = EmailMessage()
    message["From"] = formataddr((config.from_name, config.from_email))
    message["To"] = to_email
    message["Subject"] = subject
    if message_id:
        message["Message-ID"] = message_id
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        if config.security == "ssl":
            with smtplib.SMTP_SSL(
                config.host,
                config.port,
                timeout=config.timeout_seconds,
                context=ssl.create_default_context(),
            ) as client:
                _authenticate_and_send(client, config, message)
        else:
            with smtplib.SMTP(
                config.host,
                config.port,
                timeout=config.timeout_seconds,
            ) as client:
                if config.security == "starttls":
                    client.ehlo()
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                _authenticate_and_send(client, config, message)
    except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
        raise SmtpDeliveryError("SMTP delivery failed.") from exc


def _authenticate_and_send(
    client: smtplib.SMTP | smtplib.SMTP_SSL,
    config: SmtpTransportConfig,
    message: EmailMessage,
) -> None:
    if config.username:
        client.login(config.username, config.password or "")
    client.send_message(message)


async def send_smtp_message(
    config: SmtpTransportConfig,
    to_email: str,
    subject: str,
    body: str,
    *,
    html_body: str | None = None,
    message_id: str | None = None,
) -> None:
    """Send one message without blocking the FastAPI event loop."""
    await asyncio.to_thread(
        _send_smtp_message_sync,
        config,
        to_email,
        subject,
        body,
        html_body,
        message_id,
    )

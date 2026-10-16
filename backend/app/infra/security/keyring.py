"""Deployment-stable signing and encryption keys kept in PostgreSQL.

``JWT_SECRET_KEY`` and ``MODEL_SECRET_KEY`` historically lived only in ``.env``.
Regenerating or losing that file then invalidated every session and orphaned
stored ciphertext (model credentials, MCP registrations, SMTP password,
enterprise client secrets, queued email payloads).

Both keys are therefore created once per deployment and stored in
``platform_secrets``: startup checks for the row, creates it when missing, and
uses the stored value from then on. An environment value only seeds an empty
store; the stored key always wins, and the application never rewrites it.
"""

import logging
import os
import secrets
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.entities.defaults import utc_now
from app.entities.platform.models import PlatformSecret
from app.infra.config.settings import Settings
from app.infra.db.repositories.platform import secrets as secret_repository
from app.infra.db.session import get_session_factory
from app.infra.observability.logger import get_logger, log_event

logger = get_logger(__name__)

JWT_SIGNING_KEY_NAME = "jwt_signing_key"
APPLICATION_KEY_NAME = "application_encryption_key"

# Template values from .env.example are never adopted as real keys.
PLACEHOLDER_KEY_VALUES = frozenset(
    {
        "replace-with-a-random-32-byte-jwt-secret",
        "replace-with-a-random-32-byte-model-secret",
    }
)


@dataclass(frozen=True)
class SecretKeySpec:
    name: str
    environment_variable: str
    environment_value: Callable[[Settings], str]
    description: str


KEY_SPECS: tuple[SecretKeySpec, ...] = (
    SecretKeySpec(
        JWT_SIGNING_KEY_NAME,
        "JWT_SECRET_KEY",
        lambda settings: settings.jwt_secret_key,
        "session and download-token signing key",
    ),
    SecretKeySpec(
        APPLICATION_KEY_NAME,
        "MODEL_SECRET_KEY",
        lambda settings: settings.model_secret_key,
        "stored-secret encryption key",
    ),
)

_resolved: dict[str, str] = {}


async def initialize_secret_keys(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict[str, str]:
    """Create missing deployment keys and cache the authoritative values.

    Both the API and the Worker call this once at startup. The API keeps the
    values in process; the Worker exports them to the Celery process so a
    generated key is never lost with the resolving process.
    """
    factory = session_factory or get_session_factory()
    async with factory() as db:
        for spec in KEY_SPECS:
            if _resolved.get(spec.name):
                continue
            _resolved[spec.name] = await _resolve(db, spec, settings)
    return dict(_resolved)


async def _resolve(db: AsyncSession, spec: SecretKeySpec, settings: Settings) -> str:
    environment_value = _normalized(spec.environment_value(settings))
    stored = await secret_repository.get(db, spec.name)
    if stored is not None:
        if environment_value and environment_value != stored.value:
            log_event(
                logger,
                logging.ERROR,
                "Environment secret key ignored; the stored key is authoritative.",
                secret=spec.name,
                environment_variable=spec.environment_variable,
            )
        return stored.value

    value = environment_value or secrets.token_urlsafe(48)
    try:
        await secret_repository.create(
            db,
            PlatformSecret(name=spec.name, value=value, created_at=utc_now()),
        )
        await db.commit()
    except IntegrityError:
        # Another API/Worker process created the key first; use its value.
        await db.rollback()
        winner = await secret_repository.get(db, spec.name)
        if winner is None:
            raise
        return winner.value
    log_event(
        logger,
        logging.INFO,
        "Stored the deployment secret key."
        if environment_value
        else "Created a new deployment secret key.",
        secret=spec.name,
        seeded_from_environment=bool(environment_value),
    )
    return value


def jwt_signing_key(settings: Settings | None = None) -> str:
    """Return the deployment session signing key."""
    return _cached_or_environment(
        JWT_SIGNING_KEY_NAME,
        "JWT_SECRET_KEY",
        settings.jwt_secret_key if settings is not None else os.getenv("JWT_SECRET_KEY", ""),
    )


def application_secret_key(settings: Settings | None = None) -> str:
    """Return the key that encrypts stored credentials and integration secrets."""
    return _cached_or_environment(
        APPLICATION_KEY_NAME,
        "MODEL_SECRET_KEY",
        (
            settings.model_secret_key
            if settings is not None
            else os.getenv("MODEL_SECRET_KEY", "")
        ),
    )


def reset_secret_keys() -> None:
    """Drop the in-process cache. Tests only; the stored keys are untouched."""
    _resolved.clear()


def _cached_or_environment(name: str, environment_variable: str, value: str) -> str:
    stored = _resolved.get(name)
    if stored:
        return stored
    environment_value = _normalized(value)
    if environment_value:
        # No store has been read yet in this process: tests and one-off scripts
        # rely on the deployment value, which the first startup adopts verbatim.
        return environment_value
    raise RuntimeError(
        f"{environment_variable} is unavailable: no stored key exists yet and the "
        "environment value is empty. Start the API or Worker once so it can create "
        "and keep the key in PostgreSQL."
    )


def _normalized(value: str) -> str:
    trimmed = (value or "").strip()
    return "" if trimmed in PLACEHOLDER_KEY_VALUES else trimmed


__all__ = [
    "APPLICATION_KEY_NAME",
    "JWT_SIGNING_KEY_NAME",
    "KEY_SPECS",
    "PLACEHOLDER_KEY_VALUES",
    "SecretKeySpec",
    "application_secret_key",
    "initialize_secret_keys",
    "jwt_signing_key",
    "reset_secret_keys",
]

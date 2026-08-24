from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import secrets
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.infrastructure.config import Settings

ALGORITHM = "HS256"
ARTIFACT_TOKEN_SCOPE = "artifact:download"
REFRESH_TOKEN_BYTES = 48
_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(user_id: str, settings: Settings) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expires_minutes)
    payload: dict[str, Any] = {"sub": user_id, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def decode_access_token(token: str, settings: Settings) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def _artifact_signing_key(settings: Settings) -> bytes:
    return hmac.digest(
        settings.jwt_secret_key.encode(),
        b"nexaflow-generated-artifact-v1",
        sha256,
    )


def create_artifact_download_token(
    artifact_id: str,
    expires_at: datetime,
    settings: Settings,
) -> str:
    return jwt.encode(
        {"sub": artifact_id, "scope": ARTIFACT_TOKEN_SCOPE, "exp": expires_at},
        _artifact_signing_key(settings),
        algorithm=ALGORITHM,
    )


def decode_artifact_download_token(token: str, settings: Settings) -> str | None:
    try:
        payload = jwt.decode(
            token,
            _artifact_signing_key(settings),
            algorithms=[ALGORITHM],
        )
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return (
        subject
        if isinstance(subject, str) and payload.get("scope") == ARTIFACT_TOKEN_SCOPE
        else None
    )

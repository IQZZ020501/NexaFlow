from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.system_log import SystemLog
from app.infrastructure.repositories import system_log as system_log_repository
from app.schemas.system_log import SystemLogResponse

_SENSITIVE_PARTS = (
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
)
_REDACTED = "[REDACTED]"


def _is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)


def redact_system_value(value: Any) -> Any:
    """Return JSON-safe log data without credential-shaped fields."""
    if isinstance(value, dict):
        return {
            str(key): _REDACTED if _is_sensitive(str(key)) else redact_system_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_system_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_system_value(item) for item in value]
    return value


def _to_response(log: SystemLog, include_stack: bool) -> SystemLogResponse:
    stack = log.stack_trace[:4000] if include_stack and log.stack_trace else None
    return SystemLogResponse(
        id=log.id,
        level=log.level,
        event=log.event,
        message=log.message[:1000],
        path=log.path,
        method=log.method,
        status_code=log.status_code,
        user_id=log.user_id,
        username=log.username,
        ip_address=log.ip_address,
        details=redact_system_value(log.details),
        stack_trace=stack,
        created_at=log.created_at,
    )


async def list_system_logs(
    db: AsyncSession,
    limit: int,
    offset: int = 0,
    *,
    level: str | None = None,
    event: str | None = None,
    status_code: int | None = None,
    user_id: str | None = None,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    include_stack: bool = False,
) -> list[SystemLogResponse]:
    logs = await system_log_repository.list_system_logs(
        db,
        limit,
        offset,
        level=level,
        event=event,
        status_code=status_code,
        user_id=user_id,
        search=search,
        from_date=from_date,
        to_date=to_date,
    )
    return [_to_response(log, include_stack) for log in logs]

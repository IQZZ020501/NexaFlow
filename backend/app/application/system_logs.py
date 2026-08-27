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
    """Determine whether a key indicates sensitive data.
    
    Parameters:
    	key (str): The key to inspect.
    
    Returns:
    	bool: `true` if the key contains a sensitive-data marker, `false` otherwise.
    """
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)


def redact_system_value(value: Any) -> Any:
    """
    Recursively redact credential-like fields in log data.
    
    Parameters:
    	value (Any): A value that may contain dictionaries, lists, or tuples with sensitive fields.
    
    Returns:
    	Any: The sanitized value, with sensitive fields replaced by "[REDACTED]" and tuples converted to lists.
    """
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
    """
    Convert a system log entity into a response with redacted details and bounded text fields.
    
    Parameters:
    	log (SystemLog): The system log entity to convert.
    	include_stack (bool): Whether to include the stack trace.
    
    Returns:
    	SystemLogResponse: The converted log response.
    """
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
    """
    Retrieve system logs with pagination and optional filters.
    
    Parameters:
        limit (int): Maximum number of logs to retrieve.
        offset (int): Number of logs to skip.
        level (str | None): Log level filter.
        event (str | None): Event name filter.
        status_code (int | None): HTTP status code filter.
        user_id (str | None): User identifier filter.
        search (str | None): Text search filter.
        from_date (datetime | None): Earliest log timestamp to include.
        to_date (datetime | None): Exclusive upper bound for log timestamps.
        include_stack (bool): Whether to include stack traces in the responses.
    
    Returns:
        list[SystemLogResponse]: The filtered system logs as response objects.
    """
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


async def count_system_logs(db: AsyncSession, **filters: Any) -> int:
    return await system_log_repository.count_system_logs(db, **filters)

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.system_logs.models import SystemLog


def record_system_log(
    db: AsyncSession,
    level: str,
    event: str,
    message: str,
    path: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    user_id: str | None = None,
    username: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
    stack_trace: str | None = None,
) -> None:
    db.add(
        SystemLog(
            level=level,
            event=event,
            message=message[:1000],
            path=path,
            method=method,
            status_code=status_code,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            details=details or {},
            stack_trace=stack_trace,
        )
    )

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    level: Mapped[str] = mapped_column(String(20), default="info", index=True)
    event: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(String(1000))
    path: Mapped[str | None] = mapped_column(String(255), index=True)
    method: Mapped[str | None] = mapped_column(String(12))
    status_code: Mapped[int | None] = mapped_column(Integer, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    username: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stack_trace: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=True
    )


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

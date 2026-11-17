from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base


class McpRemoteTask(Base):
    __tablename__ = "mcp_remote_tasks"
    __table_args__ = (Index("ix_mcp_remote_tasks_cleanup", "next_cancel_at", "status"),)
    # Opaque references preserve cleanup intent when a conversation/application
    # and its execution ledger are deleted. This table never stores call results.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invocation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    server_id: Mapped[str] = mapped_column(String(36), nullable=False)
    server_binding: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(255), nullable=False)
    contract: Mapped[dict] = mapped_column(JSON, nullable=False)
    remote_id: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="submitting"
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    cancel_owner: Mapped[str | None] = mapped_column(String(36))
    cancel_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_cancel_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    cancel_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

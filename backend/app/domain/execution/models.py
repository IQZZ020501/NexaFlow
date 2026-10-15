from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String, column
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base


class ExecutionSession(Base):
    __tablename__ = "execution_sessions"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('run', 'mcp')", name="ck_execution_sessions_purpose"
        ),
        CheckConstraint(
            "state IN ('creating', 'ready', 'closing', 'closed')",
            name="ck_execution_sessions_state",
        ),
        Index(
            "uq_execution_sessions_live_owner",
            "workspace_id",
            "run_id",
            "purpose",
            "owner_key",
            unique=True,
            postgresql_where=column("state") != "closed",
            sqlite_where=column("state") != "closed",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # No FK: deletion must leave cleanup intent until the external guest is gone.
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="run")
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    sandbox_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    image: Mapped[str] = mapped_column(String(512), nullable=False)
    profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="creating", index=True
    )
    staged_packages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    environments: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    capacity_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consumer_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    holder: Mapped[str | None] = mapped_column(String(64), nullable=True)
    holder_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

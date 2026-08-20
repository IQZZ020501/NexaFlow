from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import utc_now


class WorkspaceGovernance(Base):
    __tablename__ = "workspace_governance"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    daily_run_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    alert_threshold_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=80, server_default="80"
    )
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

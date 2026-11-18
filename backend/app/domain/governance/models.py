"""Durable model usage; caller IDs survive deletion as opaque audit references."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import utc_now
from app.infra.db.base import Base


class WorkspaceTokenMonth(Base):
    __tablename__ = "workspace_token_months"
    __table_args__ = (
        CheckConstraint(
            "used_tokens >= 0 AND reserved_tokens >= 0",
            name="ck_workspace_token_months_nonnegative",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    used_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, default=0)


class ModelUsageReservation(Base):
    __tablename__ = "model_usage_reservations"
    __table_args__ = (
        CheckConstraint(
            "reserved_tokens > 0 AND charged_tokens >= 0",
            name="ck_model_usage_reservation_tokens",
        ),
        CheckConstraint(
            "state IN ('dispatched', 'settled', 'uncertain')",
            name="ck_model_usage_reservation_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    period: Mapped[str] = mapped_column(String(7))
    model_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(16), default="dispatched")
    reserved_tokens: Mapped[int] = mapped_column(BigInteger)
    charged_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

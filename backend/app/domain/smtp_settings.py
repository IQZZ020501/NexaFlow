from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.smtp_settings import SMTP_SETTINGS_ID
from app.infrastructure.base import Base
from app.infrastructure.model_utils import utc_now


class SmtpSettings(Base):
    """Global SMTP configuration, intentionally limited to one ``default`` row."""

    __tablename__ = "smtp_settings"
    __table_args__ = (
        CheckConstraint("id = 'default'", name="ck_smtp_settings_singleton"),
        CheckConstraint("port BETWEEN 1 AND 65535", name="ck_smtp_settings_port"),
        CheckConstraint(
            "security IN ('none', 'starttls', 'ssl')",
            name="ck_smtp_settings_security",
        ),
        CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 120",
            name="ck_smtp_settings_timeout",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=SMTP_SETTINGS_ID,
        server_default=SMTP_SETTINGS_ID,
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=587, server_default="587")
    username: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    security: Mapped[str] = mapped_column(
        String(20), nullable=False, default="starttls", server_default="starttls"
    )
    from_email: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    from_name: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    site_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, default="", server_default=""
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    timeout_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0, server_default="10"
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

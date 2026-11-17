from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base


class McpOAuthConnection(Base):
    __tablename__ = "mcp_oauth_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    server_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    secrets_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="disconnected"
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_owner: Mapped[str | None] = mapped_column(String(36))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class McpOAuthAttempt(Base):
    __tablename__ = "mcp_oauth_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_oauth_connections.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    verifier_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class McpOAuthRevocation(Base):
    __tablename__ = "mcp_oauth_revocations"
    __table_args__ = (Index("ix_mcp_oauth_revocations_due", "next_attempt_at"),)
    # Independent of the source/account so disconnect and deletion cannot lose
    # the encrypted revocation intent. Success removes the retained secrets.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    secrets_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

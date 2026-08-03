from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


class McpServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_mcp_servers_workspace_name"),
        UniqueConstraint("workspace_id", "id", name="uq_mcp_servers_workspace_id"),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_mcp_servers_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    bearer_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    bearer_token_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

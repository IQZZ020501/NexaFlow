from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


class ResourceFolder(Base):
    __tablename__ = "resource_folders"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_resource_folders_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "resource_type",
            "id",
            name="uq_resource_folders_workspace_type_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "resource_type", "parent_id"],
            [
                "resource_folders.workspace_id",
                "resource_folders.resource_type",
                "resource_folders.id",
            ],
            name="fk_resource_folders_parent_workspace_type",
        ),
        CheckConstraint(
            "resource_type IN ('knowledge', 'application', 'tool')",
            name="ck_resource_folders_resource_type",
        ),
        Index(
            "uq_resource_folders_workspace_parent_name",
            "workspace_id",
            "resource_type",
            "parent_id",
            "name",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

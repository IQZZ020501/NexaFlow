from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nexaflow.db.base import Base
from nexaflow.db.model_utils import new_id, utc_now


class ResourcePermission(Base):
    __tablename__ = "resource_permissions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "resource_type",
            "resource_id",
            "user_id",
            name="uq_resource_permission_user",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_memberships.workspace_id", "workspace_memberships.user_id"],
            name="fk_resource_permission_workspace_user",
        ),
        CheckConstraint(
            "resource_type IN ('knowledge_base')",
            name="ck_resource_permissions_resource_type",
        ),
        CheckConstraint(
            "permission IN ('view', 'edit')",
            name="ck_resource_permissions_permission",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

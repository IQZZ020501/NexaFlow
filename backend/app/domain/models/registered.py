from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.entities.defaults import new_id, utc_now
from app.domain.resource_folders.models import ResourceFolder  # noqa: F401


class RegisteredModel(Base):
    __tablename__ = "model"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "folder_id"],
            ["resource_folders.workspace_id", "resource_folders.id"],
            name="fk_model_folder_workspace",
        ),
        UniqueConstraint("workspace_id", "name", name="uq_model_registry_model_workspace_name"),
        CheckConstraint(
            "provider_type IN ('openai_compatible', 'anthropic', 'bedrock', "
            "'azure_openai', 'deepseek', 'google_genai', 'ollama')",
            name="ck_model_registry_models_provider_type",
        ),
        CheckConstraint(
            "model_type IN ('LLM', 'VISION', 'EMBEDDING', 'RERANKER')",
            name="ck_model_registry_models_type",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_model_registry_models_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False, default="openai_compatible")
    api_base: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credential_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    credential_secret_hints: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    model_type: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

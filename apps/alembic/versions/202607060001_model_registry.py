"""model registry

Revision ID: 202607060001
Revises: 202607050004
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607060001"
down_revision: str | None = "202607050004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_registry_models",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("provider_type", sa.String(length=40), nullable=False),
        sa.Column("api_base", sa.Text(), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("api_key_hint", sa.String(length=32), nullable=True),
        sa.Column("api_key_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_type", sa.String(length=20), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider_type IN ('openai_compatible')",
            name="ck_model_registry_models_provider_type",
        ),
        sa.CheckConstraint(
            "model_type IN ('LLM', 'EMBEDDING', 'RERANKER')",
            name="ck_model_registry_models_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_model_registry_models_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_model_registry_model_workspace_name"),
    )
    op.create_index(
        op.f("ix_model_registry_models_created_by_user_id"),
        "model_registry_models",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_registry_models_provider"),
        "model_registry_models",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_registry_models_workspace_id"),
        "model_registry_models",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_registry_models_workspace_id"), table_name="model_registry_models")
    op.drop_index(op.f("ix_model_registry_models_provider"), table_name="model_registry_models")
    op.drop_index(op.f("ix_model_registry_models_created_by_user_id"), table_name="model_registry_models")
    op.drop_table("model_registry_models")

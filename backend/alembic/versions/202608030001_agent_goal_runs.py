"""agent goal runs

Revision ID: 202608030001
Revises: 202608020011
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608030001"
down_revision: str | None = "202608020011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_agents_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["model.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_agents_workspace_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
    )
    op.create_index(op.f("ix_agents_created_by_user_id"), "agents", ["created_by_user_id"])
    op.create_index(op.f("ix_agents_model_id"), "agents", ["model_id"])
    op.create_index(op.f("ix_agents_workspace_id"), "agents", ["workspace_id"])

    op.create_table(
        "agent_knowledge_bases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_knowledge_bases_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_agent_knowledge_bases_knowledge_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "knowledge_base_id",
            name="uq_agent_knowledge_bases_binding",
        ),
    )
    op.create_index(
        op.f("ix_agent_knowledge_bases_agent_id"),
        "agent_knowledge_bases",
        ["agent_id"],
    )
    op.create_index(
        op.f("ix_agent_knowledge_bases_knowledge_base_id"),
        "agent_knowledge_bases",
        ["knowledge_base_id"],
    )
    op.create_index(
        op.f("ix_agent_knowledge_bases_workspace_id"),
        "agent_knowledge_bases",
        ["workspace_id"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("knowledge_base_ids", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('planning', 'planned', 'running', 'succeeded', 'failed')",
            name="ck_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_runs_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_agent_id"), "agent_runs", ["agent_id"])
    op.create_index(
        op.f("ix_agent_runs_requested_by_user_id"),
        "agent_runs",
        ["requested_by_user_id"],
    )
    op.create_index(op.f("ix_agent_runs_status"), "agent_runs", ["status"])
    op.create_index(op.f("ix_agent_runs_workspace_id"), "agent_runs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_runs_workspace_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_status"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_requested_by_user_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_agent_id"), table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index(
        op.f("ix_agent_knowledge_bases_workspace_id"),
        table_name="agent_knowledge_bases",
    )
    op.drop_index(
        op.f("ix_agent_knowledge_bases_knowledge_base_id"),
        table_name="agent_knowledge_bases",
    )
    op.drop_index(
        op.f("ix_agent_knowledge_bases_agent_id"),
        table_name="agent_knowledge_bases",
    )
    op.drop_table("agent_knowledge_bases")

    op.drop_index(op.f("ix_agents_workspace_id"), table_name="agents")
    op.drop_index(op.f("ix_agents_model_id"), table_name="agents")
    op.drop_index(op.f("ix_agents_created_by_user_id"), table_name="agents")
    op.drop_table("agents")

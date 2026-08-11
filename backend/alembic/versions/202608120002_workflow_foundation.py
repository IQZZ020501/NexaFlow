"""Add workflow definitions, versions, run details, and node executions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608120002"
down_revision: str | None = "202608120001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("graph_hash", sa.String(64), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_workflow_definitions_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("agent_id", name="uq_workflow_definitions_agent_id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_workflow_definitions_workspace_id"),
        sa.CheckConstraint("revision >= 1", name="ck_workflow_definitions_revision"),
    )
    op.create_index("ix_workflow_definitions_workspace_id", "workflow_definitions", ["workspace_id"])
    op.create_index("ix_workflow_definitions_agent_id", "workflow_definitions", ["agent_id"])
    op.create_index(
        "ix_workflow_definitions_updated_by_user_id",
        "workflow_definitions",
        ["updated_by_user_id"],
    )

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("definition_id", sa.String(36), nullable=False),
        sa.Column("definition_revision", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "default_model_id",
            sa.String(36),
            sa.ForeignKey("model.id"),
            nullable=False,
        ),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("graph_hash", sa.String(64), nullable=False),
        sa.Column("published_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_workflow_versions_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "definition_id"],
            ["workflow_definitions.workspace_id", "workflow_definitions.id"],
            name="fk_workflow_versions_definition_workspace",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_workflow_versions_agent_number"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_workflow_versions_workspace_id"),
        sa.CheckConstraint("version_number >= 1", name="ck_workflow_versions_number"),
        sa.CheckConstraint("definition_revision >= 1", name="ck_workflow_versions_revision"),
    )
    for column in (
        "workspace_id",
        "agent_id",
        "definition_id",
        "default_model_id",
        "published_by_user_id",
    ):
        op.create_index(f"ix_workflow_versions_{column}", "workflow_versions", [column])

    op.create_table(
        "workflow_run_details",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("definition_id", sa.String(36), nullable=False),
        sa.Column("definition_revision", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.String(36), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("graph_hash", sa.String(64), nullable=False),
        sa.Column("graph_snapshot", sa.JSON(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_model_tokens", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("token_usage", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_workflow_run_details_run_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "definition_id"],
            ["workflow_definitions.workspace_id", "workflow_definitions.id"],
            name="fk_workflow_run_details_definition_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "version_id"],
            ["workflow_versions.workspace_id", "workflow_versions.id"],
            name="fk_workflow_run_details_version_workspace",
        ),
        sa.UniqueConstraint("run_id", name="uq_workflow_run_details_run_id"),
        sa.CheckConstraint("source IN ('draft', 'published')", name="ck_workflow_run_details_source"),
        sa.CheckConstraint("max_steps > 0", name="ck_workflow_run_details_max_steps"),
        sa.CheckConstraint("max_model_tokens > 0", name="ck_workflow_run_details_max_tokens"),
        sa.CheckConstraint("step_count >= 0", name="ck_workflow_run_details_steps"),
        sa.CheckConstraint("token_usage >= 0", name="ck_workflow_run_details_tokens"),
        sa.CheckConstraint(
            "(source = 'draft' AND version_id IS NULL AND version_number IS NULL) OR "
            "(source = 'published' AND version_id IS NOT NULL AND version_number IS NOT NULL)",
            name="ck_workflow_run_details_version_source",
        ),
    )
    for column in ("workspace_id", "run_id", "definition_id", "version_id"):
        op.create_index(f"ix_workflow_run_details_{column}", "workflow_run_details", [column])

    op.create_table(
        "workflow_node_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(80), nullable=False),
        sa.Column("node_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("model_usage", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_workflow_node_executions_run_workspace",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "node_id", name="uq_workflow_node_executions_run_node"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'skipped')",
            name="ck_workflow_node_executions_status",
        ),
    )
    for column in ("workspace_id", "run_id", "status"):
        op.create_index(
            f"ix_workflow_node_executions_{column}", "workflow_node_executions", [column]
        )


def downgrade() -> None:
    op.drop_table("workflow_node_executions")
    op.drop_table("workflow_run_details")
    op.drop_table("workflow_versions")
    op.drop_table("workflow_definitions")

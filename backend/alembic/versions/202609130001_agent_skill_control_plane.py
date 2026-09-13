"""Add versioned Agent Skill control-plane resources."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609130001"
down_revision: str | None = "202609110003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run_snapshots",
        sa.Column("skill_snapshots", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "agent_run_snapshots",
            "skill_snapshots",
            existing_type=sa.JSON(),
            server_default=None,
        )
    op.create_table(
        "agent_skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("draft_definition", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_published_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_agent_skills_workspace_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_agent_skills_workspace_name"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name="ck_agent_skills_status"
        ),
    )
    op.create_index("ix_agent_skills_workspace_id", "agent_skills", ["workspace_id"])
    op.create_index(
        "ix_agent_skills_current_published_version_id",
        "agent_skills",
        ["current_published_version_id"],
    )
    op.create_index(
        "ix_agent_skills_created_by_user_id", "agent_skills", ["created_by_user_id"]
    )

    op.create_table(
        "agent_skill_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("definition_snapshot", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"], ["users.id"], name="fk_agent_skill_versions_published_by"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "skill_id"],
            ["agent_skills.workspace_id", "agent_skills.id"],
            name="fk_agent_skill_versions_skill_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_id", "version_number", name="uq_agent_skill_versions_skill_number"
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_agent_skill_versions_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "skill_id",
            "id",
            name="uq_agent_skill_versions_workspace_skill_id",
        ),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_agent_skill_versions_number"
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_agent_skill_versions_schema"
        ),
    )
    op.create_index(
        "ix_agent_skill_versions_workspace_id", "agent_skill_versions", ["workspace_id"]
    )
    op.create_index(
        "ix_agent_skill_versions_skill_id", "agent_skill_versions", ["skill_id"]
    )
    op.create_index(
        "ix_agent_skill_versions_published_by_user_id",
        "agent_skill_versions",
        ["published_by_user_id"],
    )

    op.create_table(
        "agent_skill_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("skill_version_id", sa.String(length=36), nullable=False),
        sa.Column("bound_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bound_by_user_id"], ["users.id"], name="fk_agent_skill_bindings_bound_by"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_skill_bindings_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "skill_id", "skill_version_id"],
            [
                "agent_skill_versions.workspace_id",
                "agent_skill_versions.skill_id",
                "agent_skill_versions.id",
            ],
            name="fk_agent_skill_bindings_version_workspace",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id", "skill_id", name="uq_agent_skill_bindings_agent_skill"
        ),
    )
    op.create_index(
        "ix_agent_skill_bindings_workspace_id", "agent_skill_bindings", ["workspace_id"]
    )
    op.create_index(
        "ix_agent_skill_bindings_agent_id", "agent_skill_bindings", ["agent_id"]
    )
    op.create_index(
        "ix_agent_skill_bindings_skill_id", "agent_skill_bindings", ["skill_id"]
    )
    op.create_index(
        "ix_agent_skill_bindings_skill_version_id",
        "agent_skill_bindings",
        ["skill_version_id"],
    )
    op.create_index(
        "ix_agent_skill_bindings_bound_by_user_id",
        "agent_skill_bindings",
        ["bound_by_user_id"],
    )

    op.drop_constraint(
        "ck_resource_permissions_type_permission", "resource_permissions", type_="check"
    )
    op.create_check_constraint(
        "ck_resource_permissions_type_permission",
        "resource_permissions",
        "(resource_type = 'knowledge_base' AND permission IN ('view', 'edit')) OR "
        "(resource_type = 'agent' AND permission = 'view') OR "
        "(resource_type = 'tool' AND permission IN ('view', 'use')) OR "
        "(resource_type = 'agent_skill' AND permission IN ('view', 'use'))",
    )


def downgrade() -> None:
    op.drop_column("agent_run_snapshots", "skill_snapshots")
    op.drop_constraint(
        "ck_resource_permissions_type_permission", "resource_permissions", type_="check"
    )
    op.create_check_constraint(
        "ck_resource_permissions_type_permission",
        "resource_permissions",
        "(resource_type = 'knowledge_base' AND permission IN ('view', 'edit')) OR "
        "(resource_type = 'agent' AND permission = 'view') OR "
        "(resource_type = 'tool' AND permission IN ('view', 'use'))",
    )
    op.drop_table("agent_skill_bindings")
    op.drop_table("agent_skill_versions")
    op.drop_table("agent_skills")

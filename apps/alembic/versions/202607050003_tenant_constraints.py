"""tenant constraints

Revision ID: 202607050003
Revises: 202607050002
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607050003"
down_revision: str | None = "202607050002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("workspace_id", sa.String(length=36), nullable=True))
    op.create_index(op.f("ix_audit_logs_workspace_id"), "audit_logs", ["workspace_id"], unique=False)

    op.add_column("team_memberships", sa.Column("workspace_id", sa.String(length=36), nullable=True))
    op.execute(
        """
        UPDATE team_memberships
        SET workspace_id = teams.workspace_id
        FROM teams
        WHERE team_memberships.team_id = teams.id
        """
    )

    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.create_check_constraint(
            "ck_workspaces_status",
            "status IN ('active', 'archived')",
        )

    with op.batch_alter_table("teams") as batch_op:
        batch_op.create_unique_constraint("uq_team_workspace_id", ["workspace_id", "id"])
        batch_op.create_check_constraint(
            "ck_teams_status",
            "status IN ('active', 'archived')",
        )

    op.execute("UPDATE workspace_memberships SET role = 'admin' WHERE role = 'owner'")

    with op.batch_alter_table("workspace_memberships") as batch_op:
        batch_op.create_check_constraint(
            "ck_workspace_memberships_role",
            "role IN ('admin', 'member')",
        )

    with op.batch_alter_table("team_memberships") as batch_op:
        batch_op.alter_column(
            "workspace_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.create_index(op.f("ix_team_memberships_workspace_id"), ["workspace_id"], unique=False)
        batch_op.create_check_constraint(
            "ck_team_memberships_role",
            "role IN ('admin', 'member')",
        )
        batch_op.create_foreign_key(
            "fk_team_membership_workspace_team",
            "teams",
            ["workspace_id", "team_id"],
            ["workspace_id", "id"],
        )
        batch_op.create_foreign_key(
            "fk_team_membership_workspace_user",
            "workspace_memberships",
            ["workspace_id", "user_id"],
            ["workspace_id", "user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("team_memberships") as batch_op:
        batch_op.drop_constraint(
            "fk_team_membership_workspace_user",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_team_membership_workspace_team",
            type_="foreignkey",
        )
        batch_op.drop_constraint("ck_team_memberships_role", type_="check")
        batch_op.drop_index(op.f("ix_team_memberships_workspace_id"))
        batch_op.drop_column("workspace_id")

    with op.batch_alter_table("workspace_memberships") as batch_op:
        batch_op.drop_constraint("ck_workspace_memberships_role", type_="check")

    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_constraint("ck_teams_status", type_="check")
        batch_op.drop_constraint("uq_team_workspace_id", type_="unique")

    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_constraint("ck_workspaces_status", type_="check")

    op.drop_index(op.f("ix_audit_logs_workspace_id"), table_name="audit_logs")
    op.drop_column("audit_logs", "workspace_id")

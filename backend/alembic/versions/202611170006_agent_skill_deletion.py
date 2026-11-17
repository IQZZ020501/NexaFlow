"""Preserve published Skill history when deleting a custom Skill."""

import sqlalchemy as sa

from alembic import op

revision = "202611170006"
down_revision = "202611170005"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agent_skills") as batch:
        batch.drop_constraint("ck_agent_skills_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_skills_status", "status IN ('active', 'disabled', 'archived')"
        )


def downgrade():
    archived = (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM agent_skills WHERE status = 'archived' LIMIT 1")
        )
        .first()
    )
    if archived is not None:
        raise RuntimeError(
            "Cannot downgrade while deleted Skills retain immutable history."
        )
    with op.batch_alter_table("agent_skills") as batch:
        batch.drop_constraint("ck_agent_skills_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_skills_status", "status IN ('active', 'disabled')"
        )

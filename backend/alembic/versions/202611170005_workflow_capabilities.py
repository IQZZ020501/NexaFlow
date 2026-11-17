"""Enable ledger-backed MCP approval and Skill execution in Workflows.

Existing published snapshots retain their original policy revision and require
republishing. Approval, external effects, grants and access sources stay intact.
"""

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "202611170005"
down_revision = "202611170004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    supported = sa.or_(
        tools.c.kind == "mcp",
        sa.and_(
            tools.c.kind == "builtin",
            tools.c.function_name.in_(
                [
                    "bash",
                    "run_skill_script",
                    "install_skill_dependencies",
                    "documents_skill",
                    "pdf_skill",
                    "pptx_skill",
                    "spreadsheets_skill",
                    "skill_creator",
                ]
            ),
        ),
    )
    bind.execute(
        policies.update()
        .where(
            policies.c.tool_id.in_(sa.select(tools.c.id).where(supported)),
            policies.c.approval != "disabled",
            policies.c.workflow_callable.is_(False),
        )
        .values(
            workflow_callable=True,
            revision=policies.c.revision + 1,
            updated_at=datetime.now(UTC),
        )
    )
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.drop_constraint("ck_workflow_node_executions_status", type_="check")
        batch.create_check_constraint(
            "ck_workflow_node_executions_status",
            "status IN ('running', 'awaiting_input', 'awaiting_child', 'awaiting_approval', 'succeeded', 'failed', 'skipped')",
        )


def downgrade():
    # Frozen policy revisions fail closed when older code is restored.
    pass

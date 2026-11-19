"""Personal projects and conversation membership for published Agent chats."""

import sqlalchemy as sa

from alembic import op

revision = "202611190002"
down_revision = "202611190001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column(
            "file_tree_id",
            sa.String(36),
            sa.ForeignKey("agent_projects.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("dissolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_chat_projects_owner",
        "chat_projects",
        ["workspace_id", "agent_id", "owner_user_id"],
    )
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("chat_projects.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "agent_id",
            "owner_user_id",
            "conversation_id",
            name="uq_chat_conversation_scope",
        ),
    )
    op.create_index(
        "ix_chat_conversations_project", "chat_conversations", ["project_id"]
    )


def downgrade():
    op.drop_table("chat_conversations")
    op.drop_table("chat_projects")

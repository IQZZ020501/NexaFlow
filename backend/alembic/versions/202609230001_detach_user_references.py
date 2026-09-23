"""Detach account references from records that outlive the user.

User deletion is permanent. Historical and authored records (Agent runs and
publications, tool invocations and drafts, knowledge content, workflow
definitions and versions, registered models) and the Agent/Skill/Model
authorship columns keep the former account id as an opaque string, the same way
``audit_logs.actor_user_id`` does, so they no longer block the delete.

Rows that belong to the account itself keep their foreign key and are removed by
``delete_user_permanently``: workspace and team memberships, MCP servers created
by the user, and Agent Skill / Application Tool bindings authorized by the user.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202609230001"
down_revision: str | None = "202609200001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DETACHED_REFERENCES: tuple[tuple[str, str, str], ...] = (
    ("agent_api_credentials", "created_by_user_id", "agent_api_credentials_created_by_user_id_fkey"),
    (
        "agent_publication_versions",
        "published_by_user_id",
        "agent_publication_versions_published_by_user_id_fkey",
    ),
    ("agent_runs", "execution_user_id", "fk_agent_runs_execution_user_id"),
    ("agent_runs", "requested_by_user_id", "agent_runs_requested_by_user_id_fkey"),
    ("agent_skill_versions", "published_by_user_id", "fk_agent_skill_versions_published_by"),
    ("agent_skills", "created_by_user_id", "agent_skills_created_by_user_id_fkey"),
    ("agents", "created_by_user_id", "agents_created_by_user_id_fkey"),
    ("agents", "published_by_user_id", "fk_agents_published_by_user_id"),
    ("knowledge", "created_by_user_id", "knowledge_bases_created_by_user_id_fkey"),
    (
        "knowledge_attachments",
        "created_by_user_id",
        "knowledge_attachments_created_by_user_id_fkey",
    ),
    (
        "knowledge_documents",
        "created_by_user_id",
        "knowledge_documents_created_by_user_id_fkey",
    ),
    (
        "knowledge_evaluation_cases",
        "created_by_user_id",
        "knowledge_evaluation_cases_created_by_user_id_fkey",
    ),
    (
        "knowledge_graph_review_items",
        "created_by_user_id",
        "knowledge_graph_review_items_created_by_user_id_fkey",
    ),
    (
        "knowledge_graph_review_items",
        "reviewed_by_user_id",
        "knowledge_graph_review_items_reviewed_by_user_id_fkey",
    ),
    (
        "knowledge_graph_revisions",
        "created_by_user_id",
        "knowledge_graph_revisions_created_by_user_id_fkey",
    ),
    (
        "knowledge_graph_schemas",
        "created_by_user_id",
        "knowledge_graph_schemas_created_by_user_id_fkey",
    ),
    ("knowledge_tasks", "created_by_user_id", "knowledge_tasks_created_by_user_id_fkey"),
    ("model", "created_by_user_id", "model_registry_models_created_by_user_id_fkey"),
    ("tool_drafts", "updated_by_user_id", "tool_drafts_updated_by_user_id_fkey"),
    ("tool_invocations", "execution_user_id", "tool_invocations_execution_user_id_fkey"),
    (
        "workflow_definitions",
        "updated_by_user_id",
        "workflow_definitions_updated_by_user_id_fkey",
    ),
    (
        "workflow_versions",
        "published_by_user_id",
        "workflow_versions_published_by_user_id_fkey",
    ),
)


def upgrade() -> None:
    for table, _column, constraint in DETACHED_REFERENCES:
        op.drop_constraint(constraint, table, type_="foreignkey")


def downgrade() -> None:
    # Restoring the constraints fails while any detached id has no matching user
    # row, so only run this before the first account deletion.
    for table, column, constraint in DETACHED_REFERENCES:
        op.create_foreign_key(constraint, table, "users", [column], ["id"])

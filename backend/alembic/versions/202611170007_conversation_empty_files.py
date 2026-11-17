"""Keep empty files in uploaded conversation directory trees."""

import sqlalchemy as sa

from alembic import op

revision = "202611170007"
down_revision = "202611170006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("workflow_upload_storage_cleanups") as batch:
        batch.drop_constraint("ck_workflow_upload_cleanups_size", type_="check")
        batch.create_check_constraint(
            "ck_workflow_upload_cleanups_size", "size_bytes >= 0"
        )
    with op.batch_alter_table("workflow_uploads") as batch:
        batch.drop_constraint("ck_workflow_uploads_size", type_="check")
        batch.create_check_constraint("ck_workflow_uploads_size", "size_bytes >= 0")
    with op.batch_alter_table("project_file_versions") as batch:
        batch.drop_constraint("ck_project_file_deleted_size", type_="check")
        batch.create_check_constraint(
            "ck_project_file_deleted_size", "NOT deleted OR size_bytes = 0"
        )


def downgrade():
    empty_file = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM project_file_versions WHERE NOT deleted AND size_bytes = 0 "
                "UNION ALL SELECT 1 FROM workflow_uploads WHERE size_bytes = 0 "
                "UNION ALL SELECT 1 FROM workflow_upload_storage_cleanups WHERE size_bytes = 0 LIMIT 1"
            )
        )
        .first()
    )
    if empty_file is not None:
        raise RuntimeError(
            "Cannot downgrade while conversation history contains empty files."
        )
    with op.batch_alter_table("project_file_versions") as batch:
        batch.drop_constraint("ck_project_file_deleted_size", type_="check")
        batch.create_check_constraint(
            "ck_project_file_deleted_size",
            "(deleted AND size_bytes = 0) OR (NOT deleted AND size_bytes > 0)",
        )
    with op.batch_alter_table("workflow_uploads") as batch:
        batch.drop_constraint("ck_workflow_uploads_size", type_="check")
        batch.create_check_constraint("ck_workflow_uploads_size", "size_bytes > 0")
    with op.batch_alter_table("workflow_upload_storage_cleanups") as batch:
        batch.drop_constraint("ck_workflow_upload_cleanups_size", type_="check")
        batch.create_check_constraint(
            "ck_workflow_upload_cleanups_size", "size_bytes > 0"
        )

"""The empty-file migration preserves bytes and refuses a lossy downgrade."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class MigrationTests(unittest.TestCase):
    def test_empty_files_and_downgrade_guard(self):
        filename = (
            Path(__file__).parents[2]
            / "alembic/versions/202611170007_conversation_empty_files.py"
        )
        spec = importlib.util.spec_from_file_location("empty_files_migration", filename)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = sa.create_engine("sqlite://")
        with engine.begin() as connection:
            connection.execute(
                sa.text("""
                CREATE TABLE workflow_upload_storage_cleanups (
                    id INTEGER PRIMARY KEY, size_bytes INTEGER NOT NULL,
                    CONSTRAINT ck_workflow_upload_cleanups_size CHECK (size_bytes > 0)
                )
            """)
            )
            connection.execute(
                sa.text("""
                CREATE TABLE workflow_uploads (
                    id INTEGER PRIMARY KEY, size_bytes INTEGER NOT NULL,
                    CONSTRAINT ck_workflow_uploads_size CHECK (size_bytes > 0)
                )
            """)
            )
            connection.execute(
                sa.text("""
                CREATE TABLE project_file_versions (
                    id INTEGER PRIMARY KEY, deleted BOOLEAN NOT NULL,
                    size_bytes INTEGER NOT NULL, content BLOB NOT NULL,
                    CONSTRAINT ck_project_file_size CHECK (size_bytes BETWEEN 0 AND 5242880),
                    CONSTRAINT ck_project_file_deleted_size CHECK (
                        (deleted AND size_bytes = 0) OR (NOT deleted AND size_bytes > 0)
                    )
                )
            """)
            )
            connection.execute(
                sa.text(
                    "INSERT INTO project_file_versions VALUES (1, false, 3, :content)"
                ),
                {"content": b"old"},
            )
            with patch.object(
                migration, "op", Operations(MigrationContext.configure(connection))
            ):
                migration.upgrade()
                self.assertEqual(
                    connection.scalar(
                        sa.text(
                            "SELECT content FROM project_file_versions WHERE id = 1"
                        )
                    ),
                    b"old",
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO project_file_versions VALUES (2, false, 0, :content)"
                    ),
                    {"content": b""},
                )
                with self.assertRaisesRegex(RuntimeError, "empty files"):
                    migration.downgrade()
                connection.execute(
                    sa.text("DELETE FROM project_file_versions WHERE id = 2")
                )
                connection.execute(
                    sa.text("INSERT INTO workflow_uploads VALUES (1, 0)")
                )
                with self.assertRaisesRegex(RuntimeError, "empty files"):
                    migration.downgrade()
                connection.execute(sa.text("DELETE FROM workflow_uploads"))
                connection.execute(
                    sa.text(
                        "INSERT INTO workflow_upload_storage_cleanups VALUES (1, 0)"
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "empty files"):
                    migration.downgrade()
                connection.execute(
                    sa.text("DELETE FROM workflow_upload_storage_cleanups")
                )
                migration.downgrade()
                with self.assertRaises(sa.exc.IntegrityError):
                    connection.execute(
                        sa.text(
                            "INSERT INTO project_file_versions VALUES (3, false, 0, :content)"
                        ),
                        {"content": b""},
                    )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()

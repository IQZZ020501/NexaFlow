"""File and chat project migrations preserve existing stored content."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class MigrationTests(unittest.TestCase):
    def test_chat_projects_upgrade_and_downgrade(self):
        filename = (
            Path(__file__).parents[2]
            / "alembic/versions/202611190002_public_chat_projects.py"
        )
        spec = importlib.util.spec_from_file_location(
            "chat_projects_migration", filename
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = sa.create_engine("sqlite://")
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            metadata = sa.MetaData()
            for name in ("workspaces", "agents", "agent_projects"):
                table = sa.Table(
                    name, metadata, sa.Column("id", sa.String(36), primary_key=True)
                )
                table.create(connection)
                connection.execute(table.insert().values(id="existing"))
            with patch.object(
                migration, "op", Operations(MigrationContext.configure(connection))
            ):
                migration.upgrade()
                inspector = sa.inspect(connection)
                self.assertEqual(
                    {
                        column["name"]
                        for column in inspector.get_columns("chat_projects")
                    },
                    {
                        "id",
                        "workspace_id",
                        "agent_id",
                        "owner_user_id",
                        "file_tree_id",
                        "name",
                        "instructions",
                        "archived",
                        "dissolved_at",
                        "created_at",
                        "updated_at",
                    },
                )
                self.assertNotIn(
                    "users",
                    {
                        fk["referred_table"]
                        for fk in inspector.get_foreign_keys("chat_projects")
                    },
                )
                connection.exec_driver_sql("""
                    INSERT INTO chat_projects
                    (id, workspace_id, agent_id, owner_user_id, file_tree_id, name,
                     instructions, archived, created_at, updated_at)
                    VALUES ('project', 'existing', 'existing', 'former-user', 'existing',
                            'Research', '', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """)
                connection.exec_driver_sql("""
                    INSERT INTO chat_conversations
                    (id, workspace_id, agent_id, owner_user_id, conversation_id, project_id, created_at)
                    VALUES ('membership', 'existing', 'existing', 'former-user',
                            'conversation', 'project', CURRENT_TIMESTAMP)
                """)
                connection.exec_driver_sql("DELETE FROM chat_projects")
                self.assertIsNone(
                    connection.scalar(
                        sa.text("SELECT project_id FROM chat_conversations")
                    )
                )
                migration.downgrade()
                self.assertNotIn(
                    "chat_projects", sa.inspect(connection).get_table_names()
                )
                self.assertEqual(
                    connection.scalar(sa.text("SELECT id FROM agent_projects")),
                    "existing",
                )
                migration.upgrade()
                self.assertIn(
                    "chat_conversations", sa.inspect(connection).get_table_names()
                )
        engine.dispose()

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

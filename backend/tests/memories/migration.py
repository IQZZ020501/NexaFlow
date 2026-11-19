"""The memory migration upgrades and removes only its own account-owned data."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class MigrationTests(unittest.TestCase):
    def test_upgrade_cascades_and_downgrade(self):
        filename = (
            Path(__file__).parents[2] / "alembic/versions/202611190004_user_memories.py"
        )
        spec = importlib.util.spec_from_file_location(
            "user_memories_migration", filename
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                metadata = sa.MetaData()
                for name in ("workspaces", "agents", "users", "agent_runs"):
                    table = sa.Table(
                        name, metadata, sa.Column("id", sa.String(36), primary_key=True)
                    )
                    table.create(connection)
                    connection.execute(table.insert().values(id="existing"))
                with patch.object(
                    migration, "op", Operations(MigrationContext.configure(connection))
                ):
                    migration.upgrade()
                    self.assertTrue(
                        {
                            "user_memory_preferences",
                            "user_memories",
                            "user_memory_jobs",
                        }.issubset(sa.inspect(connection).get_table_names())
                    )
                    connection.exec_driver_sql("""
                        INSERT INTO user_memory_preferences
                        (id, workspace_id, user_id, created_at)
                        VALUES ('profile', 'existing', 'existing', CURRENT_TIMESTAMP)
                    """)
                    connection.exec_driver_sql("""
                        INSERT INTO user_memories
                        (id, profile_id, category, key, content, origin,
                         source_created_at, created_at, updated_at)
                        VALUES ('memory', 'profile', 'preference', 'language', 'Chinese',
                                'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """)
                    connection.exec_driver_sql("""
                        INSERT INTO user_memory_jobs
                        (id, profile_id, run_id, epoch, status, available_at)
                        VALUES ('job', 'profile', 'existing', 0, 'pending', CURRENT_TIMESTAMP)
                    """)
                    self.assertEqual(
                        connection.scalar(
                            sa.text("SELECT automatic FROM user_memory_preferences")
                        ),
                        0,
                    )
                    connection.exec_driver_sql("DELETE FROM users")
                    for table in (
                        "user_memory_preferences",
                        "user_memories",
                        "user_memory_jobs",
                    ):
                        self.assertEqual(
                            connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")),
                            0,
                        )
                    migration.downgrade()
                    self.assertNotIn(
                        "user_memories", sa.inspect(connection).get_table_names()
                    )
                    self.assertEqual(
                        connection.scalar(sa.text("SELECT id FROM agents")), "existing"
                    )
                    migration.upgrade()
                    self.assertIn(
                        "user_memories", sa.inspect(connection).get_table_names()
                    )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

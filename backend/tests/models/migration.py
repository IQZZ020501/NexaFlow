"""Existing model access survives upgrades; personal names remain owner-scoped."""

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class ModelMigrationTests(unittest.TestCase):
    def test_upgrade_uniqueness_and_guarded_downgrade(self):
        filename = (
            Path(__file__).parents[2]
            / "alembic/versions/202611220001_personal_models.py"
        )
        spec = importlib.util.spec_from_file_location(
            "personal_models_migration", filename
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = sa.create_engine(
            os.environ.get("MODEL_MIGRATION_TEST_URL", "sqlite://")
        )
        try:
            with engine.begin() as connection:
                metadata = sa.MetaData()
                model = sa.Table(
                    "model",
                    metadata,
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("workspace_id", sa.String(36), nullable=False),
                    sa.Column("created_by_user_id", sa.String(36), nullable=False),
                    sa.Column("name", sa.String(120), nullable=False),
                    sa.UniqueConstraint(
                        "workspace_id",
                        "name",
                        name="uq_model_registry_model_workspace_name",
                    ),
                )
                metadata.create_all(connection)
                connection.execute(
                    model.insert().values(
                        id="legacy",
                        workspace_id="ws",
                        created_by_user_id="admin",
                        name="Chat",
                    )
                )
                with patch.object(
                    migration, "op", Operations(MigrationContext.configure(connection))
                ):
                    migration.upgrade()
                    self.assertEqual(
                        connection.scalar(
                            sa.text("SELECT visibility FROM model WHERE id='legacy'")
                        ),
                        "workspace",
                    )
                    connection.execute(
                        sa.text(
                            "INSERT INTO model (id, workspace_id, created_by_user_id, name, visibility) VALUES ('a', 'ws', 'alice', 'Chat', 'personal'), ('b', 'ws', 'bob', 'Chat', 'personal')"
                        )
                    )
                    for owner, visibility in (
                        ("alice", "personal"),
                        ("admin", "workspace"),
                    ):
                        with (
                            self.assertRaises(sa.exc.IntegrityError),
                            connection.begin_nested(),
                        ):
                            connection.execute(
                                sa.text(
                                    "INSERT INTO model (id, workspace_id, created_by_user_id, name, visibility) VALUES ('duplicate', 'ws', :owner, 'Chat', :visibility)"
                                ),
                                {"owner": owner, "visibility": visibility},
                            )
                    with (
                        self.assertRaises(sa.exc.IntegrityError),
                        connection.begin_nested(),
                    ):
                        connection.execute(
                            sa.text(
                                "INSERT INTO model (id, workspace_id, created_by_user_id, name, visibility) VALUES ('bad', 'ws', 'alice', 'Bad', 'public')"
                            )
                        )
                    with self.assertRaisesRegex(RuntimeError, "personal model"):
                        migration.downgrade()
                    connection.execute(
                        sa.text("DELETE FROM model WHERE visibility = 'personal'")
                    )
                    migration.downgrade()
                    self.assertNotIn(
                        "visibility",
                        {
                            column["name"]
                            for column in sa.inspect(connection).get_columns("model")
                        },
                    )
                    self.assertEqual(
                        connection.scalar(
                            sa.text("SELECT name FROM model WHERE id='legacy'")
                        ),
                        "Chat",
                    )
                    migration.upgrade()
                    self.assertEqual(
                        connection.scalar(
                            sa.text("SELECT visibility FROM model WHERE id='legacy'")
                        ),
                        "workspace",
                    )
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE IF EXISTS model")
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

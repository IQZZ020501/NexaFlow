"""Migration round trips preserve ordinary Runs and fence incompatible rollback."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class MigrationTests(unittest.TestCase):
    def test_upgrade_and_guarded_downgrade(self):
        path = (
            Path(__file__).parents[2]
            / "alembic/versions/202611230001_automations_notifications.py"
        )
        spec = importlib.util.spec_from_file_location("automation_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        engine = sa.create_engine("sqlite://")
        with engine.begin() as db:
            meta = sa.MetaData()
            for name in (
                "users",
                "workspaces",
                "agents",
                "agent_publication_versions",
                "workflow_versions",
            ):
                sa.Table(name, meta, sa.Column("id", sa.String(36), primary_key=True))
            runs = sa.Table(
                "agent_runs",
                meta,
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("access_source", sa.String(20), nullable=False),
                sa.Column("requested_by_user_id", sa.String(36)),
                sa.Column("consumer_id", sa.String(36)),
                sa.Column("execution_user_id", sa.String(36)),
                sa.CheckConstraint(
                    "access_source IN ('console', 'public', 'api')",
                    name="ck_agent_runs_access_source",
                ),
                sa.CheckConstraint(
                    "(access_source = 'console' AND requested_by_user_id = consumer_id AND execution_user_id = consumer_id) OR access_source IN ('public', 'api')",
                    name="ck_agent_runs_access_identity",
                ),
            )
            sa.Table(
                "tool_invocations",
                meta,
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("access_source", sa.String(20), nullable=False),
                sa.CheckConstraint(
                    "access_source IN ('console', 'public', 'api')",
                    name="ck_tool_invocations_access_source",
                ),
            )
            meta.create_all(db)
            ordinary = {
                "id": "ordinary",
                "access_source": "console",
                "requested_by_user_id": "user",
                "consumer_id": "user",
                "execution_user_id": "user",
            }
            db.execute(runs.insert().values(**ordinary))
            with patch.object(module, "op", Operations(MigrationContext.configure(db))):
                module.upgrade()
                self.assertIn("automation_executions", sa.inspect(db).get_table_names())
                self.assertEqual(
                    db.scalar(sa.text("SELECT id FROM agent_runs")), "ordinary"
                )
                # Immutable history retains the departed caller as an opaque id.
                db.execute(
                    runs.insert().values(
                        **{
                            **ordinary,
                            "id": "automatic",
                            "access_source": "automation",
                            "execution_user_id": "publisher",
                        }
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "automation runs"):
                    module.downgrade()
                db.execute(runs.delete().where(runs.c.id == "automatic"))
                module.downgrade()
                self.assertNotIn("automations", sa.inspect(db).get_table_names())
                self.assertEqual(
                    db.scalar(sa.text("SELECT id FROM agent_runs")), "ordinary"
                )
                module.upgrade()
                self.assertIn("user_notifications", sa.inspect(db).get_table_names())


if __name__ == "__main__":
    unittest.main()

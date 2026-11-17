"""Upgrade old file tools, register the missing creator, and retain frozen history."""

from dataclasses import asdict, replace
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domain.tools.catalog.service import (
    build_skill_artifact_tool,
    stable_catalog_id,
)


def check_upgrade(connection):
    """Use a fresh SQLite DB or isolated PostgreSQL temporary tables."""
    workspace = "guide-upgrade-workspace"
    originals = [
        build_skill_artifact_tool(workspace, name)
        for name in ("documents", "pdf", "pptx", "spreadsheets")
    ]
    metadata = sa.MetaData()

    def table(name, sample):
        if sa.inspect(connection).has_table(name):
            return sa.Table(name, metadata, autoload_with=connection)
        types = {
            bool: sa.Boolean,
            int: sa.Integer,
            dict: sa.JSON,
            list: sa.JSON,
            datetime: sa.DateTime,
        }
        return sa.Table(
            name,
            metadata,
            *[
                sa.Column(
                    key, types.get(type(value), sa.String), primary_key=key == "id"
                )
                for key, value in sample.items()
            ],
        )

    tools, versions, policies = [
        table(name, asdict(sample))
        for name, sample in zip(
            ("tools", "tool_versions", "tool_policies"), originals[0], strict=True
        )
    ]
    bindings = table(
        "application_tool_bindings",
        {
            "id": "binding",
            "workspace_id": workspace,
            "tool_id": "",
            "tool_version_id": "",
            "bound_by_user_id": "author",
            "application_id": "fixture-agent",
            "created_at": originals[0][0].created_at,
        },
    )
    metadata.create_all(connection)
    original_policies = {}
    for tool, version, policy in originals:
        old_version = replace(
            version, id=stable_catalog_id("old:" + tool.id), definition_hash="a" * 64
        )
        old_policy = replace(
            policy,
            tool_version_id=old_version.id,
            definition_hash="a" * 64,
            approval="disabled" if tool.function_name == "pdf_skill" else "each_call",
            allowed_access_sources=["console"],
            workflow_callable=True,
            revision=7,
        )
        connection.execute(
            tools.insert().values(
                **asdict(replace(tool, current_version_id=old_version.id))
            )
        )
        connection.execute(versions.insert().values(**asdict(old_version)))
        connection.execute(policies.insert().values(**asdict(old_policy)))
        connection.execute(
            bindings.insert().values(
                id=stable_catalog_id("binding:" + tool.id),
                workspace_id=workspace,
                tool_id=tool.id,
                tool_version_id=old_version.id,
                bound_by_user_id="author",
                application_id="fixture-agent",
                created_at=tool.created_at,
            )
        )
        original_policies[tool.id] = asdict(old_policy)

    source = (
        Path(__file__).parents[2]
        / "alembic/versions/202611170003_builtin_authoring_guides.py"
    )
    spec = spec_from_file_location("guide_upgrade", source)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with patch.object(
        migration, "op", Operations(MigrationContext.configure(connection))
    ):
        migration.upgrade()
        first_versions = list(connection.execute(sa.select(versions)).mappings())
        first_policies = list(connection.execute(sa.select(policies)).mappings())
        assert len(first_versions) == 9
        assert connection.scalar(sa.select(sa.func.count()).select_from(tools)) == 5
        creator, creator_version, _creator_policy = build_skill_artifact_tool(
            workspace, "skill-creator"
        )
        assert (
            connection.scalar(
                sa.select(tools.c.current_version_id).where(tools.c.id == creator.id)
            )
            == creator_version.id
        )
        for tool, version, _policy in originals:
            actual = (
                connection.execute(
                    sa.select(policies).where(policies.c.tool_id == tool.id)
                )
                .mappings()
                .one()
            )
            prior = original_policies[tool.id]
            assert actual["workflow_callable"] is False
            assert actual["revision"] == 8
            assert actual["tool_version_id"] == version.id
            for field in (
                "approval",
                "effect",
                "allowed_access_sources",
                "parallel_safe",
                "reviewed_by_user_id",
            ):
                assert actual[field] == prior[field], field
            assert (
                connection.scalar(
                    sa.select(bindings.c.tool_version_id).where(
                        bindings.c.tool_id == tool.id
                    )
                )
                == version.id
            )
        # Repair a stale editable binding even when the current tool is already upgraded.
        connection.execute(
            bindings.update().values(tool_version_id="older-frozen-binding")
        )
        migration.upgrade()
        for tool, version, _policy in originals:
            assert (
                connection.scalar(
                    sa.select(bindings.c.tool_version_id).where(
                        bindings.c.tool_id == tool.id
                    )
                )
                == version.id
            )
        migration.upgrade()
        migration.downgrade()
        assert (
            list(connection.execute(sa.select(versions)).mappings()) == first_versions
        )
        assert (
            list(connection.execute(sa.select(policies)).mappings()) == first_policies
        )


def test_guide_upgrade():
    with sa.create_engine("sqlite://").begin() as connection:
        check_upgrade(connection)


if __name__ == "__main__":
    test_guide_upgrade()
    print("SKILL_GUIDE_MIGRATION_OK")

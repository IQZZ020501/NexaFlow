"""Use Shanghai time for user-facing and business calendar behavior."""

from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision: str = "202609050001"
down_revision: str | None = "202609040001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Fix governance settings and refresh the built-in current-time tool."""
    bind = op.get_bind()
    op.execute(
        sa.text(
            "UPDATE workspace_governance "
            "SET timezone = 'Asia/Shanghai' "
            "WHERE timezone <> 'Asia/Shanghai'"
        )
    )
    op.alter_column(
        "workspace_governance",
        "timezone",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        server_default="Asia/Shanghai",
    )

    from app.shareddomain.tools.catalog import build_workspace_system_catalog

    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    workspace_ids = bind.execute(
        sa.select(tools.c.workspace_id).where(
            tools.c.stable_key == "current_time"
        )
    ).scalars()
    timestamp = datetime.now(UTC)

    for workspace_id in workspace_ids:
        catalog = build_workspace_system_catalog(workspace_id, timestamp)
        version = catalog.version
        if bind.scalar(
            sa.select(versions.c.id).where(versions.c.id == version.id)
        ) is None:
            revision_no = bind.execute(
                sa.select(
                    sa.func.coalesce(sa.func.max(versions.c.revision), 0) + 1
                ).where(versions.c.tool_id == catalog.tool.id)
            ).scalar_one()
            bind.execute(
                versions.insert().values(
                    **asdict(replace(version, revision=revision_no))
                )
            )
        bind.execute(
            tools.update()
            .where(tools.c.id == catalog.tool.id)
            .values(current_version_id=version.id, updated_at=timestamp)
        )
        bind.execute(
            policies.update()
            .where(policies.c.tool_id == catalog.tool.id)
            .values(
                tool_version_id=version.id,
                definition_hash=version.definition_hash,
                revision=policies.c.revision + 1,
                updated_at=timestamp,
            )
        )
        bind.execute(
            bindings.update()
            .where(bindings.c.tool_id == catalog.tool.id)
            .values(tool_version_id=version.id)
        )


def downgrade() -> None:
    """Restore the legacy governance default and retain immutable tool history."""
    op.execute(sa.text("UPDATE workspace_governance SET timezone = 'UTC'"))
    op.alter_column(
        "workspace_governance",
        "timezone",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        server_default="UTC",
    )

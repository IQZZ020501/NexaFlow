"""Allow image models and register the approval-backed image Tool."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "202609200001"
down_revision: str | None = "202609190002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_model_registry_models_type", "model", type_="check")
    op.create_check_constraint(
        "ck_model_registry_models_type",
        "model",
        "model_type IN ('LLM', 'VISION', 'EMBEDDING', 'RERANKER', 'IMAGE')",
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    inspector = sa.inspect(bind)
    names = ("tool_sources", "tools", "tool_versions", "tool_policies")
    if any(not inspector.has_table(name) for name in names):
        return
    sources, tools, versions, policies = (
        sa.Table(name, metadata, autoload_with=bind) for name in names
    )
    from app.domain.tools.catalog.service import build_image_generation_tool

    workspace_ids = bind.execute(
        sa.select(sources.c.workspace_id)
        .where(sources.c.kind == "builtin")
        .distinct()
    ).scalars()
    timestamp = datetime.now(UTC)
    for workspace_id in workspace_ids:
        tool, version, policy = build_image_generation_tool(workspace_id)
        if bind.scalar(sa.select(tools.c.id).where(tools.c.id == tool.id)) is None:
            values = asdict(tool)
            values["current_version_id"] = None
            values["created_at"] = timestamp
            values["updated_at"] = timestamp
            bind.execute(tools.insert().values(**values))
        if bind.scalar(sa.select(versions.c.id).where(versions.c.id == version.id)) is None:
            values = asdict(version)
            values["created_at"] = timestamp
            bind.execute(versions.insert().values(**values))
        if bind.scalar(sa.select(policies.c.id).where(policies.c.id == policy.id)) is None:
            values = asdict(policy)
            values["created_at"] = timestamp
            values["updated_at"] = timestamp
            bind.execute(policies.insert().values(**values))
        bind.execute(
            tools.update().where(tools.c.id == tool.id).values(
                current_version_id=version.id,
                status="active",
                availability="available",
                updated_at=timestamp,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    model = sa.table("model", sa.column("model_type", sa.String))
    if bind.scalar(
        sa.select(sa.func.count()).select_from(model).where(model.c.model_type == "IMAGE")
    ):
        raise RuntimeError("Disable and remove IMAGE model registrations before downgrading.")
    tools = sa.table(
        "tools",
        sa.column("stable_key", sa.String),
        sa.column("status", sa.String),
        sa.column("availability", sa.String),
    )
    bind.execute(
        tools.update().where(tools.c.stable_key == "image_generation").values(
            status="disabled", availability="unavailable"
        )
    )
    op.drop_constraint("ck_model_registry_models_type", "model", type_="check")
    op.create_check_constraint(
        "ck_model_registry_models_type",
        "model",
        "model_type IN ('LLM', 'VISION', 'EMBEDDING', 'RERANKER')",
    )

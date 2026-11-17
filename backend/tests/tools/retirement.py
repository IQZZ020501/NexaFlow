"""Regression checks for retiring Python Tools and Workflow code nodes."""

import asyncio
from dataclasses import asdict, replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from fastapi import HTTPException
from tests.support import activate_admin, auth_headers, test_client
from tests.tools.fixtures import (
    build_inline_python_tool,
    build_workspace_system_catalog,
)

from app.application.tools.runtime.service import _validate_live_state
from app.domain.tools.access.bindings import build_bindable_tool_snapshot
from app.domain.tools.access.permissions import evaluate_tool_authorization
from app.domain.tools.catalog.service import ensure_workspace_system_catalog
from app.domain.tools.runtime import build_tool_snapshot
from app.entities.identity.user import User
from app.infra.db.repositories.tools import repository
from app.infra.db.session import get_session_factory


def test_retired_capabilities_cannot_be_authorized_bound_or_executed():
    catalog = build_workspace_system_catalog("workspace")
    actor = User(id="owner", is_global_admin=True)
    for tool, version, policy in (
        (catalog.tool, catalog.version, catalog.policy),
        build_inline_python_tool("workspace"),
    ):
        source = next(item for item in catalog.sources if item.id == tool.source_id)
        if tool.kind == "python":
            for candidate in (tool, replace(tool, created_by_user_id=actor.id)):
                authorization = evaluate_tool_authorization(
                    candidate, actor, "admin", None
                )
                assert not authorization.access.can_view
                assert not authorization.access.can_use
                assert not authorization.access.can_manage
        try:
            build_bindable_tool_snapshot(tool, source, version, policy, actor.id)
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("Retired capabilities must not be bindable")
        snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        failure, server = asyncio.run(_validate_live_state(None, None, snapshot))
        assert failure is not None and failure.error_code == "tool_disabled"
        assert server is None


def test_catalog_and_http_exclude_python_before_migration():
    with test_client() as client:
        token, workspace_id = activate_admin(client)
        catalog = build_workspace_system_catalog(workspace_id)

        async def seed_legacy_rows():
            async with get_session_factory()() as db:
                await ensure_workspace_system_catalog(db, workspace_id)
                sources = await repository.list_tool_sources(db, workspace_id)
                assert all(source.kind != "python" for source in sources)
                tools = await repository.list_tools(db, workspace_id)
                assert all(tool.kind != "python" for tool in tools)
                assert all(tool.function_name != "inline_python" for tool in tools)
                await repository.save_tool_source(db, catalog.sources[1])
                await repository.save_tool(
                    db, replace(catalog.tool, current_version_id=None)
                )
                await repository.save_tool_version(db, catalog.version)
                await repository.save_tool_policy(db, catalog.policy)
                await repository.save_tool(db, catalog.tool)
                await db.commit()

        asyncio.run(seed_legacy_rows())
        headers = auth_headers(token)
        for offset in range(6):
            response = client.get(
                f"/api/v1/workspaces/{workspace_id}/tools?limit=1&offset={offset}",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert len(response.json()) == 1, response.text
            assert response.json()[0]["kind"] != "python"
        response = client.get(
            f"/api/v1/workspaces/{workspace_id}/tools/{catalog.tool.id}",
            headers=headers,
        )
        assert response.status_code == 404, response.text
        for method, suffix in (
            ("POST", "/python"),
            ("PUT", f"/{catalog.tool.id}/draft"),
            ("POST", f"/{catalog.tool.id}/tests"),
            ("GET", f"/{catalog.tool.id}/tests/invocation"),
            ("POST", f"/{catalog.tool.id}/publish"),
            ("POST", f"/{catalog.tool.id}/enable"),
            ("POST", f"/{catalog.tool.id}/disable"),
            ("DELETE", f"/{catalog.tool.id}"),
        ):
            response = client.request(
                method,
                f"/api/v1/workspaces/{workspace_id}/tools{suffix}",
                headers=headers,
                json={},
            )
            assert response.status_code in {404, 405}, (method, suffix, response.text)


def test_retirement_migration_preserves_history_and_other_tools():
    spec = spec_from_file_location(
        "retire_python_tools",
        Path(__file__).resolve().parents[2]
        / "alembic/versions/202611170004_retire_python_tools.py",
    )
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = sa.MetaData()
    sources = sa.Table(
        "tool_sources",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("kind", sa.String),
        sa.Column("status", sa.String),
        sa.Column("updated_at", sa.DateTime),
    )
    tools = sa.Table(
        "tools",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("kind", sa.String),
        sa.Column("function_name", sa.String),
        sa.Column("status", sa.String),
        sa.Column("availability", sa.String),
        sa.Column("updated_at", sa.DateTime),
    )
    bindings = sa.Table(
        "application_tool_bindings",
        metadata,
        sa.Column("tool_id", sa.String, primary_key=True),
    )
    sa.Table("tool_drafts", metadata, sa.Column("id", sa.String, primary_key=True))
    history = sa.Table(
        "tool_versions",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("snapshot", sa.JSON),
    )
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sources.insert(),
            [
                {"id": kind, "kind": kind, "status": "active"}
                for kind in ("python", "builtin", "mcp")
            ],
        )
        connection.execute(
            tools.insert(),
            [
                {
                    "id": name,
                    "kind": kind,
                    "function_name": name,
                    "status": "active",
                    "availability": "available",
                }
                for name, kind in (
                    ("custom", "python"),
                    ("inline_python", "builtin"),
                    ("bash", "builtin"),
                    ("remote", "mcp"),
                )
            ],
        )
        connection.execute(
            bindings.insert(),
            [
                {"tool_id": name}
                for name in ("custom", "inline_python", "bash", "remote")
            ],
        )
        payload = asdict(build_workspace_system_catalog("workspace").version)
        payload["created_at"] = payload["created_at"].isoformat()
        connection.execute(history.insert().values(id="historical", snapshot=payload))
        migration.op = SimpleNamespace(get_bind=lambda: connection)
        migration.upgrade()
        assert "tool_drafts" not in sa.inspect(connection).get_table_names()
        assert set(connection.scalars(sa.select(bindings.c.tool_id))) == {
            "bash",
            "remote",
        }
        rows = {row.id: row for row in connection.execute(sa.select(tools))}
        for name in ("custom", "inline_python"):
            assert rows[name].status == "archived"
            assert rows[name].availability == "unavailable"
        assert rows["bash"].status == rows["remote"].status == "active"
        assert connection.scalar(sa.select(history.c.snapshot)) == payload
        migration.downgrade()
        assert (
            connection.scalar(sa.select(tools.c.status).where(tools.c.id == "custom"))
            == "archived"
        )
    engine.dispose()


def test_python_nodes_are_rejected_by_the_workflow_schema():
    from app.schemas.workflows.contracts import WorkflowGraph

    try:
        WorkflowGraph.model_validate(
            {
                "nodes": [
                    {
                        "id": "removed",
                        "type": "workflow",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "code", "title": "Old code", "config": {}},
                    }
                ],
                "edges": [],
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("A removed Python code node entered the runtime graph")


def main():
    test_retired_capabilities_cannot_be_authorized_bound_or_executed()
    test_catalog_and_http_exclude_python_before_migration()
    test_retirement_migration_preserves_history_and_other_tools()
    test_python_nodes_are_rejected_by_the_workflow_schema()
    print("Python Tool retirement regressions passed")


if __name__ == "__main__":
    main()

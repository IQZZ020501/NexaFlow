"""Existing workspaces must receive updated built-ins before creating new Runs."""

import asyncio
from contextlib import ExitStack
from dataclasses import asdict, replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from tests.agents.agents import (
    AgentModelHandler,
    agent_model_server,
    agents_url,
    model_payload,
)
from tests.support import activate_admin, auth_headers, test_client

from app.application.agents.access import service as agent_access
from app.application.agents.runs import service as agent_runs
from app.domain.tools.catalog import service as catalog
from app.infra.db.repositories.tools import repository
from app.infra.db.session import get_session_factory


def test_existing_file_catalog_upgrade():
    builders = {
        name: getattr(catalog, name)
        for name in ("build_shell_tool", "build_skill_artifact_tool", "build_image_generation_tool")
    }

    def legacy(builder):
        def build(*args, **kwargs):
            tool, version, policy = builder(*args, **kwargs)
            identity = catalog.stable_catalog_id(f"legacy-file-delivery:{tool.id}")
            if tool.function_name == "generate_image":
                tool = replace(tool, availability="unavailable")
                policy = replace(policy, approval="disabled")
            return (
                replace(tool, current_version_id=identity),
                replace(version, id=identity, description="Legacy file delivery", definition_hash="a" * 64),
                replace(policy, tool_version_id=identity, definition_hash="a" * 64,
                        revision=4, approval="disabled" if policy.approval == "disabled" else "each_call",
                        allowed_access_sources=["console", "public"]),
            )
        return build

    path = Path(__file__).parents[2] / "alembic/versions/202611170001_builtin_file_delivery_catalog.py"
    spec = spec_from_file_location("builtin_file_delivery_catalog", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "202611160006"

    async def inspect(workspace_id):
        async with get_session_factory()() as db:
            tools = await repository.list_tools(db, workspace_id)
            versions = [asdict(version) for tool in tools for version in await repository.list_tool_versions(db, workspace_id, tool.id)]
            policies = {tool.id: asdict(await repository.get_tool_policy(db, workspace_id, tool.id)) for tool in tools}
            bindings = [tuple(row) for row in await db.execute(sa.text("SELECT id, tool_id, tool_version_id, bound_by_user_id FROM application_tool_bindings ORDER BY id"))]
            snapshots = [tuple(row) for row in await db.execute(sa.text("SELECT * FROM agent_run_snapshots ORDER BY run_id"))]
            publications = [tuple(row) for row in await db.execute(sa.text("SELECT * FROM agent_publication_versions ORDER BY id"))]
            return tools, versions, policies, bindings, snapshots, publications

    async def upgrade():
        async with get_session_factory()() as db:
            connection = await db.connection()
            def execute(sync_connection):
                with patch.object(migration, "op", Operations(MigrationContext.configure(sync_connection))):
                    migration.upgrade()
            await connection.run_sync(execute)
            await db.commit()

    with test_client() as client, agent_model_server() as model_url:
        with ExitStack() as stack:
            for name, builder in builders.items():
                stack.enter_context(patch.object(catalog, name, legacy(builder)))
            token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(f"/api/v1/workspaces/{workspace_id}/models", headers=headers,
                            json=model_payload(model_url, "Catalog Upgrade Model"))
        assert model.status_code == 201, model.text
        tools = client.get(f"/api/v1/workspaces/{workspace_id}/tools", headers=headers).json()
        references = [{"tool_id": tool["id"], "version_id": tool["current_version_id"]}
                      for tool in tools if tool["function_name"] in {"documents_skill", "pdf_skill", "pptx_skill", "spreadsheets_skill"}]
        assert len(references) == 4
        agent = client.post(agents_url(workspace_id), headers=headers,
                            json={"name": "Existing File Agent", "model_id": model.json()["id"], "tools": references})
        assert agent.status_code == 201, agent.text
        agent_id = agent.json()["id"]
        published = client.patch(agents_url(workspace_id, f"/{agent_id}"), headers=headers, json={"published": True})
        assert published.status_code == 200, published.text
        run_url = agents_url(workspace_id, f"/{agent_id}/runs")
        with (
            patch.object(agent_access, "enqueue_prepared_agent_run"),
            patch.object(agent_runs, "enqueue_prepared_agent_run"),
        ):
            with patch.object(agent_runs, "build_shell_tool", legacy(builders["build_shell_tool"])):
                old_run = client.post(run_url, headers=headers, json={"goal": "Saved historical configuration"})
                assert old_run.status_code == 201, old_run.text
            failed = client.post(run_url, headers=headers, json={"goal": "Reproduce version mismatch"})
            assert failed.status_code == 422, failed.text
            assert failed.json()["detail"] == "Tool version is not available for binding."
            before = asyncio.run(inspect(workspace_id))
            model_calls = len(AgentModelHandler.calls)
            asyncio.run(upgrade())
            created = client.post(run_url, headers=headers, json={"goal": "New run after catalog upgrade"})
            assert created.status_code == 201, created.text
            assert len(AgentModelHandler.calls) == model_calls
        after = asyncio.run(inspect(workspace_id))
        before_tools, old_versions, old_policies, old_bindings, old_snapshots, old_publications = before
        after_tools, new_versions, new_policies, new_bindings, new_snapshots, new_publications = after
        assert all(version in new_versions for version in old_versions)
        assert len(new_versions) == len(old_versions) + 6
        assert all(snapshot in new_snapshots for snapshot in old_snapshots)
        assert new_publications == old_publications
        changed_ids = {tool.id for tool in after_tools
                       if tool.current_version_id != next(old.current_version_id for old in before_tools if old.id == tool.id)}
        assert len(changed_ids) == 6
        for tool in after_tools:
            old_tool = next(old for old in before_tools if old.id == tool.id)
            assert (tool.status, tool.availability) == (old_tool.status, old_tool.availability)
            prior = old_policies[tool.id]
            policy = new_policies[tool.id]
            for key in prior.keys() - {"tool_version_id", "definition_hash", "revision", "updated_at"}:
                assert policy[key] == prior[key], key
            assert policy["revision"] == prior["revision"] + int(tool.id in changed_ids)
            assert policy["tool_version_id"] == tool.current_version_id
        assert [row[:2] + row[3:] for row in old_bindings] == [row[:2] + row[3:] for row in new_bindings]
        versions_by_tool = {tool.id: tool.current_version_id for tool in after_tools}
        assert all(row[2] == versions_by_tool[row[1]] for row in new_bindings)
        asyncio.run(upgrade())
        assert asyncio.run(inspect(workspace_id)) == after


if __name__ == "__main__":
    test_existing_file_catalog_upgrade()
    print("BUILTIN_FILE_CATALOG_UPGRADE_OK")

"""Upgrade existing MCP policies without weakening binding or frozen Run checks."""

import asyncio
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from tests.support import activate_admin, auth_headers, test_client

from app.domain.tools.access.bindings import (
    build_bindable_tool_snapshot,
    resolve_tool_refs_for_actor,
)
from app.entities.defaults import new_id, utc_now
from app.entities.tools import ToolRef
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.tools import repository
from app.infra.db.session import get_session_factory


def test_existing_mcp_approval_upgrade():
    path = (
        Path(__file__).parents[2]
        / "alembic/versions/202611190003_mcp_conversation_approval.py"
    )
    spec = spec_from_file_location("mcp_approval_upgrade", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "202611190002"

    cases = (
        "changed",
        "hash_only",
        "policy_disabled",
        "tool_disabled",
        "archived",
        "current",
    )
    discovery = SimpleNamespace(
        tools=[
            {"name": name, "description": name, "input_schema": {"type": "object"}}
            for name in cases
        ]
    )
    with (
        test_client() as client,
        patch(
            "app.domain.tools.mcp.service.discover_mcp_tools",
            new=AsyncMock(return_value=discovery),
        ),
    ):
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        actor_id = client.get("/api/v1/auth/me", headers=headers).json()["user"]["id"]
        root = f"/api/v1/workspaces/{workspace_id}"
        created = client.post(
            root + "/tool-sources/mcp",
            headers=headers,
            json={"name": "Existing MCP", "url": "https://tools.example.com/mcp"},
        )
        assert created.status_code == 201, created.text
        source_id = created.json()["id"]

        async def check():
            async with get_session_factory()() as db:
                source = await repository.get_tool_source(db, workspace_id, source_id)
                tools = await repository.list_tools_by_source(
                    db, workspace_id, source_id
                )
                actor = await users.get_user_by_id(db, actor_id)
                before = {}
                for tool in tools:
                    name = tool.stable_key
                    version = await repository.get_tool_version(
                        db, workspace_id, tool.current_version_id
                    )
                    policy = await repository.get_tool_policy(db, workspace_id, tool.id)
                    policy.approval = (
                        "disabled" if name == "policy_disabled" else "auto"
                    )
                    policy.effect = "external_read"
                    policy.allowed_access_sources = ["console", "public", "api"]
                    policy.parallel_safe = True
                    policy.reviewed_by_user_id = actor_id
                    policy.reviewed_at = utc_now()
                    if name == "hash_only":
                        policy.definition_hash = "a" * 64
                    elif name != "current":
                        version = replace(
                            version,
                            id=new_id(),
                            revision=version.revision + 1,
                            description="Changed " + name,
                            definition_hash=sha256(name.encode()).hexdigest(),
                        )
                        await repository.save_tool_version(db, version)
                        tool.current_version_id = version.id
                    if name == "tool_disabled":
                        tool.status = "disabled"
                    elif name == "archived":
                        tool.status = "archived"
                        tool.availability = "unavailable"
                    await repository.save_tool(db, tool)
                    await repository.save_tool_policy(db, policy)
                    before[name] = (tool, version, asdict(policy))
                await db.commit()
                db.expire_all()
                for name, (tool, version, _) in before.items():
                    policy = await repository.get_tool_policy(db, workspace_id, tool.id)
                    before[name] = (tool, version, asdict(policy))

                for name in ("changed", "hash_only"):
                    tool, version, _ = before[name]
                    try:
                        await resolve_tool_refs_for_actor(
                            db,
                            workspace_id,
                            [ToolRef(tool_id=tool.id, version_id=version.id)],
                            actor,
                            "admin",
                        )
                    except HTTPException as exc:
                        assert exc.detail == "Tool is not available for binding."
                    else:
                        raise AssertionError(
                            "The stale policy fixture must reproduce binding failure."
                        )

                connection = await db.connection()

                def upgrade(sync_connection):
                    with patch.object(
                        migration,
                        "op",
                        Operations(MigrationContext.configure(sync_connection)),
                    ):
                        migration.upgrade()

                await connection.run_sync(upgrade)
                await db.commit()
                db.expire_all()
                after = {}
                for name, (tool, version, prior) in before.items():
                    policy = await repository.get_tool_policy(db, workspace_id, tool.id)
                    after[name] = asdict(policy)
                    stored_version = await repository.get_tool_version(
                        db, workspace_id, version.id
                    )
                    assert asdict(stored_version) == asdict(version)
                    if name in {"archived", "current"}:
                        assert asdict(policy) == prior
                        continue
                    assert policy.tool_version_id == version.id
                    assert policy.definition_hash == version.definition_hash
                    assert policy.revision == prior["revision"] + 1
                    assert policy.effect == "unknown"
                    assert not policy.parallel_safe
                    assert (
                        policy.reviewed_by_user_id is None
                        and policy.reviewed_at is None
                    )
                    if name in {"policy_disabled", "tool_disabled"}:
                        assert policy.approval == "disabled"
                        assert policy.allowed_access_sources == []
                        assert not policy.workflow_callable
                        try:
                            build_bindable_tool_snapshot(
                                tool, source, version, policy, actor_id
                            )
                        except HTTPException as exc:
                            assert exc.status_code == 422
                        else:
                            raise AssertionError(
                                "Upgrade must not re-enable disabled tools."
                            )
                    else:
                        assert policy.approval == "each_call"
                        assert policy.allowed_access_sources == ["console", "public"]
                        snapshots = await resolve_tool_refs_for_actor(
                            db,
                            workspace_id,
                            [ToolRef(tool_id=tool.id, version_id=version.id)],
                            actor,
                            "admin",
                        )
                        assert len(snapshots) == 1
                        assert snapshots[0].policy_revision == policy.revision

                # Replaying the migration is idempotent and a downgrade never
                # restores an automatic grant to an unreviewed definition.
                connection = await db.connection()
                await connection.run_sync(upgrade)
                migration.downgrade()
                await db.commit()
                for name, (tool, _version, _prior) in before.items():
                    policy = await repository.get_tool_policy(db, workspace_id, tool.id)
                    assert asdict(policy) == after[name]

        asyncio.run(check())


if __name__ == "__main__":
    test_existing_mcp_approval_upgrade()
    print("MCP_APPROVAL_UPGRADE_OK")

"""Personal MCP/Skill configuration, sharing boundaries and name migration."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine
from tests.support import activate_admin, auth_headers, create_active_user, test_client

from app.ports.mcp import McpDiscovery


def test_personal_configuration() -> None:
    with test_client() as client:
        admin, workspace_id = activate_admin(client)
        people = [create_active_user(client, admin, f"personal-{i}") for i in range(2)]
        for index, (user_id, _) in enumerate(people):
            response = client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=auth_headers(admin),
                json={"user_id": user_id, "role": "admin" if index else "member"},
            )
            assert response.status_code == 201, response.text
        prefix = f"/api/v1/workspaces/{workspace_id}"
        discovery = AsyncMock(
            return_value=McpDiscovery(
                tools=[
                    {
                        "name": "lookup",
                        "description": "Look up my account",
                        "input_schema": {"type": "object"},
                    }
                ]
            )
        )
        sources, servers, skills = [], [], []
        with patch("app.domain.tools.mcp.service.discover_mcp_tools", discovery):
            for user_id, token in people:
                headers = auth_headers(token)
                source = client.post(
                    f"{prefix}/tool-sources/mcp",
                    headers=headers,
                    json={
                        "name": "My connection",
                        "url": "https://mcp.example.com/mcp",
                        "bearer_token": f"token-for-{user_id}",
                    },
                )
                assert source.status_code == 201, source.text
                sources.append(source.json())
                own = client.get(f"{prefix}/mcp-servers", headers=headers)
                assert own.status_code == 200 and len(own.json()) == 1, own.text
                servers.append(own.json()[0])
                # A duplicate in the same owner's namespace remains an error.
                duplicate = client.post(
                    f"{prefix}/tool-sources/mcp",
                    headers=headers,
                    json={
                        "name": "My connection",
                        "url": "https://mcp.example.com/mcp",
                    },
                )
                assert duplicate.status_code == 409, duplicate.text
                skill = client.post(
                    f"{prefix}/agent-skills",
                    headers=headers,
                    json={
                        "name": "My skill",
                        "description": "Personal instructions",
                        "definition": {
                            "instructions": "Use my connection.",
                            "tools": [],
                            "knowledge_base_ids": [],
                        },
                    },
                )
                assert skill.status_code == 201, skill.text
                skills.append(skill.json())
                duplicate_skill = client.post(
                    f"{prefix}/agent-skills",
                    headers=headers,
                    json={
                        "name": "My skill",
                        "description": "Duplicate",
                        "definition": {"instructions": "Other"},
                    },
                )
                assert duplicate_skill.status_code == 409, duplicate_skill.text

            for index, (_, token) in enumerate(people):
                headers = auth_headers(token)
                own_sources = client.get(
                    f"{prefix}/tool-sources?limit=1", headers=headers
                )
                assert [item["id"] for item in own_sources.json()] == [
                    sources[index]["id"]
                ]
                own_skills = client.get(
                    f"{prefix}/agent-skills?limit=1", headers=headers
                )
                assert [item["id"] for item in own_skills.json()] == [
                    skills[index]["id"]
                ]
                hidden_source = sources[1 - index]["id"]
                hidden_server = servers[1 - index]["id"]
                hidden_skill = skills[1 - index]["id"]
                for suffix in (
                    f"tool-sources/{hidden_source}/refresh",
                    f"tool-sources/{hidden_source}/disable",
                    f"mcp-servers/{hidden_server}/refresh",
                ):
                    assert (
                        client.post(f"{prefix}/{suffix}", headers=headers).status_code
                        == 404
                    )
                assert (
                    client.delete(
                        f"{prefix}/tool-sources/{hidden_source}", headers=headers
                    ).status_code
                    == 404
                )
                assert (
                    client.get(
                        f"{prefix}/agent-skills/{hidden_skill}", headers=headers
                    ).status_code
                    == 404
                )
                assert (
                    client.patch(
                        f"{prefix}/agent-skills/{hidden_skill}",
                        headers=headers,
                        json={"name": "Changed by another person"},
                    ).status_code
                    == 404
                )

            root_headers = auth_headers(admin)
            assert (
                client.get(f"{prefix}/mcp-servers", headers=root_headers).json() == []
            )
            assert (
                client.get(f"{prefix}/agent-skills", headers=root_headers).json() == []
            )
            assert (
                client.post(
                    f"{prefix}/mcp-servers/{servers[0]['id']}/disable",
                    headers=root_headers,
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"{prefix}/agent-skills/{skills[0]['id']}/publish",
                    headers=root_headers,
                ).status_code
                == 404
            )
            owner_headers = auth_headers(people[0][1])
            grantee_headers = auth_headers(people[1][1])
            grant = client.put(
                f"{prefix}/agent-skills/{skills[0]['id']}/permissions/{people[1][0]}",
                headers=owner_headers,
                json={"permission": "use"},
            )
            assert grant.status_code == 200, grant.text
            shared = client.get(
                f"{prefix}/agent-skills/{skills[0]['id']}", headers=grantee_headers
            )
            assert shared.status_code == 200 and not shared.json()["can_manage"], (
                shared.text
            )
            denied_edit = client.patch(
                f"{prefix}/agent-skills/{skills[0]['id']}",
                headers=grantee_headers,
                json={"name": "Still cannot edit"},
            )
            assert denied_edit.status_code == 403, denied_edit.text
            assert denied_edit.json()["detail"] == "Agent Skill owner required."
            tools = client.get(f"{prefix}/tools", headers=owner_headers).json()
            tool = next(item for item in tools if item["kind"] == "mcp")
            for mode in ("disabled", "read_only"):
                policy = client.put(
                    f"{prefix}/tools/{tool['id']}/policy",
                    headers=owner_headers,
                    json={"mode": mode},
                )
                assert policy.status_code == 200, policy.text
            refreshed = client.post(
                f"{prefix}/tool-sources/{sources[0]['id']}/refresh",
                headers=owner_headers,
            )
            assert refreshed.status_code == 200, refreshed.text
            assert (
                discovery.await_args.args[0].bearer_token == f"token-for-{people[0][0]}"
            )


async def test_personal_name_migration() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/202610250003_personal_resource_names.py"
    )
    spec = importlib.util.spec_from_file_location("personal_names", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:

            def check(sync):
                for table, old, _, columns in migration._CONSTRAINTS:
                    extra = ", kind TEXT NOT NULL" if table == "tool_sources" else ""
                    sync.exec_driver_sql(
                        f"CREATE TABLE {table} (workspace_id TEXT NOT NULL, name TEXT NOT NULL, "
                        f"created_by_user_id TEXT{extra}, CONSTRAINT {old} UNIQUE ({', '.join(columns)}))"
                    )
                    fields = "workspace_id, name, created_by_user_id" + (
                        ", kind" if extra else ""
                    )
                    values = "'ws', 'same', 'owner-a'" + (", 'mcp'" if extra else "")
                    sync.exec_driver_sql(
                        f"INSERT INTO {table} ({fields}) VALUES ({values})"
                    )
                with patch.object(
                    migration, "op", Operations(MigrationContext.configure(sync))
                ):
                    migration.upgrade()
                    for table, _, _, _ in migration._CONSTRAINTS:
                        fields = "workspace_id, name, created_by_user_id" + (
                            ", kind" if table == "tool_sources" else ""
                        )
                        values = "'ws', 'same', 'owner-b'" + (
                            ", 'mcp'" if table == "tool_sources" else ""
                        )
                        sync.exec_driver_sql(
                            f"INSERT INTO {table} ({fields}) VALUES ({values})"
                        )
                        assert (
                            sync.exec_driver_sql(
                                f"SELECT count(*) FROM {table}"
                            ).scalar()
                            == 2
                        )
                    try:
                        migration.downgrade()
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError(
                            "Downgrade lost conflicting personal names"
                        )
                    for table, _, _, _ in migration._CONSTRAINTS:
                        sync.exec_driver_sql(
                            f"DELETE FROM {table} WHERE created_by_user_id = 'owner-b'"
                        )
                    migration.downgrade()
                    migration.upgrade()

            await connection.run_sync(check)
    finally:
        await engine.dispose()


def main() -> None:
    test_personal_configuration()
    asyncio.run(test_personal_name_migration())
    print("PERSONAL_TOOLS_OK")


if __name__ == "__main__":
    main()

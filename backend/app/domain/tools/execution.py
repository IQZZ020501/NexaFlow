"""Conservative environment demand for a frozen capability catalog."""

from app.infra.db.repositories.tools import mcp as repository
from app.infra.execution.profile import sandbox_resource_profile


async def sandbox_requirements(db, tools, skills, legacy_mcp=()):
    servers = {
        item.get("execution_spec", {}).get("server_id")
        for item in tools
        if item.get("kind") == "mcp"
    } | {item.get("server_id") for item in legacy_mcp}
    stdio = False
    for identity in servers - {None, ""}:
        server = await repository.get_mcp_server_by_id(db, identity)
        stdio = stdio or bool(server and server.transport == "stdio")
    profiles = [sandbox_resource_profile(tools, skills)]
    if stdio:
        profiles.append("standard")
    return {"schema_version": 1, "profiles": profiles, "max_stdio_hosts": int(stdio)}

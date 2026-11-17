from fastapi import HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.domain.tools.catalog.service import reconcile_mcp_discovery
from app.domain.tools.mcp.service import get_mcp_server
from app.domain.tools.mcp.task_contract import apply_task_contracts
from app.infra.db.repositories.tools import mcp as repository
from app.infra.db.repositories.tools import repository as tools
from app.infra.db.repositories.workspaces import repository as workspaces


async def configuration(db, workspace_id, server_id, actor, role):
    server = await get_mcp_server(db, workspace_id, server_id, actor, role)
    return {
        "tools": [item["name"] for item in server.tools],
        "contracts": server.long_task_contracts,
    }


async def configure(db, workspace_id, server_id, actor, role, payload):
    await workspaces.lock_workspace(db, workspace_id)
    server = await get_mcp_server(db, workspace_id, server_id, actor, role)
    if server.transport == "stdio":
        raise HTTPException(
            422, "Durable remote jobs require a remote HTTP MCP source."
        )
    by_name = {item["name"]: item for item in server.tools}
    for submit, contract in payload.contracts.items():
        controls = [contract.status_tool, contract.result_tool, contract.cancel_tool]
        if (
            submit not in by_name
            or any(name in payload.contracts for name in controls)
            or any(name not in by_name for name in controls)
        ):
            raise HTTPException(
                422,
                "Long-task tools must exist in the same source and use distinct operations.",
            )
        for name in controls:
            try:
                schema = (
                    by_name[name].get("input_schema")
                    or by_name[name].get("inputSchema")
                    or {}
                )
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema).validate(
                    {
                        "request_id": "nexaflow-contract-check",
                        "task_id": "task-contract-check",
                    }
                )
                Draft202012Validator(schema).validate(
                    {"request_id": "nexaflow-contract-check", "task_id": None}
                )
            except (SchemaError, ValidationError) as exc:
                raise HTTPException(
                    422, "Control tools must accept request_id and a nullable task_id."
                ) from exc
    server.long_task_contracts = payload.model_dump()["contracts"]
    definitions = apply_task_contracts(server.tools, server.long_task_contracts)
    sources = await tools.list_mcp_tool_sources(db, workspace_id, server.id)
    if not sources:
        raise HTTPException(404, "MCP source is unavailable.")
    source = sources[0]
    await reconcile_mcp_discovery(db, server, source, definitions)
    server.tools = definitions
    await repository.save_mcp_server(db, server)
    await db.commit()
    return await configuration(db, workspace_id, server_id, actor, role)

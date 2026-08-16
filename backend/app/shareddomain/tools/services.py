import hashlib
import json
from dataclasses import dataclass
from typing import cast

from fastapi import HTTPException, status
from mcp.types import Tool as McpTool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ports.mcp import (
    McpConnection,
    McpClientError,
    McpTransport,
    discover_mcp_tools,
    normalize_mcp_url,
)
from app.entities.tools import McpServer, McpToolPolicy
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.repositories import mcp as mcp_repository
from app.infrastructure.model_utils import utc_now
from app.infrastructure.mcp_stdio import (
    McpStdioConfig,
    McpStdioConfigError,
    parse_mcp_stdio_config,
    serialize_mcp_stdio_config,
)
from app.infrastructure.secrets import decrypt_secret, encrypt_secret, secret_hint
from app.infrastructure.validation import normalize_name
from app.schemas.mcp import (
    McpServerCreateRequest,
    McpServerResponse,
)
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.tools.catalog import (
    ToolCatalogDetail,
    ToolCatalogItem,
    get_tool_catalog_detail,
    list_tool_catalog,
    tombstone_mcp_server_catalog,
)
from app.shareddomain.tools.permissions import (
    ToolAuthorization,
    ToolPermissionEntry,
    evaluate_tool_authorization,
    has_tool_workspace_access,
    list_tool_permissions,
    require_tool_manage,
    require_tool_use,
    require_tool_view,
    revoke_tool_permission,
    upsert_tool_permission,
)


@dataclass(frozen=True)
class ResolvedMcpTool:
    server: McpServer
    definition: McpTool


def mcp_tool_definition_hash(definition: McpTool) -> str:
    payload = {
        "name": definition.name,
        "description": definition.description or "",
        "input_schema": definition.input_schema,
        "annotations": (
            definition.annotations.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
            if definition.annotations is not None
            else None
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def effective_mcp_tool_policy_mode(
    definition: McpTool,
    policy: McpToolPolicy | None,
) -> str:
    definition_hash = mcp_tool_definition_hash(definition)
    if policy is not None:
        return (
            policy.mode
            if policy.definition_hash == definition_hash
            else "approval_required"
        )
    return "approval_required"


def _mcp_tool_definition(tool: dict) -> McpTool:
    return McpTool(
        name=str(tool.get("name") or ""),
        description=str(tool.get("description") or ""),
        input_schema=tool.get("input_schema") or {"type": "object"},
        annotations=tool.get("annotations"),
    )


def mcp_server_to_response(
    server: McpServer,
    policies: list[McpToolPolicy] | None = None,
) -> McpServerResponse:
    policy_map = {
        (policy.mcp_server_id, policy.tool_name): policy
        for policy in policies or []
    }
    tools = []
    for tool in server.tools:
        definition = _mcp_tool_definition(tool)
        definition_hash = mcp_tool_definition_hash(definition)
        policy = policy_map.get((server.id, str(tool.get("name") or "")))
        tools.append(
            {
                **tool,
                "definition_hash": definition_hash,
                "policy_mode": effective_mcp_tool_policy_mode(definition, policy),
            }
        )
    return McpServerResponse(
        id=server.id,
        workspace_id=server.workspace_id,
        name=server.name,
        transport=server.transport,
        url=server.url,
        stdio_command=server.stdio_command,
        tools=tools,
        status=server.status,
        has_bearer_token=server.bearer_token_ciphertext is not None,
        bearer_token_hint=server.bearer_token_hint,
        last_error=server.last_error,
        created_by_user_id=server.created_by_user_id,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def bearer_token(server: McpServer, settings: Settings) -> str | None:
    if server.bearer_token_ciphertext is None:
        return None
    return decrypt_secret(server.bearer_token_ciphertext, settings.model_secret_key)


def stdio_config(server: McpServer, settings: Settings) -> McpStdioConfig | None:
    if server.stdio_config_ciphertext is None:
        return None
    try:
        return parse_mcp_stdio_config(
            decrypt_secret(
                server.stdio_config_ciphertext,
                settings.model_secret_key,
            )
        )
    except McpStdioConfigError as exc:
        raise McpClientError("Stored MCP stdio configuration is invalid.") from exc


def mcp_server_connection(
    server: McpServer,
    settings: Settings,
) -> McpConnection:
    return McpConnection(
        transport=cast(McpTransport, server.transport),
        url=server.url,
        bearer_token=bearer_token(server, settings),
        stdio_config=stdio_config(server, settings),
    )


async def list_mcp_servers(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[McpServerResponse]:
    policies = await mcp_repository.list_mcp_tool_policies(db, workspace_id)
    return [
        mcp_server_to_response(server, policies)
        for server in await mcp_repository.list_mcp_servers(
            db,
            workspace_id,
            limit,
            offset,
        )
    ]


async def get_mcp_server(
    db: AsyncSession,
    workspace_id: str,
    server_id: str,
) -> McpServer:
    server = await mcp_repository.get_mcp_server_by_id(db, server_id)
    if server is None or server.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found.")
    return server


async def create_mcp_server(
    db: AsyncSession,
    workspace_id: str,
    payload: McpServerCreateRequest,
    actor: User,
    settings: Settings,
) -> McpServerResponse:
    try:
        token = payload.bearer_token.strip() if payload.bearer_token else None
        url = (
            normalize_mcp_url(
                payload.url or "",
                preserve_trailing_slash=payload.transport == "sse",
            )
            if payload.transport != "stdio"
            else None
        )
        direct_stdio_config = (
            parse_mcp_stdio_config(payload.stdio_config.model_dump())
            if payload.transport == "stdio" and payload.stdio_config
            else None
        )
        discovery = await discover_mcp_tools(
            McpConnection(
                transport=payload.transport,
                url=url,
                bearer_token=token,
                stdio_config=direct_stdio_config,
            ),
            settings,
        )
    except (McpClientError, McpStdioConfigError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    server = McpServer(
        workspace_id=workspace_id,
        name=normalize_name(payload.name),
        transport=payload.transport,
        url=url,
        stdio_command=(
            direct_stdio_config.command if direct_stdio_config is not None else None
        ),
        stdio_config_ciphertext=(
            encrypt_secret(
                serialize_mcp_stdio_config(direct_stdio_config),
                settings.model_secret_key,
            )
            if direct_stdio_config is not None
            else None
        ),
        tools=discovery.tools,
        status="active",
        created_by_user_id=actor.id,
    )
    if token:
        server.bearer_token_ciphertext = encrypt_secret(token, settings.model_secret_key)
        server.bearer_token_hint = secret_hint(token)
    try:
        server = await mcp_repository.create_mcp_server(db, server)
        record_audit_log(
            db,
            actor,
            "mcp_server.create",
            "mcp_server",
            server.id,
            server.name,
            {
                "transport": server.transport,
                "url": server.url,
                "stdio_command": server.stdio_command,
                "tool_count": len(server.tools),
            },
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "MCP server name already exists.",
        ) from exc
    server = await mcp_repository.refresh_mcp_server(db, server)
    policies = await mcp_repository.list_mcp_tool_policies(db, server.workspace_id)
    return mcp_server_to_response(server, policies)


async def refresh_mcp_server(
    db: AsyncSession,
    server: McpServer,
    actor: User,
    settings: Settings,
) -> McpServerResponse:
    try:
        discovery = await discover_mcp_tools(
            mcp_server_connection(server, settings),
            settings,
        )
        server.tools = discovery.tools
        server.last_error = None
    except McpClientError as exc:
        server.last_error = str(exc)
        await mcp_repository.save_mcp_server(db, server)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    record_audit_log(
        db,
        actor,
        "mcp_server.refresh",
        "mcp_server",
        server.id,
        server.name,
        {"transport": server.transport, "tool_count": len(server.tools)},
        workspace_id=server.workspace_id,
    )
    await mcp_repository.save_mcp_server(db, server)
    await db.commit()
    server = await mcp_repository.refresh_mcp_server(db, server)
    policies = await mcp_repository.list_mcp_tool_policies(db, server.workspace_id)
    return mcp_server_to_response(server, policies)


async def delete_mcp_server(
    db: AsyncSession,
    server: McpServer,
    actor: User,
) -> None:
    record_audit_log(
        db,
        actor,
        "mcp_server.delete",
        "mcp_server",
        server.id,
        server.name,
        workspace_id=server.workspace_id,
    )
    await tombstone_mcp_server_catalog(db, server.workspace_id, server.id)
    await mcp_repository.delete_mcp_server(db, server)
    await db.commit()


async def resolve_mcp_tools(
    db: AsyncSession,
    workspace_id: str,
    references: list[dict[str, str]],
    *,
    strict: bool,
) -> list[ResolvedMcpTool]:
    pairs = [(item["server_id"], item["tool_name"]) for item in references]
    if len(set(pairs)) != len(pairs):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Agent MCP tools must be unique.",
        )
    servers = await mcp_repository.list_mcp_servers_by_ids(
        db,
        workspace_id,
        list({server_id for server_id, _ in pairs}),
    )
    server_map = {server.id: server for server in servers}
    resolved: list[ResolvedMcpTool] = []
    for server_id, tool_name in pairs:
        server = server_map.get(server_id)
        tool = (
            next(
                (item for item in server.tools if item.get("name") == tool_name),
                None,
            )
            if server and server.status == "active"
            else None
        )
        if tool is None:
            if strict:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Agent MCP tool is not available.",
                )
            continue
        resolved.append(
            ResolvedMcpTool(
                server=server,
                definition=McpTool(
                    name=tool_name,
                    description=str(tool.get("description") or ""),
                    input_schema=tool.get("input_schema") or {"type": "object"},
                    annotations=tool.get("annotations"),
                ),
            )
        )
    return resolved


async def get_mcp_tool_policy(
    db: AsyncSession,
    workspace_id: str,
    server_id: str,
    tool_name: str,
) -> McpToolPolicy | None:
    return await mcp_repository.get_mcp_tool_policy(
        db, workspace_id, server_id, tool_name
    )


async def set_mcp_tool_policy(
    db: AsyncSession,
    server: McpServer,
    tool_name: str,
    mode: str,
    actor: User,
) -> McpToolPolicy:
    tool = next((item for item in server.tools if item.get("name") == tool_name), None)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP tool not found.")
    definition = _mcp_tool_definition(tool)
    policy = McpToolPolicy(
        workspace_id=server.workspace_id,
        mcp_server_id=server.id,
        tool_name=tool_name,
        definition_hash=mcp_tool_definition_hash(definition),
        mode=mode,
        reviewed_by_user_id=actor.id,
        reviewed_at=utc_now(),
    )
    policy = await mcp_repository.save_mcp_tool_policy(db, policy)
    record_audit_log(
        db,
        actor,
        "mcp_tool.policy.update",
        "mcp_tool_policy",
        policy.id,
        f"{server.name} / {tool_name}",
        {
            "mcp_server_id": server.id,
            "tool_name": tool_name,
            "mode": mode,
            "definition_hash": policy.definition_hash,
        },
        workspace_id=server.workspace_id,
    )
    return policy

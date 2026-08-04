from dataclasses import dataclass

from fastapi import HTTPException, status
from mcp.types import Tool as McpTool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.mcp.client import (
    McpClientError,
    discover_mcp_tools,
    normalize_mcp_url,
)
from app.domain.user import User
from app.infrastructure.config import Settings
from app.infrastructure.repositories import mcp as mcp_repository
from app.infrastructure.secrets import decrypt_secret, encrypt_secret, secret_hint
from app.infrastructure.validation import normalize_name
from app.schemas.mcp import McpServerCreateRequest, McpServerResponse
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.tools.models import McpServer


@dataclass(frozen=True)
class ResolvedMcpTool:
    server: McpServer
    definition: McpTool


def mcp_server_to_response(server: McpServer) -> McpServerResponse:
    return McpServerResponse(
        id=server.id,
        workspace_id=server.workspace_id,
        name=server.name,
        url=server.url,
        tools=server.tools,
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


async def list_mcp_servers(
    db: AsyncSession,
    workspace_id: str,
) -> list[McpServerResponse]:
    return [
        mcp_server_to_response(server)
        for server in await mcp_repository.list_mcp_servers(db, workspace_id)
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
        url = normalize_mcp_url(payload.url)
        token = payload.bearer_token.strip() if payload.bearer_token else None
        tools = await discover_mcp_tools(
            url,
            token,
            settings.mcp_allow_private_networks,
            settings.mcp_request_timeout_seconds,
        )
    except McpClientError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    server = McpServer(
        workspace_id=workspace_id,
        name=normalize_name(payload.name),
        url=url,
        tools=tools,
        status="active",
        created_by_user_id=actor.id,
    )
    if token:
        server.bearer_token_ciphertext = encrypt_secret(token, settings.model_secret_key)
        server.bearer_token_hint = secret_hint(token)
    db.add(server)
    try:
        await db.flush()
        record_audit_log(
            db,
            actor,
            "mcp_server.create",
            "mcp_server",
            server.id,
            server.name,
            {"url": server.url, "tool_count": len(server.tools)},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "MCP server name already exists.",
        ) from exc
    await db.refresh(server)
    return mcp_server_to_response(server)


async def refresh_mcp_server(
    db: AsyncSession,
    server: McpServer,
    actor: User,
    settings: Settings,
) -> McpServerResponse:
    try:
        server.tools = await discover_mcp_tools(
            server.url,
            bearer_token(server, settings),
            settings.mcp_allow_private_networks,
            settings.mcp_request_timeout_seconds,
        )
        server.last_error = None
    except McpClientError as exc:
        server.last_error = str(exc)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    record_audit_log(
        db,
        actor,
        "mcp_server.refresh",
        "mcp_server",
        server.id,
        server.name,
        {"tool_count": len(server.tools)},
        workspace_id=server.workspace_id,
    )
    await db.commit()
    await db.refresh(server)
    return mcp_server_to_response(server)


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
    await mcp_repository.delete_mcp_server(db, server.id)
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
                ),
            )
        )
    return resolved

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, cast

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
from app.entities.tools import McpServer, McpToolPolicy, ToolPolicy, ToolSource
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.repositories import mcp as mcp_repository
from app.infrastructure.repositories import resource_permission as permission_repository
from app.infrastructure.repositories import tools as tools_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
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
    McpCatalogLeaf,
    ToolCatalogDetail,
    ToolCatalogItem,
    get_mcp_catalog_leaf,
    get_tool_catalog_detail,
    legacy_mcp_policy_mode,
    list_mcp_catalog_leaves,
    list_tool_catalog,
    mcp_catalog_leaf_definition,
    reconcile_mcp_discovery,
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
    tool_id: str = ""
    tool_version_id: str = ""
    function_name: str = ""


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
    leaves: list[McpCatalogLeaf] | None = None,
) -> McpServerResponse:
    tools = []
    for leaf in leaves or []:
        if leaf.tool.availability != "available":
            continue
        definition = mcp_catalog_leaf_definition(leaf)
        tools.append(
            {
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
                "definition_hash": leaf.version.definition_hash,
                "policy_mode": legacy_mcp_policy_mode(leaf),
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
        network_policy=cast(
            Literal["public_only", "deployment"],
            server.network_policy,
        ),
    )


def _is_workspace_admin(actor: User, workspace_role: str | None) -> bool:
    return actor.is_global_admin or workspace_role == "admin"


async def _mcp_server_response(
    db: AsyncSession,
    server: McpServer,
) -> McpServerResponse:
    leaves = await list_mcp_catalog_leaves(
        db,
        server.workspace_id,
        server.id,
        available_only=True,
    )
    return mcp_server_to_response(server, leaves)


async def list_mcp_servers(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int | None = None,
    offset: int = 0,
) -> list[McpServerResponse]:
    return [
        await _mcp_server_response(db, server)
        for server in await mcp_repository.list_manageable_mcp_servers(
            db,
            workspace_id,
            actor.id,
            _is_workspace_admin(actor, workspace_role),
            limit,
            offset,
        )
    ]


async def get_mcp_server(
    db: AsyncSession,
    workspace_id: str,
    server_id: str,
    actor: User | None = None,
    workspace_role: str | None = None,
) -> McpServer:
    server = await mcp_repository.get_mcp_server_by_id(db, server_id)
    if server is None or server.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found.")
    if actor is not None and not _is_workspace_admin(actor, workspace_role):
        source_rows = await tools_repository.list_mcp_tool_sources(
            db,
            workspace_id,
            server_id,
        )
        source = source_rows[0] if source_rows else None
        if source is None or source.created_by_user_id != actor.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found.")
    return server


async def _require_mcp_source_manager(
    db: AsyncSession,
    server: McpServer,
    actor: User,
    workspace_role: str | None,
) -> ToolSource:
    sources = await tools_repository.list_mcp_tool_sources(
        db,
        server.workspace_id,
        server.id,
    )
    source = sources[0] if sources else None
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found.")
    if (
        not _is_workspace_admin(actor, workspace_role)
        and source.created_by_user_id != actor.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found.")
    return source


async def create_mcp_server(
    db: AsyncSession,
    workspace_id: str,
    payload: McpServerCreateRequest,
    actor: User,
    settings: Settings,
    workspace_role: str | None = None,
) -> McpServerResponse:
    is_admin = _is_workspace_admin(actor, workspace_role)
    if payload.transport == "stdio" and not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Workspace admin required for MCP stdio sources.",
        )
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
        server = McpServer(
            workspace_id=workspace_id,
            name=normalize_name(payload.name),
            transport=payload.transport,
            network_policy="deployment" if is_admin else "public_only",
            url=url,
            stdio_command=(
                direct_stdio_config.command
                if direct_stdio_config is not None
                else None
            ),
            stdio_config_ciphertext=(
                encrypt_secret(
                    serialize_mcp_stdio_config(direct_stdio_config),
                    settings.model_secret_key,
                )
                if direct_stdio_config is not None
                else None
            ),
            tools=[],
            status="active",
            created_by_user_id=actor.id,
        )
        if token:
            server.bearer_token_ciphertext = encrypt_secret(
                token, settings.model_secret_key
            )
            server.bearer_token_hint = secret_hint(token)
        discovery = await discover_mcp_tools(
            McpConnection(
                transport=cast(McpTransport, server.transport),
                url=server.url,
                bearer_token=token,
                stdio_config=direct_stdio_config,
                network_policy=cast(
                    Literal["public_only", "deployment"],
                    server.network_policy,
                ),
            ),
            settings,
        )
    except (McpClientError, McpStdioConfigError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    try:
        server = await mcp_repository.create_mcp_server(db, server)
        source = await tools_repository.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=server.id,
                kind="mcp",
                name=server.name,
                status="active",
                created_by_user_id=actor.id,
            ),
        )
        await reconcile_mcp_discovery(db, server, source, discovery.tools)
        server.tools = discovery.tools
        await mcp_repository.save_mcp_server(db, server)
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
    return await _mcp_server_response(db, server)


async def refresh_mcp_server(
    db: AsyncSession,
    server: McpServer,
    actor: User,
    settings: Settings,
    workspace_role: str | None = None,
) -> McpServerResponse:
    source = await _require_mcp_source_manager(db, server, actor, workspace_role)
    try:
        discovery = await discover_mcp_tools(
            mcp_server_connection(server, settings),
            settings,
        )
    except McpClientError as exc:
        server.last_error = str(exc)
        await mcp_repository.save_mcp_server(db, server)
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await reconcile_mcp_discovery(db, server, source, discovery.tools)
    server.tools = discovery.tools
    server.last_error = None
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
    return await _mcp_server_response(db, server)


async def delete_mcp_server(
    db: AsyncSession,
    server: McpServer,
    actor: User,
    workspace_role: str | None = None,
) -> None:
    await _require_mcp_source_manager(db, server, actor, workspace_role)
    await _delete_mcp_server_records(db, server, actor)
    await db.commit()


async def _delete_mcp_server_records(
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


async def delete_owned_mcp_servers_for_user(
    db: AsyncSession,
    user_id: str,
    actor: User,
) -> None:
    for server in await mcp_repository.list_mcp_servers_by_creator(db, user_id):
        await _delete_mcp_server_records(db, server, actor)


async def set_mcp_server_enabled(
    db: AsyncSession,
    server: McpServer,
    enabled: bool,
    actor: User,
    workspace_role: str | None = None,
) -> McpServerResponse:
    source = await _require_mcp_source_manager(db, server, actor, workspace_role)
    target_status = "active" if enabled else "disabled"
    source.status = target_status
    server.status = target_status
    for tool in await tools_repository.list_tools_by_source(
        db,
        server.workspace_id,
        source.id,
    ):
        policy = await tools_repository.get_tool_policy(
            db,
            server.workspace_id,
            tool.id,
        )
        tool.status = (
            "disabled"
            if not enabled or (policy is not None and policy.approval == "disabled")
            else "active"
        )
        await tools_repository.save_tool(db, tool)
    await tools_repository.save_tool_source(db, source)
    await mcp_repository.save_mcp_server(db, server)
    record_audit_log(
        db,
        actor,
        "mcp_server.enable" if enabled else "mcp_server.disable",
        "mcp_server",
        server.id,
        server.name,
        workspace_id=server.workspace_id,
    )
    await db.commit()
    server = await mcp_repository.refresh_mcp_server(db, server)
    return await _mcp_server_response(db, server)


async def resolve_mcp_tools(
    db: AsyncSession,
    workspace_id: str,
    references: list[dict[str, str]],
    *,
    strict: bool,
    actor: User | None = None,
    workspace_role: str | None = None,
    application_id: str | None = None,
) -> list[ResolvedMcpTool]:
    if actor is not None and application_id is not None:
        raise ValueError("Resolve MCP Tools by actor or application, not both.")
    if references and actor is None and application_id is None:
        raise ValueError("MCP Tool resolution requires an authorization context.")
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
        leaf = (
            await get_mcp_catalog_leaf(db, workspace_id, server_id, tool_name)
            if server is not None and server.status == "active"
            else None
        )
        if (
            leaf is None
            or leaf.source.status != "active"
            or leaf.tool.status != "active"
            or leaf.tool.availability != "available"
        ):
            if strict:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Agent MCP tool is not available.",
                )
            continue
        try:
            authorization_actor = actor
            authorization_role = workspace_role
            if application_id is not None:
                binding = await tools_repository.get_application_tool_binding(
                    db,
                    workspace_id,
                    application_id,
                    leaf.tool.id,
                )
                if (
                    binding is None
                    or binding.tool_version_id != leaf.version.id
                ):
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found.")
                authorization_actor = await user_repository.get_user_by_id(
                    db,
                    binding.bound_by_user_id,
                )
                membership = (
                    await workspace_repository.get_workspace_membership(
                        db,
                        workspace_id,
                        binding.bound_by_user_id,
                    )
                    if authorization_actor is not None
                    else None
                )
                authorization_role = membership.role if membership is not None else None
            if authorization_actor is not None:
                grant = await permission_repository.get_user_grant(
                    db,
                    workspace_id,
                    "tool",
                    leaf.tool.id,
                    authorization_actor.id,
                )
                require_tool_use(
                    evaluate_tool_authorization(
                        leaf.tool,
                        authorization_actor,
                        authorization_role,
                        grant,
                    )
                )
            elif application_id is not None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found.")
        except HTTPException:
            if strict:
                raise
            continue
        resolved.append(
            ResolvedMcpTool(
                server=server,
                definition=mcp_catalog_leaf_definition(leaf),
                tool_id=leaf.tool.id,
                tool_version_id=leaf.version.id,
                function_name=leaf.tool.function_name,
            )
        )
    return resolved


def _legacy_mcp_policy(leaf: McpCatalogLeaf) -> McpToolPolicy | None:
    if leaf.policy is None:
        return None
    return McpToolPolicy(
        id=leaf.policy.id,
        workspace_id=leaf.tool.workspace_id,
        mcp_server_id=leaf.source.mcp_server_id or "",
        tool_name=leaf.tool.stable_key,
        definition_hash=(
            leaf.version.definition_hash
            if legacy_mcp_policy_mode(leaf) == "disabled"
            else leaf.policy.definition_hash
        ),
        mode=legacy_mcp_policy_mode(leaf),
        reviewed_by_user_id=leaf.policy.reviewed_by_user_id,
        reviewed_at=leaf.policy.reviewed_at,
        created_at=leaf.policy.created_at,
        updated_at=leaf.policy.updated_at,
    )


async def get_mcp_tool_policy(
    db: AsyncSession,
    workspace_id: str,
    server_id: str,
    tool_name: str,
) -> McpToolPolicy | None:
    leaf = await get_mcp_catalog_leaf(db, workspace_id, server_id, tool_name)
    return _legacy_mcp_policy(leaf) if leaf is not None else None


async def set_mcp_tool_policy(
    db: AsyncSession,
    server: McpServer,
    tool_name: str,
    mode: str,
    actor: User,
    workspace_role: str | None = None,
) -> McpToolPolicy:
    source = await _require_mcp_source_manager(db, server, actor, workspace_role)
    leaf = await get_mcp_catalog_leaf(
        db,
        server.workspace_id,
        server.id,
        tool_name,
    )
    if leaf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP tool not found.")
    is_admin = _is_workspace_admin(actor, workspace_role)
    if mode == "disabled" and not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Workspace admin required to disable an MCP Tool.",
        )
    if leaf.tool.status == "disabled" and not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Workspace admin disabled this MCP Tool.",
        )

    effective_mode = mode
    if effective_mode == "read_only":
        approval = "auto"
        effect = "external_read"
        allowed_access_sources = ["console", "public", "api"]
        workflow_callable = True
        parallel_safe = True
    elif effective_mode == "disabled":
        approval = "disabled"
        effect = "unknown"
        allowed_access_sources = []
        workflow_callable = False
        parallel_safe = False
    else:
        approval = "each_call"
        effect = "unknown"
        allowed_access_sources = ["console"]
        workflow_callable = False
        parallel_safe = False

    policy = leaf.policy
    expected_revision = policy.revision if policy is not None else None
    if policy is None:
        policy = ToolPolicy(
            workspace_id=server.workspace_id,
            tool_id=leaf.tool.id,
            tool_version_id=leaf.version.id,
            definition_hash=leaf.version.definition_hash,
        )
    policy.tool_version_id = leaf.version.id
    policy.definition_hash = leaf.version.definition_hash
    policy.revision = expected_revision + 1 if expected_revision is not None else 1
    policy.approval = approval
    policy.effect = effect
    policy.allowed_access_sources = allowed_access_sources
    policy.workflow_callable = workflow_callable
    policy.parallel_safe = parallel_safe
    policy.reviewed_by_user_id = actor.id
    policy.reviewed_at = utc_now()
    policy.updated_at = policy.reviewed_at
    if expected_revision is None:
        try:
            policy = await tools_repository.save_tool_policy(db, policy)
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "MCP Tool policy was updated concurrently.",
            ) from exc
    else:
        saved_policy = await tools_repository.update_tool_policy_if_revision(
            db,
            policy,
            expected_revision,
        )
        if saved_policy is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "MCP Tool policy was updated concurrently.",
            )
        policy = saved_policy
    leaf.tool.status = "disabled" if effective_mode == "disabled" else "active"
    await tools_repository.save_tool(db, leaf.tool)
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
            "mode": effective_mode,
            "definition_hash": policy.definition_hash,
        },
        workspace_id=server.workspace_id,
    )
    projected = McpCatalogLeaf(
        source=source,
        tool=leaf.tool,
        version=leaf.version,
        policy=policy,
    )
    legacy_policy = _legacy_mcp_policy(projected)
    assert legacy_policy is not None
    return legacy_policy

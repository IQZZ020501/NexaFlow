"""Unified Tool catalog, Python lifecycle, test, and grant use cases."""

from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.tool_runtime import queue_tool_invocation
from app.entities.tools import McpServer, ToolDraft, ToolInvocation, ToolSource
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import tools as tool_repository
from app.infrastructure.tool_dispatch import enqueue_tool_invocation
from app.ports.tool_runtime import ToolInvocationContext
from app.schemas.mcp import McpServerCreateRequest, McpServerResponse
from app.schemas.tool import (
    PythonToolCreateRequest,
    PythonToolDraftUpdateRequest,
    ToolDetailResponse,
    ToolDraftResponse,
    ToolInvocationResponse,
    ToolPermissionResponse,
    ToolSourceDetailResponse,
    ToolSummaryResponse,
)
from app.schemas.user import user_to_response
from app.shareddomain.tools.catalog import (
    ToolCatalogDetail,
    ToolCatalogItem,
    get_tool_catalog_detail,
    list_tool_catalog,
)
from app.shareddomain.tools.permissions import (
    list_tool_permissions,
    require_managed_tool,
    require_tool_manage,
    revoke_tool_permission,
    upsert_tool_permission,
)
from app.shareddomain.tools.python_tools import (
    archive_python_tool,
    build_python_test_snapshot,
    create_python_tool,
    publish_python_tool,
    set_python_tool_enabled,
    update_python_tool_draft,
)
from app.shareddomain.tools.services import (
    create_mcp_server,
    delete_mcp_server,
    get_mcp_server,
    list_mcp_servers,
    refresh_mcp_server,
    set_mcp_server_enabled,
    set_mcp_tool_policy,
)
from app.shareddomain.tools.runtime import validate_tool_arguments


async def list_tools(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int,
    offset: int,
) -> list[ToolSummaryResponse]:
    items = await list_tool_catalog(
        db,
        workspace_id,
        actor,
        workspace_role,
        limit,
        offset,
    )
    return [_summary_response(item) for item in items]


async def get_tool(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
) -> ToolDetailResponse:
    detail = await get_tool_catalog_detail(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
    )
    return _detail_response(detail)


def _source_response(
    source: ToolSource,
    server: McpServerResponse,
) -> ToolSourceDetailResponse:
    return ToolSourceDetailResponse(
        id=source.id,
        workspace_id=source.workspace_id,
        name=source.name,
        kind="mcp",
        transport=server.transport,
        status=source.status,
        url=server.url,
        stdio_command=server.stdio_command,
        has_bearer_token=server.has_bearer_token,
        bearer_token_hint=server.bearer_token_hint,
        last_error=server.last_error,
        created_by_user_id=source.created_by_user_id,
        created_at=source.created_at,
        updated_at=source.updated_at,
        tool_count=len(server.tools),
    )


async def _mcp_source(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
    actor: User,
    workspace_role: str | None,
) -> tuple[ToolSource, McpServer]:
    source = await tool_repository.get_tool_source(db, workspace_id, source_id)
    if source is None or source.kind != "mcp" or not source.mcp_server_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool source not found.")
    server = await get_mcp_server(
        db,
        workspace_id,
        source.mcp_server_id,
        actor,
        workspace_role,
    )
    return source, server


async def list_sources(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int,
    offset: int,
) -> list[ToolSourceDetailResponse]:
    servers = await list_mcp_servers(
        db,
        workspace_id,
        actor,
        workspace_role,
        limit,
        offset,
    )
    sources = {
        source.mcp_server_id: source
        for source in await tool_repository.list_mcp_tool_sources(db, workspace_id)
    }
    return [
        _source_response(sources[server.id], server)
        for server in servers
        if server.id in sources
    ]


async def create_mcp_source(
    db: AsyncSession,
    workspace_id: str,
    payload: McpServerCreateRequest,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> ToolSourceDetailResponse:
    server = await create_mcp_server(
        db,
        workspace_id,
        payload,
        actor,
        settings,
        workspace_role,
    )
    sources = await tool_repository.list_mcp_tool_sources(db, workspace_id, server.id)
    if not sources:  # pragma: no cover - source and server are committed together
        raise RuntimeError("Created MCP source is missing.")
    return _source_response(sources[0], server)


async def refresh_source(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> ToolSourceDetailResponse:
    source, server = await _mcp_source(
        db, workspace_id, source_id, actor, workspace_role
    )
    response = await refresh_mcp_server(
        db, server, actor, settings, workspace_role
    )
    source = await tool_repository.get_tool_source(db, workspace_id, source.id)
    if source is None:  # pragma: no cover - refresh does not delete its source
        raise RuntimeError("Refreshed MCP source is missing.")
    return _source_response(source, response)


async def set_source_enabled(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
    enabled: bool,
    actor: User,
    workspace_role: str | None,
) -> ToolSourceDetailResponse:
    source, server = await _mcp_source(
        db, workspace_id, source_id, actor, workspace_role
    )
    response = await set_mcp_server_enabled(
        db, server, enabled, actor, workspace_role
    )
    source = await tool_repository.get_tool_source(db, workspace_id, source.id)
    if source is None:  # pragma: no cover - enable does not delete its source
        raise RuntimeError("Updated MCP source is missing.")
    return _source_response(source, response)


async def delete_source(
    db: AsyncSession,
    workspace_id: str,
    source_id: str,
    actor: User,
    workspace_role: str | None,
) -> None:
    _source, server = await _mcp_source(
        db, workspace_id, source_id, actor, workspace_role
    )
    await delete_mcp_server(db, server, actor, workspace_role)


async def create_python(
    db: AsyncSession,
    workspace_id: str,
    payload: PythonToolCreateRequest,
    actor: User,
    workspace_role: str | None,
) -> ToolDetailResponse:
    tool, _draft = await create_python_tool(
        db,
        workspace_id,
        actor,
        workspace_role,
        **payload.model_dump(),
    )
    return await get_tool(db, workspace_id, tool.id, actor, workspace_role)


async def update_python_draft(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    payload: PythonToolDraftUpdateRequest,
    actor: User,
    workspace_role: str | None,
) -> ToolDraftResponse:
    draft = await update_python_tool_draft(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        **payload.model_dump(),
    )
    return _draft_response(draft)


async def publish_python(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
) -> ToolDetailResponse:
    await publish_python_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
    )
    return await get_tool(db, workspace_id, tool_id, actor, workspace_role)


async def set_python_enabled(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    enabled: bool,
    actor: User,
    workspace_role: str | None,
) -> ToolDetailResponse:
    await set_python_tool_enabled(
        db,
        workspace_id,
        tool_id,
        enabled,
        actor,
        workspace_role,
    )
    return await get_tool(db, workspace_id, tool_id, actor, workspace_role)


async def delete_python(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
) -> None:
    await archive_python_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
    )


async def update_policy(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    mode: str,
    actor: User,
    workspace_role: str | None,
) -> ToolDetailResponse:
    detail = await get_tool_catalog_detail(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
    )
    require_tool_manage(detail.authorization)
    if detail.tool.kind != "mcp" or not detail.source.mcp_server_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only MCP Tool policy can be changed.",
        )
    server = await get_mcp_server(
        db,
        workspace_id,
        detail.source.mcp_server_id,
        actor,
        workspace_role,
    )
    await set_mcp_tool_policy(
        db,
        server,
        detail.tool.stable_key,
        mode,
        actor,
        workspace_role,
    )
    await db.commit()
    return await get_tool(db, workspace_id, tool_id, actor, workspace_role)


async def queue_python_test(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    arguments: dict[str, Any],
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> ToolInvocationResponse:
    snapshot = await build_python_test_snapshot(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
    )
    try:
        validate_tool_arguments(snapshot, arguments)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Tool arguments are invalid.",
        ) from exc
    invocation_id = new_id()
    invocation = await queue_tool_invocation(
        db,
        snapshot,
        arguments,
        ToolInvocationContext(
            workspace_id=workspace_id,
            origin="test",
            root_run_id=None,
            run_id=None,
            invocation_id=invocation_id,
            execution_user_id=actor.id,
            access_source="console",
            deadline_at=utc_now() + timedelta(seconds=settings.agent_run_timeout_seconds),
            idempotency_key=f"tool-test:{invocation_id}",
        ),
    )
    await db.commit()
    await enqueue_tool_invocation(invocation.id, settings)
    return _invocation_response(invocation)


async def get_python_test(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    invocation_id: str,
    actor: User,
    workspace_role: str | None,
) -> ToolInvocationResponse:
    await require_managed_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=False,
    )
    invocation = await tool_repository.get_tool_invocation(
        db,
        workspace_id,
        invocation_id,
    )
    if invocation is None or invocation.origin != "test" or invocation.tool_id != tool_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool test not found.")
    return _invocation_response(invocation)


async def list_permissions(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int,
    offset: int,
) -> list[ToolPermissionResponse]:
    entries = await list_tool_permissions(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        limit,
        offset,
    )
    return [
        ToolPermissionResponse(
            user=user_to_response(entry.user),
            permission=entry.grant.permission,
        )
        for entry in entries
    ]


async def upsert_permission(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    target_user_id: str,
    permission: str,
    actor: User,
    workspace_role: str | None,
) -> ToolPermissionResponse:
    entry = await upsert_tool_permission(
        db,
        workspace_id,
        tool_id,
        target_user_id,
        permission,
        actor,
        workspace_role,
    )
    return ToolPermissionResponse(
        user=user_to_response(entry.user),
        permission=entry.grant.permission,
    )


async def revoke_permission(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    target_user_id: str,
    actor: User,
    workspace_role: str | None,
) -> None:
    await revoke_tool_permission(
        db,
        workspace_id,
        tool_id,
        target_user_id,
        actor,
        workspace_role,
    )


def _summary_response(item: ToolCatalogItem) -> ToolSummaryResponse:
    definition = item.version or (item.draft if item.access.can_manage else None)
    return ToolSummaryResponse(
        id=item.tool.id,
        workspace_id=item.tool.workspace_id,
        folder_id=item.tool.folder_id,
        kind=item.tool.kind,
        function_name=item.tool.function_name,
        display_name=definition.display_name if definition else item.tool.function_name,
        description=definition.description if definition else "",
        current_version_id=item.tool.current_version_id,
        status=item.tool.status,
        availability=item.tool.availability,
        source={
            "id": item.source.id,
            "name": item.source.name,
            "kind": item.source.kind,
        },
        created_by_user_id=item.tool.created_by_user_id,
        permission=item.permission,
        can_view=item.access.can_view,
        can_use=item.access.can_use,
        can_manage=item.access.can_manage,
    )


def _detail_response(detail: ToolCatalogDetail) -> ToolDetailResponse:
    summary = _summary_response(
        ToolCatalogItem(
            tool=detail.tool,
            source=detail.source,
            version=detail.version,
            draft=detail.draft,
            access=detail.access,
            permission=detail.permission,
        )
    )
    version = detail.version
    policy = detail.policy
    return ToolDetailResponse(
        **summary.model_dump(),
        version_id=version.id if version else None,
        revision=version.revision if version else None,
        input_schema=version.input_schema if version else None,
        output_schema=version.output_schema if version else None,
        approval=policy.approval if policy else None,
        effect=policy.effect if policy else None,
        workflow_callable=policy.workflow_callable if policy else False,
        parallel_safe=policy.parallel_safe if policy else False,
        draft=(
            _draft_response(detail.draft)
            if detail.access.can_manage and detail.draft is not None
            else None
        ),
    )


def _draft_response(draft: ToolDraft) -> ToolDraftResponse:
    code = draft.execution_spec.get("code")
    return ToolDraftResponse(
        display_name=draft.display_name,
        description=draft.description,
        input_schema=draft.input_schema,
        output_schema=draft.output_schema,
        code=code if isinstance(code, str) else "",
        revision=draft.revision,
        updated_at=draft.updated_at,
    )


def _invocation_response(invocation: ToolInvocation) -> ToolInvocationResponse:
    return ToolInvocationResponse(
        id=invocation.id,
        tool_id=invocation.tool_id,
        tool_version_id=invocation.tool_version_id,
        status=invocation.status,
        attempts=invocation.attempts,
        result_data=invocation.result_data,
        result_summary=invocation.result_summary,
        outcome=invocation.outcome,
        error_code=invocation.error_code,
        error_message=invocation.error_message,
        usage=invocation.usage,
        created_at=invocation.created_at,
        started_at=invocation.started_at,
        finished_at=invocation.finished_at,
    )


__all__ = [
    "create_python",
    "delete_python",
    "get_python_test",
    "get_tool",
    "list_permissions",
    "list_tools",
    "publish_python",
    "queue_python_test",
    "revoke_permission",
    "set_python_enabled",
    "update_python_draft",
    "upsert_permission",
]

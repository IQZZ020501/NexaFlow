"""Creator-owned MCP connection management; credentials never leave the server."""

from app.domain.tools.mcp import oauth
from app.domain.tools.mcp.service import get_mcp_server
from app.infra.db.repositories.tools import mcp as mcp_repository


async def owned_server(db, workspace_id, server_id, actor, role):
    return await get_mcp_server(db, workspace_id, server_id, actor, role)


async def configure(db, workspace_id, server_id, actor, role, payload, settings):
    server = await owned_server(db, workspace_id, server_id, actor, role)
    await oauth.configure(db, server, payload, settings)
    server.auth_mode = "oauth"
    server.bearer_token_ciphertext = None
    server.bearer_token_hint = None
    await mcp_repository.save_mcp_server(db, server)
    await db.commit()
    return await oauth.status(db, server)


async def status(db, workspace_id, server_id, actor, role):
    server = await owned_server(db, workspace_id, server_id, actor, role)
    return await oauth.status(db, server)


async def authorize(db, workspace_id, server_id, actor, role, settings):
    server = await owned_server(db, workspace_id, server_id, actor, role)
    return await oauth.authorize(db, server, actor, settings)


async def callback(db, workspace_id, server_id, actor, role, payload, settings):
    server = await owned_server(db, workspace_id, server_id, actor, role)
    return await oauth.callback(db, server, actor, payload, settings)


async def disconnect(db, workspace_id, server_id, actor, role):
    server = await owned_server(db, workspace_id, server_id, actor, role)
    await oauth.queue_disconnect(db, server.id)
    await db.commit()
    return await oauth.status(db, server)

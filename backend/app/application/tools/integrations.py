"""Public use cases for personal integration installations."""

from app.domain.tools.integrations import service
from app.domain.tools.integrations.catalog import PROVIDERS


async def list_integrations(db, workspace_id, actor):
    return [
        await service.status(db, workspace_id, actor.id, provider)
        for provider in PROVIDERS
    ]


async def authorize(
    db, workspace_id, actor, provider, settings, *, browser_origin=None
):
    return await service.begin(
        db, workspace_id, actor, provider, settings, browser_origin=browser_origin
    )


async def callback(db, workspace_id, actor, provider, payload, settings):
    service.provider_definition(provider)
    return await service.complete(db, workspace_id, actor, provider, payload, settings)


async def uninstall(db, workspace_id, actor, provider):
    return await service.uninstall(db, workspace_id, actor, provider)


async def sync_tools(db, workspace_id, actor, provider):
    return await service.sync_tools(db, workspace_id, actor, provider)


__all__ = [
    "authorize",
    "callback",
    "list_integrations",
    "sync_tools",
    "uninstall",
]

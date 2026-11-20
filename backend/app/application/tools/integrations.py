"""Public use cases for personal integration installations."""

from fastapi import HTTPException

from app.domain.tools.integrations import service
from app.domain.tools.integrations.catalog import PROVIDERS


def _require_admin(actor, role):
    if not actor.is_global_admin and role != "admin":
        raise HTTPException(403, "Workspace role required.")


async def list_integrations(db, workspace_id, actor):
    return [
        await service.status(db, workspace_id, actor.id, provider)
        for provider in PROVIDERS
    ]


async def application_status(db, workspace_id, actor, role, provider):
    _require_admin(actor, role)
    return await service.application_status(db, workspace_id, provider)


async def configure(db, workspace_id, actor, role, provider, payload, settings):
    _require_admin(actor, role)
    return await service.configure(db, workspace_id, provider, payload, settings)


async def authorize(db, workspace_id, actor, provider, settings):
    return await service.begin(db, workspace_id, actor, provider, settings)


async def callback(db, workspace_id, actor, provider, payload, settings):
    service.provider_definition(provider)
    return await service.complete(db, workspace_id, actor, provider, payload, settings)


async def uninstall(db, workspace_id, actor, provider):
    return await service.uninstall(db, workspace_id, actor, provider)


async def sync_tools(db, workspace_id, actor, provider):
    return await service.sync_tools(db, workspace_id, actor, provider)


__all__ = [
    "application_status",
    "authorize",
    "callback",
    "configure",
    "list_integrations",
    "sync_tools",
    "uninstall",
]

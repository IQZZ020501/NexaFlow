from sqlalchemy import delete, select, update

from app.domain.tools.integrations import models
from app.entities.tools import integrations as entities
from app.infra.db import mapping


async def _get(db, model, entity, conditions, lock):
    query = select(model).where(*conditions)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    return mapping.to_entity(entity, row) if row else None


async def connection(db, workspace_id, user_id, provider, *, lock=False):
    model = models.IntegrationConnection
    return await _get(
        db,
        model,
        entities.IntegrationConnection,
        [
            model.workspace_id == workspace_id,
            model.user_id == user_id,
            model.provider == provider,
        ],
        lock,
    )


async def connection_by_id(db, connection_id, *, lock=False):
    model = models.IntegrationConnection
    return await _get(
        db, model, entities.IntegrationConnection, [model.id == connection_id], lock
    )


async def authorization(db, state_hash, *, lock=False):
    model = models.IntegrationAuthorization
    return await _get(
        db,
        model,
        entities.IntegrationAuthorization,
        [model.state_hash == state_hash],
        lock,
    )


async def save_connection(db, entity):
    return mapping.to_entity(
        entities.IntegrationConnection,
        await mapping.save(db, models.IntegrationConnection, entity),
    )


async def save_authorization(db, entity):
    return mapping.to_entity(
        entities.IntegrationAuthorization,
        await mapping.save(db, models.IntegrationAuthorization, entity),
    )


async def clear_authorizations(db, connection_id):
    await db.execute(
        delete(models.IntegrationAuthorization).where(
            models.IntegrationAuthorization.connection_id == connection_id
        )
    )


async def archive_user_sources(db, user_id):
    from app.domain.tools.models import Tool, ToolSource

    await db.execute(
        update(Tool)
        .where(Tool.kind == "integration", Tool.created_by_user_id == user_id)
        .values(status="archived", availability="unavailable")
    )
    await db.execute(
        update(ToolSource)
        .where(
            ToolSource.kind == "integration", ToolSource.created_by_user_id == user_id
        )
        .values(status="archived", name="archived-integration-" + ToolSource.id)
    )

from sqlalchemy import delete, select

from app.domain.tools.mcp import oauth_models as models
from app.entities import mcp_oauth as entities
from app.infra.db import mapping


async def get_connection(db, server_id, *, lock=False):
    query = select(models.McpOAuthConnection).where(
        models.McpOAuthConnection.server_id == server_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    return mapping.to_entity(entities.McpOAuthConnection, row) if row else None


async def save_connection(db, entity):
    return mapping.to_entity(
        entities.McpOAuthConnection,
        await mapping.save(db, models.McpOAuthConnection, entity),
    )


async def save_attempt(db, entity):
    return mapping.to_entity(
        entities.McpOAuthAttempt, await mapping.save(db, models.McpOAuthAttempt, entity)
    )


async def get_attempt(db, state_hash, *, lock=False):
    query = select(models.McpOAuthAttempt).where(
        models.McpOAuthAttempt.state_hash == state_hash
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    return mapping.to_entity(entities.McpOAuthAttempt, row) if row else None


async def connection_server_id(db, connection_id):
    return await db.scalar(
        select(models.McpOAuthConnection.server_id).where(
            models.McpOAuthConnection.id == connection_id
        )
    )


async def queue_revocation(db, connection):
    # The encrypted payload includes the client secret and refresh/access tokens.
    await mapping.save(
        db,
        models.McpOAuthRevocation,
        entities.McpOAuthRevocation(
            configuration=connection.configuration,
            secrets_ciphertext=connection.secrets_ciphertext,
        ),
    )


async def due_revocations(db, now, limit=20):
    rows = await db.scalars(
        select(models.McpOAuthRevocation)
        .where(models.McpOAuthRevocation.next_attempt_at <= now)
        .order_by(models.McpOAuthRevocation.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return [mapping.to_entity(entities.McpOAuthRevocation, row) for row in rows]


async def retry_revocation(db, entity):
    await mapping.save(db, models.McpOAuthRevocation, entity)


async def delete_revocation(db, id):
    await db.execute(
        delete(models.McpOAuthRevocation).where(models.McpOAuthRevocation.id == id)
    )


async def expire_attempts(db, now):
    await db.execute(
        delete(models.McpOAuthAttempt).where(models.McpOAuthAttempt.expires_at <= now)
    )

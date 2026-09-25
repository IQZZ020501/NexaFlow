from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.platform.models import PlatformSecret as PlatformSecretOrm
from app.entities.platform.models import PlatformSecret
from app.infra.db import mapping


async def get(db: AsyncSession, name: str) -> PlatformSecret | None:
    row = await db.get(PlatformSecretOrm, name)
    return mapping.to_entity(PlatformSecret, row) if row is not None else None


async def create(db: AsyncSession, entity: PlatformSecret) -> PlatformSecret:
    row = mapping.to_orm(PlatformSecretOrm, entity)
    db.add(row)
    await db.flush()
    return mapping.to_entity(PlatformSecret, row)

"""Generic ORM <-> entity mapping helpers.

Entities in ``app.entities`` mirror database columns exactly (same field
names), so mapping is mechanical via ``dataclasses.fields``. Repositories use
these helpers at their service-facing boundary; business code never touches
ORM rows.
"""

from dataclasses import fields
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

EntityT = TypeVar("EntityT")
OrmT = TypeVar("OrmT")


def to_entity(entity_cls: type[EntityT], orm_row: Any) -> EntityT:
    return entity_cls(
        **{field.name: getattr(orm_row, field.name) for field in fields(entity_cls)}
    )


def to_orm(orm_cls: type[OrmT], entity: Any) -> OrmT:
    return orm_cls(
        **{field.name: getattr(entity, field.name) for field in fields(entity)}
    )


def apply_to_orm(orm_row: Any, entity: Any) -> None:
    for field in fields(entity):
        setattr(orm_row, field.name, getattr(entity, field.name))


async def save(db: AsyncSession, orm_cls: type[OrmT], entity: Any) -> Any:
    """Persist an entity: create the ORM row or update it, then flush.

    Returns the ORM row with generated defaults populated. The caller
    coordinates commit/rollback.
    """
    orm_row = await db.get(orm_cls, entity.id)
    if orm_row is None:
        orm_row = to_orm(orm_cls, entity)
        db.add(orm_row)
    else:
        apply_to_orm(orm_row, entity)
    await db.flush()
    return orm_row


async def refresh_entity(
    db: AsyncSession,
    orm_cls: type[OrmT],
    entity_cls: type[EntityT],
    entity: Any,
) -> EntityT:
    """Re-read the ORM row and update the entity IN PLACE.

    Mutating the existing entity (instead of returning a fresh one) preserves
    object identity for callers that hold the entity across the refresh, the
    same semantics ``AsyncSession.refresh`` had for ORM rows.
    """
    orm_row = await db.get(orm_cls, entity.id)
    if orm_row is None:
        return entity
    await db.refresh(orm_row)
    fresh = to_entity(entity_cls, orm_row)
    for field in fields(entity):
        setattr(entity, field.name, getattr(fresh, field.name))
    return entity

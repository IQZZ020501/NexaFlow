from datetime import datetime

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.email import EmailDelivery, PasswordResetToken
from app.infrastructure.repositories import mapping
from app.shareddomain.email.models import EmailDelivery as EmailDeliveryOrm
from app.shareddomain.email.models import PasswordResetToken as PasswordResetTokenOrm


async def create_delivery(
    db: AsyncSession,
    entity: EmailDelivery,
) -> EmailDelivery:
    row = await mapping.save(db, EmailDeliveryOrm, entity)
    return mapping.to_entity(EmailDelivery, row)


async def lock_delivery(
    db: AsyncSession,
    delivery_id: str,
) -> EmailDelivery | None:
    row = await db.scalar(
        select(EmailDeliveryOrm)
        .where(EmailDeliveryOrm.id == delivery_id)
        .with_for_update()
    )
    return mapping.to_entity(EmailDelivery, row) if row is not None else None


async def save_delivery(
    db: AsyncSession,
    entity: EmailDelivery,
) -> EmailDelivery:
    row = await mapping.save(db, EmailDeliveryOrm, entity)
    return mapping.to_entity(EmailDelivery, row)


async def delete_delivery(db: AsyncSession, delivery_id: str) -> None:
    await db.execute(
        delete(EmailDeliveryOrm).where(EmailDeliveryOrm.id == delivery_id)
    )


async def delete_password_reset_deliveries(
    db: AsyncSession,
    user_id: str,
) -> None:
    await db.execute(
        delete(EmailDeliveryOrm).where(
            EmailDeliveryOrm.user_id == user_id,
            EmailDeliveryOrm.kind == "password_reset",
        )
    )


async def delete_source_deliveries(
    db: AsyncSession,
    source_type: str,
    source_id: str,
) -> None:
    await db.execute(
        delete(EmailDeliveryOrm).where(
            EmailDeliveryOrm.source_type == source_type,
            EmailDeliveryOrm.source_id == source_id,
        )
    )


async def list_due_delivery_ids(
    db: AsyncSession,
    now: datetime,
    limit: int,
) -> list[str]:
    rows = await db.scalars(
        select(EmailDeliveryOrm.id)
        .where(
            or_(
                and_(
                    EmailDeliveryOrm.status.in_(("pending", "retry")),
                    EmailDeliveryOrm.next_attempt_at <= now,
                ),
                and_(
                    EmailDeliveryOrm.status == "sending",
                    EmailDeliveryOrm.lease_expires_at <= now,
                ),
            )
        )
        .order_by(EmailDeliveryOrm.next_attempt_at, EmailDeliveryOrm.created_at)
        .limit(limit)
    )
    return list(rows.all())


async def create_password_reset_token(
    db: AsyncSession,
    entity: PasswordResetToken,
) -> PasswordResetToken:
    row = await mapping.save(db, PasswordResetTokenOrm, entity)
    return mapping.to_entity(PasswordResetToken, row)


async def get_password_reset_token_user_id(
    db: AsyncSession,
    token_hash: str,
) -> str | None:
    return await db.scalar(
        select(PasswordResetTokenOrm.user_id).where(
            PasswordResetTokenOrm.token_hash == token_hash
        )
    )


async def lock_active_password_reset_token(
    db: AsyncSession,
    token_hash: str,
    now: datetime,
) -> PasswordResetToken | None:
    row = await db.scalar(
        select(PasswordResetTokenOrm)
        .where(
            PasswordResetTokenOrm.token_hash == token_hash,
            PasswordResetTokenOrm.expires_at > now,
            PasswordResetTokenOrm.used_at.is_(None),
        )
        .with_for_update()
    )
    return mapping.to_entity(PasswordResetToken, row) if row is not None else None


async def save_password_reset_token(
    db: AsyncSession,
    entity: PasswordResetToken,
) -> PasswordResetToken:
    row = await mapping.save(db, PasswordResetTokenOrm, entity)
    return mapping.to_entity(PasswordResetToken, row)


async def invalidate_password_reset_tokens(
    db: AsyncSession,
    user_id: str,
    now: datetime,
) -> None:
    await db.execute(
        update(PasswordResetTokenOrm)
        .where(
            PasswordResetTokenOrm.user_id == user_id,
            PasswordResetTokenOrm.used_at.is_(None),
        )
        .values(used_at=now)
    )


async def delete_expired_password_reset_tokens(
    db: AsyncSession,
    now: datetime,
) -> None:
    await db.execute(
        delete(PasswordResetTokenOrm).where(
            PasswordResetTokenOrm.expires_at <= now
        )
    )

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.smtp_settings import SmtpSettings as SmtpSettingsOrm
from app.entities.smtp_settings import SMTP_SETTINGS_ID, SmtpSettings
from app.infrastructure.repositories import mapping


async def get(db: AsyncSession) -> SmtpSettings | None:
    row = await db.get(SmtpSettingsOrm, SMTP_SETTINGS_ID)
    return mapping.to_entity(SmtpSettings, row) if row is not None else None


async def save(db: AsyncSession, entity: SmtpSettings) -> SmtpSettings:
    row = await mapping.save(db, SmtpSettingsOrm, entity)
    return mapping.to_entity(SmtpSettings, row)

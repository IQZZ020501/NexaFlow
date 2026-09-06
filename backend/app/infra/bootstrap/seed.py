import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.platform.models import User
from app.infra.config.settings import Settings
from app.infra.observability.logger import get_logger, log_event
from app.infra.security.auth import hash_password

logger = get_logger(__name__)


async def seed_bootstrap_admin(db: AsyncSession, settings: Settings) -> None:
    admin = await db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
    if admin is None:
        admin = User(
            username=settings.bootstrap_admin_username,
            email=settings.bootstrap_admin_email,
            name=settings.bootstrap_admin_name,
            password_hash=hash_password(settings.bootstrap_admin_password),
            is_global_admin=True,
            must_change_password=True,
        )
        db.add(admin)
    else:
        admin.is_global_admin = True

    await db.commit()
    log_event(
        logger,
        logging.INFO,
        "Bootstrap admin ensured.",
        admin_username=admin.username,
    )

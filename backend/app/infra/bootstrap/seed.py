import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.platform.models import BootstrapState
from app.entities.identity.user import User
from app.infra.config.settings import Settings
from app.infra.db.repositories.identity import users as user_repository
from app.infra.observability.logger import get_logger, log_event
from app.infra.security.auth import hash_password

logger = get_logger(__name__)


async def seed_bootstrap_admin(db: AsyncSession, settings: Settings) -> None:
    if await db.get(BootstrapState, 1) is not None:
        return
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    claimed = await db.scalar(
        insert(BootstrapState)
        .values(id=1)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(BootstrapState.id)
    )
    if claimed is None:
        return
    try:
        # Bootstrap is strictly for an empty installation. Never adopt a user via
        # its mutable username or recreate a removed administrator.
        if await user_repository.list_users(db, limit=1):
            await db.commit()
            return
        admin = User(
            username=settings.bootstrap_admin_username,
            email=settings.bootstrap_admin_email,
            name=settings.bootstrap_admin_name,
            password_hash=hash_password(settings.bootstrap_admin_password),
            is_global_admin=True,
            must_change_password=True,
        )
        await user_repository.create_user(db, admin)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    log_event(logger, logging.INFO, "Bootstrap admin created.", admin_user_id=admin.id)

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from nexaflow.core.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_database(settings: Settings) -> None:
    global _engine, _session_factory

    kwargs = {}
    if settings.database_url == "sqlite+aiosqlite:///:memory:":
        kwargs = {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }

    _engine = create_async_engine(settings.database_url, **kwargs)
    _session_factory = async_sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def get_engine() -> AsyncEngine:
    if _engine is None:
        configure_database(Settings.from_env())
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        configure_database(Settings.from_env())
    assert _session_factory is not None
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session

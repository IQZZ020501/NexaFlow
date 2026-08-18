from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from app.infrastructure.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_database(settings: Settings, *, worker_process: bool = False) -> None:
    global _engine, _session_factory

    kwargs = {}
    if settings.database_url == "sqlite+aiosqlite:///:memory:":
        if worker_process:
            raise ValueError(
                "Celery workers cannot use in-memory SQLite; use a file-backed database URL."
            )
        kwargs = {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    elif settings.database_url.startswith("postgresql+psycopg://"):
        kwargs["connect_args"] = {
            "application_name": "nexaflow-worker" if worker_process else "nexaflow-api"
        }
        if worker_process:
            # Celery jobs call asyncio.run per task; pooled connections must not
            # be reused across the event loops those calls create.
            kwargs["poolclass"] = NullPool
        else:
            kwargs["pool_pre_ping"] = True
    elif worker_process:
        # Celery jobs call asyncio.run per task; pooled connections must not
        # be reused across the event loops those calls create.
        kwargs["poolclass"] = NullPool

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

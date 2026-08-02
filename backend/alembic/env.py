from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import Settings
from app.models.audit import AuditLog  # noqa: F401
from app.core.base import Base
from app.models.user import User  # noqa: F401
from app.models.knowledge import (  # noqa: F401
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeTask,
)
from app.models.model import RegisteredModel  # noqa: F401
from app.models.resource_permission import ResourcePermission  # noqa: F401
from app.models.system_log import SystemLog  # noqa: F401
from app.models.team import Team, TeamMembership  # noqa: F401
from app.models.workspace import Workspace, WorkspaceMembership  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return Settings.from_env(require_bootstrap=False).database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

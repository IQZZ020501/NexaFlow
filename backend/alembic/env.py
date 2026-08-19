from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.infrastructure.config import Settings
from app.shareddomain.agents.models import (  # noqa: F401
    Agent,
    AgentApiCredential,
    AgentKnowledgeBase,
    AgentMcpTool,
    AgentPublicationVersion,
    AgentRun,
    AgentRunEvent,
    AgentToolCall,
)
from app.shareddomain.audit.models import AuditLog  # noqa: F401
from app.infrastructure.base import Base
from app.domain.user import RefreshSession, User  # noqa: F401
from app.domain.workspace_governance import WorkspaceGovernance  # noqa: F401
from app.domain.workspace_invitation import WorkspaceInvitation  # noqa: F401
from app.shareddomain.knowledge.models import (  # noqa: F401
    KnowledgeAsset,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeChunkAsset,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeDocumentReference,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationExpectation,
    KnowledgeEvaluationResult,
    KnowledgeStorageCleanup,
    KnowledgeTask,
)
from app.shareddomain.tools.models import (  # noqa: F401
    ApplicationToolBinding,
    McpServer,
    McpToolPolicy,
    Tool,
    ToolDraft,
    ToolInvocation,
    ToolPolicy,
    ToolSource,
    ToolVersion,
)
from app.shareddomain.workflows.models import (  # noqa: F401
    WorkflowDefinition,
    WorkflowNodeExecution,
    WorkflowRunDetail,
    WorkflowUpload,
    WorkflowUploadStorageCleanup,
    WorkflowVersion,
)
from app.capabilities.llm.models import RegisteredModel  # noqa: F401
from app.domain.resource_permission import ResourcePermission  # noqa: F401
from app.infrastructure.system_log import SystemLog  # noqa: F401
from app.domain.team import Team, TeamMembership  # noqa: F401
from app.domain.workspace import Workspace, WorkspaceMembership  # noqa: F401

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

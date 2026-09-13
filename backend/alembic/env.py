from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.domain.agent_skills.models import (  # noqa: F401
    AgentSkill,
    AgentSkillBinding,
    AgentSkillVersion,
)
from app.domain.agents.models import (  # noqa: F401
    Agent,
    AgentApiCredential,
    AgentKnowledgeBase,
    AgentMcpTool,
    AgentPublicationVersion,
    AgentRun,
    AgentRunEvent,
    AgentRunSnapshot,
    AgentRunState,
)
from app.domain.announcements.models import Announcement, AnnouncementRead  # noqa: F401
from app.domain.artifacts.models import GeneratedArtifact  # noqa: F401
from app.domain.audit.models import AuditLog  # noqa: F401
from app.domain.email.models import EmailDelivery, PasswordResetToken  # noqa: F401
from app.domain.identity.enterprise.models import (  # noqa: F401
    EnterpriseIdentity,
    EnterpriseIdentityConnection,
    EnterpriseLoginState,
)
from app.domain.knowledge.graph.models import (  # noqa: F401
    KnowledgeGraphAlias,
    KnowledgeGraphClaim,
    KnowledgeGraphClaimEvidence,
    KnowledgeGraphEntity,
    KnowledgeGraphMention,
    KnowledgeGraphReviewItem,
    KnowledgeGraphRevision,
    KnowledgeGraphRevisionChange,
    KnowledgeGraphSchema,
)
from app.domain.knowledge.models import (  # noqa: F401
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
from app.domain.models.registered import RegisteredModel  # noqa: F401
from app.domain.platform.models import (  # noqa: F401  # noqa: F401  # noqa: F401
    RefreshSession,
    ResourcePermission,
    SmtpSettings,
    Team,
    TeamMembership,
    User,
    Workspace,
    WorkspaceGovernance,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from app.domain.resource_folders.models import ResourceFolder  # noqa: F401
from app.domain.tools.models import (  # noqa: F401
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
from app.domain.workflows.models import (  # noqa: F401
    WorkflowDefinition,
    WorkflowNodeExecution,
    WorkflowRunDetail,
    WorkflowUpload,
    WorkflowUploadStorageCleanup,
    WorkflowVersion,
)
from app.infra.config.settings import Settings
from app.infra.db.base import Base
from app.infra.observability.system_log import SystemLog  # noqa: F401

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

"""Explicit application module interfaces and permitted runtime dependencies.

An interface is an existing use-case facade or a capability-specific entry
point. Its __all__ lists the names available to HTTP and other modules.
Workers and bootstrap are composition roots and may assemble implementations.
"""

PUBLIC_INTERFACES = {
    "agent_skills": {
        "app.application.agent_skills",
        "app.application.agent_skills.dependencies",
        "app.application.agent_skills.execution",
        "app.application.agent_skills.packages",
        "app.application.agent_skills.scripts",
    },
    "agents": {
        "app.application.agents",
        "app.application.agents.integration",
        "app.application.agents.runs.session",
    },
    "analytics": {
        "app.application.analytics",
    },
    "announcements": {
        "app.application.announcements",
    },
    "artifacts": {
        "app.application.artifacts.service",
        "app.application.artifacts.workspace",
    },
    "audit": {
        "app.application.audit",
        "app.application.audit.system_logs",
    },
    "email": {
        "app.application.email.delivery",
        "app.application.email.smtp",
    },
    "governance": {
        "app.application.governance.service",
    },
    "identity": {
        "app.application.identity.enterprise",
        "app.application.identity.invitations",
        "app.application.identity.password_reset",
        "app.application.identity.service",
        "app.application.identity.sessions",
    },
    "knowledge": {
        "app.application.knowledge.documents.service",
        "app.application.knowledge.retrieval.service",
    },
    "models": {
        "app.application.models.service",
    },
    "projects": {
        "app.application.projects.runtime",
        "app.application.projects.service",
    },
    "publications": {
        "app.application.publications.service",
    },
    "resource_folders": {
        "app.application.resource_folders.service",
    },
    "runs": {
        "app.application.runs.feedback",
        "app.application.runs.leases",
        "app.application.runs.lifecycle",
    },
    "teams": {
        "app.application.teams",
    },
    "tools": {
        "app.application.tools",
        "app.application.tools.oauth",
        "app.application.tools.remote_task_configuration",
        "app.application.tools.runtime.service",
    },
    "uploads": {
        "app.application.uploads.service",
    },
    "workflows": {
        "app.application.workflows.definitions.service",
    },
    "workspaces": {
        "app.application.workspaces.service",
    },
}

MODULE_DEPENDENCIES = {
    "agent_skills": {"artifacts"},
    "agents": {
        "agent_skills",
        "governance",
        "knowledge",
        "projects",
        "publications",
        "runs",
        "tools",
        "uploads",
        "workspaces",
    },
    "analytics": set(),
    "announcements": {"workspaces"},
    "artifacts": {"publications", "workspaces"},
    "audit": set(),
    "email": set(),
    "governance": set(),
    "identity": {"email"},
    "knowledge": set(),
    "models": set(),
    "projects": {"artifacts", "workspaces"},
    "publications": {"workspaces"},
    "resource_folders": set(),
    "runs": set(),
    "teams": set(),
    "tools": {"agent_skills", "artifacts", "projects"},
    "uploads": set(),
    "workflows": {
        "agent_skills",
        "agents",
        "governance",
        "publications",
        "runs",
        "tools",
        "uploads",
        "workspaces",
    },
    "workspaces": {"identity", "knowledge"},
}

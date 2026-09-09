from fastapi import APIRouter

from app.api.v1.admin.audit import routes as audit
from app.api.v1.admin.governance import routes as governance
from app.api.v1.admin.smtp import routes as smtp
from app.api.v1.admin.system_logs import routes as system_logs
from app.api.v1.admin.users import routes as users
from app.api.v1.announcements import routes as announcements
from app.api.v1.artifacts import routes as artifacts
from app.api.v1.workspaces import routes as workspaces
from app.api.v1.teams import routes as teams
from app.api.v1.resource_folders import routes as resource_folders
from app.api.v1.models import routes as models
from app.api.v1.tools import mcp as mcp_servers
from app.api.v1.tools import routes as tools
from app.api.v1.knowledge import evaluation as knowledge_evaluation
from app.api.v1.knowledge import graph as knowledge_graph
from app.api.v1.knowledge import lifecycle as knowledge_lifecycle
from app.api.v1.knowledge import retrieval as knowledge_retrieval
from app.api.v1.agents import access as agent_access
from app.api.v1.agents import routes as agents
from app.api.v1.knowledge import routes as knowledge
from app.api.v1.workflows import access as workflow_access
from app.api.v1.workflows import routes as workflows
from app.api.v1.tools import sources as tool_sources
from app.api.v1.identity import auth, enterprise as enterprise_identity

api_router = APIRouter(prefix="/api/v1")

admin_router = APIRouter(prefix="/admin")
admin_router.include_router(users.router)
admin_router.include_router(audit.router)
admin_router.include_router(system_logs.router)
admin_router.include_router(governance.router)
admin_router.include_router(smtp.router)
admin_router.include_router(enterprise_identity.admin_router)
api_router.include_router(admin_router)

api_router.include_router(auth.router)
api_router.include_router(announcements.message_router)
api_router.include_router(announcements.global_admin_router)
api_router.include_router(announcements.workspace_router)
api_router.include_router(enterprise_identity.public_router)
api_router.include_router(artifacts.router)
api_router.include_router(workspaces.router)
api_router.include_router(teams.router)
api_router.include_router(knowledge.router)
api_router.include_router(knowledge_evaluation.router)
api_router.include_router(knowledge_graph.router)
api_router.include_router(knowledge_lifecycle.router)
api_router.include_router(knowledge_retrieval.router)
api_router.include_router(models.router)
api_router.include_router(resource_folders.router)
api_router.include_router(mcp_servers.router)
api_router.include_router(tool_sources.router)
api_router.include_router(tools.router)
api_router.include_router(agents.router)
api_router.include_router(workflows.router)
api_router.include_router(agent_access.public_router)
api_router.include_router(agent_access.api_router)
api_router.include_router(workflow_access.public_router)
api_router.include_router(workflow_access.api_router)

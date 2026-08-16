from fastapi import APIRouter

from app.api.v1.admin import audit, users
from app.api.v1.endpoints import (
    agent_access,
    agents,
    auth,
    knowledge,
    knowledge_evaluation,
    knowledge_lifecycle,
    knowledge_retrieval,
    mcp_servers,
    models,
    teams,
    workflows,
    workflow_access,
    workspaces,
)

api_router = APIRouter(prefix="/api/v1")

admin_router = APIRouter(prefix="/admin")
admin_router.include_router(users.router)
admin_router.include_router(audit.router)
api_router.include_router(admin_router)

api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(teams.router)
api_router.include_router(knowledge.router)
api_router.include_router(knowledge_evaluation.router)
api_router.include_router(knowledge_lifecycle.router)
api_router.include_router(knowledge_retrieval.router)
api_router.include_router(models.router)
api_router.include_router(mcp_servers.router)
api_router.include_router(agents.router)
api_router.include_router(workflows.router)
api_router.include_router(agent_access.public_router)
api_router.include_router(agent_access.api_router)
api_router.include_router(workflow_access.public_router)
api_router.include_router(workflow_access.api_router)

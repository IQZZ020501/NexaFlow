from fastapi import APIRouter

from app.api.v1.admin import audit, users
from app.api.v1.endpoints import (
    auth,
    knowledge,
    knowledge_legacy,
    knowledge_lifecycle,
    knowledge_retrieval,
    models,
    teams,
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
api_router.include_router(knowledge_lifecycle.router)
api_router.include_router(knowledge_retrieval.router)
api_router.include_router(knowledge_legacy.router)
api_router.include_router(knowledge_legacy.legacy_router)
api_router.include_router(models.router)

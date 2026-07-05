from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from nexaflow.core.config import Settings
from nexaflow.core.seed import seed_defaults
from nexaflow.audit import api as audit_api
from nexaflow.db.session import configure_database, get_session_factory
from nexaflow.identity import api as auth_api
from nexaflow.knowledge_bases import api as knowledge_bases_api
from nexaflow.system_logs.services import record_system_log
from nexaflow.teams import api as teams_api
from nexaflow.workspaces import api as workspaces_api

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        async with get_session_factory()() as db:
            await seed_defaults(db, settings)
        yield

    app = FastAPI(title="NexaFlow API", lifespan=lifespan)
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def record_unhandled_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            logger.exception("Unhandled request error.")
            forwarded_for = request.headers.get("x-forwarded-for", "")
            ip_address = forwarded_for.split(",", 1)[0].strip()
            if not ip_address and request.client:
                ip_address = request.client.host

            try:
                async with get_session_factory()() as db:
                    record_system_log(
                        db,
                        level="error",
                        event="request.unhandled_exception",
                        message=str(exc) or exc.__class__.__name__,
                        path=request.url.path,
                        method=request.method,
                        status_code=500,
                        ip_address=ip_address or None,
                        details={"exception_type": exc.__class__.__name__},
                        stack_trace=traceback.format_exc(),
                    )
                    await db.commit()
            except Exception:
                logger.exception("Failed to record system log.")
            raise

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_api.router)
    app.include_router(auth_api.users_router)
    app.include_router(workspaces_api.router)
    app.include_router(teams_api.router)
    app.include_router(knowledge_bases_api.router)
    app.include_router(audit_api.router)
    return app


app = create_app()

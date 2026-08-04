from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.infrastructure.config import Settings
from app.infrastructure.seed import seed_defaults
from app.infrastructure.session import configure_database, get_session_factory
from app.infrastructure.system_log import record_system_log

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env(require_bootstrap=False)
    configure_database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings.validate()
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

    app.include_router(api_router)
    return app


app = create_app()

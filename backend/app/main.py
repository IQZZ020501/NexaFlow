from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.infrastructure.config import Settings
from app.infrastructure.errors import classify_error, log_error
from app.infrastructure.event_loop import configure_windows_event_loop_policy
from app.infrastructure.logger import get_logger, setup_logging
from app.infrastructure.request_body_limit import RequestBodyLimitMiddleware
from app.infrastructure.seed import seed_bootstrap_admin
from app.infrastructure.session import configure_database, get_session_factory
from app.infrastructure.system_log import record_system_log

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env(require_bootstrap=False)
    setup_logging(level=settings.log_level)
    configure_windows_event_loop_policy()
    configure_database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings.validate()
        async with get_session_factory()() as db:
            await seed_bootstrap_admin(db, settings)
        yield

    app = FastAPI(title="NexaFlow API", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestBodyLimitMiddleware)

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
            log_error(
                logger,
                "Unhandled request error.",
                exc,
                path=request.url.path,
                method=request.method,
                status_code=500,
            )
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
                        details={
                            "exception_type": exc.__class__.__name__,
                            "source": classify_error(exc),
                        },
                        stack_trace=traceback.format_exc(),
                    )
                    await db.commit()
            except Exception as log_exc:
                log_error(logger, "Failed to record system log.", log_exc)
            raise

    @app.middleware("http")
    async def prevent_api_caching(request: Request, call_next):
        # API responses are authenticated and tenant-scoped: they must never
        # be stored by browsers or shared caches (RFC 9111 heuristic caching
        # would otherwise apply to GET responses without Cache-Control).
        # Endpoints that opt into their own policy (e.g. the agent NDJSON
        # stream sets `Cache-Control: no-cache`) are left untouched.
        response = await call_next(request)
        if (
            request.url.path.startswith("/api/")
            and "cache-control" not in response.headers
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()

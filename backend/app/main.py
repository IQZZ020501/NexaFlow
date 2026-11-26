import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.infra.bootstrap.seed import seed_bootstrap_admin
from app.infra.config.settings import Settings
from app.infra.db.session import configure_database, get_session_factory
from app.infra.observability.errors import classify_error, log_error
from app.infra.observability.logger import get_logger, setup_logging
from app.infra.observability.system_log import record_system_log
from app.infra.runtime.event_loop import configure_windows_event_loop_policy
from app.infra.runtime.request_body_limit import RequestBodyLimitMiddleware
from app.infra.runtime.timezone import configure_process_timezone
from app.infra.security.keyring import initialize_secret_keys

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env(require_bootstrap=False)
    configure_process_timezone()
    setup_logging(level=settings.log_level)
    configure_windows_event_loop_policy()
    configure_database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings.validate()
        async with get_session_factory()() as db:
            await seed_bootstrap_admin(db, settings)
        # Create or adopt the signing/encryption keys before serving traffic.
        await initialize_secret_keys(settings)
        yield

    app = FastAPI(
        title="NexaFlow API",
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )
    app.state.settings = settings
    app.add_middleware(RequestBodyLimitMiddleware)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Total-Count"],
        )

    @app.middleware("http")
    async def record_unhandled_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            route_path = getattr(request.scope.get("route"), "path", None) or "<unmatched>"
            exception_type = exc.__class__.__name__
            source = classify_error(exc)
            # Exception messages (including SQL parameters) may repeat bearer
            # URLs or submitted credentials. Retain frames without their values.
            stack_trace = "".join(traceback.format_tb(exc.__traceback__))
            log_error(
                logger,
                "Unhandled request error.",
                source=source,
                exception_type=exception_type,
                stack_trace=stack_trace,
                path=route_path,
                method=request.method,
                status_code=500,
            )
            ip_address = request.client.host if request.client else None

            try:
                async with get_session_factory()() as db:
                    record_system_log(
                        db,
                        level="error",
                        event="request.unhandled_exception",
                        message=f"Unhandled {exception_type}.",
                        path=route_path,
                        method=request.method,
                        status_code=500,
                        ip_address=ip_address or None,
                        details={
                            "exception_type": exception_type,
                            "source": source,
                        },
                        stack_trace=stack_trace,
                    )
                    await db.commit()
            except Exception as log_exc:
                log_error(logger, "Failed to record system log.", exception_type=type(log_exc).__name__)
            return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

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
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()

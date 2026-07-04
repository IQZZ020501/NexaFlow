from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexaflow.core.config import Settings
from nexaflow.core.seed import seed_defaults
from nexaflow.db.session import configure_database, get_session_factory
from nexaflow.identity import api as auth_api
from nexaflow.teams import api as teams_api
from nexaflow.workspaces import api as workspaces_api


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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_api.router)
    app.include_router(auth_api.users_router)
    app.include_router(workspaces_api.router)
    app.include_router(teams_api.router)
    return app


app = create_app()

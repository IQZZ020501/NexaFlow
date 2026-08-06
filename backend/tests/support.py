import asyncio
import os
import shutil
from pathlib import Path
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

BOOTSTRAP_ADMIN_PASSWORD = "NexaFlow@123."
ADMIN_PASSWORD = "NexaFlow@12345."
RESEARCH_PASSWORD = "Research@12345."

os.environ.update(
    {
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-for-app-smoke-suite",
        "MODEL_SECRET_KEY": "test-model-secret-for-app-smoke-suite",
        "BOOTSTRAP_ADMIN_USERNAME": "admin",
        "BOOTSTRAP_ADMIN_EMAIL": "admin@app.local",
        "BOOTSTRAP_ADMIN_NAME": "NexaFlow Admin",
        "BOOTSTRAP_ADMIN_PASSWORD": BOOTSTRAP_ADMIN_PASSWORD,
        "DEFAULT_WORKSPACE_NAME": "Default Workspace",
        "DEFAULT_WORKSPACE_SLUG": "default",
        "DEFAULT_TEAM_NAME": "Default Team",
        "DEFAULT_TEAM_SLUG": "default",
        "ENVIRONMENT": "test",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "QDRANT_URL": ":memory:",
        "CELERY_BROKER_URL": "redis://localhost:6379/0",
        "KNOWLEDGE_STORAGE_DIR": "/tmp/app-test-knowledge-storage",
    }
)

from app.infrastructure.config import Settings
from app.infrastructure.base import Base
from app.infrastructure.session import get_engine
from app.main import create_app


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret-for-app-smoke-suite",
        model_secret_key="test-model-secret-for-app-smoke-suite",
        knowledge_storage_dir=Path("/tmp/app-test-knowledge-storage"),
        qdrant_url=":memory:",
        celery_broker_url="redis://localhost:6379/0",
        celery_task_always_eager=True,
        bootstrap_admin_username="admin",
        bootstrap_admin_email="admin@app.local",
        bootstrap_admin_name="NexaFlow Admin",
        bootstrap_admin_password=BOOTSTRAP_ADMIN_PASSWORD,
        default_workspace_name="Default Workspace",
        default_workspace_slug="default",
        default_team_name="Default Team",
        default_team_slug="default",
        environment="test",
    )


@contextmanager
def test_client() -> Iterator[TestClient]:
    runtime_settings = settings()
    shutil.rmtree(runtime_settings.knowledge_storage_dir, ignore_errors=True)
    app = create_app(runtime_settings)

    async def create_schema() -> None:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())

    with TestClient(app) as client:
        yield client


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def activate_user(
    client: TestClient,
    username: str,
    current_password: str,
    new_password: str,
) -> str:
    payload = login(client, username, current_password)
    assert payload["must_change_password"] is True
    token = payload["access_token"]

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(token),
        json={"new_password": new_password},
    )
    assert changed.status_code == 204, changed.text

    payload = login(client, username, new_password)
    assert payload["must_change_password"] is False
    return payload["access_token"]


def create_active_user(
    client: TestClient,
    admin_token: str,
    username: str,
    new_password: str = RESEARCH_PASSWORD,
) -> tuple[str, str]:
    created = client.post(
        "/api/v1/admin/users",
        headers=auth_headers(admin_token),
        json={
            "username": username,
            "email": f"{username}@example.com",
            "name": username,
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    token = activate_user(
        client,
        username,
        payload["initial_password"],
        new_password,
    )
    return payload["user"]["id"], token


def activate_admin(client: TestClient) -> tuple[str, str]:
    payload = login(client, "admin", BOOTSTRAP_ADMIN_PASSWORD)
    token = payload["access_token"]

    me = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text
    default_workspace_id = me.json()["memberships"][0]["workspace_id"]

    admin_token = activate_user(client, "admin", BOOTSTRAP_ADMIN_PASSWORD, ADMIN_PASSWORD)
    return admin_token, default_workspace_id

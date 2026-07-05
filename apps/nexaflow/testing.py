import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

BOOTSTRAP_ADMIN_PASSWORD = "NexaFlow@123."
ADMIN_PASSWORD = "NexaFlow@12345."
RESEARCH_PASSWORD = "Research@12345."

os.environ.update(
    {
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-for-nexaflow-smoke-suite",
        "BOOTSTRAP_ADMIN_USERNAME": "admin",
        "BOOTSTRAP_ADMIN_EMAIL": "admin@nexaflow.local",
        "BOOTSTRAP_ADMIN_NAME": "NexaFlow Admin",
        "BOOTSTRAP_ADMIN_PASSWORD": BOOTSTRAP_ADMIN_PASSWORD,
        "DEFAULT_WORKSPACE_NAME": "Default Workspace",
        "DEFAULT_WORKSPACE_SLUG": "default",
        "DEFAULT_TEAM_NAME": "Default Team",
        "DEFAULT_TEAM_SLUG": "default",
        "ENVIRONMENT": "test",
    }
)

from nexaflow.core.config import Settings
from nexaflow.db.base import Base
from nexaflow.db.session import get_engine
from nexaflow.main import create_app


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret-for-nexaflow-smoke-suite",
        bootstrap_admin_username="admin",
        bootstrap_admin_email="admin@nexaflow.local",
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
    app = create_app(settings())

    async def create_schema() -> None:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())

    with TestClient(app) as client:
        yield client


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/auth/login",
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
        "/auth/change-password",
        headers=auth_headers(token),
        json={"new_password": new_password},
    )
    assert changed.status_code == 204, changed.text

    payload = login(client, username, new_password)
    assert payload["must_change_password"] is False
    return payload["access_token"]


def activate_admin(client: TestClient) -> tuple[str, str]:
    payload = login(client, "admin", BOOTSTRAP_ADMIN_PASSWORD)
    token = payload["access_token"]

    me = client.get("/auth/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text
    default_workspace_id = me.json()["memberships"][0]["workspace_id"]

    admin_token = activate_user(client, "admin", BOOTSTRAP_ADMIN_PASSWORD, ADMIN_PASSWORD)
    return admin_token, default_workspace_id

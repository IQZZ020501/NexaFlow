import asyncio

from fastapi.testclient import TestClient

from app.infrastructure.base import Base
from app.infrastructure.session import get_engine
from app.main import create_app
from tests.support import settings as testing_settings


def main() -> None:
    app = create_app(testing_settings())

    async def create_schema() -> None:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text
        assert health.json() == {"status": "ok"}

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "NexaFlow@123."},
        )
        assert login.status_code == 200, login.text
        assert login.headers.get("cache-control") == "no-store"

        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["user"]["username"] == "admin"
        assert me.headers.get("cache-control") == "no-store"

        unknown = client.get("/no-such-route")
        assert unknown.status_code == 404, unknown.text


if __name__ == "__main__":
    main()

import asyncio

from fastapi.testclient import TestClient

from tests.support import settings as testing_settings
from app.infrastructure.base import Base
from app.infrastructure.session import get_engine
from app.infrastructure.request_body_limit import RequestBodyLimitMiddleware
from app.main import create_app


async def check_streaming_request_body_limit() -> None:
    downstream_called = False

    async def app(scope, receive, send) -> None:
        nonlocal downstream_called
        downstream_called = True
        while (await receive()).get("more_body", False):
            pass

    messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    await RequestBodyLimitMiddleware(app, max_bytes=5)(
        {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [],
            "query_string": b"",
        },
        receive,
        send,
    )
    assert downstream_called
    assert sent[0]["status"] == 413


def main() -> None:
    asyncio.run(check_streaming_request_body_limit())
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
        assert me.json()["memberships"] == []
        assert me.json()["user"]["workspaces"] == []
        assert me.json()["user"]["teams"] == []
        assert me.headers.get("cache-control") == "no-store"

        oversized = client.post(
            "/api/v1/auth/login",
            headers={"content-length": str(111 * 1024 * 1024)},
            content=b"{}",
        )
        assert oversized.status_code == 413, oversized.text

        unknown = client.get("/no-such-route")
        assert unknown.status_code == 404, unknown.text


if __name__ == "__main__":
    main()

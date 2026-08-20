import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tests.support import (
    ADMIN_PASSWORD,
    auth_headers,
    activate_admin,
    login,
    settings as test_settings,
    test_client,
)
from app.application.governance import (
    _check_health_component,
    _probe_qdrant,
    _probe_redis,
    _probe_storage,
    _probe_storage_sync,
    _probe_worker,
    get_admin_health,
)


async def check_health_probe_functions() -> None:
    probe = AsyncMock()
    component = await _check_health_component(False, probe)
    assert component.status == "not_configured"
    probe.assert_not_awaited()

    component = await _check_health_component(True, probe)
    assert component.status == "ok"

    component = await _check_health_component(
        True,
        AsyncMock(side_effect=OSError("down")),
    )
    assert component.status == "error"
    assert component.detail == "unavailable"

    async def slow_probe() -> None:
        await asyncio.sleep(0.02)

    with patch("app.application.governance.HEALTH_PROBE_TIMEOUT_SECONDS", 0.001):
        component = await _check_health_component(True, slow_probe)
    assert component.status == "error"
    assert component.detail == "timeout"

    redis = AsyncMock()
    redis.ping.return_value = True
    with patch("app.application.governance.Redis.from_url", return_value=redis) as factory:
        await _probe_redis(test_settings())
    factory.assert_called_once()
    redis.aclose.assert_awaited_once()

    redis = AsyncMock()
    redis.ping.return_value = False
    with patch("app.application.governance.Redis.from_url", return_value=redis):
        try:
            await _probe_redis(test_settings())
        except RuntimeError:
            pass
        else:
            raise AssertionError("Redis health probe accepted a false PING response")
    redis.aclose.assert_awaited_once()

    with patch("app.application.governance.check_vector_store_health") as qdrant:
        await _probe_qdrant(test_settings())
    qdrant.assert_called_once_with(test_settings())

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _probe_storage_sync(root)
        assert list(root.iterdir()) == []
        await _probe_storage(replace(test_settings(), knowledge_storage_dir=root))
        assert list(root.iterdir()) == []
    try:
        _probe_storage_sync(Path(directory))
    except OSError:
        pass
    else:
        raise AssertionError("Missing storage directory was reported healthy")

    celery_app = MagicMock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    celery_app.connection_for_read.return_value = connection
    celery_app.control.ping.return_value = [{"worker@test": {"ok": "pong"}}]
    with patch("app.infrastructure.celery.celery_app", celery_app):
        await _probe_worker(test_settings())
    celery_app.control.ping.assert_called_once()

    celery_app.control.ping.return_value = []
    with patch("app.infrastructure.celery.celery_app", celery_app):
        try:
            await _probe_worker(test_settings())
        except RuntimeError:
            pass
        else:
            raise AssertionError("Missing Celery worker was reported healthy")

    from app.capabilities.rag import vector_store as qdrant_module
    from app.ports import vector_store as vector_store_port

    qdrant_client = MagicMock()
    with patch.object(qdrant_module, "_client", return_value=qdrant_client):
        qdrant_module.check_vector_store_health(test_settings())
    qdrant_client.get_collections.assert_called_once_with()

    settings = test_settings()
    vector_store_adapter = qdrant_module.QdrantVectorStore(settings)
    with patch.object(qdrant_module, "check_vector_store_health") as check_health:
        vector_store_adapter.check_health()
    check_health.assert_called_once_with(settings)

    vector_store = MagicMock()
    with patch.object(vector_store_port, "build_vector_store", return_value=vector_store):
        vector_store_port.check_vector_store_health(test_settings())
    vector_store.check_health.assert_called_once_with()


async def check_health_degradation() -> None:
    settings = test_settings()
    db = AsyncMock()
    healthy_probe = AsyncMock()
    with (
        patch("app.application.governance._probe_redis", healthy_probe),
        patch("app.application.governance._probe_qdrant", healthy_probe),
        patch("app.application.governance._probe_storage", healthy_probe),
        patch("app.application.governance._probe_worker", healthy_probe),
        patch(
            "app.application.governance.governance_repository.health_counts",
            new=AsyncMock(return_value=(2, 3)),
        ) as counts,
    ):
        response = await get_admin_health(db, settings)
    assert response.status == "ok"
    assert all(component.status == "ok" for component in response.components.values())
    assert (response.pending_tasks, response.failed_logs_24h) == (2, 3)
    counts.assert_awaited_once()

    db = AsyncMock()
    db.execute.side_effect = OSError("database down")
    with (
        patch("app.application.governance._probe_redis", healthy_probe),
        patch("app.application.governance._probe_qdrant", healthy_probe),
        patch("app.application.governance._probe_storage", healthy_probe),
        patch("app.application.governance._probe_worker", healthy_probe),
        patch(
            "app.application.governance.governance_repository.health_counts",
            new=AsyncMock(),
        ) as counts,
    ):
        response = await get_admin_health(db, settings)
    assert response.status == "degraded"
    assert response.components["database"].status == "error"
    assert response.pending_tasks == 0
    counts.assert_not_awaited()

    db = AsyncMock()
    with (
        patch("app.application.governance._probe_redis", healthy_probe),
        patch("app.application.governance._probe_qdrant", healthy_probe),
        patch("app.application.governance._probe_storage", healthy_probe),
        patch("app.application.governance._probe_worker", healthy_probe),
        patch(
            "app.application.governance.governance_repository.health_counts",
            new=AsyncMock(side_effect=OSError("query failed")),
        ),
    ):
        response = await get_admin_health(db, settings)
    assert response.components["database"].detail == "unavailable"

    async def slow_counts(*_args) -> tuple[int, int]:
        await asyncio.sleep(0.02)
        return 0, 0

    with (
        patch("app.application.governance._probe_redis", healthy_probe),
        patch("app.application.governance._probe_qdrant", healthy_probe),
        patch("app.application.governance._probe_storage", healthy_probe),
        patch("app.application.governance._probe_worker", healthy_probe),
        patch(
            "app.application.governance.governance_repository.health_counts",
            new=slow_counts,
        ),
        patch("app.application.governance.HEALTH_PROBE_TIMEOUT_SECONDS", 0.001),
    ):
        response = await get_admin_health(AsyncMock(), settings)
    assert response.components["database"].detail == "timeout"


def main() -> None:
    """
    Run the end-to-end governance and access-control integration test.
    """
    asyncio.run(check_health_probe_functions())
    asyncio.run(check_health_degradation())
    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        admin_headers = auth_headers(admin_token)

        with (
            patch("app.application.governance._probe_redis", new=AsyncMock()),
            patch("app.application.governance._probe_qdrant", new=AsyncMock()),
            patch("app.application.governance._probe_storage", new=AsyncMock()),
            patch("app.application.governance._probe_worker", new=AsyncMock()),
        ):
            health = client.get(
                "/api/v1/admin/governance/health", headers=admin_headers
            )
        assert health.status_code == 200, health.text
        assert health.json()["components"]["database"]["status"] == "ok"
        assert all(
            component["status"] == "ok"
            for component in health.json()["components"].values()
        )

        updated = client.patch(
            f"/api/v1/workspaces/{workspace_id}/governance",
            headers=admin_headers,
            json={
                "daily_run_limit": 50,
                "monthly_token_limit": 100_000,
                "alert_threshold_percent": 80,
                "retention_days": 90,
                "timezone": "Asia/Shanghai",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["daily_run_limit"] == 50

        inventory = client.get(
            f"/api/v1/workspaces/{workspace_id}/inventory", headers=admin_headers
        )
        assert inventory.status_code == 200, inventory.text
        assert inventory.json()["members_total"] == 1

        sessions = client.get("/api/v1/auth/sessions", headers=admin_headers)
        assert sessions.status_code == 200, sessions.text
        assert any(item["is_current"] for item in sessions.json())
        current_session = next(item for item in sessions.json() if item["is_current"])
        assert current_session["user_agent"] == "testclient"
        assert current_session["ip_address"] == "testclient"

        failed_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Wrong@12345."},
        )
        assert failed_login.status_code == 401, failed_login.text
        system_logs = client.get(
            "/api/v1/admin/system-logs?event=auth.login_failed",
            headers=admin_headers,
        )
        assert system_logs.status_code == 200, system_logs.text
        assert system_logs.json()[0]["message"] == "Login failed."

        invitation = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={
                "username": "workspace-admin",
                "email": "workspace-admin@example.com",
                "name": "Workspace Admin",
                "role": "admin",
            },
        )
        assert invitation.status_code == 201, invitation.text
        assert invitation.json()["kind"] == "personal"
        assert invitation.json()["invite_url"].startswith("/invite/")
        assert "?" not in invitation.json()["invite_url"]
        invite_token = invitation.json()["token"]

        accepted = client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": invite_token, "password": ADMIN_PASSWORD},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["workspaces"][0]["role"] == "admin"
        reused_personal = client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": invite_token, "password": ADMIN_PASSWORD},
        )
        assert reused_personal.status_code == 400, reused_personal.text

        ambiguous_invitation = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"role": "member"},
        )
        assert ambiguous_invitation.status_code == 422, ambiguous_invitation.text

        generic = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"kind": "generic", "role": "member"},
        )
        assert generic.status_code == 201, generic.text
        generic_payload = generic.json()
        assert generic_payload["kind"] == "generic"
        assert generic_payload["username"] is None
        assert generic_payload["invite_url"].endswith("?mode=generic")
        generic_token = generic_payload["token"]

        generic_admin = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"kind": "generic", "role": "admin"},
        )
        assert generic_admin.status_code == 422, generic_admin.text

        missing_identity = client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": generic_token, "password": ADMIN_PASSWORD},
        )
        assert missing_identity.status_code == 422, missing_identity.text

        for suffix in ("one", "two"):
            generic_acceptance = client.post(
                "/api/v1/auth/invitations/accept",
                json={
                    "token": generic_token,
                    "username": f"generic-{suffix}",
                    "email": f"generic-{suffix}@example.com",
                    "name": f"Generic {suffix.title()}",
                    "password": ADMIN_PASSWORD,
                },
            )
            assert generic_acceptance.status_code == 200, generic_acceptance.text
            assert generic_acceptance.json()["workspaces"][0]["role"] == "member"

        generic_invitation = next(
            item
            for item in client.get(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                headers=admin_headers,
            ).json()
            if item["id"] == generic_payload["id"]
        )
        assert generic_invitation["accepted_at"] is None

        revoked = client.delete(
            f"/api/v1/workspaces/{workspace_id}/invitations/{generic_payload['id']}",
            headers=admin_headers,
        )
        assert revoked.status_code == 204, revoked.text
        after_revoke = client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": generic_token,
                "username": "generic-three",
                "email": "generic-three@example.com",
                "name": "Generic Three",
                "password": ADMIN_PASSWORD,
            },
        )
        assert after_revoke.status_code == 400, after_revoke.text

        deleted = client.delete(
            f"/api/v1/workspaces/{workspace_id}/invitations/{generic_payload['id']}/permanent",
            headers=admin_headers,
        )
        assert deleted.status_code == 204, deleted.text
        remaining_invitations = client.get(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
        )
        assert remaining_invitations.status_code == 200, remaining_invitations.text
        assert generic_payload["id"] not in {
            item["id"] for item in remaining_invitations.json()
        }

        workspace_admin_token = login(
            client, "workspace-admin", ADMIN_PASSWORD
        )["access_token"]
        workspace_admin_headers = auth_headers(workspace_admin_token)
        assert (
            client.get(
                f"/api/v1/workspaces/{workspace_id}/governance",
                headers=workspace_admin_headers,
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/admin/system-logs", headers=workspace_admin_headers
            ).status_code
            == 403
        )


if __name__ == "__main__":
    main()

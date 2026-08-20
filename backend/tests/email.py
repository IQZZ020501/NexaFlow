"""Identity email and password-reset regression checks.

Run from ``backend/`` with ``uv run python -m tests.email``.
"""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, call, patch

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.support import (
    ADMIN_PASSWORD,
    activate_admin,
    auth_headers,
    login,
    settings as test_settings,
    test_client,
)
from app.application.email import (
    EMAIL_BROKER_TIMEOUT_SECONDS,
    EMAIL_DISPATCH_TIMEOUT_SECONDS,
    EMAIL_PUBLISH_RETRY_POLICY,
    _claim_delivery,
    _defer_unconfigured,
    _finish_delivery,
    dispatch_email_deliveries,
    list_due_email_delivery_ids,
    queue_identity_email,
    run_email_delivery,
)
from app.entities.email import EmailDelivery as EmailDeliveryEntity
from app.entities.smtp_settings import SmtpSettings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import email as email_repository
from app.infrastructure.secrets import decrypt_secret, encrypt_secret
from app.infrastructure.session import get_session_factory
from app.infrastructure.smtp import SmtpConfigurationError, SmtpDeliveryError
from app.shareddomain.email.models import EmailDelivery, PasswordResetToken
from app.shareddomain.email.services import EmailPayloadError, render_email


async def delivery_rows() -> list[EmailDelivery]:
    async with get_session_factory()() as db:
        return list(await db.scalars(select(EmailDelivery).order_by(EmailDelivery.created_at)))


async def reset_rows() -> list[PasswordResetToken]:
    async with get_session_factory()() as db:
        return list(await db.scalars(select(PasswordResetToken)))


async def reset_delivery_due(delivery_id: str) -> None:
    async with get_session_factory()() as db:
        row = await db.get(EmailDelivery, delivery_id)
        assert row is not None
        row.next_attempt_at = utc_now() - timedelta(seconds=1)
        await db.commit()


async def delivery_count() -> int:
    async with get_session_factory()() as db:
        return int(await db.scalar(select(func.count()).select_from(EmailDelivery)) or 0)


async def create_delivery(
    *,
    kind: str = "password_changed",
    payload: object | None = None,
    status: str = "pending",
    attempts: int = 0,
    max_attempts: int = 24,
    next_attempt_delta: timedelta = timedelta(seconds=-1),
    lease_token: str | None = None,
    lease_delta: timedelta | None = None,
    expires_delta: timedelta = timedelta(days=1),
) -> str:
    now = utc_now()
    content = (
        payload
        if payload is not None
        else {
            "recipient": "member@example.com",
            "name": "Member",
            "changed_by": "test",
            "changed_at": now.isoformat(),
        }
    )
    async with get_session_factory()() as db:
        delivery = await email_repository.create_delivery(
            db,
            EmailDeliveryEntity(
                kind=kind,
                payload_ciphertext=encrypt_secret(
                    json.dumps(content),
                    test_settings().model_secret_key,
                ),
                source_type="coverage",
                source_id=hashlib.sha256(str(now).encode()).hexdigest()[:36],
                status=status,
                attempts=attempts,
                max_attempts=max_attempts,
                next_attempt_at=now + next_attempt_delta,
                lease_token=lease_token,
                lease_expires_at=(
                    now + lease_delta if lease_delta is not None else None
                ),
                expires_at=now + expires_delta,
            ),
        )
        await db.commit()
        return delivery.id


async def get_delivery(delivery_id: str) -> EmailDelivery | None:
    async with get_session_factory()() as db:
        row = await db.get(EmailDelivery, delivery_id)
        return row


def test_email_templates() -> None:
    cases = {
        "workspace_invitation": {
            "recipient": "invitee@example.com",
            "name": "<Invitee>",
            "workspace": "Workspace",
            "inviter": "Admin",
            "role": "member",
            "url": "https://nexaflow.example/invite/a&b",
        },
        "welcome": {
            "recipient": "member@example.com",
            "name": "Member",
            "username": "member",
            "workspace": "Workspace",
            "url": "https://nexaflow.example/login",
        },
        "password_reset": {
            "recipient": "member@example.com",
            "name": "Member",
            "url": "https://nexaflow.example/reset-password/token",
        },
        "password_changed": {
            "recipient": "member@example.com",
            "name": "Member",
            "changed_by": "self service",
            "changed_at": "2026-08-20T12:00:00+00:00",
        },
    }
    for kind, payload in cases.items():
        rendered = render_email(kind, payload)
        assert rendered.recipient == payload["recipient"]
        assert "NexaFlow" in rendered.subject
        assert "NexaFlow" in rendered.html_body
    assert "&lt;Invitee&gt;" in render_email(
        "workspace_invitation", cases["workspace_invitation"]
    ).html_body

    for kind, payload in (("unsupported", {}), ("welcome", {"recipient": "x@y"})):
        try:
            render_email(kind, payload)
        except EmailPayloadError:
            pass
        else:
            raise AssertionError("Invalid email payload was accepted")


def test_email_task_wrappers() -> None:
    import app.tasks.email as email_tasks

    settings = test_settings()
    with (
        patch("app.tasks.email.Settings.from_env", return_value=settings),
        patch("app.tasks.email.configure_task_worker") as configure_worker,
        patch("app.tasks.email.run_email_delivery", new=AsyncMock()) as run_delivery,
    ):
        email_tasks.run_email_delivery_job.run("delivery-id")
    configure_worker.assert_called_once_with(settings)
    run_delivery.assert_awaited_once_with("delivery-id", settings)

    with (
        patch("app.tasks.email.Settings.from_env", return_value=settings),
        patch("app.tasks.email.configure_task_worker"),
        patch(
            "app.tasks.email.run_email_delivery",
            new=AsyncMock(side_effect=RuntimeError("crashed")),
        ),
        patch("app.tasks.email.log_error") as log_error,
    ):
        email_tasks.run_email_delivery_job.run("failed-id")
    log_error.assert_called_once()

    with (
        patch("app.tasks.email.Settings.from_env", return_value=settings),
        patch("app.tasks.email.configure_task_worker") as configure_worker,
        patch(
            "app.tasks.email.list_due_email_delivery_ids",
            new=AsyncMock(return_value=["one", "two"]),
        ),
        patch.object(email_tasks.run_email_delivery_job, "apply_async") as apply_async,
    ):
        email_tasks.recover_email_deliveries_job.run()
    configure_worker.assert_called_once_with(settings)
    assert apply_async.call_args_list == [
        call(args=("one",)),
        call(args=("two",)),
    ]


async def test_delivery_edge_cases() -> None:
    settings = test_settings()

    smtp = SmtpSettings(
        host="smtp.example.com",
        from_email="noreply@example.com",
        site_url="https://nexaflow.example/",
        enabled=True,
    )
    create_delivery_mock = AsyncMock(side_effect=lambda _db, delivery: delivery)
    with (
        patch(
            "app.application.email.smtp_repository.get",
            new=AsyncMock(return_value=smtp),
        ),
        patch(
            "app.application.email.email_repository.create_delivery",
            new=create_delivery_mock,
        ),
    ):
        queued_id = await queue_identity_email(
            AsyncMock(),
            settings,
            kind="password_reset",
            recipient="member@example.com",
            payload={"name": "Member"},
            expires_at=utc_now() + timedelta(minutes=30),
            source_type="password_reset",
            source_id="reset-id",
            path="/reset-password/token",
        )
    queued_delivery = create_delivery_mock.await_args.args[1]
    assert queued_id == queued_delivery.id
    queued_payload = json.loads(
        decrypt_secret(queued_delivery.payload_ciphertext, settings.model_secret_key)
    )
    assert queued_payload["url"] == "https://nexaflow.example/reset-password/token"

    await _defer_unconfigured("missing-delivery")

    live_id = await create_delivery(
        status="sending",
        attempts=1,
        lease_token="live-lease",
        lease_delta=timedelta(minutes=5),
    )
    await _defer_unconfigured(live_id)
    assert (await get_delivery(live_id)).status == "sending"  # type: ignore[union-attr]

    expired_id = await create_delivery(expires_delta=timedelta(seconds=-1))
    await _defer_unconfigured(expired_id)
    assert await get_delivery(expired_id) is None

    deferred_id = await create_delivery()
    await _defer_unconfigured(deferred_id)
    deferred = await get_delivery(deferred_id)
    assert deferred is not None
    assert deferred.status == "retry"
    assert deferred.last_error_code == "EmailServiceUnavailable"

    with (
        patch(
            "app.application.email.smtp_repository.get",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.application.email._defer_unconfigured",
            new=AsyncMock(),
        ) as defer,
    ):
        assert await _claim_delivery("not-ready", settings) is None
    defer.assert_awaited_once_with("not-ready")

    with (
        patch(
            "app.application.email.build_smtp_transport_config",
            side_effect=SmtpConfigurationError("invalid"),
        ),
        patch(
            "app.application.email._defer_unconfigured",
            new=AsyncMock(),
        ) as defer,
    ):
        assert await _claim_delivery("invalid-config", settings) is None
    defer.assert_awaited_once_with("invalid-config")

    assert await _claim_delivery("missing-delivery", settings) is None

    expired_claim_id = await create_delivery(expires_delta=timedelta(seconds=-1))
    assert await _claim_delivery(expired_claim_id, settings) is None
    assert await get_delivery(expired_claim_id) is None

    leased_id = await create_delivery(
        status="sending",
        attempts=1,
        lease_token="leased",
        lease_delta=timedelta(minutes=5),
    )
    assert await _claim_delivery(leased_id, settings) is None

    stale_id = await create_delivery(
        status="sending",
        attempts=1,
        lease_token="current-lease",
        lease_delta=timedelta(minutes=5),
    )
    await _finish_delivery(stale_id, "stale-lease", error=None)
    assert await get_delivery(stale_id) is not None

    invalid_payload_id = await create_delivery(
        payload=[],
        max_attempts=1,
    )
    await run_email_delivery(invalid_payload_id, settings)
    assert await get_delivery(invalid_payload_id) is None

    due_id = await create_delivery()
    assert due_id in await list_due_email_delivery_ids()

    with patch(
        "app.application.email.run_email_delivery",
        new=AsyncMock(),
    ) as eager_delivery:
        await dispatch_email_deliveries(["one", "two"], settings)
    assert eager_delivery.await_args_list == [
        call("one", settings),
        call("two", settings),
    ]

    broker_settings = replace(settings, celery_task_always_eager=False)
    import app.tasks.email as email_tasks

    from app.infrastructure.celery import celery_app

    with (
        patch.object(email_tasks.run_email_delivery_job, "apply_async") as apply_async,
        patch(
            "app.application.email.asyncio.wait_for",
            wraps=asyncio.wait_for,
        ) as wait_for,
    ):
        await dispatch_email_deliveries(["queued"], broker_settings)
    apply_async.assert_called_once_with(
        args=("queued",),
        retry=True,
        retry_policy=EMAIL_PUBLISH_RETRY_POLICY,
    )
    wait_for.assert_awaited_once()
    assert wait_for.await_args.kwargs["timeout"] == EMAIL_DISPATCH_TIMEOUT_SECONDS
    assert celery_app.conf.broker_connection_timeout == EMAIL_BROKER_TIMEOUT_SECONDS
    assert (
        celery_app.conf.broker_transport_options["socket_connect_timeout"]
        == EMAIL_BROKER_TIMEOUT_SECONDS
    )
    assert (
        celery_app.conf.broker_transport_options["socket_timeout"]
        == EMAIL_BROKER_TIMEOUT_SECONDS
    )

    with (
        patch.object(
            email_tasks.run_email_delivery_job,
            "apply_async",
            side_effect=RuntimeError("broker down"),
        ),
        patch("app.application.email.log_error") as log_error,
    ):
        await dispatch_email_deliveries(["deferred"], broker_settings)
    log_error.assert_called_once()


async def test_invitation_and_reset_validation() -> None:
    from app.application.invitations import create_workspace_invitation
    from app.application.password_reset import confirm_password_reset
    from app.entities.user import User
    from app.schemas.invitation import WorkspaceInvitationCreateRequest

    db = AsyncMock()
    personal_admin = WorkspaceInvitationCreateRequest(
        kind="personal",
        username="admin-invite",
        email="admin-invite@example.com",
        name="Admin Invite",
        role="admin",
    )
    try:
        await create_workspace_invitation(
            db,
            "workspace-id",
            User(is_global_admin=False),
            personal_admin,
            test_settings(),
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Non-system admin invitation was accepted")

    generic = WorkspaceInvitationCreateRequest(kind="generic", role="member")
    with patch(
        "app.application.invitations.workspace_repository.get_workspace_by_id",
        new=AsyncMock(return_value=None),
    ):
        try:
            await create_workspace_invitation(
                db,
                "missing-workspace",
                User(is_global_admin=True),
                generic,
                test_settings(),
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("Invitation was created for a missing workspace")

    workspace = type("Workspace", (), {"status": "active", "name": "Workspace"})()
    with (
        patch(
            "app.application.invitations.workspace_repository.get_workspace_by_id",
            new=AsyncMock(return_value=workspace),
        ),
        patch(
            "app.application.invitations.invitation_repository.create",
            new=AsyncMock(
                side_effect=IntegrityError("insert", {}, RuntimeError("duplicate"))
            ),
        ),
    ):
        try:
            await create_workspace_invitation(
                db,
                "workspace-id",
                User(is_global_admin=True),
                generic,
                test_settings(),
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Duplicate invitation token was accepted")
    db.rollback.assert_awaited()

    inactive = User(id="inactive-user", is_active=False)
    with (
        patch(
            "app.application.password_reset.email_repository.get_password_reset_token_user_id",
            new=AsyncMock(return_value=inactive.id),
        ),
        patch(
            "app.application.password_reset.user_repository.lock_user",
            new=AsyncMock(return_value=inactive),
        ),
    ):
        try:
            await confirm_password_reset(
                db,
                "token",
                "NewPassword@123",
                test_settings(),
            )
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Inactive user reset was accepted")


def configure_identity_email(client, headers: dict[str, str]) -> None:
    response = client.patch(
        "/api/v1/admin/smtp",
        headers=headers,
        json={
            "host": "smtp.example.com",
            "port": 587,
            "security": "starttls",
            "from_email": "noreply@example.com",
            "from_name": "NexaFlow",
            "site_url": "https://nexaflow.example/",
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["site_url"] == "https://nexaflow.example"
    assert response.json()["identity_configured"] is True


def main() -> None:
    test_email_templates()
    test_email_task_wrappers()
    asyncio.run(test_invitation_and_reset_validation())
    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        admin_headers = auth_headers(admin_token)

        unavailable = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "admin@app.local"},
        )
        assert unavailable.status_code == 503, unavailable.text
        assert unavailable.json()["detail"] == "Email service is not configured."
        assert asyncio.run(reset_rows()) == []

        offline_invite = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={
                "kind": "personal",
                "username": "offline-member",
                "email": "offline-member@example.com",
                "name": "Offline Member",
                "role": "member",
            },
        )
        assert offline_invite.status_code == 201, offline_invite.text
        assert offline_invite.json()["email_delivery_status"] == "not_configured"
        assert offline_invite.json()["token"]
        assert asyncio.run(delivery_count()) == 0

        configure_identity_email(client, admin_headers)

        with patch(
            "app.application.invitations.dispatch_email_deliveries",
            new=AsyncMock(),
        ) as dispatch:
            personal = client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                headers=admin_headers,
                json={
                    "kind": "personal",
                    "username": "mail-member",
                    "email": "mail-member@example.com",
                    "name": "Mail Member",
                    "role": "member",
                },
            )
        assert personal.status_code == 201, personal.text
        personal_payload = personal.json()
        assert personal_payload["email_delivery_status"] == "queued"
        invitation_delivery_id = dispatch.await_args.args[0][0]
        invitation_delivery = next(
            row
            for row in asyncio.run(delivery_rows())
            if row.id == invitation_delivery_id
        )
        encrypted = invitation_delivery.payload_ciphertext
        assert personal_payload["token"] not in encrypted
        invitation_email = json.loads(
            decrypt_secret(encrypted, test_settings().model_secret_key)
        )
        assert invitation_email["recipient"] == "mail-member@example.com"
        assert invitation_email["url"] == (
            f"https://nexaflow.example/invite/{personal_payload['token']}"
        )

        with patch(
            "app.application.invitations.dispatch_email_deliveries",
            new=AsyncMock(),
        ):
            generic = client.post(
                f"/api/v1/workspaces/{workspace_id}/invitations",
                headers=admin_headers,
                json={"kind": "generic", "role": "member"},
            )
        assert generic.status_code == 201, generic.text
        generic_payload = generic.json()
        assert generic_payload["email_delivery_status"] == "not_applicable"

        incomplete_generic = client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": generic_payload["token"],
                "password": "Generic@123",
            },
        )
        assert incomplete_generic.status_code == 422, incomplete_generic.text

        invitations = client.get(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
        )
        assert invitations.status_code == 200, invitations.text
        assert generic_payload["id"] in {item["id"] for item in invitations.json()}

        with patch(
            "app.application.invitations.dispatch_email_deliveries",
            new=AsyncMock(),
        ) as welcome_dispatch:
            accepted = client.post(
                "/api/v1/auth/invitations/accept",
                json={
                    "token": personal_payload["token"],
                    "password": "Member@123",
                },
            )
        assert accepted.status_code == 200, accepted.text
        welcome_id = welcome_dispatch.await_args.args[0][0]
        remaining = asyncio.run(delivery_rows())
        assert all(row.id != invitation_delivery_id for row in remaining)
        welcome = next(row for row in remaining if row.id == welcome_id)
        welcome_payload = json.loads(
            decrypt_secret(welcome.payload_ciphertext, test_settings().model_secret_key)
        )
        assert welcome.kind == "welcome"
        assert welcome_payload["url"] == "https://nexaflow.example/login"

        with patch(
            "app.application.invitations.dispatch_email_deliveries",
            new=AsyncMock(),
        ) as generic_welcome_dispatch:
            generic_accepted = client.post(
                "/api/v1/auth/invitations/accept",
                json={
                    "token": generic_payload["token"],
                    "username": "generic-member",
                    "email": "generic-member@example.com",
                    "name": "Generic Member",
                    "password": "Generic@123",
                },
            )
        assert generic_accepted.status_code == 200, generic_accepted.text
        generic_welcome_dispatch.assert_awaited_once()

        duplicate_generic = client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": generic_payload["token"],
                "username": "generic-member",
                "email": "generic-member@example.com",
                "name": "Generic Member",
                "password": "Generic@456",
            },
        )
        assert duplicate_generic.status_code == 409, duplicate_generic.text

        invalid_invitation = client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": "x" * 32, "password": "Member@123"},
        )
        assert invalid_invitation.status_code == 400, invalid_invitation.text

        revokable = client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"kind": "generic", "role": "member"},
        )
        assert revokable.status_code == 201, revokable.text
        revoked = client.delete(
            f"/api/v1/workspaces/{workspace_id}/invitations/{revokable.json()['id']}",
            headers=admin_headers,
        )
        assert revoked.status_code == 204, revoked.text
        missing_revoke = client.delete(
            f"/api/v1/workspaces/{workspace_id}/invitations/missing-invitation",
            headers=admin_headers,
        )
        assert missing_revoke.status_code == 404, missing_revoke.text

        member_token = login(client, "mail-member", "Member@123")["access_token"]
        with patch(
            "app.application.identity.dispatch_email_deliveries",
            new=AsyncMock(),
        ) as password_dispatch:
            changed = client.post(
                "/api/v1/auth/change-password",
                headers=auth_headers(member_token),
                json={
                    "current_password": "Member@123",
                    "new_password": "Member@456",
                },
            )
        assert changed.status_code == 204, changed.text
        password_delivery_id = password_dispatch.await_args.args[0][0]

        failure = AsyncMock(side_effect=SmtpDeliveryError("SMTP delivery failed."))
        with patch("app.application.email.send_smtp_message", new=failure):
            asyncio.run(run_email_delivery(password_delivery_id, test_settings()))
        retried = next(
            row
            for row in asyncio.run(delivery_rows())
            if row.id == password_delivery_id
        )
        assert retried.status == "retry"
        assert retried.attempts == 1
        assert retried.last_error_code == "SmtpDeliveryError"

        sender = AsyncMock()
        with patch("app.application.email.send_smtp_message", new=sender):
            asyncio.run(run_email_delivery(password_delivery_id, test_settings()))
        sender.assert_not_awaited()
        asyncio.run(reset_delivery_due(password_delivery_id))
        with patch("app.application.email.send_smtp_message", new=sender):
            asyncio.run(run_email_delivery(password_delivery_id, test_settings()))
        sender.assert_awaited_once()
        assert all(
            row.id != password_delivery_id for row in asyncio.run(delivery_rows())
        )

        unknown = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "missing@example.com"},
        )
        assert unknown.status_code == 202, unknown.text
        assert unknown.content == b""

        with patch(
            "app.application.password_reset.dispatch_email_deliveries",
            new=AsyncMock(),
        ) as reset_dispatch:
            requested = client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "admin@app.local"},
            )
        assert requested.status_code == 202, requested.text
        assert requested.content == unknown.content
        reset_delivery_id = reset_dispatch.await_args.args[0][0]
        reset_delivery = next(
            row
            for row in asyncio.run(delivery_rows())
            if row.id == reset_delivery_id
        )
        reset_payload = json.loads(
            decrypt_secret(
                reset_delivery.payload_ciphertext,
                test_settings().model_secret_key,
            )
        )
        raw_reset_token = reset_payload["url"].rsplit("/", 1)[-1]
        stored_resets = asyncio.run(reset_rows())
        assert len(stored_resets) == 1
        stored_reset = stored_resets[0]
        assert stored_reset.token_hash == hashlib.sha256(
            raw_reset_token.encode("utf-8")
        ).hexdigest()
        assert raw_reset_token not in stored_reset.token_hash
        assert raw_reset_token not in reset_delivery.payload_ciphertext

        same_password = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": raw_reset_token, "new_password": ADMIN_PASSWORD},
        )
        assert same_password.status_code == 400, same_password.text
        assert same_password.json()["detail"] == "New password must be different."

        invalid = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": "x" * 32, "new_password": "Reset@123"},
        )
        assert invalid.status_code == 400, invalid.text
        assert invalid.json()["detail"] == "Password reset link is invalid or expired."

        with patch(
            "app.application.password_reset.dispatch_email_deliveries",
            new=AsyncMock(),
        ):
            confirmed = client.post(
                "/api/v1/auth/password-reset/confirm",
                json={"token": raw_reset_token, "new_password": "Reset@123"},
            )
        assert confirmed.status_code == 204, confirmed.text
        reused = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": raw_reset_token, "new_password": "Again@123"},
        )
        assert reused.status_code == 400, reused.text
        assert login(client, "admin", "Reset@123")["access_token"]
        old_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD},
        )
        assert old_login.status_code == 401, old_login.text

        class LimitedRedis:
            async def eval(self, *_args):
                return [4, 1, 42, 42]

        with patch(
            "app.infrastructure.agent_rate_limit._rate_limit_redis",
            return_value=LimitedRedis(),
        ):
            limited = client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "missing@example.com"},
            )
        assert limited.status_code == 429, limited.text
        assert limited.headers["retry-after"] == "42"

        class BrokenRedis:
            async def eval(self, *_args):
                raise OSError("unavailable")

        with patch(
            "app.infrastructure.agent_rate_limit._rate_limit_redis",
            return_value=BrokenRedis(),
        ):
            limited = client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "missing@example.com"},
            )
        assert limited.status_code == 503, limited.text
        assert limited.json()["detail"] == "Password reset is temporarily unavailable."

        with patch(
            "app.application.password_reset.queue_identity_email",
            new=AsyncMock(return_value=None),
        ):
            configuration_race = client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "admin@app.local"},
            )
        assert configuration_race.status_code == 503, configuration_race.text

        asyncio.run(test_delivery_edge_cases())

        import app.tasks.email  # noqa: F401
        from app.infrastructure.celery import celery_app

        assert "app.email.send" in celery_app.tasks
        assert "app.email.recover" in celery_app.tasks
        assert (
            celery_app.conf.beat_schedule["recover-email-deliveries"]["task"]
            == "app.email.recover"
        )

    print("email tests passed")


if __name__ == "__main__":
    main()

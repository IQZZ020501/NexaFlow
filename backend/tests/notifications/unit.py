"""Pure unit tests for personal task notifications and unified message inbox."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401

from app.adapters.notifications.live_stream import user_notification_stream_key
from app.application.notifications.service import (
    get_unified_message_summary,
    list_unified_messages,
    notification_to_message_response,
)
from app.domain.notifications.service import (
    build_notification_copy,
    notification_severity,
)
from app.entities.identity.user import User
from app.entities.notifications import UserNotification
from app.schemas.announcements import AnnouncementMessageResponse


def test_notification_copy_and_severity() -> None:
    title, body = build_notification_copy(
        automation_name="Daily Digest",
        event_type="awaiting_approval",
    )
    assert "Daily Digest" in title
    assert "审批" in body
    assert notification_severity("awaiting_approval") == "warning"
    assert notification_severity("awaiting_input") == "warning"
    assert notification_severity("failed") == "critical"
    assert notification_severity("succeeded") == "info"
    assert notification_severity("cancelled") == "info"

    fail_title, fail_body = build_notification_copy(
        automation_name="Nightly Sync",
        event_type="failed",
        error_message="Connection timeout",
    )
    assert "Nightly Sync" in fail_title
    assert "Connection timeout" not in fail_body


def test_per_user_stream_key_isolation() -> None:
    key_a = user_notification_stream_key("user-a")
    key_b = user_notification_stream_key("user-b")
    assert key_a != key_b
    assert "user-a" in key_a
    assert "user-b" in key_b


async def _run_unified_inbox_merge() -> None:
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    actor = User(id="user-1", username="alice")
    pinned_ann = AnnouncementMessageResponse(
        id="ann-1",
        scope_type="global",
        workspace_id=None,
        title="Pinned Notice",
        body="Maintenance",
        severity="info",
        pinned=True,
        published_at=now - timedelta(hours=2),
        expires_at=None,
        is_read=False,
        read_at=None,
        created_at=now - timedelta(hours=2),
    )
    notif = UserNotification(
        id="notif-1",
        user_id="user-1",
        workspace_id="ws-1",
        automation_id="auto-1",
        execution_id="exec-1",
        run_id="run-1",
        event_type="succeeded",
        title="Auto: done",
        body="All good",
        metadata_json={
            "automation_name": "Auto",
            "target_app_id": "app-1",
            "target_app_type": "agent",
            "trigger_source": "schedule",
        },
        dedup_key="exec:exec-1:succeeded",
        created_at=now - timedelta(minutes=1),
    )
    assert notification_to_message_response(notif).automation_name == "Auto"

    with (
        patch(
            "app.application.notifications.service.notification_repository.list_unified_message_keys",
            new=AsyncMock(
                return_value=(
                    [("announcement", "ann-1"), ("notification", "notif-1")],
                    2,
                )
            ),
        ),
        patch(
            "app.application.notifications.service.list_announcement_messages",
            new=AsyncMock(return_value=([pinned_ann], 1)),
        ),
        patch(
            "app.application.notifications.service.notification_repository.list_user_notifications",
            new=AsyncMock(return_value=([notif], 1)),
        ),
        patch(
            "app.application.notifications.service.get_announcement_message_summary",
            new=AsyncMock(return_value=(1, None)),
        ),
        patch(
            "app.application.notifications.service.notification_repository.count_unread_notifications",
            new=AsyncMock(return_value=1),
        ),
    ):
        items, total = await list_unified_messages(
            None,
            user=actor,
            workspace_id="ws-1",
            limit=10,
            offset=0,  # type: ignore[arg-type]
        )
        assert total == 2
        assert items[0].id == "ann-1"  # pinned stays first
        assert items[1].id == "notif-1"
        assert items[1].kind == "notification"

        unread, _ = await get_unified_message_summary(
            None,
            user=actor,
            workspace_id="ws-1",  # type: ignore[arg-type]
        )
        assert unread == 2


def main() -> None:
    test_notification_copy_and_severity()
    test_per_user_stream_key_isolation()
    asyncio.run(_run_unified_inbox_merge())
    print("NOTIFICATIONS_UNIT_OK")


if __name__ == "__main__":
    main()

"""Timezone contracts; run with ``uv run python -m tests.infra.timezone``."""

import os
import time
from datetime import UTC, datetime, timedelta

import tests.support  # noqa: F401
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infra.queue.celery import celery_app
from app.infra.runtime.timezone import configure_process_timezone
from app.schemas.announcements.contracts import AnnouncementResponse


def announcement(value: datetime) -> AnnouncementResponse:
    return AnnouncementResponse(
        id="notice", scope_type="global", workspace_id=None, title="Notice",
        body="Body", severity="info", pinned=False, status="published",
        published_at=value, expires_at=None, created_by_user_id=None,
        updated_by_user_id=None, created_at=value, updated_at=value,
    )


def test_api_timestamps_preserve_instants_in_shanghai() -> None:
    instant = datetime(2026, 11, 19, 16, 30, tzinfo=UTC)
    model = announcement(instant)
    # Internal Python values keep their original instant and timezone.
    assert model.model_dump()["created_at"] is instant
    for source in (instant, instant.replace(tzinfo=None)):
        app = FastAPI()

        @app.get("/notices")
        async def notices() -> list[AnnouncementResponse]:
            return [announcement(source)]

        with TestClient(app) as client:
            payload = client.get("/notices").json()[0]
        for field in ("published_at", "created_at", "updated_at"):
            assert payload[field] == "2026-11-20T00:30:00+08:00", payload
            decoded = datetime.fromisoformat(payload[field])
            assert decoded == instant
            assert decoded.utcoffset() == timedelta(hours=8)
        assert payload["expires_at"] is None


def main() -> None:
    test_api_timestamps_preserve_instants_in_shanghai()
    assert celery_app.conf.timezone == "Asia/Shanghai"
    assert celery_app.conf.enable_utc is True
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    configure_process_timezone()
    assert os.environ["TZ"] == "Asia/Shanghai"
    if hasattr(time, "tzset"):
        assert time.localtime(0).tm_hour == 8
    print("TIMEZONE_OK")


if __name__ == "__main__":
    main()

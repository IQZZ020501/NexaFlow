"""Entity default value helpers.

Pure stdlib id/time helpers shared by entity dataclasses, ORM models and
repositories. Kept free of any infra or framework import so the entities
layer never depends on infrastructure.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

APP_TIMEZONE_NAME = "Asia/Shanghai"
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)

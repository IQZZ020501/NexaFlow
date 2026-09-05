from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo


APP_TIMEZONE_NAME = "Asia/Shanghai"
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)

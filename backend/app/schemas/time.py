"""Public timestamps use China Standard Time without changing stored instants."""

from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer

from app.entities.defaults import to_app_timezone


def _serialize_datetime(value: datetime) -> str:
    return to_app_timezone(value).isoformat()


AppDateTime = Annotated[
    datetime,
    PlainSerializer(_serialize_datetime, return_type=str, when_used="json"),
]

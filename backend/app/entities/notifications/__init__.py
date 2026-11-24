"""Pure entity definitions for personal user notifications."""

from app.entities.notifications.models import (
    USER_NOTIFICATION_EVENT_TYPES,
    UserNotification,
)

__all__ = [
    "USER_NOTIFICATION_EVENT_TYPES",
    "UserNotification",
]

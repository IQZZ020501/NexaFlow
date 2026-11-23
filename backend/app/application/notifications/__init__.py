"""Public interface for per-user task notifications and unified inbox feed."""

from app.application.notifications.live import (
    UnifiedMessageStreamUpdate,
    stream_unified_message_updates,
)
from app.application.notifications.service import (
    create_task_notification_in_txn,
    get_unified_message_summary,
    list_unified_messages,
    mark_all_unified_messages_read,
    mark_unified_message_read,
    notification_to_message_response,
    publish_live_task_notification,
)

__all__ = [
    "UnifiedMessageStreamUpdate",
    "create_task_notification_in_txn",
    "get_unified_message_summary",
    "list_unified_messages",
    "mark_all_unified_messages_read",
    "mark_unified_message_read",
    "notification_to_message_response",
    "publish_live_task_notification",
    "stream_unified_message_updates",
]

"""Pure formatting and severity rules for personal task notifications."""

from app.entities.notifications import USER_NOTIFICATION_EVENT_TYPES

NOTIFICATION_EVENT_SEVERITY = {
    "succeeded": "info",
    "failed": "critical",
    "cancelled": "info",
    "awaiting_approval": "warning",
    "awaiting_input": "warning",
}

EVENT_TITLES = {
    "succeeded": "{name}: 执行成功",
    "failed": "{name}: 执行失败",
    "cancelled": "{name}: 已取消",
    "awaiting_approval": "{name}: 待审批确认",
    "awaiting_input": "{name}: 待填写表单",
}


def notification_severity(event_type: str) -> str:
    return NOTIFICATION_EVENT_SEVERITY.get(event_type, "info")


def build_notification_copy(
    *,
    automation_name: str,
    event_type: str,
    error_message: str | None = None,
    result_preview: str | None = None,
) -> tuple[str, str]:
    if event_type not in USER_NOTIFICATION_EVENT_TYPES:
        raise ValueError(f"Unsupported notification event type: {event_type}")
    title = EVENT_TITLES[event_type].format(name=automation_name)[:200]
    # Notification bodies remain status-only; results and errors require live Run access.
    bodies = {
        "succeeded": "自动化任务已完成。",
        "failed": "自动化任务执行失败，请查看运行详情。",
        "cancelled": "本次自动化执行已被取消。",
        "awaiting_approval": "运行过程中触发了需要人工审批的工具调用，请前往执行详情处理。",
        "awaiting_input": "工作流正等待补充表单输入，请前往执行详情提交后继续运行。",
    }
    return title, bodies[event_type]

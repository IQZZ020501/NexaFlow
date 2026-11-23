"""Pure entity definitions for workspace automations and execution triggers."""

from app.entities.automations.models import (
    AUTOMATION_APPROVAL_MODES,
    AUTOMATION_EXECUTION_DISPATCH_STATUSES,
    AUTOMATION_EXECUTION_TRIGGER_SOURCES,
    AUTOMATION_STATUSES,
    AUTOMATION_TARGET_APP_TYPES,
    AUTOMATION_TRIGGER_TYPES,
    Automation,
    AutomationExecution,
)

__all__ = [
    "AUTOMATION_APPROVAL_MODES",
    "AUTOMATION_EXECUTION_DISPATCH_STATUSES",
    "AUTOMATION_EXECUTION_TRIGGER_SOURCES",
    "AUTOMATION_STATUSES",
    "AUTOMATION_TARGET_APP_TYPES",
    "AUTOMATION_TRIGGER_TYPES",
    "Automation",
    "AutomationExecution",
]

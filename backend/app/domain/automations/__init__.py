"""Pure domain helpers for workspace automations."""

from app.domain.automations.inputs import (
    build_execution_input_snapshot,
    extract_run_goal_and_extra_inputs,
    validate_input_config,
)
from app.domain.automations.models import (
    AUTOMATION_STATUS_ACTIVE,
    AUTOMATION_STATUS_COMPLETED,
    AUTOMATION_STATUS_PAUSED,
    EXECUTION_DISPATCH_DISPATCHED,
    EXECUTION_DISPATCH_PENDING,
    EXECUTION_DISPATCH_QUEUED,
    EXECUTION_DISPATCH_REJECTED,
    EXECUTION_DISPATCH_SKIPPED,
)
from app.domain.automations.schedule import (
    DEFAULT_TIMEZONE_NAME,
    compute_next_schedule_at,
    resolve_due_schedule_slot,
    validate_trigger_config,
)
from app.domain.automations.webhook import (
    DEFAULT_WEBHOOK_MAX_PENDING,
    MAX_WEBHOOK_MAX_PENDING,
    MAX_WEBHOOK_PAYLOAD_BYTES,
    MAX_WEBHOOK_TIMESTAMP_SKEW_SECONDS,
    canonical_payload_hash,
    generate_webhook_secret,
    normalize_event_id,
    sign_webhook_payload,
    verify_webhook_signature,
)

__all__ = [
    "AUTOMATION_STATUS_ACTIVE",
    "AUTOMATION_STATUS_COMPLETED",
    "AUTOMATION_STATUS_PAUSED",
    "DEFAULT_TIMEZONE_NAME",
    "DEFAULT_WEBHOOK_MAX_PENDING",
    "EXECUTION_DISPATCH_DISPATCHED",
    "EXECUTION_DISPATCH_PENDING",
    "EXECUTION_DISPATCH_QUEUED",
    "EXECUTION_DISPATCH_REJECTED",
    "EXECUTION_DISPATCH_SKIPPED",
    "MAX_WEBHOOK_MAX_PENDING",
    "MAX_WEBHOOK_PAYLOAD_BYTES",
    "MAX_WEBHOOK_TIMESTAMP_SKEW_SECONDS",
    "build_execution_input_snapshot",
    "canonical_payload_hash",
    "compute_next_schedule_at",
    "extract_run_goal_and_extra_inputs",
    "generate_webhook_secret",
    "normalize_event_id",
    "resolve_due_schedule_slot",
    "sign_webhook_payload",
    "validate_input_config",
    "validate_trigger_config",
    "verify_webhook_signature",
]

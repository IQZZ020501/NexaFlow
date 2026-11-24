"""Pydantic contracts for workspace automations and webhook triggers."""

from app.schemas.automations.contracts import (
    AutomationArtifactLinkResponse,
    AutomationCreateRequest,
    AutomationCreateResponse,
    AutomationExecuteRequest,
    AutomationExecutionDetailResponse,
    AutomationExecutionListResponse,
    AutomationExecutionSummaryResponse,
    AutomationInputConfig,
    AutomationListResponse,
    AutomationNotificationPreferences,
    AutomationResponse,
    AutomationToolApprovalRequest,
    AutomationUpdateRequest,
    AutomationWebhookReceiptResponse,
    AutomationWebhookSecretRotateResponse,
)

__all__ = [
    "AutomationArtifactLinkResponse",
    "AutomationCreateRequest",
    "AutomationCreateResponse",
    "AutomationExecuteRequest",
    "AutomationExecutionDetailResponse",
    "AutomationExecutionListResponse",
    "AutomationExecutionSummaryResponse",
    "AutomationInputConfig",
    "AutomationListResponse",
    "AutomationNotificationPreferences",
    "AutomationResponse",
    "AutomationToolApprovalRequest",
    "AutomationUpdateRequest",
    "AutomationWebhookReceiptResponse",
    "AutomationWebhookSecretRotateResponse",
]

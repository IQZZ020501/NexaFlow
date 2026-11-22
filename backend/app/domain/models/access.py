"""Personal credentials stay with their owner; workspace models are shared."""

from fastapi import HTTPException, status

from app.entities.models import RegisteredModel


def can_use_model(model: RegisteredModel, user_id: str | None) -> bool:
    return (getattr(model, "visibility", None) or "workspace") == "workspace" or (
        (getattr(model, "visibility", None) or "workspace") == "personal"
        and model.created_by_user_id == user_id
    )


def can_manage_model(
    model: RegisteredModel, user_id: str, workspace_role: str | None
) -> bool:
    if (getattr(model, "visibility", None) or "workspace") == "personal":
        return model.created_by_user_id == user_id
    return (
        getattr(model, "visibility", None) or "workspace"
    ) == "workspace" and workspace_role == "admin"


def require_model_management(
    model: RegisteredModel, user_id: str, workspace_role: str | None
) -> None:
    if not can_use_model(model, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found.")
    if not can_manage_model(model, user_id, workspace_role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Model management access denied."
        )


def require_shared_model(model: RegisteredModel) -> None:
    if not can_use_model(model, None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Published applications require workspace-shared models.",
        )

"""Workspace-scoped image Tool operation, using the ordinary artifact store."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agents.runs.snapshots import (
    build_model_runtime_snapshot,
    require_model_runtime_snapshot,
)
from app.application.artifacts.service import create_generated_artifact
from app.application.tools.runtime.contracts import (
    ToolInvocationContext,
    ToolRuntimeResult,
)
from app.domain.artifacts.services import MAX_ARTIFACT_BYTES
from app.domain.models.registered import RegisteredModel
from app.infra.config.settings import Settings
from app.infra.db.repositories.models import registry as model_repository
from app.infra.db.session import get_session_factory
from app.ports.llm import ModelProviderError, generate_image


def _validate_image_model(model: RegisteredModel, workspace_id: str) -> None:
    if (
        getattr(model, "workspace_id", None) != workspace_id
        or getattr(model, "model_type", None) != "IMAGE"
        or getattr(model, "status", None) != "active"
    ):
        raise ValueError(
            "The queued image model is no longer active in this workspace."
        )
    if getattr(model, "provider", None) not in {
        "model_openai_provider",
        "model_custom_provider",
    }:
        raise ValueError(
            "The active image model must use an OpenAI-compatible provider."
        )


async def build_image_model_resource_snapshot(
    db: AsyncSession,
    workspace_id: str,
) -> dict[str, object]:
    models = await model_repository.list_active_image_models(db, workspace_id)
    if not models:
        raise ValueError(
            "Configure an active OpenAI-compatible image model in this workspace first."
        )
    if len(models) != 1:
        raise ValueError("Keep exactly one image model active in this workspace.")
    model = models[0]
    _validate_image_model(model, workspace_id)
    return {"image_model": build_model_runtime_snapshot(model)}


async def generate_image_artifact(
    settings: Settings,
    arguments: dict[str, str],
    context: ToolInvocationContext,
) -> ToolRuntimeResult:
    image_model_snapshot = context.resource_snapshot.get("image_model")
    if not isinstance(image_model_snapshot, dict):
        raise ValueError("Image model configuration was not frozen for this call.")
    model_id = image_model_snapshot.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("Image model configuration is invalid.")
    async with get_session_factory()() as db:
        model = await model_repository.get_registered_model_by_id(db, model_id)
    if model is None:
        raise ValueError("The queued image model is no longer available.")
    _validate_image_model(model, context.workspace_id)
    try:
        require_model_runtime_snapshot(model, image_model_snapshot)
    except ValueError as exc:
        raise ValueError(
            "Image model configuration changed after this call was queued."
        ) from exc
    prompt = arguments["prompt"].strip()
    if not prompt or len(prompt) > 4000:
        raise ValueError("Image prompt must contain 1–4000 characters.")
    size = arguments.get("size", "square")
    if size not in {"square", "landscape", "portrait"}:
        raise ValueError("Image size is invalid.")
    content = await generate_image(settings, model, prompt, size)
    if not content or len(content) > MAX_ARTIFACT_BYTES:
        raise ModelProviderError("Generated image exceeds the 5 MiB file limit.")
    filename = "generated-image.png"
    async with get_session_factory()() as db:
        link = await create_generated_artifact(
            db,
            settings,
            workspace_id=context.workspace_id,
            run_id=context.run_id,
            idempotency_key=context.idempotency_key,
            artifact_format="png",
            filename=filename,
            content=content,
        )
        await db.commit()
    return ToolRuntimeResult(
        ok=True,
        data={
            "artifact_id": link.artifact_id,
            "format": link.format,
            "filename": link.filename,
            "mime_type": link.media_type,
            "download_url": link.download_url,
            "preview_url": f"{link.download_url}/preview",
            "expires_at": link.expires_at.isoformat(),
            "size_bytes": link.size_bytes,
        },
        summary="Image generated.",
        error_code=None,
        error_message=None,
        outcome="confirmed",
        usage={"size_bytes": link.size_bytes},
    )

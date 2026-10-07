"""OpenAI image generation through registered, workspace-owned credentials."""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING

from openai import AsyncOpenAI, OpenAIError

from app.adapters.llm.runtime import (
    _model_provider_error,
    _openai_api_key,
    _registered_model_credentials,
    openai_compatible_base,
)
from app.ports.llm import MODEL_REQUEST_PARAMS_META_KEY, ModelProviderError

if TYPE_CHECKING:
    from app.domain.models.registered import RegisteredModel
    from app.infra.config.settings import Settings

IMAGE_SIZES = {
    "square": "1024x1024",
    "landscape": "1536x1024",
    "portrait": "1024x1536",
}
IMAGE_RESOLUTION_FACTORS = {
    "1K": 1,
    "2K": 2,
    "4K": 4,
}
DALL_E_3_SIZES = {
    "square": "1024x1024",
    "landscape": "1792x1024",
    "portrait": "1024x1792",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_ENCODED_IMAGE_CHARS = 7 * 1024 * 1024
MIN_IMAGE_REQUEST_TIMEOUT_SECONDS = 300


async def generate_registered_image(
    model: RegisteredModel,
    settings: Settings,
    prompt: str,
    size: str,
    resolution: str = "1K",
) -> bytes:
    if model.provider not in {"model_openai_provider", "model_custom_provider"}:
        raise ModelProviderError("Image model provider is not OpenAI-compatible.")
    credentials = _registered_model_credentials(model, settings, "IMAGE")
    api_base = credentials.get("api_base")
    if not api_base:
        raise ModelProviderError("Image model credentials are incomplete.")
    model_name = model.model_name.strip()
    if not model_name:
        raise ModelProviderError("Image model name is missing.")
    if size not in IMAGE_SIZES:
        raise ModelProviderError("Image orientation is invalid.")
    if resolution not in IMAGE_RESOLUTION_FACTORS:
        raise ModelProviderError("Image resolution is invalid.")
    # GPT Image models always return Base64 and reject the legacy
    # ``response_format`` parameter. DALL·E-compatible endpoints still use
    # that parameter, so keep the request shape compatible with both families.
    model_family = model_name.lower()
    model_meta = getattr(model, "meta", {})
    request_params = (
        model_meta.get(MODEL_REQUEST_PARAMS_META_KEY, {})
        if isinstance(model_meta, dict)
        else {}
    )
    request = dict(request_params) if isinstance(request_params, dict) else {}
    request.update(
        {
            "model": model_name,
            "prompt": prompt,
            "size": (
                DALL_E_3_SIZES[size]
                if model_family.startswith("dall-e-3")
                else _scaled_image_size(size, resolution)
            ),
            "n": 1,
        }
    )
    if model_family.startswith(("dall-e-2", "dall-e-3")) and resolution != "1K":
        raise ModelProviderError(
            f"{model_name} only supports 1K image generation."
        )
    _apply_dynamic_resolution(request, resolution)
    if model_family.startswith("gpt-image"):
        request.pop("response_format", None)
        request["output_format"] = "png"
    else:
        request.pop("output_format", None)
        if model_family.startswith("dall-e-2"):
            request["size"] = "1024x1024"
        request["response_format"] = "b64_json"
    try:
        async with AsyncOpenAI(
            api_key=_openai_api_key(credentials),
            base_url=openai_compatible_base(api_base),
            timeout=max(
                settings.model_request_timeout_seconds,
                MIN_IMAGE_REQUEST_TIMEOUT_SECONDS,
            ),
            max_retries=0,
        ) as client:
            response = await client.images.generate(**request)
    except OpenAIError as exc:
        raise _model_provider_error(exc) from exc
    encoded = response.data[0].b64_json if response.data else None
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > MAX_ENCODED_IMAGE_CHARS
    ):
        raise ModelProviderError("Image model returned no usable PNG image.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ModelProviderError("Image model returned invalid image data.") from exc
    if not content.startswith(PNG_SIGNATURE):
        raise ModelProviderError("Image model returned an unexpected image format.")
    return content


def _scaled_image_size(size: str, resolution: str) -> str:
    width, height = (int(value) for value in IMAGE_SIZES[size].split("x"))
    factor = IMAGE_RESOLUTION_FACTORS[resolution]
    return f"{width * factor}x{height * factor}"


def _apply_dynamic_resolution(request: dict[str, object], resolution: str) -> None:
    """Update configured provider extensions without leaking control keys."""
    extra_body = request.get("extra_body")
    if not isinstance(extra_body, dict):
        return
    updated = dict(extra_body)
    for key in ("image_size", "resolution"):
        if key in updated:
            updated[key] = resolution
    request["extra_body"] = updated

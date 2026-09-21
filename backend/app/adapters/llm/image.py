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
from app.ports.llm import ModelProviderError

if TYPE_CHECKING:
    from app.domain.models.registered import RegisteredModel
    from app.infra.config.settings import Settings

IMAGE_SIZES = {
    "square": "1024x1024",
    "landscape": "1536x1024",
    "portrait": "1024x1536",
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
    # GPT Image models always return Base64 and reject the legacy
    # ``response_format`` parameter. DALL·E-compatible endpoints still use
    # that parameter, so keep the request shape compatible with both families.
    model_family = model_name.lower()
    request: dict[str, object] = {
        "model": model_name,
        "prompt": prompt,
        "size": (
            DALL_E_3_SIZES[size]
            if model_family.startswith("dall-e-3")
            else IMAGE_SIZES[size]
        ),
        "n": 1,
    }
    if model_family.startswith("gpt-image"):
        request["output_format"] = "png"
    else:
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

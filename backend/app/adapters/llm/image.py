"""OpenAI image generation through registered, workspace-owned credentials."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from openai import AsyncOpenAI, OpenAIError

from app.adapters.llm.network import PUBLIC_ENDPOINT_CREDENTIAL, public_async_client
from app.adapters.llm.runtime import (
    _model_provider_error,
    _openai_api_key,
    _registered_model_credentials,
    openai_compatible_base,
)
from app.infra.observability.logger import get_logger, log_event
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
MAX_IMAGE_RESPONSE_BYTES = MAX_ENCODED_IMAGE_CHARS + 64 * 1024
IMAGE_CLOSE_TIMEOUT_SECONDS = 1
_image_cleanup_tasks: set[asyncio.Task] = set()
logger = get_logger(__name__)


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
        raise ModelProviderError(f"{model_name} only supports 1K image generation.")
    _apply_dynamic_resolution(request, resolution)
    if model_family.startswith("gpt-image"):
        request.pop("response_format", None)
        request["output_format"] = "png"
    else:
        request.pop("output_format", None)
        if model_family.startswith("dall-e-2"):
            request["size"] = "1024x1024"
        request["response_format"] = "b64_json"
    started = monotonic()
    diagnostics = {
        "image_request_id": str(uuid4()),
        "model_id": getattr(model, "id", None),
    }
    progress = {"phase": "request", "received_bytes": 0}
    client = None
    response = None
    log_event(logger, logging.INFO, "Image request started.", **diagnostics)
    try:
        client = AsyncOpenAI(
            api_key=_openai_api_key(credentials),
            base_url=openai_compatible_base(api_base),
            timeout=max(
                settings.model_request_timeout_seconds,
                MIN_IMAGE_REQUEST_TIMEOUT_SECONDS,
            ),
            max_retries=0,
            **(
                {
                    "http_client": public_async_client(
                        max(
                            settings.model_request_timeout_seconds,
                            MIN_IMAGE_REQUEST_TIMEOUT_SECONDS,
                        )
                    )
                }
                if credentials.get(PUBLIC_ENDPOINT_CREDENTIAL) == "true"
                else {}
            ),
        )
        # Stream the HTTP body without requesting model-side image streaming.
        # Some compatible services send a complete JSON result but leave the
        # chunked response open. A valid bounded JSON object is sufficient.
        response = await client.images.with_streaming_response.generate(
            **request
        ).__aenter__()
        progress["phase"] = "response_body"
        log_event(
            logger,
            logging.INFO,
            "Image response headers received.",
            **diagnostics,
            status_code=response.status_code,
            elapsed_ms=round((monotonic() - started) * 1000),
        )
        payload = await _read_image_response(response, progress)
        progress["phase"] = "decode"
        content = await asyncio.to_thread(_decode_image_payload, payload)
        log_event(
            logger,
            logging.INFO,
            "Image response received.",
            **diagnostics,
            received_bytes=progress["received_bytes"],
            image_bytes=len(content),
            elapsed_ms=round((monotonic() - started) * 1000),
        )
        return content
    except OpenAIError as exc:
        raise _model_provider_error(exc) from exc
    except asyncio.CancelledError:
        log_event(
            logger,
            logging.WARNING,
            "Image request interrupted.",
            **diagnostics,
            **progress,
            elapsed_ms=round((monotonic() - started) * 1000),
        )
        raise
    finally:
        if client is not None:
            # Business completion must not wait for a broken connection close.
            # Retain the task until both resources receive bounded cleanup.
            cleanup = asyncio.create_task(
                _close_image_resources(response, client, diagnostics)
            )
            _image_cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(_image_cleanup_tasks.discard)


async def _read_image_response(response, progress: dict) -> dict[str, Any]:
    body = bytearray()
    async for chunk in response.iter_bytes():
        if len(body) + len(chunk) > MAX_IMAGE_RESPONSE_BYTES:
            raise ModelProviderError(
                "Image model response exceeds the image size limit."
            )
        body.extend(chunk)
        progress["received_bytes"] = len(body)
        if not chunk.rstrip().endswith(b"}"):
            continue
        try:
            payload = await asyncio.to_thread(json.loads, body)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
        raise ModelProviderError("Image model returned an invalid JSON response.")
    raise ModelProviderError("Image model returned an incomplete JSON response.")


def _decode_image_payload(payload: dict[str, Any]) -> bytes:
    data = payload.get("data")
    encoded = (
        data[0].get("b64_json")
        if isinstance(data, list) and data and isinstance(data[0], dict)
        else None
    )
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


async def _close_image_resources(response, client, diagnostics: dict) -> None:
    async def close_resource(name, resource):
        if resource is None:
            return
        try:
            async with asyncio.timeout(IMAGE_CLOSE_TIMEOUT_SECONDS):
                await resource.close()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "Image connection cleanup did not complete.",
                **diagnostics,
                resource=name,
                error_type=type(exc).__name__,
            )

    try:
        await close_resource("response", response)
    finally:
        await close_resource("client", client)


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

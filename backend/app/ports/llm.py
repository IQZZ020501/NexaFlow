"""LLM provider port.

Business code consumes providers through the structural protocols and
value/error types defined here; concrete provider construction lives in
``app.adapters.llm``. This module never imports adapters or infra at
import time - the delegate factories below resolve the current adapter
implementation lazily so composition happens at the call site while the
layer boundary stays import-free.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from app.ports.errors import ExternalServiceError

if TYPE_CHECKING:
    from app.domain.models.registered import RegisteredModel
    from app.infra.config.settings import Settings

VISION_MODEL_REQUIRED_MESSAGE = "Vision model is not configured for this workspace."

MODEL_REQUEST_PARAMS_META_KEY = "request_params"
DEFAULT_MODEL_REQUEST_PARAMS: dict[str, object] = {}
SUPPORTED_PROVIDER_TYPES = {
    "openai_compatible",
    "anthropic",
    "bedrock",
    "azure_openai",
    "deepseek",
    "google_genai",
    "ollama",
}


class ModelProviderError(ExternalServiceError):
    pass


class ModelProviderStatusError(ModelProviderError):
    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        self.message = message
        detail = f"Provider returned status {status_code}"
        if message:
            detail = f"{detail}: {message}"
        super().__init__(detail)


class ModelProviderTimeoutError(ModelProviderError):
    pass


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelCompletion:
    content: str
    tool_calls: tuple[ModelToolCall, ...]
    finish_reason: str


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class RerankProvider(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]: ...


class ChatProvider(Protocol):
    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> Any: ...

    def astream(
        self,
        messages: list[Any],
        **kwargs: Any,
    ) -> AsyncIterator[Any]: ...


def build_embeddings(settings: Settings, model: RegisteredModel) -> EmbeddingProvider:
    from app.adapters.llm.runtime import build_registered_embeddings

    return build_registered_embeddings(model, settings)


def build_reranker(settings: Settings, model: RegisteredModel) -> RerankProvider:
    from app.adapters.llm.runtime import build_registered_reranker

    return build_registered_reranker(model, settings)


def build_chat_model(
    settings: Settings,
    model: RegisteredModel,
    *,
    timeout: float | None = None,
) -> ChatProvider:
    from app.adapters.llm.runtime import build_registered_chat_model

    return build_registered_chat_model(model, settings, timeout=timeout)


def extract_image_text(
    settings: Settings,
    model: RegisteredModel,
    media_type: str,
    image_bytes: bytes,
) -> str:
    from app.adapters.llm.runtime import extract_registered_image_text

    return extract_registered_image_text(model, settings, media_type, image_bytes)


def test_model_connection(
    provider_type: str,
    credentials: dict[str, str],
    model_name: str,
    model_type: str,
    request_params: dict[str, Any] | None = None,
) -> dict[str, bool]:
    from app.adapters.llm.runtime import test_model_connection as _test

    return _test(
        provider_type,
        credentials,
        model_name,
        model_type,
        request_params,
    )


__all__ = [
    "ChatProvider",
    "EmbeddingProvider",
    "ExternalServiceError",
    "ModelCompletion",
    "ModelProviderError",
    "ModelProviderStatusError",
    "ModelProviderTimeoutError",
    "ModelToolCall",
    "MODEL_REQUEST_PARAMS_META_KEY",
    "DEFAULT_MODEL_REQUEST_PARAMS",
    "SUPPORTED_PROVIDER_TYPES",
    "RerankProvider",
    "VISION_MODEL_REQUIRED_MESSAGE",
    "build_chat_model",
    "build_embeddings",
    "build_reranker",
    "test_model_connection",
    "extract_image_text",
]

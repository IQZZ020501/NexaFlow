"""LLM provider port.

Business code builds chat/embedding/rerank providers through the factory
functions here and consumes them through the structural protocols, so a
provider swap stays inside ``app.adapters.llm``.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.domain.models.registered import RegisteredModel
from app.adapters.llm.runtime import (
    ModelCompletion,
    ModelProviderError,
    ModelProviderStatusError,
    ModelProviderTimeoutError,
    ModelToolCall,
    build_registered_chat_model,
    build_registered_embeddings,
    build_registered_reranker,
    extract_registered_image_text,
)
from app.infra.config.settings import Settings

VISION_MODEL_REQUIRED_MESSAGE = "Vision model is not configured for this workspace."


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
    return build_registered_embeddings(model, settings)


def build_reranker(settings: Settings, model: RegisteredModel) -> RerankProvider:
    return build_registered_reranker(model, settings)


def build_chat_model(
    settings: Settings,
    model: RegisteredModel,
    *,
    timeout: float | None = None,
) -> ChatProvider:
    return build_registered_chat_model(model, settings, timeout=timeout)


def extract_image_text(
    settings: Settings,
    model: RegisteredModel,
    media_type: str,
    image_bytes: bytes,
) -> str:
    return extract_registered_image_text(model, settings, media_type, image_bytes)


__all__ = [
    "ChatProvider",
    "EmbeddingProvider",
    "ModelCompletion",
    "ModelProviderError",
    "ModelProviderStatusError",
    "ModelProviderTimeoutError",
    "ModelToolCall",
    "RegisteredModel",
    "RerankProvider",
    "VISION_MODEL_REQUIRED_MESSAGE",
    "build_chat_model",
    "build_embeddings",
    "build_reranker",
    "extract_image_text",
]

"""LLM provider port.

Business code builds chat/embedding/rerank providers through the factory
functions here and consumes them through the structural protocols, so a
provider swap stays inside ``app.capabilities.llm``.
"""

from typing import Any, Protocol

from app.capabilities.llm.models import RegisteredModel
from app.capabilities.llm.runtime import (
    ModelCompletion,
    ModelProviderError,
    ModelProviderStatusError,
    ModelProviderTimeoutError,
    ModelToolCall,
    build_registered_chat_model,
    build_registered_embeddings,
    build_registered_reranker,
)
from app.infrastructure.config import Settings


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class RerankProvider(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]: ...


class ChatProvider(Protocol):
    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> Any: ...


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
    "build_chat_model",
    "build_embeddings",
    "build_reranker",
]

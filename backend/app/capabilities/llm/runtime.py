import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from anthropic import AnthropicError
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError
from google.genai.errors import APIError as GoogleAPIError
from langchain_anthropic import ChatAnthropic
from langchain_aws import BedrockEmbeddings, BedrockRerank, ChatBedrockConverse
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings,
)
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import (
    AzureChatOpenAI,
    AzureOpenAIEmbeddings,
    ChatOpenAI,
    OpenAIEmbeddings,
)
from ollama import RequestError as OllamaRequestError
from ollama import ResponseError as OllamaResponseError
from openai import APIStatusError, OpenAIError
from pydantic import SecretStr

from app.capabilities.llm.credentials import (
    decrypt_credential_secrets,
    legacy_credential_config,
)
from app.capabilities.llm.models import RegisteredModel
from app.infrastructure.config import Settings
from app.infrastructure.errors import ExternalServiceError, log_error
from app.infrastructure.logger import get_logger

logger = get_logger(__name__)

MODEL_REQUEST_TIMEOUT_SECONDS = 60
STREAM_USAGE_SUPPORTED_META_KEY = "stream_usage_supported"
SUPPORTED_PROVIDER_TYPES = {
    "openai_compatible",
    "anthropic",
    "bedrock",
    "azure_openai",
    "deepseek",
    "google_genai",
    "ollama",
}
PROVIDER_EXCEPTIONS = (
    AnthropicError,
    BotoCoreError,
    ClientError,
    GoogleAPIError,
    OllamaRequestError,
    OllamaResponseError,
    OpenAIError,
)


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


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]: ...


def _api_error_detail(exc: APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, str) else json.dumps(exc.body) if exc.body else ""
    return body or exc.message or ""


def _provider_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status_code, int):
        return status_code
    if isinstance(exc, ClientError):
        value = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return value if isinstance(value, int) else None
    return None


def _model_provider_error(exc: Exception) -> ModelProviderError:
    log_error(logger, "LLM provider request failed.", exc)
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError) or type(current).__name__ in {
            "APITimeoutError",
            "ConnectTimeout",
            "ReadTimeout",
            "TimeoutException",
        }:
            return ModelProviderTimeoutError("Model request timed out.")
        current = current.__cause__ or current.__context__
    if isinstance(exc, APIStatusError):
        return ModelProviderStatusError(exc.status_code, _api_error_detail(exc))
    status_code = _provider_status_code(exc)
    if status_code is not None:
        return ModelProviderStatusError(status_code)
    return ModelProviderError("Model request failed.")


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


def openai_compatible_base(api_base: str) -> str:
    base = api_base.rstrip("/")
    return f"{base}/v1" if urlparse(base).path in {"", "/"} else base


def _reasoning_content(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    reasoning = value.get("reasoning_content") or value.get("reasoning")
    return reasoning if isinstance(reasoning, str) else ""


class _ProviderErrorChatMixin:
    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        try:
            return super()._generate(*args, **kwargs)
        except PROVIDER_EXCEPTIONS as exc:
            raise _model_provider_error(exc) from exc

    async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
        try:
            return await super()._agenerate(*args, **kwargs)
        except PROVIDER_EXCEPTIONS as exc:
            raise _model_provider_error(exc) from exc

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        try:
            yield from super()._stream(*args, **kwargs)
        except PROVIDER_EXCEPTIONS as exc:
            raise _model_provider_error(exc) from exc

    async def _astream(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        try:
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
        except PROVIDER_EXCEPTIONS as exc:
            raise _model_provider_error(exc) from exc


class AnthropicChatModel(_ProviderErrorChatMixin, ChatAnthropic):
    pass


class BedrockChatModel(_ProviderErrorChatMixin, ChatBedrockConverse):
    pass


class AzureChatModel(_ProviderErrorChatMixin, AzureChatOpenAI):
    pass


class DeepSeekChatModel(_ProviderErrorChatMixin, ChatDeepSeek):
    pass


class GoogleChatModel(_ProviderErrorChatMixin, ChatGoogleGenerativeAI):
    pass


class OllamaChatModel(_ProviderErrorChatMixin, ChatOllama):
    pass


class OpenAICompatibleChatModel(ChatOpenAI):
    def _create_chat_result(
        self,
        response: dict[str, Any] | Any,
        generation_info: dict[str, Any] | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        payload = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}},
                warnings=False,
            )
        )
        for choice, generation in zip(
            payload.get("choices") or [],
            result.generations,
            strict=False,
        ):
            reasoning = _reasoning_content(choice.get("message"))
            if reasoning and isinstance(generation.message, AIMessage):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type[BaseMessageChunk],
        base_generation_info: dict[str, Any] | None,
    ) -> ChatGenerationChunk | None:
        generation = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        choices = chunk.get("choices") or (chunk.get("chunk") or {}).get("choices") or []
        reasoning = _reasoning_content(choices[0].get("delta")) if choices else ""
        if (
            generation is not None
            and reasoning
            and isinstance(generation.message, AIMessageChunk)
        ):
            generation.message.additional_kwargs["reasoning_content"] = reasoning
        return generation

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        try:
            return super()._generate(*args, **kwargs)
        except OpenAIError as exc:
            raise _model_provider_error(exc) from exc

    async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
        try:
            return await super()._agenerate(*args, **kwargs)
        except OpenAIError as exc:
            raise _model_provider_error(exc) from exc

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        try:
            yield from super()._stream(*args, **kwargs)
        except OpenAIError as exc:
            raise _model_provider_error(exc) from exc

    async def _astream(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        try:
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
        except OpenAIError as exc:
            raise _model_provider_error(exc) from exc


class CheckedEmbeddings(Embeddings):
    def __init__(self, delegate: Embeddings) -> None:
        self._delegate = delegate

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            embeddings = self._delegate.embed_documents(texts)
        except PROVIDER_EXCEPTIONS as exc:
            raise _model_provider_error(exc) from exc
        if len(embeddings) != len(texts):
            raise ModelProviderError(
                "Embedding response count did not match input count."
            )
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        try:
            embedding = self._delegate.embed_query(text)
        except PROVIDER_EXCEPTIONS as exc:
            raise _model_provider_error(exc) from exc
        if not embedding:
            raise ModelProviderError("Embedding provider returned no query embedding.")
        return embedding


class OpenAICompatibleEmbeddings(CheckedEmbeddings):
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model_name: str,
        timeout: float = MODEL_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            OpenAIEmbeddings(
                model=model_name,
                api_key=api_key,
                base_url=openai_compatible_base(api_base),
                timeout=timeout,
                max_retries=0,
                check_embedding_ctx_length=False,
            )
        )


class OpenAICompatibleReranker:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model_name: str,
        timeout: float = MODEL_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.api_base = openai_compatible_base(api_base)
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout

    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        payload = {"model": self.model_name, "query": query, "documents": documents}
        request = Request(
            f"{self.api_base}/rerank",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if response.status < 200 or response.status >= 300:
                    raise ModelProviderStatusError(response.status)
                body = response.read().decode()
        except HTTPError as exc:
            raise ModelProviderStatusError(exc.code) from exc
        except (OSError, TimeoutError, URLError) as exc:
            raise _model_provider_error(exc) from exc
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise ModelProviderError("Model response was invalid.") from exc
        if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
            raise ModelProviderError("Model response was invalid.")
        return data.get("results", [])


class BedrockModelReranker:
    def __init__(self, delegate: BedrockRerank) -> None:
        self._delegate = delegate

    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        if not documents:
            return []
        try:
            return self._delegate.rerank(documents, query, top_n=len(documents))
        except PROVIDER_EXCEPTIONS as exc:
            raise _model_provider_error(exc) from exc


def _required(credentials: dict[str, str], field: str) -> str:
    value = credentials.get(field, "").strip()
    if not value:
        raise ModelProviderError(f"Model credential {field} is missing.")
    return value


def _optional(credentials: dict[str, str], field: str) -> str | None:
    value = credentials.get(field, "").strip()
    return value or None


def _secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value else None


def _openai_api_key(credentials: dict[str, str]) -> str:
    return _optional(credentials, "api_key") or "not-required"


def _bedrock_config(timeout: float) -> BotocoreConfig:
    return BotocoreConfig(
        connect_timeout=timeout,
        read_timeout=timeout,
        retries={"max_attempts": 0},
    )


def _bedrock_credentials(
    credentials: dict[str, str],
    timeout: float = MODEL_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    access_key = _optional(credentials, "aws_access_key_id")
    secret_key = _optional(credentials, "aws_secret_access_key")
    if bool(access_key) != bool(secret_key):
        raise ModelProviderError(
            "AWS access key ID and secret access key must be provided together."
        )
    return {
        "region_name": _required(credentials, "region_name"),
        "aws_access_key_id": _secret(access_key),
        "aws_secret_access_key": _secret(secret_key),
        "aws_session_token": _secret(
            _optional(credentials, "aws_session_token")
        ),
        "config": _bedrock_config(timeout),
    }


def _bedrock_model_arn(model_name: str, region_name: str) -> str:
    if model_name.startswith("arn:"):
        return model_name
    partition = (
        "aws-cn"
        if region_name.startswith("cn-")
        else "aws-us-gov"
        if region_name.startswith("us-gov-")
        else "aws"
    )
    return f"arn:{partition}:bedrock:{region_name}::foundation-model/{model_name}"


def build_chat_model(
    provider_type: str,
    credentials: dict[str, str],
    model_name: str,
    *,
    stream_usage: bool = False,
    timeout: float = MODEL_REQUEST_TIMEOUT_SECONDS,
) -> BaseChatModel:
    if provider_type == "openai_compatible":
        return OpenAICompatibleChatModel(
            model=model_name,
            api_key=_openai_api_key(credentials),
            base_url=openai_compatible_base(_required(credentials, "api_base")),
            stream_usage=stream_usage,
            timeout=timeout,
            max_retries=0,
        )
    if provider_type == "anthropic":
        return AnthropicChatModel(
            model_name=model_name,
            api_key=_required(credentials, "api_key"),
            base_url=_optional(credentials, "api_base"),
            timeout=timeout,
            max_retries=0,
        )
    if provider_type == "bedrock":
        return BedrockChatModel(
            model=model_name,
            base_url=_optional(credentials, "endpoint_url"),
            timeout=timeout,
            max_retries=0,
            **_bedrock_credentials(credentials, timeout),
        )
    if provider_type == "azure_openai":
        return AzureChatModel(
            model=model_name,
            azure_deployment=model_name,
            azure_endpoint=_required(credentials, "azure_endpoint"),
            api_version=_required(credentials, "api_version"),
            api_key=_required(credentials, "api_key"),
            timeout=timeout,
            max_retries=0,
        )
    if provider_type == "deepseek":
        return DeepSeekChatModel(
            model=model_name,
            api_key=_required(credentials, "api_key"),
            base_url=openai_compatible_base(_required(credentials, "api_base")),
            timeout=timeout,
            max_retries=0,
        )
    if provider_type == "google_genai":
        return GoogleChatModel(
            model=model_name,
            api_key=_required(credentials, "api_key"),
            base_url=_optional(credentials, "api_base"),
            api_version=_optional(credentials, "api_version"),
            request_timeout=timeout,
            retries=0,
        )
    if provider_type == "ollama":
        return OllamaChatModel(
            model=model_name,
            base_url=_required(credentials, "api_base"),
            client_kwargs={"timeout": timeout},
        )
    raise ModelProviderError("Model provider type is not supported.")


def build_embeddings(
    provider_type: str,
    credentials: dict[str, str],
    model_name: str,
    *,
    timeout: float = MODEL_REQUEST_TIMEOUT_SECONDS,
) -> Embeddings:
    if provider_type == "openai_compatible":
        return OpenAICompatibleEmbeddings(
            _required(credentials, "api_base"),
            _openai_api_key(credentials),
            model_name,
            timeout,
        )
    if provider_type == "bedrock":
        return CheckedEmbeddings(
            BedrockEmbeddings(
                model_id=model_name,
                endpoint_url=_optional(credentials, "endpoint_url"),
                **_bedrock_credentials(credentials, timeout),
            )
        )
    if provider_type == "azure_openai":
        return CheckedEmbeddings(
            AzureOpenAIEmbeddings(
                model=model_name,
                azure_deployment=model_name,
                azure_endpoint=_required(credentials, "azure_endpoint"),
                api_version=_required(credentials, "api_version"),
                api_key=_required(credentials, "api_key"),
                timeout=timeout,
                max_retries=0,
                check_embedding_ctx_length=False,
            )
        )
    if provider_type == "google_genai":
        return CheckedEmbeddings(
            GoogleGenerativeAIEmbeddings(
                model=model_name,
                api_key=_required(credentials, "api_key"),
                base_url=_optional(credentials, "api_base"),
                api_version=_optional(credentials, "api_version"),
                request_options={"timeout": timeout},
            )
        )
    if provider_type == "ollama":
        return CheckedEmbeddings(
            OllamaEmbeddings(
                model=model_name,
                base_url=_required(credentials, "api_base"),
                client_kwargs={"timeout": timeout},
            )
        )
    raise ModelProviderError("Embedding provider type is not supported.")


def build_reranker(
    provider_type: str,
    credentials: dict[str, str],
    model_name: str,
    *,
    timeout: float = MODEL_REQUEST_TIMEOUT_SECONDS,
) -> Reranker:
    if provider_type == "openai_compatible":
        return OpenAICompatibleReranker(
            _required(credentials, "api_base"),
            _openai_api_key(credentials),
            model_name,
            timeout,
        )
    if provider_type == "bedrock":
        bedrock_credentials = _bedrock_credentials(credentials, timeout)
        region_name = bedrock_credentials["region_name"]
        return BedrockModelReranker(
            BedrockRerank(
                model_arn=_bedrock_model_arn(model_name, region_name),
                base_url=_optional(credentials, "endpoint_url"),
                **bedrock_credentials,
            )
        )
    raise ModelProviderError("Reranker provider type is not supported.")


def _registered_model_credentials(
    model: RegisteredModel,
    settings: Settings,
    expected_model_type: str,
) -> dict[str, str]:
    if model.status != "active":
        raise ModelProviderError("Model is disabled.")
    if model.provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise ModelProviderError("Model provider type is not supported.")
    if model.model_type != expected_model_type:
        raise ModelProviderError("Model capability does not match its registered type.")
    config = {
        key: value
        for key, value in (model.credential_config or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    if not config:
        config = legacy_credential_config(model.provider_type, model.api_base)
    try:
        secrets = decrypt_credential_secrets(
            model.api_key_ciphertext,
            settings.model_secret_key,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise ModelProviderError("Stored model credentials are invalid.") from exc
    return {**config, **secrets}


def build_registered_chat_model(
    model: RegisteredModel,
    settings: Settings,
) -> BaseChatModel:
    return build_chat_model(
        model.provider_type,
        _registered_model_credentials(model, settings, "LLM"),
        model.model_name,
        stream_usage=(model.meta or {}).get(STREAM_USAGE_SUPPORTED_META_KEY) is True,
        timeout=settings.model_request_timeout_seconds,
    )


def build_registered_embeddings(
    model: RegisteredModel,
    settings: Settings,
) -> Embeddings:
    return build_embeddings(
        model.provider_type,
        _registered_model_credentials(model, settings, "EMBEDDING"),
        model.model_name,
        timeout=settings.model_request_timeout_seconds,
    )


def build_registered_reranker(
    model: RegisteredModel,
    settings: Settings,
) -> Reranker:
    return build_reranker(
        model.provider_type,
        _registered_model_credentials(model, settings, "RERANKER"),
        model.model_name,
        timeout=settings.model_request_timeout_seconds,
    )


def test_model_connection(
    provider_type: str,
    credentials: dict[str, str],
    model_name: str,
    model_type: str,
) -> dict[str, bool]:
    if model_type == "LLM":
        output_limit = (
            {"num_predict": 1}
            if provider_type == "ollama"
            else {"max_tokens": 1}
        )
        if provider_type == "openai_compatible":
            try:
                chunks = list(
                    build_chat_model(
                        provider_type,
                        credentials,
                        model_name,
                        stream_usage=True,
                    ).stream([("human", "Hello")], **output_limit)
                )
            except ModelProviderStatusError as exc:
                if exc.status_code not in {400, 422}:
                    raise
                list(
                    build_chat_model(
                        provider_type,
                        credentials,
                        model_name,
                    ).stream([("human", "Hello")], **output_limit)
                )
                return {STREAM_USAGE_SUPPORTED_META_KEY: False}
            return {
                STREAM_USAGE_SUPPORTED_META_KEY: any(
                    chunk.usage_metadata is not None for chunk in chunks
                )
            }
        build_chat_model(provider_type, credentials, model_name).invoke(
            [("human", "Hello")],
            **output_limit,
        )
    elif model_type == "EMBEDDING":
        build_embeddings(provider_type, credentials, model_name).embed_query("Hello")
    elif model_type == "RERANKER":
        build_reranker(provider_type, credentials, model_name).rerank(
            "Hello",
            ["Hello"],
        )
    else:
        raise ModelProviderError("Model type is not supported.")
    return {STREAM_USAGE_SUPPORTED_META_KEY: False}

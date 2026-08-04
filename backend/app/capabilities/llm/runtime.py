import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai import APIStatusError, AsyncOpenAI, OpenAI, OpenAIError

from app.infrastructure.config import Settings
from app.infrastructure.secrets import decrypt_secret
from app.capabilities.llm.models import RegisteredModel

MODEL_REQUEST_TIMEOUT_SECONDS = 20


class ModelProviderError(Exception):
    pass


class ModelProviderStatusError(ModelProviderError):
    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        self.message = message
        detail = f"Provider returned status {status_code}"
        if message:
            detail = f"{detail}: {message}"
        super().__init__(detail)


def _api_error_detail(exc: APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, str) else json.dumps(exc.body) if exc.body else ""
    return body or exc.message or ""


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
    return base if base.endswith("/v1") else f"{base}/v1"


class OpenAICompatibleModelProvider:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model_name: str,
        timeout: int = MODEL_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.api_base = openai_compatible_base(api_base)
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.api_base,
            timeout=timeout,
            max_retries=0,
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.api_base,
            timeout=timeout,
            max_retries=0,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return self.complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ).content

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ModelCompletion:
        kwargs: dict[str, Any] = {"model": self.model_name, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            response = self.client.chat.completions.create(**kwargs)
        except APIStatusError as exc:
            raise ModelProviderStatusError(exc.status_code, _api_error_detail(exc)) from exc
        except OpenAIError as exc:
            raise ModelProviderError("Model request failed.") from exc

        if not response.choices:
            return ModelCompletion(content="", tool_calls=(), finish_reason="stop")

        choice = response.choices[0]
        return ModelCompletion(
            content=choice.message.content or "",
            tool_calls=tuple(
                ModelToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments,
                )
                for tool_call in choice.message.tool_calls or []
                if tool_call.type == "function"
            ),
            finish_reason=choice.finish_reason or "stop",
        )
    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> ModelCompletion:
        kwargs: dict[str, Any] = {"model": self.model_name, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        content_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        try:
            stream = await self.async_client.chat.completions.create(
                **kwargs,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                reasoning = getattr(delta, "reasoning_content", None)
                if not reasoning and delta.model_extra:
                    reasoning = delta.model_extra.get("reasoning_content") or delta.model_extra.get(
                        "reasoning"
                    )
                if isinstance(reasoning, str) and reasoning and on_reasoning_delta:
                    await on_reasoning_delta(reasoning)

                if delta.content:
                    content_parts.append(delta.content)
                    if on_content_delta:
                        await on_content_delta(delta.content)

                for tool_call in delta.tool_calls or []:
                    part = tool_call_parts.setdefault(
                        tool_call.index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if tool_call.id:
                        part["id"] = tool_call.id
                    if tool_call.function:
                        if tool_call.function.name:
                            part["name"] += tool_call.function.name
                        if tool_call.function.arguments:
                            part["arguments"] += tool_call.function.arguments
        except APIStatusError as exc:
            raise ModelProviderStatusError(exc.status_code, _api_error_detail(exc)) from exc
        except OpenAIError as exc:
            raise ModelProviderError("Model request failed.") from exc

        return ModelCompletion(
            content="".join(content_parts),
            tool_calls=tuple(
                ModelToolCall(
                    id=part["id"],
                    name=part["name"],
                    arguments=part["arguments"],
                )
                for _, part in sorted(tool_call_parts.items())
                if part["name"]
            ),
            finish_reason=finish_reason,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embeddings.create(
                model=self.model_name,
                input=texts,
                encoding_format="float",
            )
        except APIStatusError as exc:
            raise ModelProviderStatusError(exc.status_code, _api_error_detail(exc)) from exc
        except OpenAIError as exc:
            raise ModelProviderError("Model request failed.") from exc
        return [list(item.embedding) for item in response.data]

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
            raise ModelProviderError("Model request failed.") from exc
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise ModelProviderError("Model response was invalid.") from exc
        if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
            raise ModelProviderError("Model response was invalid.")
        return data.get("results", [])

    def test(self, model_type: str) -> None:
        if model_type == "LLM":
            self.chat([{"role": "user", "content": "Hello"}], max_tokens=1, temperature=0)
        elif model_type == "EMBEDDING":
            self.embed(["Hello"])
        elif model_type == "RERANKER":
            self.rerank("Hello", ["Hello"])
        else:
            raise ModelProviderError("Model type is not supported.")


def build_registered_model_provider(
    model: RegisteredModel,
    settings: Settings,
) -> OpenAICompatibleModelProvider:
    if model.status != "active":
        raise ModelProviderError("Model is disabled.")
    if model.provider_type != "openai_compatible":
        raise ModelProviderError("Model provider type is not supported.")
    if model.api_key_ciphertext is None:
        raise ModelProviderError("Model API Key is missing.")

    return OpenAICompatibleModelProvider(
        api_base=model.api_base,
        api_key=decrypt_secret(model.api_key_ciphertext, settings.model_secret_key),
        model_name=model.model_name,
    )

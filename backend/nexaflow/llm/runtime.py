import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai import APIStatusError, OpenAI, OpenAIError

from nexaflow.core.config import Settings
from nexaflow.core.secrets import decrypt_secret
from nexaflow.llm.models import RegisteredModel

MODEL_REQUEST_TIMEOUT_SECONDS = 20


class ModelProviderError(Exception):
    pass


class ModelProviderStatusError(ModelProviderError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Provider returned status {status_code}.")


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

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {"model": self.model_name, "messages": messages}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            response = self.client.chat.completions.create(**kwargs)
        except APIStatusError as exc:
            raise ModelProviderStatusError(exc.status_code) from exc
        except OpenAIError as exc:
            raise ModelProviderError("Model request failed.") from exc

        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

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
            raise ModelProviderStatusError(exc.status_code) from exc
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

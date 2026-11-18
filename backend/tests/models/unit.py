"""Pure unit tests for the models feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.models.unit
"""
import tests.support  # noqa: F401  (sets required env before app imports)

"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.application.models.registry import (
    is_masked_secret,
    normalize_model_type,
    normalize_provider_credentials,
    normalize_url_credential,
    validate_status,
)


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError("expected HTTPException")

def payload_with(**fields):
    return SimpleNamespace(model_dump=lambda: fields)

def test_model_type_normalization() -> None:
    assert normalize_model_type("llm") == "LLM"
    assert normalize_model_type("vision") == "VISION"
    assert normalize_model_type("image") == "IMAGE"
    assert normalize_model_type(" embeddings ") == "EMBEDDING"
    assert normalize_model_type("rerank") == "RERANKER"
    expect_http_error(lambda: normalize_model_type("audio"), 422)


def test_siliconflow_embedding_catalog_includes_existing_bge_model() -> None:
    from app.application.models.service import list_base_models

    models = list_base_models("model_siliconflow_provider", "EMBEDDING")
    assert "BAAI/bge-m3" in {model.name for model in models}


def test_registered_model_connection_test_has_a_hard_deadline() -> None:
    from app.application.models.registry import test_registered_model

    def slow_model_test(*_args, **_kwargs):
        time.sleep(0.03)
        return {}

    with patch(
        "app.application.models.registry.run_model_test",
        side_effect=slow_model_test,
    ):
        try:
            asyncio.run(
                test_registered_model(
                    "openai_compatible",
                    {},
                    "slow-model",
                    "LLM",
                    timeout_seconds=0.001,
                )
            )
        except HTTPException as exc:
            assert exc.status_code == 504
            assert exc.detail == "Model connection test timed out."
        else:
            raise AssertionError("Slow model test did not time out.")


def test_image_model_registration_skips_paid_connection_tests() -> None:
    from app.application.models.registry import run_model_test

    assert run_model_test("openai_compatible", {}, "gpt-image-1", "IMAGE") == {}

def test_status_validation() -> None:
    assert validate_status("active") == "active"
    expect_http_error(lambda: validate_status("paused"), 422)

def test_url_credential_validation() -> None:
    assert (
        normalize_url_credential("https://api.example.com/", "api_base")
        == "https://api.example.com"
    )
    expect_http_error(
        lambda: normalize_url_credential("file:///tmp/x", "api_base"),
        422,
    )

def test_masked_secret_detection() -> None:
    assert is_masked_secret("****abcd", "abcd")
    assert not is_masked_secret("real-secret", "abcd")

def test_provider_credentials_aws_pairing_rule() -> None:
    entry = {
        "credential_fields": [
            {"field": "aws_access_key_id", "input_type": "PasswordInput", "required": False},
            {"field": "aws_secret_access_key", "input_type": "PasswordInput", "required": False},
            {"field": "aws_session_token", "input_type": "PasswordInput", "required": False},
        ]
    }
    expect_http_error(
        lambda: normalize_provider_credentials(
            entry,
            {"aws_access_key_id": "AKIA123"},
        ),
        422,
    )
    expect_http_error(
        lambda: normalize_provider_credentials(
            entry,
            {"aws_session_token": "token"},
        ),
        422,
    )
    _config, secrets, _hints, changed = normalize_provider_credentials(
        entry,
        {"aws_access_key_id": "AKIA123", "aws_secret_access_key": "secret"},
    )
    assert changed == {"aws_access_key_id", "aws_secret_access_key"}
    assert secrets["aws_access_key_id"] == "AKIA123"

def test_run_knowledge_model_test_uses_injected_providers() -> None:
    from app.domain.knowledge.service import run_knowledge_model_test
    from app.schemas.knowledge import KnowledgeModelTestRequest

    embedding_model = SimpleNamespace(id="emb-1")
    reranker_model = SimpleNamespace(id="rerank-1")
    calls = {"embed": 0, "rerank": 0}

    class FakeEmbeddings:
        def embed_query(self, text: str) -> list[float]:
            assert text == "query"
            calls["embed"] += 1
            return [1.0, 2.0, 3.0]

    class FakeReranker:
        def rerank(self, query: str, documents: list[str]) -> list[dict]:
            assert query == "query"
            assert documents == ["doc"]
            calls["rerank"] += 1
            return [{"index": 0, "relevance_score": 0.9}]

    from app.domain.knowledge.bases import service as knowledge_kb

    original_embeddings = knowledge_kb.build_embeddings
    original_reranker = knowledge_kb.build_reranker
    knowledge_kb.build_embeddings = lambda _settings, _model: FakeEmbeddings()
    knowledge_kb.build_reranker = lambda _settings, _model: FakeReranker()
    try:
        response = run_knowledge_model_test(
            embedding_model,
            reranker_model,
            KnowledgeModelTestRequest(query="query", documents=["doc"]),
            settings=object(),
        )
        assert response.embedding_dimensions == 3
        assert response.reranker_results == 1
        assert calls == {"embed": 1, "rerank": 1}

        # without a reranker the rerank port is never touched
        no_rerank = run_knowledge_model_test(
            embedding_model,
            None,
            KnowledgeModelTestRequest(query="query", documents=["doc"]),
            settings=object(),
        )
        assert no_rerank.reranker_model_id is None
        assert calls["rerank"] == 1
    finally:
        knowledge_kb.build_embeddings = original_embeddings
        knowledge_kb.build_reranker = original_reranker


def test_chat_adapters_normalize_sync_async_and_stream_finish_reasons() -> None:
    from enum import Enum

    from langchain_core.messages import AIMessage, AIMessageChunk
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

    from app.adapters.llm import runtime
    from app.ports.llm import MODEL_TRUNCATED_META_KEY, normalize_finish_reason

    class GeminiReason(Enum):
        MAX_TOKENS = "MAX_TOKENS"

    assert normalize_finish_reason({"finish_reason": GeminiReason.MAX_TOKENS}) == "length"
    assert normalize_finish_reason({"finish_reason": "stop", "stop_reason": "max_tokens"}) == "length"
    for native in ("stop", "end_turn", "STOP", "stop_sequence"):
        assert normalize_finish_reason({"stop_reason": native}) == "stop"
    for native in ("tool_use", "function_call", "tool_calls"):
        assert normalize_finish_reason({"stop_reason": native}) == "tool_calls"
    assert normalize_finish_reason({}, default=None) is None

    providers = (
        (runtime.AnthropicChatModel, runtime.ChatAnthropic, {"stop_reason": "max_tokens"}),
        (runtime.BedrockChatModel, runtime.ChatBedrockConverse, {"stopReason": "max_tokens"}),
        (runtime.GoogleChatModel, runtime.ChatGoogleGenerativeAI, {"finish_reason": "MAX_TOKENS"}),
        (runtime.OllamaChatModel, runtime.ChatOllama, {"done_reason": "length"}),
        (runtime.OpenAICompatibleChatModel, runtime.ChatOpenAI, {"finish_reason": "length"}),
        (runtime.AzureChatModel, runtime.AzureChatOpenAI, {"finish_reason": "length"}),
        (runtime.DeepSeekChatModel, runtime.ChatDeepSeek, {"finish_reason": "length"}),
    )
    for adapter_type, parent, metadata in providers:
        model = adapter_type.model_construct(model="test")

        def result(*_args, **_kwargs):
            # Anthropic returns stop_reason in llm_output, Bedrock on the
            # message, and OpenAI/Gemini in generation_info.
            return ChatResult(
                generations=[ChatGeneration(
                    message=AIMessage(
                        content="Partial",
                        response_metadata=metadata.copy() if parent is runtime.ChatBedrockConverse else {},
                    ),
                    generation_info=None if parent in (runtime.ChatAnthropic, runtime.ChatBedrockConverse) else metadata.copy(),
                )],
                llm_output=metadata.copy() if parent is runtime.ChatAnthropic else None,
            )

        def stream(*_args, **_kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content="Partial"))
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", response_metadata=metadata.copy())
            )
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", response_metadata=metadata.copy())
            )
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))

        async def astream(*args, **kwargs):
            for chunk in stream(*args, **kwargs):
                yield chunk

        async def check_async():
            response = await model._agenerate([])
            assert response.generations[0].generation_info["finish_reason"] == "length"
            return [chunk async for chunk in model._astream([])]

        with (
            patch.object(parent, "_generate", side_effect=result),
            patch.object(parent, "_agenerate", AsyncMock(side_effect=result)),
            patch.object(parent, "_stream", stream),
            patch.object(parent, "_astream", astream),
        ):
            generated = model._generate([]).generations[0]
            assert generated.generation_info["finish_reason"] == "length"
            assert generated.message.response_metadata["finish_reason"] == "length"
            for chunks in (list(model._stream([])), asyncio.run(check_async())):
                assert "finish_reason" not in chunks[0].message.response_metadata
                assert chunks[1].message.response_metadata["finish_reason"] == "length"
                aggregate = chunks[0]
                for chunk in chunks[1:]:
                    aggregate += chunk
                assert aggregate.message.response_metadata[MODEL_TRUNCATED_META_KEY] is True
                assert normalize_finish_reason(aggregate.message.response_metadata) == "length"


def test_reasoning_content_round_trips_in_chat_history() -> None:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from app.adapters.llm.runtime import build_chat_model

    for provider in ("openai_compatible", "deepseek"):
        model = build_chat_model(
            provider,
            {"api_base": "https://example.invalid/v1", "api_key": "test"},
            "reasoning-model",
        )
        for reasoning in ("Inspect the tool result first.", ""):
            assistant = AIMessage(
                content="",
                additional_kwargs={"reasoning_content": reasoning},
                tool_calls=[{"name": "weather", "args": {}, "id": "call-1"}],
            )
            messages = [
                HumanMessage(content="Weather?"),
                assistant,
                ToolMessage(content="Sunny", tool_call_id="call-1"),
                AIMessage(
                    content="Sunny", additional_kwargs={"reasoning_content": "Done"}
                ),
                AIMessage(content="No reasoning field"),
            ]
            payload = model._get_request_payload(messages)
            assert payload["messages"][1]["reasoning_content"] == reasoning
            assert payload["messages"][2]["tool_call_id"] == "call-1"
            assert payload["messages"][3]["reasoning_content"] == "Done"
            assert "reasoning_content" not in payload["messages"][4]
            assert assistant.additional_kwargs == {"reasoning_content": reasoning}

    model = build_chat_model(
        "openai_compatible",
        {"api_base": "https://example.invalid/v1", "api_key": "test"},
        "reasoning-model",
        request_params={"use_responses_api": True},
    )
    payload = model._get_request_payload([AIMessage(content="Answer")])
    assert "messages" not in payload
    assert "input" in payload


def test_metered_chat_preserves_context_window_through_binding() -> None:
    from langchain_deepseek import ChatDeepSeek

    from app.application.agents.runs.memory import _configured_context_window
    from app.infra.models.metering import MeteredChatModel

    profile = {"max_input_tokens": 1_000_000, "tool_calling": True}
    provider = ChatDeepSeek(
        model="unit-profile-model", api_key="test", profile=profile
    )
    registered = SimpleNamespace(meta={})
    metered = MeteredChatModel(provider, registered)
    tool = {
        "name": "echo",
        "description": "Return a value.",
        "parameters": {"type": "object", "properties": {}},
    }
    for model in (metered, metered.bind(max_tokens=8), metered.bind_tools([tool])):
        assert model.profile == provider.profile
        assert _configured_context_window(registered, model) == 1_000_000
        configured = SimpleNamespace(meta={"context_window_tokens": 65536})
        assert _configured_context_window(configured, model) == 65536

    provider.profile = None
    assert MeteredChatModel(provider, registered).profile is None


def main() -> None:
    test_metered_chat_preserves_context_window_through_binding()
    test_reasoning_content_round_trips_in_chat_history()
    test_chat_adapters_normalize_sync_async_and_stream_finish_reasons()
    test_model_type_normalization()
    test_siliconflow_embedding_catalog_includes_existing_bge_model()
    test_registered_model_connection_test_has_a_hard_deadline()
    test_status_validation()
    test_url_credential_validation()
    test_masked_secret_detection()
    test_provider_credentials_aws_pairing_rule()
    test_run_knowledge_model_test_uses_injected_providers()
    print("MODELS_UNIT_OK")


if __name__ == "__main__":
    main()

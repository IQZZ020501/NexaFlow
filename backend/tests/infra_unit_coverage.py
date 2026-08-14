"""Unit and DB-backed coverage for LLM/MCP infrastructure and team services.

Run from ``backend/`` with:

    uv run coverage run --source=<modules> --data-file=.coverage.InfraUnitCoverage \
        -m tests.infra_unit_coverage
    uv run coverage report -m --data-file=.coverage.InfraUnitCoverage

Most tests are pure unit tests: repositories, capabilities and the network are
mocked. DB-backed tests run inside ``test_client()`` against a fresh in-memory
SQLite database (schema created per ``with`` block).
"""

import asyncio
import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.error import HTTPError, URLError

from tests.support import (  # noqa: F401  (must run before any app import)
    activate_admin,
    auth_headers,
    settings,
    test_client,
)

from fastapi import HTTPException
from openai import APIStatusError, OpenAIError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool, StaticPool

from app.application import models as app_models
from app.api import deps as deps_mod
from app.capabilities import mcp as mcp_capabilities
from app.capabilities.llm import credentials as llm_credentials
from app.capabilities.llm import registry as llm_registry
from app.capabilities.llm import registry_repository as llm_registry_repository
from app.capabilities.llm import runtime as llm_runtime
from app.capabilities.llm.models import RegisteredModel
from app.capabilities.llm.providers import PROVIDER_CATALOG
from app.entities.resource_permission import ResourcePermission
from app.entities.team import TEAM_MEMBER_ROLES, Team, TeamMembership
from app.entities.tools import McpServer, McpToolPolicy
from app.entities.user import User
from app.infrastructure import celery as celery_mod
from app.infrastructure import code_sandbox
from app.infrastructure import config as config_mod
from app.infrastructure import mcp_stdio
from app.infrastructure import object_storage
from app.infrastructure import seed as seed_mod
from app.infrastructure import security as security_mod
from app.infrastructure import session as session_mod
from app.infrastructure import validation as validation_mod
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import mcp as mcp_repo
from app.infrastructure.repositories import mapping as mapping_repo
from app.infrastructure.repositories import resource_permission as rp_repo
from app.infrastructure.secrets import decrypt_secret, encrypt_secret, secret_hint
from app.infrastructure.session import get_session_factory
from app.ports import mcp as ports_mcp
from app.ports import model_registry as ports_model_registry
from app.schemas.mcp import McpServerCreateRequest
from app.schemas.model import RegisteredModelCreateRequest, RegisteredModelUpdateRequest
from app.schemas.team import TeamCreateRequest, TeamMemberUpdateRequest, TeamUpdateRequest
from app.shareddomain.agents.models import Agent as AgentOrm
from app.shareddomain.agents.models import AgentMcpTool as AgentMcpToolOrm
from app.shareddomain.teams import services as teams_services
from app.shareddomain.tools import services as tools_services
from app.shareddomain.tools.models import McpServer as McpServerOrm
from app.shareddomain.tools.models import McpToolPolicy as McpToolPolicyOrm
from app.tasks import configure_task_worker
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from mcp.types import Tool as McpTool
from mcp.types import ToolAnnotations

from app.capabilities.mcp.client import (
    MAX_MCP_RESULT_CHARS,
    MAX_MCP_TOOLS,
    McpClientError,
    McpConnection,
    McpDiscovery,
    MultiTransportMcpClient,
    _hardened_http_client_factory,
    call_mcp_tool,
    discover_mcp_tools,
    is_private_address,
    mcp_client,
    normalize_mcp_url,
    validate_mcp_destination,
)
from app.capabilities.llm.runtime import (
    STREAM_USAGE_SUPPORTED_META_KEY,
    CheckedEmbeddings,
    ModelCompletion,
    ModelProviderError,
    ModelProviderStatusError,
    ModelProviderTimeoutError,
    ModelToolCall,
    OpenAICompatibleChatModel,
    OpenAICompatibleReranker,
    _ProviderErrorChatMixin,
    _api_error_detail,
    _bedrock_credentials,
    _bedrock_model_arn,
    _model_provider_error,
    _provider_status_code,
    _reasoning_content,
    _registered_model_credentials,
    _required,
    build_chat_model,
    build_embeddings,
    build_registered_chat_model,
    build_registered_embeddings,
    build_registered_reranker,
    build_reranker,
    openai_compatible_base,
    test_model_connection,
)
from app.domain.resource_permission import ResourcePermission as ResourcePermissionOrm
from app.domain.team import Team as TeamOrm
from app.domain.user import User as UserOrm
from app.domain.workspace import Workspace as WorkspaceOrm
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipOrm
from app.infrastructure.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.infrastructure.validation import (
    normalize_email,
    normalize_name,
    normalize_username,
)
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


def run(coro):
    return asyncio.run(coro)


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError(f"expected HTTPException with status {status_code}")


async def expect_http_error_async(coro, status_code: int) -> None:
    try:
        await coro
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError(f"expected HTTPException with status {status_code}")


def expect_error(fn, error_type) -> None:
    try:
        fn()
    except error_type as exc:
        return exc
    raise AssertionError(f"expected {error_type.__name__}")


# ================================================================ llm/runtime


def test_runtime_error_helpers() -> None:
    import httpx

    response = httpx.Response(400, request=httpx.Request("POST", "http://x"))
    assert _api_error_detail(APIStatusError("m", response=response, body="plain")) == "plain"
    assert _api_error_detail(APIStatusError("m", response=response, body={"error": "bad"})) == '{"error": "bad"}'
    assert _api_error_detail(APIStatusError("m", response=response, body=None)) == "m"

    assert _provider_status_code(SimpleNamespace(status_code=418)) == 418
    assert _provider_status_code(SimpleNamespace(code=401)) == 401
    assert _provider_status_code(SimpleNamespace(code="x")) is None
    client_error = __import__("botocore.exceptions", fromlist=["ClientError"]).ClientError(
        {"Error": {"Code": "X", "Message": "m"}, "ResponseMetadata": {"HTTPStatusCode": 500}},
        "op",
    )
    assert _provider_status_code(client_error) == 500
    assert _provider_status_code(ValueError("x")) is None

    # timeout via cause chain
    cause = TimeoutError("slow")
    exc = ValueError("wrapped")
    exc.__cause__ = cause
    assert isinstance(_model_provider_error(exc), ModelProviderTimeoutError)
    assert isinstance(_model_provider_error(TimeoutError("t")), ModelProviderTimeoutError)

    named = type("APITimeoutError", (Exception,), {})("x")
    assert isinstance(_model_provider_error(named), ModelProviderTimeoutError)

    status_exc = APIStatusError("bad", response=response, body="detail")
    mapped = _model_provider_error(status_exc)
    assert isinstance(mapped, ModelProviderStatusError)
    assert mapped.status_code == 400
    assert mapped.message == "detail"

    client_error = __import__("botocore.exceptions", fromlist=["ClientError"]).ClientError(
        {"Error": {"Code": "X", "Message": "m"}, "ResponseMetadata": {"HTTPStatusCode": 502}},
        "op",
    )
    mapped = _model_provider_error(client_error)
    assert isinstance(mapped, ModelProviderStatusError)
    assert mapped.status_code == 502

    generic = _model_provider_error(RuntimeError("boom"))
    assert isinstance(generic, ModelProviderError)
    assert not isinstance(generic, ModelProviderStatusError)

    # ModelProviderStatusError message formatting
    with_message = ModelProviderStatusError(500, "oops")
    assert with_message.message == "oops"
    assert str(with_message) == "Provider returned status 500: oops"


def test_openai_compatible_base() -> None:
    assert openai_compatible_base("https://api.deepseek.com") == "https://api.deepseek.com/v1"
    assert openai_compatible_base("https://api.deepseek.com/") == "https://api.deepseek.com/v1"
    assert openai_compatible_base("https://host/v1") == "https://host/v1"
    assert openai_compatible_base("https://host/custom/") == "https://host/custom"


def test_reasoning_content() -> None:
    assert _reasoning_content({"reasoning_content": "think"}) == "think"
    assert _reasoning_content({"reasoning": "think"}) == "think"
    assert _reasoning_content({"reasoning": 123}) == ""
    assert _reasoning_content({"reasoning": ""}) == ""
    assert _reasoning_content("not-a-dict") == ""


class _RaisingParent:
    def _generate(self, *args, **kwargs):
        raise OpenAIError("sync boom")

    async def _agenerate(self, *args, **kwargs):
        raise OpenAIError("async boom")

    def _stream(self, *args, **kwargs):
        yield from ()
        raise OpenAIError("stream boom")

    async def _astream(self, *args, **kwargs):
        raise OpenAIError("astream boom")
        yield  # pragma: no cover


class _ErrorMappedModel(_ProviderErrorChatMixin, _RaisingParent):
    pass


def test_provider_error_mixin_maps_errors() -> None:
    model = _ErrorMappedModel()
    for error in (
        expect_error(lambda: model._generate("m"), ModelProviderError),
        expect_error(lambda: list(model._stream("m")), ModelProviderError),
    ):
        assert isinstance(error, ModelProviderError)

    async def async_cases() -> None:
        try:
            await model._agenerate("m")
        except ModelProviderError:
            pass
        else:
            raise AssertionError("expected ModelProviderError")
        try:
            async for _ in model._astream("m"):
                pass
        except ModelProviderError:
            pass
        else:
            raise AssertionError("expected ModelProviderError")

    run(async_cases())


def test_openai_compatible_chat_model_error_paths() -> None:
    model = OpenAICompatibleChatModel(
        model="m",
        api_key="k",
        base_url="http://localhost:9/v1",
        timeout=5,
        max_retries=0,
    )
    with patch.object(
        llm_runtime.ChatOpenAI, "_generate", side_effect=OpenAIError("boom")
    ), patch.object(
        llm_runtime.ChatOpenAI, "_agenerate", side_effect=OpenAIError("boom")
    ), patch.object(
        llm_runtime.ChatOpenAI,
        "_stream",
        side_effect=lambda *a, **k: (_ for _ in ()).throw(OpenAIError("boom")),
    ), patch.object(
        llm_runtime.ChatOpenAI, "_astream", side_effect=OpenAIError("boom")
    ):
        assert isinstance(expect_error(lambda: model._generate("m"), ModelProviderError), ModelProviderError)

        async def async_cases() -> None:
            try:
                await model._agenerate("m")
            except ModelProviderError:
                pass
            else:
                raise AssertionError("expected ModelProviderError")
            try:
                list(model._stream("m"))
            except ModelProviderError:
                pass
            else:
                raise AssertionError("expected ModelProviderError")
            try:
                async for _ in model._astream("m"):
                    pass
            except ModelProviderError:
                pass
            else:
                raise AssertionError("expected ModelProviderError")

        run(async_cases())


def test_openai_compatible_chat_model_reasoning() -> None:
    model = OpenAICompatibleChatModel(
        model="m",
        api_key="k",
        base_url="http://localhost:9/v1",
        timeout=5,
        max_retries=0,
    )
    response = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "ok",
                    "reasoning_content": "think-step",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    result = model._create_chat_result(response)
    assert result.generations[0].message.content == "ok"
    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "think-step"

    # pydantic-backed response object path
    class _Payload:
        def __init__(self, data):
            self._data = data

        def model_dump(self, **kwargs):
            return self._data

    object_response = _Payload(response)
    result = model._create_chat_result(object_response)
    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "think-step"

    # no reasoning -> no kwarg
    plain = {**response, "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
    result = model._create_chat_result(plain)
    assert "reasoning_content" not in result.generations[0].message.additional_kwargs

    def fake_convert(chunk, default_chunk_class, base_generation_info):
        return ChatGenerationChunk(message=AIMessageChunk(content="x"), generation_info=None)

    with patch.object(llm_runtime.ChatOpenAI, "_convert_chunk_to_generation_chunk", side_effect=fake_convert):
        chunk = {
            "id": "x",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": {"reasoning_content": "r1"}, "finish_reason": None}],
        }
        converted = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
        assert converted.message.additional_kwargs["reasoning_content"] == "r1"
        nested = {"chunk": {"choices": [{"index": 0, "delta": {"reasoning_content": "r2"}, "finish_reason": None}]}}
        converted = model._convert_chunk_to_generation_chunk(nested, AIMessageChunk, None)
        assert converted.message.additional_kwargs["reasoning_content"] == "r2"
        no_reasoning = {"choices": [{"index": 0, "delta": {"content": "x"}, "finish_reason": None}]}
        converted = model._convert_chunk_to_generation_chunk(no_reasoning, AIMessageChunk, None)
        assert "reasoning_content" not in converted.message.additional_kwargs


class _FakeEmbeddings:
    def __init__(self, documents=None, query=None):
        self.documents = documents
        self.query = query

    def embed_documents(self, texts):
        if isinstance(self.documents, Exception):
            raise self.documents
        return self.documents or [[0.0] for _ in texts]

    def embed_query(self, text):
        if isinstance(self.query, Exception):
            raise self.query
        return self.query


def test_checked_embeddings() -> None:
    checked = CheckedEmbeddings(_FakeEmbeddings(documents=[[1.0]], query=[1.0]))
    assert checked.embed_documents([]) == []
    assert checked.embed_documents(["a"]) == [[1.0]]
    assert checked.embed_query("q") == [1.0]

    mismatch = CheckedEmbeddings(_FakeEmbeddings(documents=[[1.0], [2.0]]))
    expect_error(lambda: mismatch.embed_documents(["a"]), ModelProviderError)

    empty_query = CheckedEmbeddings(_FakeEmbeddings(query=[]))
    expect_error(lambda: empty_query.embed_query("q"), ModelProviderError)

    failing = CheckedEmbeddings(_FakeEmbeddings(documents=OpenAIError("boom"), query=OpenAIError("boom")))
    expect_error(lambda: failing.embed_documents(["a"]), ModelProviderError)
    expect_error(lambda: failing.embed_query("q"), ModelProviderError)


def test_openai_compatible_embeddings_construction() -> None:
    embeddings = __import__(
        "app.capabilities.llm.runtime", fromlist=["OpenAICompatibleEmbeddings"]
    ).OpenAICompatibleEmbeddings(
        "http://localhost:9/v1", "k", "embed-model", timeout=7
    )
    assert embeddings is not None


class _FakeUrlResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_openai_compatible_reranker() -> None:
    reranker = OpenAICompatibleReranker(
        "https://example.com/api", "secret-key-1234", "rerank-model", timeout=3
    )
    assert reranker.api_base == "https://example.com/api"

    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data)
        assert request.headers["Authorization"] == "Bearer secret-key-1234"
        assert body["model"] == "rerank-model"
        return _FakeUrlResponse(200, b'{"results":[{"index":0,"relevance_score":1.0}]}')

    with patch.object(llm_runtime, "urlopen", side_effect=fake_urlopen):
        assert reranker.rerank("q", ["d"]) == [{"index": 0, "relevance_score": 1.0}]

    with patch.object(llm_runtime, "urlopen", return_value=_FakeUrlResponse(500, b"")):
        error = expect_error(lambda: reranker.rerank("q", ["d"]), ModelProviderStatusError)
        assert error.status_code == 500

    with patch.object(llm_runtime, "urlopen", side_effect=HTTPError("u", 429, "m", {}, None)):
        error = expect_error(lambda: reranker.rerank("q", ["d"]), ModelProviderStatusError)
        assert error.status_code == 429

    for network_error in (URLError("down"), TimeoutError("slow"), OSError("refused")):
        with patch.object(llm_runtime, "urlopen", side_effect=network_error):
            assert isinstance(
                expect_error(lambda: reranker.rerank("q", ["d"]), ModelProviderError),
                ModelProviderError,
            )

    with patch.object(llm_runtime, "urlopen", return_value=_FakeUrlResponse(200, b"not-json")):
        expect_error(lambda: reranker.rerank("q", ["d"]), ModelProviderError)

    with patch.object(
        llm_runtime, "urlopen", return_value=_FakeUrlResponse(200, b'{"results": "not-a-list"}')
    ):
        expect_error(lambda: reranker.rerank("q", ["d"]), ModelProviderError)

    with patch.object(llm_runtime, "urlopen", return_value=_FakeUrlResponse(200, b"[1,2,3]")):
        expect_error(lambda: reranker.rerank("q", ["d"]), ModelProviderError)


def test_bedrock_model_reranker() -> None:
    from app.capabilities.llm.runtime import BedrockModelReranker

    delegate = MagicMock()
    delegate.rerank.return_value = [{"index": 0, "relevance_score": 1.0}]
    reranker = BedrockModelReranker(delegate)
    assert reranker.rerank("q", []) == []
    assert reranker.rerank("q", ["d"]) == [{"index": 0, "relevance_score": 1.0}]
    assert delegate.rerank.call_args[1] == {"top_n": 1}

    failing = MagicMock()
    failing.rerank.side_effect = OpenAIError("boom")
    erroring = BedrockModelReranker(failing)
    expect_error(lambda: erroring.rerank("q", ["d"]), ModelProviderError)


def test_credential_helpers() -> None:
    assert _required({"api_key": "  k  "}, "api_key") == "k"
    assert isinstance(expect_error(lambda: _required({}, "api_key"), ModelProviderError), ModelProviderError)

    from app.capabilities.llm.runtime import _optional, _openai_api_key, _secret

    assert _optional({"x": "  v  "}, "x") == "v"
    assert _optional({"x": "  "}, "x") is None
    assert _secret("v") is not None and str(_secret("v")) == "**********"
    assert _secret(None) is None
    assert _secret("") is None
    assert _openai_api_key({"api_key": "k"}) == "k"
    assert _openai_api_key({}) == "not-required"

    # bedrock credentials
    full = _bedrock_credentials(
        {
            "region_name": "us-east-1",
            "aws_access_key_id": "AK",
            "aws_secret_access_key": "SK",
            "aws_session_token": "TOK",
        },
        timeout=12,
    )
    assert full["region_name"] == "us-east-1"
    assert full["config"].connect_timeout == 12
    assert full["aws_session_token"] is not None
    only_key = {"region_name": "us-east-1", "aws_access_key_id": "AK"}
    assert isinstance(
        expect_error(lambda: _bedrock_credentials(only_key), ModelProviderError),
        ModelProviderError,
    )
    assert _bedrock_credentials({"region_name": "us-east-1"})["aws_access_key_id"] is None

    assert _bedrock_model_arn("amazon.nova", "us-east-1") == "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova"
    assert _bedrock_model_arn("amazon.nova", "cn-north-1").startswith("arn:aws-cn:")
    assert _bedrock_model_arn("amazon.nova", "us-gov-west-1").startswith("arn:aws-us-gov:")
    assert _bedrock_model_arn("arn:aws:bedrock:x", "us-east-1") == "arn:aws:bedrock:x"


class _YieldingParent:
    def _stream(self, *args, **kwargs):
        yield SimpleNamespace(text="chunk")

    async def _astream(self, *args, **kwargs):
        yield SimpleNamespace(text="chunk")


class _YieldingMixinModel(_ProviderErrorChatMixin, _YieldingParent):
    pass


def test_provider_error_mixin_success_paths() -> None:
    model = _YieldingMixinModel()
    assert [chunk.text for chunk in model._stream("m")] == ["chunk"]

    async def async_cases() -> None:
        chunks = [chunk.text async for chunk in model._astream("m")]
        assert chunks == ["chunk"]

    run(async_cases())


def test_openai_compatible_chat_model_astream_success() -> None:
    model = OpenAICompatibleChatModel(
        model="m",
        api_key="k",
        base_url="http://localhost:9/v1",
        timeout=5,
        max_retries=0,
    )
    produced = ChatGenerationChunk(message=AIMessageChunk(content="ok"), generation_info=None)

    async def fake_astream(self, *args, **kwargs):
        yield produced

    async def fake_agenerate(self, *args, **kwargs):
        return ChatResult(generations=[produced])

    with patch.object(llm_runtime.ChatOpenAI, "_astream", fake_astream), patch.object(
        llm_runtime.ChatOpenAI, "_agenerate", fake_agenerate
    ):
        async def async_cases() -> None:
            chunks = [chunk.text async for chunk in model._astream("m")]
            assert chunks == ["ok"]
            result = await model._agenerate("m")
            assert result.generations[0].message.content == "ok"

        run(async_cases())


def test_build_chat_model_and_friends() -> None:
    assert (
        type(build_chat_model("openai_compatible", {"api_base": "http://x"}, "m")).__name__
        == "OpenAICompatibleChatModel"
    )
    assert type(build_chat_model("anthropic", {"api_key": "k"}, "m")).__name__ == "AnthropicChatModel"
    assert type(build_chat_model("bedrock", {"region_name": "us-east-1"}, "m")).__name__ == "BedrockChatModel"
    assert (
        type(
            build_chat_model(
                "azure_openai",
                {"azure_endpoint": "https://x", "api_version": "v", "api_key": "k"},
                "m",
            )
        ).__name__
        == "AzureChatModel"
    )
    assert type(build_chat_model("deepseek", {"api_base": "http://x", "api_key": "k"}, "m")).__name__ == "DeepSeekChatModel"
    assert type(build_chat_model("google_genai", {"api_key": "k"}, "m")).__name__ == "GoogleChatModel"
    assert type(build_chat_model("ollama", {"api_base": "http://x"}, "m")).__name__ == "OllamaChatModel"
    expect_error(lambda: build_chat_model("unsupported", {}, "m"), ModelProviderError)
    expect_error(lambda: build_chat_model("anthropic", {}, "m"), ModelProviderError)

    assert isinstance(build_embeddings("openai_compatible", {"api_base": "http://x"}, "m"), CheckedEmbeddings)
    assert isinstance(build_embeddings("bedrock", {"region_name": "us-east-1"}, "m"), CheckedEmbeddings)
    assert isinstance(
        build_embeddings(
            "azure_openai",
            {"azure_endpoint": "https://x", "api_version": "v", "api_key": "k"},
            "m",
        ),
        CheckedEmbeddings,
    )
    assert isinstance(build_embeddings("google_genai", {"api_key": "k"}, "m"), CheckedEmbeddings)
    assert isinstance(build_embeddings("ollama", {"api_base": "http://x"}, "m"), CheckedEmbeddings)
    expect_error(lambda: build_embeddings("unsupported", {}, "m"), ModelProviderError)
    expect_error(lambda: build_embeddings("bedrock", {}, "m"), ModelProviderError)

    assert isinstance(build_reranker("openai_compatible", {"api_base": "http://x"}, "m"), OpenAICompatibleReranker)
    assert type(build_reranker("bedrock", {"region_name": "us-east-1"}, "m")).__name__ == "BedrockModelReranker"
    expect_error(lambda: build_reranker("unsupported", {}, "m"), ModelProviderError)
    expect_error(lambda: build_reranker("bedrock", {"aws_access_key_id": "a"}, "m"), ModelProviderError)


def _registered_model(**overrides) -> RegisteredModel:
    fields = dict(
        workspace_id="ws-1",
        name="Model",
        provider="model_deepseek_provider",
        provider_type="deepseek",
        api_base="https://api.deepseek.com",
        api_key_ciphertext=llm_credentials.encrypt_credential_secrets(
            {"api_key": "sk-test-1234"}, settings().model_secret_key
        ),
        credential_config={"api_base": "https://api.deepseek.com"},
        credential_secret_hints={"api_key": "****1234"},
        model_type="LLM",
        model_name="deepseek-chat",
        status="active",
        meta={},
        created_by_user_id="user-1",
    )
    fields.update(overrides)
    return RegisteredModel(**fields)


def test_registered_model_credentials() -> None:
    runtime_settings = settings()
    model = _registered_model()
    credentials = _registered_model_credentials(model, runtime_settings, "LLM")
    assert credentials["api_key"] == "sk-test-1234"
    assert credentials["api_base"] == "https://api.deepseek.com"

    disabled = _registered_model(status="disabled")
    expect_error(lambda: _registered_model_credentials(disabled, runtime_settings, "LLM"), ModelProviderError)

    unsupported = _registered_model(provider_type="weird")
    expect_error(lambda: _registered_model_credentials(unsupported, runtime_settings, "LLM"), ModelProviderError)

    wrong_type = _registered_model(model_type="EMBEDDING")
    expect_error(lambda: _registered_model_credentials(wrong_type, runtime_settings, "LLM"), ModelProviderError)

    legacy = _registered_model(
        provider="model_anthropic_provider",
        provider_type="anthropic",
        api_base="https://api.anthropic.com",
        credential_config={},
        api_key_ciphertext=llm_credentials.encrypt_credential_secrets({"api_key": "sk"}, runtime_settings.model_secret_key),
    )
    credentials = _registered_model_credentials(legacy, runtime_settings, "LLM")
    assert credentials["api_base"] == "https://api.anthropic.com"

    # invalid stored bundle: plaintext does not parse -> ValueError branch
    invalid_cipher = _registered_model(
        api_key_ciphertext=encrypt_secret(
            llm_credentials.SECRET_BUNDLE_PREFIX + "garbage",
            runtime_settings.model_secret_key,
        )
    )
    assert isinstance(
        expect_error(lambda: _registered_model_credentials(invalid_cipher, runtime_settings, "LLM"), ModelProviderError),
        ModelProviderError,
    )

    # tampered ciphertext leaks Fernet.InvalidToken (see buglog InfraUnitCoverage)
    from cryptography.fernet import InvalidToken

    tampered = _registered_model(api_key_ciphertext="garbage-not-a-token")
    assert isinstance(
        expect_error(lambda: _registered_model_credentials(tampered, runtime_settings, "LLM"), InvalidToken),
        InvalidToken,
    )


def test_build_registered_models() -> None:
    runtime_settings = settings()
    model = _registered_model()
    chat = build_registered_chat_model(model, runtime_settings)
    assert type(chat).__name__ == "DeepSeekChatModel"

    embedding = _registered_model(
        provider="model_custom_provider",
        provider_type="openai_compatible",
        api_base="https://api.example.com",
        credential_config={"api_base": "https://api.example.com"},
        model_type="EMBEDDING",
        model_name="embed",
    )
    assert isinstance(build_registered_embeddings(embedding, runtime_settings), CheckedEmbeddings)

    reranker = _registered_model(
        provider="model_custom_provider",
        provider_type="openai_compatible",
        api_base="https://api.example.com",
        credential_config={"api_base": "https://api.example.com"},
        model_type="RERANKER",
        model_name="rerank",
    )
    assert isinstance(build_registered_reranker(reranker, runtime_settings), OpenAICompatibleReranker)


def test_test_model_connection() -> None:
    chat_model = MagicMock()
    chat_model.stream.return_value = [SimpleNamespace(usage_metadata={"total_tokens": 3})]
    with patch.object(llm_runtime, "build_chat_model", return_value=chat_model):
        assert test_model_connection("openai_compatible", {"api_base": "http://x"}, "m", "LLM") == {
            STREAM_USAGE_SUPPORTED_META_KEY: True
        }

    no_usage = MagicMock()
    no_usage.stream.return_value = [SimpleNamespace(usage_metadata=None)]
    with patch.object(llm_runtime, "build_chat_model", return_value=no_usage):
        assert test_model_connection("openai_compatible", {"api_base": "http://x"}, "m", "LLM") == {
            STREAM_USAGE_SUPPORTED_META_KEY: False
        }

    rejecting = MagicMock()
    rejecting.stream.side_effect = ModelProviderStatusError(400)
    retry = MagicMock()
    retry.stream.return_value = [SimpleNamespace(usage_metadata=None)]
    with patch.object(llm_runtime, "build_chat_model", side_effect=[rejecting, retry]):
        assert test_model_connection("openai_compatible", {"api_base": "http://x"}, "m", "LLM") == {
            STREAM_USAGE_SUPPORTED_META_KEY: False
        }

    hard_failure = MagicMock()
    hard_failure.stream.side_effect = ModelProviderStatusError(500)
    with patch.object(llm_runtime, "build_chat_model", return_value=hard_failure):
        assert isinstance(
            expect_error(lambda: test_model_connection("openai_compatible", {"api_base": "http://x"}, "m", "LLM"), ModelProviderStatusError),
            ModelProviderStatusError,
        )

    invoke_model = MagicMock()
    invoke_model.invoke.return_value = SimpleNamespace(content="ok")
    with patch.object(llm_runtime, "build_chat_model", return_value=invoke_model):
        assert test_model_connection("deepseek", {"api_base": "http://x", "api_key": "k"}, "m", "LLM") == {
            STREAM_USAGE_SUPPORTED_META_KEY: False
        }

    embedding_model = MagicMock()
    embedding_model.embed_query.return_value = [0.1]
    with patch.object(llm_runtime, "build_embeddings", return_value=embedding_model):
        assert test_model_connection("openai_compatible", {"api_base": "http://x"}, "m", "EMBEDDING") == {
            STREAM_USAGE_SUPPORTED_META_KEY: False
        }

    reranker_model = MagicMock()
    reranker_model.rerank.return_value = [{"index": 0}]
    with patch.object(llm_runtime, "build_reranker", return_value=reranker_model):
        assert test_model_connection("openai_compatible", {"api_base": "http://x"}, "m", "RERANKER") == {
            STREAM_USAGE_SUPPORTED_META_KEY: False
        }

    expect_error(lambda: test_model_connection("openai_compatible", {"api_base": "http://x"}, "m", "WEIRD"), ModelProviderError)


# ================================================================ llm/registry


def test_registry_basics() -> None:
    deepseek = next(entry for entry in PROVIDER_CATALOG if entry["provider"] == "model_deepseek_provider")
    assert llm_registry.provider_catalog_entry("model_deepseek_provider") is deepseek
    expect_http_error(lambda: llm_registry.provider_catalog_entry("nope"), 422)

    assert llm_registry.normalize_model_type("LLM") == "LLM"
    assert llm_registry.normalize_model_type("chat") == "LLM"
    assert llm_registry.normalize_model_type("llm") == "LLM"
    assert llm_registry.normalize_model_type("embedding") == "EMBEDDING"
    assert llm_registry.normalize_model_type("embeddings") == "EMBEDDING"
    assert llm_registry.normalize_model_type("rerank") == "RERANKER"
    assert llm_registry.normalize_model_type("reranker") == "RERANKER"
    assert llm_registry.normalize_model_type("  LLM  ") == "LLM"
    expect_http_error(lambda: llm_registry.normalize_model_type("bogus"), 422)

    assert llm_registry.validate_provider_type("deepseek") == "deepseek"
    expect_http_error(lambda: llm_registry.validate_provider_type("nope"), 422)

    assert llm_registry.validate_status("active") == "active"
    assert llm_registry.validate_status("disabled") == "disabled"
    expect_http_error(lambda: llm_registry.validate_status("archived"), 422)

    assert llm_registry.normalize_url_credential("https://x.com/", "api_base") == "https://x.com"
    assert llm_registry.normalize_url_credential("", "api_base") == ""
    expect_http_error(lambda: llm_registry.normalize_url_credential("ftp://x.com", "api_base"), 422)
    expect_http_error(lambda: llm_registry.normalize_url_credential("not-a-url", "api_base"), 422)

    assert llm_registry.normalize_credential_value(None, "api_base") == ""
    expect_http_error(lambda: llm_registry.normalize_credential_value(42, "api_base"), 422)
    assert llm_registry.normalize_credential_value("  plain  ", "api_key") == "plain"

    assert llm_registry.is_masked_secret("****1234", "****1234") is True
    assert llm_registry.is_masked_secret("****1234", None) is False
    assert llm_registry.is_masked_secret("real-key", "****1234") is False

    expect_http_error(lambda: llm_registry.validate_provider_support(deepseek, "EMBEDDING"), 422)
    llm_registry.validate_provider_support(deepseek, "LLM")

    fields = llm_registry.credential_fields(deepseek)
    assert [field["field"] for field in fields] == ["api_base", "api_key"]

    custom_entry = {
        "provider": "x",
        "name": "X",
        "provider_type": "openai_compatible",
        "model_types": ["LLM"],
        "default_api_base": "https://default.example.com",
        "api_key_required": False,
    }
    default_fields = llm_registry.credential_fields(custom_entry)
    assert default_fields[0]["default_value"] == "https://default.example.com"
    assert default_fields[1]["required"] is False

    assert llm_registry.legacy_connection_value({"api_base": "https://x"}) == "https://x"
    assert llm_registry.legacy_connection_value({"region_name": "us-east-1"}) == "us-east-1"
    assert llm_registry.legacy_connection_value({}) == ""

    assert llm_registry.primary_secret_hint({"api_key": "****1", "aws_access_key_id": "****2"}) == "****1"
    assert llm_registry.primary_secret_hint({"aws_access_key_id": "****2"}) == "****2"
    assert llm_registry.primary_secret_hint({"other": "****3"}) == "****3"
    assert llm_registry.primary_secret_hint({}) is None


def test_stored_model_credentials_fallbacks() -> None:
    runtime_settings = settings()
    model = _registered_model()
    config, secrets, hints = llm_registry.stored_model_credentials(model, runtime_settings)
    assert config == {"api_base": "https://api.deepseek.com"}
    assert secrets == {"api_key": "sk-test-1234"}
    assert hints == {"api_key": "****1234"}

    legacy = _registered_model(
        provider="model_anthropic_provider",
        provider_type="anthropic",
        api_base="https://api.anthropic.com",
        credential_config={},
        credential_secret_hints={},
        api_key_hint="****5678",
    )
    config, secrets, hints = llm_registry.stored_model_credentials(legacy, runtime_settings)
    assert config == {"api_base": "https://api.anthropic.com"}
    assert hints == {"api_key": "****5678"}


_CREDENTIAL_ENTRY = {
    "provider": "x",
    "name": "X",
    "provider_type": "openai_compatible",
    "model_types": ["LLM"],
    "credential_fields": [
        {"field": "api_base", "label": "API URL", "input_type": "TextInput", "required": True, "default_value": ""},
        {"field": "api_key", "label": "API Key", "input_type": "PasswordInput", "required": True, "default_value": ""},
        {"field": "extra", "label": "Extra", "input_type": "TextInput", "required": False, "default_value": "dflt"},
    ],
}

_AWS_ENTRY = {
    "provider": "aws",
    "name": "AWS",
    "provider_type": "bedrock",
    "model_types": ["LLM"],
    "credential_fields": [
        {"field": "region_name", "label": "Region", "input_type": "TextInput", "required": True, "default_value": ""},
        {"field": "aws_access_key_id", "label": "Key", "input_type": "PasswordInput", "required": False, "default_value": ""},
        {"field": "aws_secret_access_key", "label": "Secret", "input_type": "PasswordInput", "required": False, "default_value": ""},
        {"field": "aws_session_token", "label": "Token", "input_type": "PasswordInput", "required": False, "default_value": ""},
    ],
}


def test_normalize_provider_credentials() -> None:
    config, secrets, hints, changed = llm_registry.normalize_provider_credentials(
        _CREDENTIAL_ENTRY,
        {"base_url": "https://x.example.com", "api_key": "sk-new-9876"},
    )
    assert config["api_base"] == "https://x.example.com"
    assert config["extra"] == "dflt"
    assert secrets == {"api_key": "sk-new-9876"}
    assert hints["api_key"] == "****9876"
    assert changed == {"api_key"}

    # unknown field rejected
    expect_http_error(
        lambda: llm_registry.normalize_provider_credentials(_CREDENTIAL_ENTRY, {"nope": "1"}),
        422,
    )

    # clearing a required secret with None -> 422 (required check fires)
    expect_http_error(
        lambda: llm_registry.normalize_provider_credentials(
            _CREDENTIAL_ENTRY,
            {"api_base": "https://x", "api_key": None},
            current_secrets={"api_key": "old"},
            current_hints={"api_key": "****old"},
        ),
        422,
    )

    # clearing an optional secret with None pops it
    config, secrets, hints, changed = llm_registry.normalize_provider_credentials(
        _AWS_ENTRY,
        {"region_name": "us-east-1", "aws_access_key_id": None},
        current_secrets={"aws_access_key_id": "AK"},
        current_hints={"aws_access_key_id": "****AK"},
    )
    assert "aws_access_key_id" not in secrets
    assert changed == {"aws_access_key_id"}

    # masked secret is not rewritten
    config, secrets, hints, changed = llm_registry.normalize_provider_credentials(
        _CREDENTIAL_ENTRY,
        {"api_base": "https://x", "api_key": "****9876"},
        current_secrets={"api_key": "sk-new-9876"},
        current_hints={"api_key": "****9876"},
    )
    assert secrets == {"api_key": "sk-new-9876"}
    assert changed == set()

    # required secret missing
    expect_http_error(
        lambda: llm_registry.normalize_provider_credentials(_CREDENTIAL_ENTRY, {"api_base": "https://x"}),
        422,
    )

    # required config missing
    expect_http_error(
        lambda: llm_registry.normalize_provider_credentials(_CREDENTIAL_ENTRY, {"api_key": "k"}),
        422,
    )

    # optional config falls back to default_value
    config, secrets, hints, changed = llm_registry.normalize_provider_credentials(
        _CREDENTIAL_ENTRY,
        {"api_base": "https://x", "api_key": "k"},
    )
    assert config["extra"] == "dflt"

    # empty optional value removes the stored config entry
    config, secrets, hints, changed = llm_registry.normalize_provider_credentials(
        _CREDENTIAL_ENTRY,
        {"api_base": "https://x", "api_key": "k", "extra": ""},
        current_config={"extra": "old"},
    )
    assert "extra" not in config

    # optional config keeps the stored value when present
    config, secrets, hints, changed = llm_registry.normalize_provider_credentials(
        _CREDENTIAL_ENTRY,
        {"api_base": "https://x", "api_key": "k"},
        current_config={"extra": "old"},
    )
    assert config["extra"] == "old"

    # aws access/secret must come together
    expect_http_error(
        lambda: llm_registry.normalize_provider_credentials(
            _AWS_ENTRY, {"region_name": "us-east-1", "aws_access_key_id": "AK"}
        ),
        422,
    )
    expect_http_error(
        lambda: llm_registry.normalize_provider_credentials(
            _AWS_ENTRY, {"region_name": "us-east-1", "aws_session_token": "TOK"}
        ),
        422,
    )
    config, secrets, hints, changed = llm_registry.normalize_provider_credentials(
        _AWS_ENTRY,
        {"region_name": "us-east-1", "aws_access_key_id": "AK", "aws_secret_access_key": "SK"},
    )
    assert secrets["aws_access_key_id"] == "AK"


def test_apply_model_credentials() -> None:
    runtime_settings = settings()
    model = _registered_model(api_key_ciphertext=None, api_key_hint=None)
    llm_registry.apply_model_credentials(
        model,
        {"api_base": "https://new.example.com"},
        {"api_key": "sk-rotated-1234"},
        {"api_key": "****1234"},
        runtime_settings,
        rewrite_secrets=True,
    )
    assert model.api_base == "https://new.example.com"
    assert model.api_key_hint == "****1234"
    assert model.api_key_ciphertext is not None
    assert model.api_key_updated_at is not None
    assert llm_credentials.decrypt_credential_secrets(model.api_key_ciphertext, runtime_settings.model_secret_key) == {
        "api_key": "sk-rotated-1234"
    }

    llm_registry.apply_model_credentials(
        model,
        {"api_base": "https://new.example.com"},
        {"api_key": "sk-rotated-1234"},
        {"api_key": "****1234"},
        runtime_settings,
        rewrite_secrets=False,
    )
    assert model.api_key_ciphertext is not None  # untouched (no rewrite)


def test_run_model_test() -> None:
    with patch.object(llm_registry, "test_model_connection", return_value={STREAM_USAGE_SUPPORTED_META_KEY: True}):
        assert llm_registry.run_model_test("openai_compatible", {}, "m", "LLM") == {
            STREAM_USAGE_SUPPORTED_META_KEY: True
        }

    with patch.object(llm_registry, "test_model_connection", side_effect=ModelProviderStatusError(401)):
        expect_http_error(lambda: llm_registry.run_model_test("openai_compatible", {}, "m", "LLM"), 400)

    with patch.object(llm_registry, "test_model_connection", side_effect=ModelProviderError("nope")):
        expect_http_error(lambda: llm_registry.run_model_test("openai_compatible", {}, "m", "LLM"), 400)

    with patch.object(llm_registry, "test_model_connection", side_effect=RuntimeError("boom")):
        expect_http_error(lambda: llm_registry.run_model_test("openai_compatible", {}, "m", "LLM"), 400)


def test_test_registered_model() -> None:
    with patch.object(llm_registry, "test_model_connection", return_value={STREAM_USAGE_SUPPORTED_META_KEY: False}):
        assert run(llm_registry.test_registered_model("openai_compatible", {}, "m", "LLM")) == {
            STREAM_USAGE_SUPPORTED_META_KEY: False
        }


# ================================================================ llm/credentials


def test_credentials_roundtrip() -> None:
    key = "unit-secret-key"
    assert llm_credentials.legacy_credential_config("azure_openai", "https://x") == {
        "azure_endpoint": "https://x",
        "api_version": "2024-10-21",
    }
    assert llm_credentials.legacy_credential_config("google_genai", "https://x") == {}
    assert llm_credentials.legacy_credential_config("anthropic", "https://x/v1") == {"api_base": "https://x"}
    assert llm_credentials.legacy_credential_config("ollama", "http://localhost:11434") == {
        "api_base": "http://localhost:11434"
    }
    assert llm_credentials.legacy_credential_config("deepseek", "https://x") == {"api_base": "https://x"}
    assert llm_credentials.legacy_credential_config("deepseek", "") == {}

    assert llm_credentials.encrypt_credential_secrets({}, key) is None
    ciphertext = llm_credentials.encrypt_credential_secrets({"api_key": "k", "other": "v"}, key)
    assert ciphertext is not None
    assert llm_credentials.decrypt_credential_secrets(ciphertext, key) == {"api_key": "k", "other": "v"}

    assert llm_credentials.decrypt_credential_secrets(None, key) == {}

    legacy_cipher = encrypt_secret("legacy-plain-api-key", key)
    assert llm_credentials.decrypt_credential_secrets(legacy_cipher, key) == {"api_key": "legacy-plain-api-key"}

    invalid = encrypt_secret(llm_credentials.SECRET_BUNDLE_PREFIX + '[1,2,3]', key)
    assert isinstance(
        expect_error(lambda: llm_credentials.decrypt_credential_secrets(invalid, key), ValueError),
        ValueError,
    )
    not_json = encrypt_secret(llm_credentials.SECRET_BUNDLE_PREFIX + "garbage", key)
    assert isinstance(
        expect_error(lambda: llm_credentials.decrypt_credential_secrets(not_json, key), ValueError),
        ValueError,
    )


# ================================================================ mcp/client


def test_normalize_mcp_url_unit() -> None:
    assert normalize_mcp_url("  https://example.com/mcp/  ") == "https://example.com/mcp"
    assert normalize_mcp_url("https://example.com/mcp/", preserve_trailing_slash=True) == "https://example.com/mcp/"
    expect_error(lambda: normalize_mcp_url("https://example.com:abc"), McpClientError)
    expect_error(lambda: normalize_mcp_url("ftp://example.com"), McpClientError)
    expect_error(lambda: normalize_mcp_url("https://user:pass@example.com"), McpClientError)
    expect_error(lambda: normalize_mcp_url("https://example.com?q=1"), McpClientError)
    expect_error(lambda: normalize_mcp_url("https://example.com#frag"), McpClientError)
    expect_error(lambda: normalize_mcp_url("https://"), McpClientError)


def test_is_private_address() -> None:
    assert is_private_address("10.0.0.1") is True
    assert is_private_address("127.0.0.1") is True
    assert is_private_address("169.254.1.1") is True
    assert is_private_address("224.0.0.1") is True
    assert is_private_address("240.0.0.1") is True
    assert is_private_address("0.0.0.0") is True
    assert is_private_address("192.168.1.1") is True
    assert is_private_address("8.8.8.8") is False
    assert is_private_address("93.184.216.34") is False


def test_validate_mcp_destination() -> None:
    run(validate_mcp_destination("http://10.0.0.1/mcp", allow_private_networks=True))
    expect_error(lambda: run(validate_mcp_destination("http:///mcp", allow_private_networks=False)), McpClientError)

    with patch("socket.getaddrinfo", side_effect=OSError("nxdomain")):
        expect_error(
            lambda: run(validate_mcp_destination("http://missing.example.com/mcp", allow_private_networks=False)),
            McpClientError,
        )

    with patch(
        "socket.getaddrinfo",
        return_value=[("AF_INET", "SOCK_STREAM", 6, "", ("127.0.0.1", 80))],
    ):
        expect_error(
            lambda: run(validate_mcp_destination("http://example.com/mcp", allow_private_networks=False)),
            McpClientError,
        )

    with patch(
        "socket.getaddrinfo",
        return_value=[("AF_INET", "SOCK_STREAM", 6, "", ("8.8.8.8", 80))],
    ):
        run(validate_mcp_destination("http://example.com/mcp", allow_private_networks=False))


def test_hardened_http_client_factory() -> None:
    async def enter() -> None:
        async with _hardened_http_client_factory(
            headers={"X-Test": "1"},
            auth=None,
            timeout=5,
        ) as client:
            assert client is not None

    run(enter())


class _FakeTransport:
    pass


class _FakeMcpClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.exc = None

    async def __aenter__(self):
        if self.exc is not None:
            raise self.exc
        return self

    async def __aexit__(self, *exc_info):
        return False


def _mcp_settings(**overrides):
    base = {
        "mcp_allow_private_networks": True,
        "mcp_request_timeout_seconds": 5,
    }
    base.update(overrides)
    return replace(settings(), **base)


def test_mcp_client_streamable_http() -> None:
    async def scenario() -> None:
        fake_client = _FakeMcpClient()
        client_factory = MagicMock(return_value=fake_client)
        with patch.object(mcp_capabilities.client, "Client", client_factory), patch.object(
            mcp_capabilities.client, "streamable_http_client", return_value=_FakeTransport()
        ):
            async with mcp_client(
                McpConnection(
                    transport="streamable_http",
                    url="https://example.com/mcp",
                    bearer_token="tok",
                ),
                _mcp_settings(),
                timeout_seconds=5,
            ) as client:
                assert client is fake_client
                assert client_factory.call_args.kwargs["read_timeout_seconds"] == 5
                assert client_factory.call_args.kwargs["cache"] is None

    run(scenario())


def test_mcp_client_sse() -> None:
    async def scenario() -> None:
        fake_client = _FakeMcpClient()
        with patch.object(mcp_capabilities.client, "Client", return_value=fake_client), patch.object(
            mcp_capabilities.client, "sse_client", return_value=_FakeTransport()
        ):
            async with mcp_client(
                McpConnection(transport="sse", url="https://example.com/sse/"),
                _mcp_settings(),
                timeout_seconds=5,
            ) as client:
                assert client is fake_client

    run(scenario())


def test_mcp_client_stdio() -> None:
    async def scenario() -> None:
        fake_client = _FakeMcpClient()
        client_factory = MagicMock(return_value=fake_client)
        stdio_client_mock = MagicMock(return_value=_FakeTransport())
        stdio_config = mcp_stdio.McpStdioConfig(
            command="/bin/echo",
            args=("hello",),
            cwd=None,
            env=(("A", "B"),),
        )
        with patch.object(mcp_capabilities.client, "Client", client_factory), patch.object(
            mcp_capabilities.client, "stdio_client", stdio_client_mock
        ):
            async with mcp_client(
                McpConnection(transport="stdio", stdio_config=stdio_config),
                _mcp_settings(),
                timeout_seconds=5,
            ) as client:
                assert client is fake_client
                assert client_factory.call_args.kwargs["read_timeout_seconds"] == 5
                params = stdio_client_mock.call_args.args[0]
                assert params.command == "/bin/echo"
                assert params.args == ["hello"]
                assert params.env == {"A": "B"}

    run(scenario())


def test_mcp_client_error_paths() -> None:
    async def scenario() -> None:
        # missing url for http transport
        try:
            async with mcp_client(
                McpConnection(transport="streamable_http", url=None),
                _mcp_settings(),
                timeout_seconds=5,
            ):
                pass
        except McpClientError as exc:
            assert "URL is required" in str(exc)
        else:
            raise AssertionError("expected McpClientError")

        # missing stdio config
        try:
            async with mcp_client(
                McpConnection(transport="stdio", stdio_config=None),
                _mcp_settings(),
                timeout_seconds=5,
            ):
                pass
        except McpClientError as exc:
            assert "stdio configuration is required" in str(exc)
        else:
            raise AssertionError("expected McpClientError")

        # invalid stdio config
        bad_config = mcp_stdio.McpStdioConfig(
            command="/bin/echo",
            args=(),
            cwd=None,
            env=(),
        )
        with patch.object(mcp_capabilities.client, "validate_mcp_stdio_config_runtime", side_effect=mcp_stdio.McpStdioConfigError("nope")):
            try:
                async with mcp_client(
                    McpConnection(transport="stdio", stdio_config=bad_config),
                    _mcp_settings(),
                    timeout_seconds=5,
                ):
                    pass
            except McpClientError as exc:
                assert "nope" in str(exc)
            else:
                raise AssertionError("expected McpClientError")

        # unsupported transport
        try:
            async with mcp_client(
                McpConnection(transport="carrier-pigeon"),
                _mcp_settings(),
                timeout_seconds=5,
            ):
                pass
        except McpClientError as exc:
            assert "Unsupported MCP transport" in str(exc)
        else:
            raise AssertionError("expected McpClientError")

        # validate_mcp_destination failure propagates as McpClientError
        with patch.object(
            mcp_capabilities.client,
            "validate_mcp_destination",
            side_effect=McpClientError("Private MCP server addresses are not allowed."),
        ):
            try:
                async with mcp_client(
                    McpConnection(transport="streamable_http", url="http://10.0.0.1/mcp"),
                    _mcp_settings(mcp_allow_private_networks=False),
                    timeout_seconds=5,
                ):
                    pass
            except McpClientError as exc:
                assert "Private" in str(exc)
            else:
                raise AssertionError("expected McpClientError")

        # inner failure is wrapped
        failing = _FakeMcpClient()
        failing.exc = RuntimeError("inner boom")
        with patch.object(mcp_capabilities.client, "Client", return_value=failing), patch.object(
            mcp_capabilities.client, "streamable_http_client", return_value=_FakeTransport()
        ):
            try:
                async with mcp_client(
                    McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                    _mcp_settings(),
                    timeout_seconds=5,
                ):
                    pass
            except McpClientError as exc:
                assert "MCP server request failed" in str(exc)
            else:
                raise AssertionError("expected McpClientError")

        # timeout is wrapped
        class _SlowMcpClient(_FakeMcpClient):
            def __init__(self, delay):
                super().__init__()
                self.delay = delay

            async def __aenter__(self):
                await asyncio.sleep(self.delay)
                return self

        slow = _SlowMcpClient(1.0)
        with patch.object(mcp_capabilities.client, "Client", return_value=slow), patch.object(
            mcp_capabilities.client, "streamable_http_client", return_value=_FakeTransport()
        ):
            try:
                async with mcp_client(
                    McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                    _mcp_settings(mcp_request_timeout_seconds=5),
                    timeout_seconds=0.05,
                ):
                    pass
            except McpClientError:
                pass
            else:
                raise AssertionError("expected McpClientError")

    run(scenario())


def _fake_tool(name, schema=None, description=None, annotations=None):
    return SimpleNamespace(
        name=name,
        description=description,
        input_schema=schema or {"type": "object", "properties": {}},
        annotations=annotations,
    )


def _fake_result(tools, next_cursor=None):
    return SimpleNamespace(tools=tools, next_cursor=next_cursor)


def test_discover_mcp_tools() -> None:
    async def scenario() -> None:
        fake_client = AsyncMock()
        fake_client.list_tools.side_effect = [
            _fake_result(
                [
                    _fake_tool("echo", description="Say it"),
                    _fake_tool("echo", description="duplicate"),
                    _fake_tool("wait"),
                ],
                next_cursor="page-2",
            ),
            _fake_result([_fake_tool("extra")], next_cursor=None),
        ]
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = fake_client
            discovery = await discover_mcp_tools(
                McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                _mcp_settings(),
            )
        assert [tool["name"] for tool in discovery.tools] == ["echo", "wait", "extra"]
        assert discovery.tools[0]["description"] == "Say it"
        assert discovery.tools[0]["annotations"] is None
        first_call, second_call = fake_client.list_tools.await_args_list
        assert first_call.kwargs == {"cursor": None, "cache_mode": "reload"}
        assert second_call.kwargs == {"cursor": "page-2", "cache_mode": "reload"}

        # annotations serialized when present
        annotated = AsyncMock()
        annotated.list_tools.return_value = _fake_result(
            [_fake_tool("a", annotations=ToolAnnotations(readOnlyHint=False))],
            next_cursor=None,
        )
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = annotated
            discovery = await discover_mcp_tools(
                McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                _mcp_settings(),
            )
        assert discovery.tools[0]["annotations"] == {"readOnlyHint": False}

        # invalid tool name
        for bad_name in ("", "x" * 256):
            invalid = AsyncMock()
            invalid.list_tools.return_value = _fake_result([_fake_tool(bad_name)], next_cursor=None)
            with patch.object(mcp_capabilities.client, "mcp_client") as context:
                context.return_value.__aenter__.return_value = invalid
                try:
                    await discover_mcp_tools(
                        McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                        _mcp_settings(),
                    )
                except McpClientError:
                    pass
                else:
                    raise AssertionError("expected McpClientError")

        # too many tools
        too_many = AsyncMock()
        too_many.list_tools.return_value = _fake_result(
            [_fake_tool(f"t{index}") for index in range(MAX_MCP_TOOLS + 1)],
            next_cursor=None,
        )
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = too_many
            try:
                await discover_mcp_tools(
                    McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                    _mcp_settings(),
                )
            except McpClientError as exc:
                assert "too many tools" in str(exc)
            else:
                raise AssertionError("expected McpClientError")

        # invalid schema
        for bad_schema in ("nope", {"type": "array"}):
            invalid_schema = AsyncMock()
            invalid_schema.list_tools.return_value = _fake_result(
                [_fake_tool("t", schema=bad_schema)],
                next_cursor=None,
            )
            with patch.object(mcp_capabilities.client, "mcp_client") as context:
                context.return_value.__aenter__.return_value = invalid_schema
                try:
                    await discover_mcp_tools(
                        McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                        _mcp_settings(),
                    )
                except McpClientError:
                    pass
                else:
                    raise AssertionError("expected McpClientError")

        # schema too large
        huge_schema = {"type": "object", "blob": "x" * 21_000}
        huge = AsyncMock()
        huge.list_tools.return_value = _fake_result([_fake_tool("t", schema=huge_schema)], next_cursor=None)
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = huge
            try:
                await discover_mcp_tools(
                    McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                    _mcp_settings(),
                )
            except McpClientError as exc:
                assert "schema is too large" in str(exc)
            else:
                raise AssertionError("expected McpClientError")

        # un-serializable schema
        unserializable = AsyncMock()
        unserializable.list_tools.return_value = _fake_result(
            [_fake_tool("t", schema={"type": "object", "bad": object()})],
            next_cursor=None,
        )
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = unserializable
            try:
                await discover_mcp_tools(
                    McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                    _mcp_settings(),
                )
            except McpClientError:
                pass
            else:
                raise AssertionError("expected McpClientError")

        # too many pages
        paging = AsyncMock()
        paging.list_tools.return_value = _fake_result([_fake_tool("t")], next_cursor="more")
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = paging
            try:
                await discover_mcp_tools(
                    McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                    _mcp_settings(),
                )
            except McpClientError as exc:
                assert "too many tool pages" in str(exc)
            else:
                raise AssertionError("expected McpClientError")

    run(scenario())


def test_call_mcp_tool() -> None:
    async def scenario() -> None:
        fake_client = AsyncMock()
        fake_client.call_tool.return_value = SimpleNamespace(
            structured_content={"message": "hi"},
            content=[],
            is_error=False,
        )
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = fake_client
            content, is_error = await call_mcp_tool(
                McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                _mcp_settings(),
                "echo",
                {"message": "hi"},
                idempotency_key="idem-1",
            )
        assert not is_error
        assert json.loads(content) == {"message": "hi"}
        assert fake_client.call_tool.call_args.kwargs["meta"] == {"nexaflow/idempotencyKey": "idem-1"}

        # no structured content -> dump content items
        fake_client.call_tool.return_value = SimpleNamespace(
            structured_content=None,
            content=[SimpleNamespace(model_dump=lambda **kw: {"type": "text", "text": "raw"})],
            is_error=True,
        )
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = fake_client
            content, is_error = await call_mcp_tool(
                McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                _mcp_settings(),
                "echo",
                {},
            )
        assert is_error
        assert json.loads(content) == [{"type": "text", "text": "raw"}]
        assert fake_client.call_tool.call_args.kwargs.get("meta") is None

        # truncation
        fake_client.call_tool.return_value = SimpleNamespace(
            structured_content={"data": "x" * (MAX_MCP_RESULT_CHARS + 100)},
            content=[],
            is_error=False,
        )
        with patch.object(mcp_capabilities.client, "mcp_client") as context:
            context.return_value.__aenter__.return_value = fake_client
            content, _ = await call_mcp_tool(
                McpConnection(transport="streamable_http", url="https://example.com/mcp"),
                _mcp_settings(),
                "echo",
                {},
            )
        assert content.endswith("\n[truncated]")

    run(scenario())


def test_multitransport_client() -> None:
    client = MultiTransportMcpClient(_mcp_settings())
    assert client.settings is not None

    async def scenario() -> None:
        with patch.object(mcp_capabilities.client, "discover_mcp_tools", new=AsyncMock(return_value=McpDiscovery(tools=[]))) as discover, patch.object(
            mcp_capabilities.client, "call_mcp_tool", new=AsyncMock(return_value=("{}", False))
        ) as call:
            connection = McpConnection(transport="streamable_http", url="https://example.com/mcp")
            await client.discover_mcp_tools(connection)
            discover.assert_awaited_once()
            await client.call_mcp_tool(connection, "echo", {}, "idem")
            call.assert_awaited_once_with(connection, client.settings, "echo", {}, "idem")

    run(scenario())


# ================================================================ mcp_stdio


def test_mcp_stdio_parse() -> None:
    config = mcp_stdio.parse_mcp_stdio_config(
        {
            "command": "/usr/local/bin/mcp-server",
            "args": ["--port", "8080"],
            "cwd": "/tmp",
            "env": {"TOKEN": "abc", "B": "b"},
        }
    )
    assert config.command == "/usr/local/bin/mcp-server"
    assert config.args == ("--port", "8080")
    assert config.cwd == "/tmp"
    assert config.env == (("B", "b"), ("TOKEN", "abc"))  # sorted
    assert mcp_stdio.serialize_mcp_stdio_config(config) == json.dumps(
        {
            "command": "/usr/local/bin/mcp-server",
            "args": ["--port", "8080"],
            "cwd": "/tmp",
            "env": {"B": "b", "TOKEN": "abc"},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    from_json = mcp_stdio.parse_mcp_stdio_config(
        json.dumps({"command": "/bin/echo", "args": ["x"], "env": {}})
    )
    assert from_json.args == ("x",)

    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config("x" * (mcp_stdio.MAX_STDIO_CONFIG_JSON_CHARS + 1)), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config("not json"), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config([1, 2]), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "bogus": 1}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"args": []}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "relative/path"}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": ""}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": 42}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "args": "nope"}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "args": [1]}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "args": ["x" * (mcp_stdio.MAX_STDIO_ARGUMENT_CHARS + 1)]}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "args": ["a\x00b"]}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "cwd": "relative"}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "env": "nope"}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "env": {"1BAD": "x"}}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "env": {"OK": "x" * (mcp_stdio.MAX_STDIO_ENV_VALUE_CHARS + 1)}}), mcp_stdio.McpStdioConfigError)
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config({"command": "/bin/echo", "env": {"OK": 5}}), mcp_stdio.McpStdioConfigError)
    many_args = {"command": "/bin/echo", "args": [f"a{index}" for index in range(mcp_stdio.MAX_STDIO_ARGS + 1)]}
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config(many_args), mcp_stdio.McpStdioConfigError)
    many_env = {"command": "/bin/echo", "env": {f"K{index}": "v" for index in range(mcp_stdio.MAX_STDIO_ENV_VARS + 1)}}
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config(many_env), mcp_stdio.McpStdioConfigError)
    # serialized size check
    big_env = {"command": "/bin/echo", "env": {f"K{index}": "v" * 2100 for index in range(mcp_stdio.MAX_STDIO_ENV_VARS)}}
    expect_error(lambda: mcp_stdio.parse_mcp_stdio_config(big_env), mcp_stdio.McpStdioConfigError)


def test_mcp_stdio_runtime_validation() -> None:
    valid = mcp_stdio.McpStdioConfig(command="/bin/echo", args=(), cwd=None, env=())
    mcp_stdio.validate_mcp_stdio_config_runtime(valid)
    with_cwd = mcp_stdio.McpStdioConfig(command="/bin/echo", args=(), cwd="/tmp", env=())
    mcp_stdio.validate_mcp_stdio_config_runtime(with_cwd)
    expect_error(
        lambda: mcp_stdio.validate_mcp_stdio_config_runtime(
            mcp_stdio.McpStdioConfig(command="/bin/definitely-missing", args=(), cwd=None, env=())
        ),
        mcp_stdio.McpStdioConfigError,
    )
    expect_error(
        lambda: mcp_stdio.validate_mcp_stdio_config_runtime(
            mcp_stdio.McpStdioConfig(command="/bin/echo", args=(), cwd="/definitely/missing/dir", env=())
        ),
        mcp_stdio.McpStdioConfigError,
    )


# ================================================================ code_sandbox


class _FakeSandboxWriter:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class _FakeSandboxReader:
    def __init__(self, line, error=None):
        self.line = line
        self.error = error

    async def readline(self):
        if self.error is not None:
            raise self.error
        return self.line


def _sandbox_response(**overrides):
    payload = {
        "ok": True,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


async def _run_sandbox(reader, settings_override=None, code="x = 1\nresult = x + 1", inputs=None):
    writer = _FakeSandboxWriter()
    runtime_settings = replace(settings(), workflow_sandbox_timeout_seconds=5)
    if settings_override:
        runtime_settings = replace(runtime_settings, **settings_override)
    with patch("asyncio.open_unix_connection", new=AsyncMock(return_value=(reader, writer))):
        return await code_sandbox.execute_workflow_code(
            runtime_settings,
            code,
            inputs if inputs is not None else {"v": 1},
        )


def test_code_sandbox_program_wrapping() -> None:
    program = code_sandbox._program("result = 42")
    assert "import json, sys" in program
    assert code_sandbox.RESULT_MARKER in program
    assert "result = 42" in program


def _sandbox_expect_error(coro_factory) -> code_sandbox.WorkflowSandboxError:
    try:
        run(coro_factory())
    except code_sandbox.WorkflowSandboxError as exc:
        return exc
    raise AssertionError("expected WorkflowSandboxError")


def test_code_sandbox_execute() -> None:
    result = run(
        _run_sandbox(
            _FakeSandboxReader(
                _sandbox_response(
                    stdout=f"hello\n{code_sandbox.RESULT_MARKER}{json.dumps({'result': 42})}",
                    stderr="",
                    exit_code=0,
                )
            )
        )
    )
    assert result.result == 42
    assert result.stdout == "hello"
    assert result.exit_code == 0

    # failing execution
    failed = _sandbox_expect_error(
        lambda: _run_sandbox(
            _FakeSandboxReader(
                _sandbox_response(ok=False, exit_code=1, stderr="boom", error=None)
            )
        )
    )
    assert "boom" in str(failed)

    # error field takes precedence
    errored = _sandbox_expect_error(
        lambda: _run_sandbox(
            _FakeSandboxReader(
                _sandbox_response(ok=False, exit_code=1, stderr="", error="script crashed")
            )
        )
    )
    assert "script crashed" in str(errored)

    # non-int exit code
    invalid_exit = _sandbox_expect_error(
        lambda: _run_sandbox(
            _FakeSandboxReader(_sandbox_response(ok=True, exit_code="0", stdout="no marker"))
        )
    )
    assert isinstance(invalid_exit, code_sandbox.WorkflowSandboxError)

    # ok not true
    not_ok = _sandbox_expect_error(
        lambda: _run_sandbox(_FakeSandboxReader(_sandbox_response(ok="yes", exit_code=0, stdout="x")))
    )
    assert isinstance(not_ok, code_sandbox.WorkflowSandboxError)

    # empty line
    empty = _sandbox_expect_error(lambda: _run_sandbox(_FakeSandboxReader(b"")))
    assert isinstance(empty, code_sandbox.WorkflowSandboxError)

    # non-dict response
    non_dict = _sandbox_expect_error(lambda: _run_sandbox(_FakeSandboxReader(b'[1,2,3]')))
    assert isinstance(non_dict, code_sandbox.WorkflowSandboxError)

    # missing result marker
    no_marker = _sandbox_expect_error(
        lambda: _run_sandbox(_FakeSandboxReader(_sandbox_response(exit_code=0, stdout="nothing here")))
    )
    assert isinstance(no_marker, code_sandbox.WorkflowSandboxError)

    # invalid result json
    bad_json = _sandbox_expect_error(
        lambda: _run_sandbox(
            _FakeSandboxReader(
                _sandbox_response(exit_code=0, stdout=code_sandbox.RESULT_MARKER + "not-json")
            )
        )
    )
    assert isinstance(bad_json, code_sandbox.WorkflowSandboxError)

    # payload without result key
    no_result_key = _sandbox_expect_error(
        lambda: _run_sandbox(
            _FakeSandboxReader(
                _sandbox_response(exit_code=0, stdout=code_sandbox.RESULT_MARKER + '{"other": 1}')
            )
        )
    )
    assert isinstance(no_result_key, code_sandbox.WorkflowSandboxError)

    # non-dict payload
    list_payload = _sandbox_expect_error(
        lambda: _run_sandbox(
            _FakeSandboxReader(
                _sandbox_response(exit_code=0, stdout=code_sandbox.RESULT_MARKER + '[1]')
            )
        )
    )
    assert isinstance(list_payload, code_sandbox.WorkflowSandboxError)

    # oversized line
    oversized = _sandbox_expect_error(
        lambda: _run_sandbox(_FakeSandboxReader(b"x" * (code_sandbox.MAX_RESPONSE_BYTES + 1)))
    )
    assert isinstance(oversized, code_sandbox.WorkflowSandboxError)

    # unavailable: OSError from connect
    async def run_unavailable() -> code_sandbox.WorkflowSandboxError:
        with patch("asyncio.open_unix_connection", new=AsyncMock(side_effect=OSError("refused"))):
            try:
                await code_sandbox.execute_workflow_code(
                    replace(settings(), workflow_sandbox_timeout_seconds=5),
                    "result = 1",
                    {},
                )
            except code_sandbox.WorkflowSandboxError as exc:
                return exc
            raise AssertionError("expected WorkflowSandboxError")

    unavailable = run(run_unavailable())
    assert "unavailable" in str(unavailable)

    # unavailable: readline raising
    reader_error = _sandbox_expect_error(
        lambda: _run_sandbox(_FakeSandboxReader(b"", error=TimeoutError("slow")))
    )
    assert isinstance(reader_error, code_sandbox.WorkflowSandboxError)


class _BrokenSandboxWriter:
    def write(self, data):
        raise OSError("disk full")

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def test_code_sandbox_write_failure() -> None:
    writer = _BrokenSandboxWriter()

    async def run_write_failure() -> code_sandbox.WorkflowSandboxError:
        with patch(
            "asyncio.open_unix_connection",
            new=AsyncMock(return_value=(_FakeSandboxReader(b""), writer)),
        ):
            try:
                await code_sandbox.execute_workflow_code(
                    replace(settings(), workflow_sandbox_timeout_seconds=5),
                    "result = 1",
                    {},
                )
            except code_sandbox.WorkflowSandboxError as exc:
                return exc
            raise AssertionError("expected WorkflowSandboxError")

    result = run(run_write_failure())
    assert isinstance(result, code_sandbox.WorkflowSandboxError)


# ================================================================ object_storage


async def _chunks(*items):
    for item in items:
        yield item


def test_object_storage() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        storage = object_storage.LocalObjectStorage(root)
        assert isinstance(object_storage.create_object_storage(root), object_storage.LocalObjectStorage)

        assert storage.path("a/b.txt") == (root / "a/b.txt").resolve()
        expect_error(lambda: storage.path("../escape"), object_storage.ObjectStorageError)
        expect_error(lambda: storage.path("/etc/passwd"), object_storage.ObjectStorageError)
        assert storage.path("plain.txt") == (root / "plain.txt").resolve()

        size = run(storage.put_chunks("data/blob.bin", _chunks(b"ab", b"cd"), None))
        assert size == 4
        assert (root / "data/blob.bin").read_bytes() == b"abcd"

        too_large = expect_error(
            lambda: run(storage.put_chunks("data/big.bin", _chunks(b"x" * 10, b"y" * 10), 15)),
            object_storage.ObjectTooLargeError,
        )
        assert too_large is not None
        assert not (root / "data/big.bin").exists()

        empty = expect_error(
            lambda: run(storage.put_chunks("data/empty.bin", _chunks(), None)),
            object_storage.EmptyObjectError,
        )
        assert empty is not None
        assert not (root / "data/empty.bin").exists()

        class _ExplodingChunks:
            def __init__(self):
                self.sent = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.sent:
                    self.sent = True
                    return b"partial"
                raise RuntimeError("boom")

        exploded = expect_error(
            lambda: run(storage.put_chunks("data/explode.bin", _ExplodingChunks(), None)),
            RuntimeError,
        )
        assert exploded is not None
        assert not (root / "data/explode.bin").exists()

        assert storage.put_bytes("bytes.txt", b"hello") == 5
        assert (root / "bytes.txt").read_bytes() == b"hello"
        expect_error(lambda: storage.put_bytes("empty.txt", b""), object_storage.EmptyObjectError)

        storage.delete("bytes.txt")
        assert not (root / "bytes.txt").exists()
        storage.delete("never-existed")

        nested = storage.put_bytes("deep/a/b/c.txt", b"x")
        assert nested == 1
        storage.delete("deep/a/b/c.txt")
        assert not (root / "deep/a/b/c.txt").exists()
        assert not (root / "deep/a/b").exists()
        assert not (root / "deep/a").exists()
        assert not (root / "deep").exists()

        storage.put_bytes("keep/a.txt", b"x")
        storage.put_bytes("keep/b.txt", b"y")
        storage.delete("keep/a.txt")
        assert (root / "keep").exists()  # not empty -> rmdir fails, loop breaks
        assert (root / "keep/b.txt").exists()

        storage.put_bytes("prefix/x.txt", b"x")
        storage.delete_prefix("prefix")
        assert not (root / "prefix").exists()
        storage.delete_prefix("no-such-prefix")


# ================================================================ config


def test_load_env_file() -> None:
    with TemporaryDirectory() as temp_dir:
        env_path = Path(temp_dir) / ".env"
        env_path.write_text(
            "# comment\n\nSOME_KEY=value1\nQUOTED=\"quoted value\"\nEMPTY=\n"
        )
        with patch.dict(os.environ, {}, clear=False):
            original = os.environ.get("SOME_KEY")
            original_quoted = os.environ.get("QUOTED")
            try:
                config_mod.load_env_file(env_path)
                assert os.environ["SOME_KEY"] == "value1"
                assert os.environ["QUOTED"] == "quoted value"
            finally:
                if original is None:
                    os.environ.pop("SOME_KEY", None)
                else:
                    os.environ["SOME_KEY"] = original
                if original_quoted is None:
                    os.environ.pop("QUOTED", None)
                else:
                    os.environ["QUOTED"] = original_quoted

        config_mod.load_env_file(Path(temp_dir) / "missing.env")

        # existing env keys win
        env_path2 = Path(temp_dir) / ".env2"
        env_path2.write_text("PRIORITY_KEY=new\n")
        with patch.dict(os.environ, {"PRIORITY_KEY": "existing"}, clear=False):
            config_mod.load_env_file(env_path2)
            assert os.environ["PRIORITY_KEY"] == "existing"


def _valid_settings() -> config_mod.Settings:
    return config_mod.Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        bootstrap_admin_username="admin",
        bootstrap_admin_email="admin@app.local",
        bootstrap_admin_name="Admin",
        bootstrap_admin_password="Admin@12345.",
        jwt_secret_key="jwt-key",
        model_secret_key="model-key",
        knowledge_storage_dir=Path("/tmp/nexaflow-test"),
        qdrant_url=":memory:",
        celery_broker_url="redis://localhost:6379/0",
    )


def test_settings_defaults_and_validation() -> None:
    base = _valid_settings()
    assert base.mcp_request_timeout_seconds == 30.0
    assert base.model_request_timeout_seconds == 60.0
    assert base.agent_tool_timeout_seconds == 30.0
    assert base.agent_run_timeout_seconds == 300.0
    assert base.agent_executor_lease_seconds == 90
    assert base.agent_executor_heartbeat_seconds == 30
    assert base.agent_event_poll_seconds == 0.5
    assert base.agent_external_agent_runs_per_minute == 60
    assert base.agent_external_consumer_runs_per_minute == 10
    assert base.workflow_sandbox_socket == "/run/sandbox/sandbox.sock"
    assert base.workflow_sandbox_timeout_seconds == 5.0
    assert base.jwt_expires_minutes == 1440
    assert base.refresh_token_expires_days == 30
    assert base.cors_origins == ()
    assert base.environment == "development"
    assert base.log_level == "INFO"
    base.validate()

    # require_bootstrap=False tolerates missing bootstrap values
    no_bootstrap = replace(base, bootstrap_admin_username="")
    no_bootstrap.validate(require_bootstrap=False)

    cases = [
        (replace(base, bootstrap_admin_username=""), "Missing initialization"),
        (replace(base, bootstrap_admin_email=""), "Missing initialization"),
        (replace(base, jwt_secret_key=""), "JWT_SECRET_KEY"),
        (replace(base, model_secret_key=""), "MODEL_SECRET_KEY"),
        (replace(base, knowledge_storage_dir=None), "KNOWLEDGE_STORAGE_DIR"),
        (replace(base, qdrant_url=""), "QDRANT_URL"),
        (replace(base, celery_broker_url=""), "CELERY_BROKER_URL"),
        (replace(base, log_level="TRACE"), "Invalid LOG_LEVEL"),
        (replace(base, mcp_request_timeout_seconds=0), "MCP_REQUEST_TIMEOUT_SECONDS"),
        (replace(base, mcp_request_timeout_seconds=301), "MCP_REQUEST_TIMEOUT_SECONDS"),
        (replace(base, model_request_timeout_seconds=0), "MODEL_REQUEST_TIMEOUT_SECONDS"),
        (replace(base, model_request_timeout_seconds=301), "MODEL_REQUEST_TIMEOUT_SECONDS"),
        (replace(base, agent_tool_timeout_seconds=0), "AGENT_TOOL_TIMEOUT_SECONDS"),
        (replace(base, agent_tool_timeout_seconds=301), "AGENT_TOOL_TIMEOUT_SECONDS"),
        (replace(base, agent_run_timeout_seconds=0), "AGENT_RUN_TIMEOUT_SECONDS"),
        (replace(base, agent_run_timeout_seconds=1801), "AGENT_RUN_TIMEOUT_SECONDS"),
        (replace(base, agent_executor_lease_seconds=29), "AGENT_EXECUTOR_LEASE_SECONDS"),
        (replace(base, agent_executor_heartbeat_seconds=0), "AGENT_EXECUTOR_HEARTBEAT_SECONDS"),
        (replace(base, agent_executor_heartbeat_seconds=60), "AGENT_EXECUTOR_HEARTBEAT_SECONDS"),
        (replace(base, agent_event_poll_seconds=0.05), "AGENT_EVENT_POLL_SECONDS"),
        (replace(base, agent_event_poll_seconds=6), "AGENT_EVENT_POLL_SECONDS"),
        (replace(base, agent_external_agent_runs_per_minute=0), "AGENT_EXTERNAL_AGENT_RUNS_PER_MINUTE"),
        (replace(base, agent_external_consumer_runs_per_minute=0), "AGENT_EXTERNAL_CONSUMER_RUNS_PER_MINUTE"),
        (replace(base, workflow_sandbox_socket="relative.sock"), "WORKFLOW_SANDBOX_SOCKET"),
        (replace(base, workflow_sandbox_timeout_seconds=0.05), "WORKFLOW_SANDBOX_TIMEOUT_SECONDS"),
        (replace(base, workflow_sandbox_timeout_seconds=31), "WORKFLOW_SANDBOX_TIMEOUT_SECONDS"),
        (replace(base, jwt_expires_minutes=0), "JWT_EXPIRES_MINUTES"),
        (replace(base, refresh_token_expires_days=0), "REFRESH_TOKEN_EXPIRES_DAYS"),
    ]
    for settings_variant, message in cases:
        try:
            settings_variant.validate()
        except RuntimeError as exc:
            assert message in str(exc), (message, str(exc))
        else:
            raise AssertionError(f"expected RuntimeError containing {message!r}")


def test_settings_from_env() -> None:
    required = {
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "BOOTSTRAP_ADMIN_USERNAME": "env-admin",
        "BOOTSTRAP_ADMIN_EMAIL": "env-admin@app.local",
        "BOOTSTRAP_ADMIN_NAME": "Env Admin",
        "BOOTSTRAP_ADMIN_PASSWORD": "Env@12345.",
        "JWT_SECRET_KEY": "env-jwt",
        "MODEL_SECRET_KEY": "env-model",
        "KNOWLEDGE_STORAGE_DIR": "/tmp/env-storage",
        "QDRANT_URL": ":memory:",
        "CELERY_BROKER_URL": "redis://localhost:6379/0",
    }
    with patch.dict(
        os.environ,
        {
            **required,
            "CORS_ORIGINS": "https://a.example.com, https://b.example.com",
            "MCP_REQUEST_TIMEOUT_SECONDS": "45",
            "CELERY_TASK_ALWAYS_EAGER": "true",
            "MCP_ALLOW_PRIVATE_NETWORKS": "yes",
            "LOG_LEVEL": "debug",
            "AGENT_EVENT_POLL_SECONDS": "1.5",
            "AGENT_EXECUTOR_LEASE_SECONDS": "120",
            "AGENT_EXECUTOR_HEARTBEAT_SECONDS": "45",
        },
        clear=False,
    ):
        parsed = config_mod.Settings.from_env()
        assert parsed.bootstrap_admin_username == "env-admin"
        assert parsed.jwt_secret_key == "env-jwt"
        assert parsed.knowledge_storage_dir == Path("/tmp/env-storage")
        assert parsed.cors_origins == ("https://a.example.com", "https://b.example.com")
        assert parsed.mcp_request_timeout_seconds == 45.0
        assert parsed.celery_task_always_eager is True
        assert parsed.mcp_allow_private_networks is True
        assert parsed.log_level == "DEBUG"
        assert parsed.agent_event_poll_seconds == 1.5
        assert parsed.agent_executor_lease_seconds == 120
        assert parsed.agent_executor_heartbeat_seconds == 45

    with patch.dict(os.environ, {**required, "CELERY_TASK_ALWAYS_EAGER": "no"}, clear=False):
        parsed = config_mod.Settings.from_env(require_bootstrap=False)
        assert parsed.celery_task_always_eager is False


# ================================================================ security


def test_security_tokens() -> None:
    runtime_settings = _valid_settings()
    password_hash = hash_password("NexaFlow@12345.")
    assert verify_password("NexaFlow@12345.", password_hash)
    assert not verify_password("wrong", password_hash)

    token = create_access_token("user-42", runtime_settings)
    assert decode_access_token(token, runtime_settings) == "user-42"
    assert decode_access_token(token + "tampered", runtime_settings) is None
    assert decode_access_token("not-a-jwt", runtime_settings) is None
    wrong_secret = decode_access_token(token, replace(runtime_settings, jwt_secret_key="other"))
    assert wrong_secret is None

    expired_settings = replace(runtime_settings, jwt_expires_minutes=-5)
    expired_token = create_access_token("user-42", expired_settings)
    assert decode_access_token(expired_token, expired_settings) is None

    refresh = create_refresh_token()
    assert len(refresh) >= 32
    assert hash_refresh_token(refresh) == hash_refresh_token(refresh)
    assert len(hash_refresh_token(refresh)) == 64


# ================================================================ session


def test_session_configuration() -> None:
    original_engine = session_mod._engine
    original_factory = session_mod._session_factory
    try:
        session_mod.configure_database(replace(settings(), database_url="sqlite+aiosqlite:///:memory:"))
        assert session_mod._engine is not None
        assert session_mod._session_factory is not None
        assert isinstance(session_mod._engine.pool, StaticPool)

        try:
            session_mod.configure_database(
                replace(settings(), database_url="sqlite+aiosqlite:///:memory:"),
                worker_process=True,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for in-memory worker database")

        file_url = "sqlite+aiosqlite:////tmp/nexaflow-session-worker-test.db"
        session_mod.configure_database(
            replace(settings(), database_url=file_url),
            worker_process=True,
        )
        assert isinstance(session_mod._engine.pool, NullPool)
        Path("/tmp/nexaflow-session-worker-test.db").unlink(missing_ok=True)

        # lazy configuration paths
        session_mod._engine = None
        session_mod._session_factory = None
        factory = session_mod.get_session_factory()
        assert factory is not None
        engine = session_mod.get_engine()
        assert engine is not None

        # get_engine lazy path independently
        session_mod._engine = None
        session_mod._session_factory = None
        assert session_mod.get_engine() is not None
        assert session_mod.get_session_factory() is not None

        async def consume_db() -> None:
            async for session in session_mod.get_db():
                assert session is not None

        run(consume_db())
    finally:
        session_mod._engine = original_engine
        session_mod._session_factory = original_factory


# ================================================================ validation


def test_validation_normalizers() -> None:
    assert normalize_email("  USER@Example.COM ") == "user@example.com"
    expect_http_error(lambda: normalize_email("no-at-sign"), 422)
    expect_http_error(lambda: normalize_email("@start.com"), 422)
    expect_http_error(lambda: normalize_email("end@"), 422)
    assert normalize_username("  alice  ") == "alice"
    expect_http_error(lambda: normalize_username("   "), 422)
    assert normalize_name("  Alice Smith  ") == "Alice Smith"
    expect_http_error(lambda: normalize_name(""), 422)


# ================================================================ celery


def test_celery() -> None:
    assert celery_mod.worker_pool_for_platform("darwin") == "solo"
    assert celery_mod.worker_pool_for_platform("win32") == "solo"
    assert celery_mod.worker_pool_for_platform("linux") == "prefork"

    celery_mod.log_celery_task_failure(
        sender=SimpleNamespace(name="app.tasks.test_task"),
        task_id="task-1",
        exception=RuntimeError("boom"),
    )
    celery_mod.log_celery_task_failure(
        sender=None,
        task_id="task-2",
        exception=ValueError("oops"),
    )

    app = celery_mod.create_celery_app()
    assert app.conf.broker_url == settings().celery_broker_url
    assert app.conf.worker_pool in {"solo", "prefork"}
    beat = app.conf.beat_schedule
    assert set(beat) == {
        "recover-knowledge-storage-cleanups",
        "recover-upload-storage-cleanups",
        "recover-agent-runs",
    }
    assert beat["recover-agent-runs"]["schedule"] == 30.0
    assert app.conf.accept_content == ["json"]
    assert app.conf.task_acks_late is True


# ================================================================ tasks


def test_configure_task_worker() -> None:
    import app.tasks as tasks_module

    original_pid = tasks_module._configured_process_id
    original_configure = tasks_module.configure_database
    calls = []

    def fake_configure_database(settings, *, worker_process=False):
        calls.append((settings, worker_process))

    tasks_module.configure_database = fake_configure_database
    try:
        tasks_module._configured_process_id = None
        tasks_module.configure_task_worker(settings())
        assert len(calls) == 1
        assert calls[0][1] is True
        assert tasks_module._configured_process_id == os.getpid()

        tasks_module.configure_task_worker(settings())
        assert len(calls) == 1  # idempotent within the process
    finally:
        tasks_module._configured_process_id = original_pid
        tasks_module.configure_database = original_configure


# ================================================================ api/deps


def test_deps() -> None:
    runtime_settings = settings()
    db = AsyncMock()
    active_user = User(id="u1", username="alice", name="Alice", is_global_admin=False, must_change_password=False, is_active=True)
    admin_user = User(id="u1", username="alice", name="Alice", is_global_admin=True, must_change_password=False, is_active=True)
    pending_user = User(id="u1", username="alice", name="Alice", must_change_password=True, is_active=True)

    # no credentials
    expect_http_error(lambda: run(deps_mod.get_current_user(None, runtime_settings, db)), 401)

    credentials = SimpleNamespace(credentials="token-1")
    with patch.object(deps_mod, "decode_access_token", return_value=None):
        expect_http_error(lambda: run(deps_mod.get_current_user(credentials, runtime_settings, db)), 401)

    with patch.object(deps_mod, "decode_access_token", return_value="u1"), patch.object(
        deps_mod.user_repository, "get_user_by_id", new=AsyncMock(return_value=None)
    ):
        expect_http_error(lambda: run(deps_mod.get_current_user(credentials, runtime_settings, db)), 401)

    inactive = User(id="u1", username="alice", name="Alice", is_active=False)
    with patch.object(deps_mod, "decode_access_token", return_value="u1"), patch.object(
        deps_mod.user_repository, "get_user_by_id", new=AsyncMock(return_value=inactive)
    ):
        expect_http_error(lambda: run(deps_mod.get_current_user(credentials, runtime_settings, db)), 401)

    with patch.object(deps_mod, "decode_access_token", return_value="u1"), patch.object(
        deps_mod.user_repository, "get_user_by_id", new=AsyncMock(return_value=active_user)
    ):
        assert run(deps_mod.get_current_user(credentials, runtime_settings, db)) is active_user

    expect_http_error(lambda: run(deps_mod.require_password_changed(pending_user)), 403)
    assert run(deps_mod.require_password_changed(active_user)) is active_user

    expect_http_error(lambda: run(deps_mod.require_global_admin(active_user)), 403)
    assert run(deps_mod.require_global_admin(admin_user)) is admin_user

    context_admin = SimpleNamespace(membership_role="admin")
    context_member = SimpleNamespace(membership_role="member")
    assert deps_mod.require_context_role(context_admin, {"admin"}) is context_admin
    expect_http_error(lambda: deps_mod.require_context_role(context_member, {"admin"}), 403)

    path_dependency = deps_mod.require_workspace_path_role({"admin"})
    assert run(path_dependency(context_admin)) is context_admin
    expect_http_error(lambda: run(path_dependency(context_member)), 403)

    user_context = SimpleNamespace(membership_role="member", user=SimpleNamespace(id="u1"))
    assert run(deps_mod.require_team_admin_or_workspace_admin("team-1", context_admin, db)) is context_admin
    with patch.object(
        deps_mod.team_repository,
        "get_team_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="admin")),
    ):
        assert run(deps_mod.require_team_admin_or_workspace_admin("team-1", user_context, db)) is user_context
    with patch.object(deps_mod.team_repository, "get_team_membership", new=AsyncMock(return_value=None)):
        expect_http_error(lambda: run(deps_mod.require_team_admin_or_workspace_admin("team-1", user_context, db)), 403)

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=runtime_settings)))
    assert deps_mod.get_settings(request) is runtime_settings

    workspace_context = SimpleNamespace(membership_role="admin", user=SimpleNamespace(id="u1"))
    with patch.object(
        deps_mod, "build_workspace_context", new=AsyncMock(return_value=workspace_context)
    ):
        assert (
            run(deps_mod.get_workspace_context_from_path("ws-1", active_user, db))
            is workspace_context
        )


# ================================================================ ports


def test_ports_mcp() -> None:
    assert ports_mcp.MAX_MCP_TOOL_PAGES > 0
    assert isinstance(ports_mcp.build_mcp_client(settings()), MultiTransportMcpClient)
    assert ports_mcp.normalize_mcp_url("https://example.com/mcp/") == "https://example.com/mcp"

    fake = MagicMock()
    fake.discover_mcp_tools = AsyncMock(return_value=McpDiscovery(tools=[]))
    fake.call_mcp_tool = AsyncMock(return_value=("{}", False))
    connection = McpConnection(transport="streamable_http", url="https://example.com/mcp")
    with patch.object(ports_mcp, "build_mcp_client", return_value=fake):
        discovery = run(ports_mcp.discover_mcp_tools(connection, settings()))
        assert discovery.tools == []
        content, is_error = run(ports_mcp.call_mcp_tool(connection, settings(), "echo", {}, "idem"))
        assert (content, is_error) == ("{}", False)
        fake.call_mcp_tool.assert_awaited_once_with(connection, "echo", {}, "idem")


def test_ports_model_registry_build() -> None:
    assert ports_model_registry.build_model_registry() is llm_registry_repository


# ================================================================ tools/services


def _mcp_tool_dict(name="echo", description="Echo tool", schema=None):
    return {
        "name": name,
        "description": description,
        "input_schema": schema or {"type": "object", "properties": {}},
        "annotations": None,
    }


def test_mcp_tool_hash_and_policy_mode() -> None:
    tool = McpTool(name="echo", description="d", input_schema={"type": "object"})
    hash_one = tools_services.mcp_tool_definition_hash(tool)
    assert hash_one == tools_services.mcp_tool_definition_hash(
        McpTool(name="echo", description="d", input_schema={"type": "object"})
    )
    other = McpTool(name="echo", description="different", input_schema={"type": "object"})
    assert hash_one != tools_services.mcp_tool_definition_hash(other)

    annotated = McpTool(
        name="echo",
        description="d",
        input_schema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=False),
    )
    assert tools_services.mcp_tool_definition_hash(annotated) != hash_one

    policy = McpToolPolicy(
        workspace_id="ws-1",
        mcp_server_id="srv-1",
        tool_name="echo",
        definition_hash=hash_one,
        mode="read_only",
    )
    assert tools_services.effective_mcp_tool_policy_mode(tool, policy) == "read_only"
    mismatched = McpToolPolicy(
        workspace_id="ws-1",
        mcp_server_id="srv-1",
        tool_name="echo",
        definition_hash="stale",
        mode="read_only",
    )
    assert tools_services.effective_mcp_tool_policy_mode(tool, mismatched) == "approval_required"
    assert tools_services.effective_mcp_tool_policy_mode(tool, None) == "approval_required"


def test_mcp_server_to_response() -> None:
    server = McpServer(
        id="srv-1",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://example.com/mcp",
        tools=[_mcp_tool_dict()],
        status="active",
        bearer_token_ciphertext=None,
        created_by_user_id="u1",
    )
    definition = tools_services._mcp_tool_definition(server.tools[0])
    expected_hash = tools_services.mcp_tool_definition_hash(definition)
    policy = McpToolPolicy(
        id="pol-1",
        workspace_id="ws-1",
        mcp_server_id="srv-1",
        tool_name="echo",
        definition_hash=expected_hash,
        mode="disabled",
    )
    response = tools_services.mcp_server_to_response(server, [policy])
    assert response.id == "srv-1"
    assert response.transport == "streamable_http"
    assert response.has_bearer_token is False
    assert response.tools[0].definition_hash == expected_hash
    assert response.tools[0].policy_mode == "disabled"

    response = tools_services.mcp_server_to_response(server)
    assert response.tools[0].policy_mode == "approval_required"


def test_bearer_token_and_stdio_config() -> None:
    runtime_settings = settings()
    plain = McpServer(id="s1", workspace_id="ws-1", transport="streamable_http", url="https://x")
    assert tools_services.bearer_token(plain, runtime_settings) is None
    assert tools_services.stdio_config(plain, runtime_settings) is None

    secret_server = McpServer(
        id="s2",
        workspace_id="ws-1",
        transport="streamable_http",
        url="https://x",
        bearer_token_ciphertext=encrypt_secret("tok-1234", runtime_settings.model_secret_key),
    )
    assert tools_services.bearer_token(secret_server, runtime_settings) == "tok-1234"

    stdio_server = McpServer(
        id="s3",
        workspace_id="ws-1",
        transport="stdio",
        stdio_command="/bin/echo",
        stdio_config_ciphertext=encrypt_secret(
            json.dumps({"command": "/bin/echo", "args": ["hi"], "cwd": None, "env": {}}),
            runtime_settings.model_secret_key,
        ),
    )
    config = tools_services.stdio_config(stdio_server, runtime_settings)
    assert config.command == "/bin/echo"
    assert config.args == ("hi",)

    corrupt_server = McpServer(
        id="s4",
        workspace_id="ws-1",
        transport="stdio",
        stdio_config_ciphertext=encrypt_secret("not-json", runtime_settings.model_secret_key),
    )
    assert isinstance(
        expect_error(lambda: tools_services.stdio_config(corrupt_server, runtime_settings), McpClientError),
        McpClientError,
    )

    connection = tools_services.mcp_server_connection(secret_server, runtime_settings)
    assert connection.bearer_token == "tok-1234"
    stdio_connection = tools_services.mcp_server_connection(stdio_server, runtime_settings)
    assert stdio_connection.stdio_config.command == "/bin/echo"


def test_tools_get_and_list_servers() -> None:
    server = McpServer(
        id="srv-1",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://example.com/mcp",
        tools=[_mcp_tool_dict()],
        status="active",
        created_by_user_id="u1",
    )
    db = AsyncMock()

    with patch.object(mcp_repo, "list_mcp_tool_policies", new=AsyncMock(return_value=[])), patch.object(
        mcp_repo, "list_mcp_servers", new=AsyncMock(return_value=[server])
    ):
        responses = run(tools_services.list_mcp_servers(db, "ws-1"))
        assert [item.id for item in responses] == ["srv-1"]

    with patch.object(mcp_repo, "get_mcp_server_by_id", new=AsyncMock(return_value=server)):
        assert run(tools_services.get_mcp_server(db, "ws-1", "srv-1")) is server

    with patch.object(mcp_repo, "get_mcp_server_by_id", new=AsyncMock(return_value=None)):
        expect_http_error(lambda: run(tools_services.get_mcp_server(db, "ws-1", "srv-1")), 404)

    cross_ws = McpServer(id="srv-1", workspace_id="other-ws", transport="streamable_http", url="https://x")
    with patch.object(mcp_repo, "get_mcp_server_by_id", new=AsyncMock(return_value=cross_ws)):
        expect_http_error(lambda: run(tools_services.get_mcp_server(db, "ws-1", "srv-1")), 404)


def test_create_mcp_server() -> None:
    runtime_settings = settings()
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")

    http_payload = McpServerCreateRequest(
        name="My Server",
        transport="streamable_http",
        url="https://example.com/mcp",
        bearer_token="tok-abc-1234",
    )
    created = McpServer(
        id="srv-new",
        workspace_id="ws-1",
        name="My Server",
        transport="streamable_http",
        url="https://example.com/mcp",
        tools=[_mcp_tool_dict()],
        status="active",
        created_by_user_id="u1",
    )
    with patch.object(
        tools_services, "discover_mcp_tools", new=AsyncMock(return_value=McpDiscovery(tools=[_mcp_tool_dict()]))
    ), patch.object(
        mcp_repo, "create_mcp_server", new=AsyncMock(side_effect=lambda db, entity: entity)
    ), patch.object(
        mcp_repo, "refresh_mcp_server", new=AsyncMock(side_effect=lambda db, entity: entity)
    ), patch.object(
        mcp_repo, "list_mcp_tool_policies", new=AsyncMock(return_value=[])
    ), patch.object(
        tools_services, "record_audit_log", return_value=None
    ):
        response = run(tools_services.create_mcp_server(db, "ws-1", http_payload, actor, runtime_settings))
        assert response.id
        assert response.url == "https://example.com/mcp"
        assert response.has_bearer_token is True
        assert response.bearer_token_hint == "****1234"
        assert db.commit.await_count == 1

    # discovery failure -> 400
    with patch.object(tools_services, "discover_mcp_tools", new=AsyncMock(side_effect=McpClientError("boom"))):
        expect_http_error(
            lambda: run(tools_services.create_mcp_server(db, "ws-1", http_payload, actor, runtime_settings)),
            400,
        )

    # stdio transport
    stdio_payload = McpServerCreateRequest(
        name="Stdio Server",
        transport="stdio",
        stdio_config={
            "command": "/bin/echo",
            "args": ["-n", "hi"],
            "cwd": None,
            "env": {"X": "1"},
        },
    )
    stdio_created = McpServer(
        id="srv-stdio",
        workspace_id="ws-1",
        name="Stdio Server",
        transport="stdio",
        stdio_command="/bin/echo",
        tools=[_mcp_tool_dict("echo")],
        status="active",
        created_by_user_id="u1",
    )
    with patch.object(
        tools_services, "discover_mcp_tools", new=AsyncMock(return_value=McpDiscovery(tools=[_mcp_tool_dict("echo")]))
    ), patch.object(mcp_repo, "create_mcp_server", new=AsyncMock(return_value=stdio_created)), patch.object(
        mcp_repo, "refresh_mcp_server", new=AsyncMock(return_value=stdio_created)
    ), patch.object(
        mcp_repo, "list_mcp_tool_policies", new=AsyncMock(return_value=[])
    ), patch.object(
        tools_services, "record_audit_log", return_value=None
    ):
        response = run(tools_services.create_mcp_server(db, "ws-1", stdio_payload, actor, runtime_settings))
        assert response.transport == "stdio"
        assert response.stdio_command == "/bin/echo"

    # IntegrityError -> 409
    with patch.object(
        tools_services, "discover_mcp_tools", new=AsyncMock(return_value=McpDiscovery(tools=[]))
    ), patch.object(mcp_repo, "create_mcp_server", new=AsyncMock(return_value=created)), patch.object(
        tools_services, "record_audit_log", return_value=None
    ):
        db.commit.side_effect = IntegrityError("dup", {}, Exception())
        try:
            expect_http_error(
                lambda: run(tools_services.create_mcp_server(db, "ws-1", http_payload, actor, runtime_settings)),
                409,
            )
        finally:
            db.commit.side_effect = None


def test_refresh_mcp_server() -> None:
    runtime_settings = settings()
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    server = McpServer(
        id="srv-1",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://example.com/mcp",
        tools=[_mcp_tool_dict()],
        status="active",
        created_by_user_id="u1",
    )

    with patch.object(
        tools_services, "discover_mcp_tools", new=AsyncMock(return_value=McpDiscovery(tools=[_mcp_tool_dict("new-tool")]))
    ), patch.object(mcp_repo, "save_mcp_server", new=AsyncMock()), patch.object(
        mcp_repo, "refresh_mcp_server", new=AsyncMock(return_value=server)
    ), patch.object(
        mcp_repo, "list_mcp_tool_policies", new=AsyncMock(return_value=[])
    ), patch.object(
        tools_services, "record_audit_log", return_value=None
    ):
        response = run(tools_services.refresh_mcp_server(db, server, actor, runtime_settings))
        assert response.id == "srv-1"
        assert server.tools == [_mcp_tool_dict("new-tool")]
        assert server.last_error is None

    # discovery failure -> last_error recorded, 400
    failing = McpServer(
        id="srv-1",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://example.com/mcp",
        tools=[],
        status="active",
        created_by_user_id="u1",
    )
    with patch.object(tools_services, "discover_mcp_tools", new=AsyncMock(side_effect=McpClientError("offline"))), patch.object(
        mcp_repo, "save_mcp_server", new=AsyncMock()
    ), patch.object(tools_services, "record_audit_log", return_value=None):
        expect_http_error(
            lambda: run(tools_services.refresh_mcp_server(db, failing, actor, runtime_settings)),
            400,
        )
        assert failing.last_error == "offline"


def test_delete_mcp_server() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    server = McpServer(id="srv-1", workspace_id="ws-1", name="Server", transport="streamable_http", url="https://x")
    with patch.object(mcp_repo, "delete_mcp_server", new=AsyncMock()), patch.object(
        tools_services, "record_audit_log", return_value=None
    ):
        run(tools_services.delete_mcp_server(db, server, actor))
        assert db.commit.await_count == 1


def test_resolve_mcp_tools() -> None:
    db = AsyncMock()
    references = [
        {"server_id": "s1", "tool_name": "echo"},
        {"server_id": "s1", "tool_name": "wait"},
    ]
    server = McpServer(
        id="s1",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://x",
        tools=[_mcp_tool_dict("echo"), _mcp_tool_dict("wait")],
        status="active",
        created_by_user_id="u1",
    )
    with patch.object(mcp_repo, "list_mcp_servers_by_ids", new=AsyncMock(return_value=[server])):
        resolved = run(tools_services.resolve_mcp_tools(db, "ws-1", references, strict=True))
        assert [item.definition.name for item in resolved] == ["echo", "wait"]
        assert resolved[0].server is server

    # duplicate pair
    duplicates = [{"server_id": "s1", "tool_name": "echo"}, {"server_id": "s1", "tool_name": "echo"}]
    expect_http_error(lambda: run(tools_services.resolve_mcp_tools(db, "ws-1", duplicates, strict=True)), 422)

    # missing tool strict / non-strict
    missing_tool = [{"server_id": "s1", "tool_name": "nope"}]
    with patch.object(mcp_repo, "list_mcp_servers_by_ids", new=AsyncMock(return_value=[server])):
        expect_http_error(lambda: run(tools_services.resolve_mcp_tools(db, "ws-1", missing_tool, strict=True)), 422)
        assert run(tools_services.resolve_mcp_tools(db, "ws-1", missing_tool, strict=False)) == []

    # missing server strict / non-strict
    missing_server = [{"server_id": "missing", "tool_name": "echo"}]
    with patch.object(mcp_repo, "list_mcp_servers_by_ids", new=AsyncMock(return_value=[server])):
        expect_http_error(lambda: run(tools_services.resolve_mcp_tools(db, "ws-1", missing_server, strict=True)), 422)
        assert run(tools_services.resolve_mcp_tools(db, "ws-1", missing_server, strict=False)) == []

    # inactive server
    inactive = McpServer(
        id="s1",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://x",
        tools=[_mcp_tool_dict("echo")],
        status="disabled",
        created_by_user_id="u1",
    )
    with patch.object(mcp_repo, "list_mcp_servers_by_ids", new=AsyncMock(return_value=[inactive])):
        expect_http_error(lambda: run(tools_services.resolve_mcp_tools(db, "ws-1", references[:1], strict=True)), 422)
        assert run(tools_services.resolve_mcp_tools(db, "ws-1", references[:1], strict=False)) == []


def test_mcp_tool_policy_services() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    server = McpServer(
        id="srv-1",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://x",
        tools=[_mcp_tool_dict("echo")],
        status="active",
        created_by_user_id="u1",
    )

    policy = McpToolPolicy(
        id="pol-1",
        workspace_id="ws-1",
        mcp_server_id="srv-1",
        tool_name="echo",
        definition_hash="h",
        mode="read_only",
    )
    with patch.object(mcp_repo, "get_mcp_tool_policy", new=AsyncMock(return_value=policy)):
        assert run(tools_services.get_mcp_tool_policy(db, "ws-1", "srv-1", "echo")) is policy

    saved = McpToolPolicy(
        id="pol-2",
        workspace_id="ws-1",
        mcp_server_id="srv-1",
        tool_name="echo",
        definition_hash=tools_services.mcp_tool_definition_hash(tools_services._mcp_tool_definition(_mcp_tool_dict())),
        mode="disabled",
        reviewed_by_user_id="u1",
        reviewed_at=utc_now(),
    )
    with patch.object(mcp_repo, "save_mcp_tool_policy", new=AsyncMock(return_value=saved)), patch.object(
        tools_services, "record_audit_log", return_value=None
    ):
        result = run(tools_services.set_mcp_tool_policy(db, server, "echo", "disabled", actor))
        assert result.mode == "disabled"
        assert result.reviewed_by_user_id == "u1"

    no_tool_server = McpServer(
        id="srv-2",
        workspace_id="ws-1",
        name="Server",
        transport="streamable_http",
        url="https://x",
        tools=[_mcp_tool_dict("other")],
        status="active",
        created_by_user_id="u1",
    )
    expect_http_error(lambda: run(tools_services.set_mcp_tool_policy(db, no_tool_server, "echo", "read_only", actor)), 404)


# ================================================================ teams/services


def _team(**overrides) -> Team:
    fields = dict(
        id="team-1",
        workspace_id="ws-1",
        name="Team",
        description="",
        slug="team-slug",
        status="active",
    )
    fields.update(overrides)
    return Team(**fields)


def _team_membership(**overrides) -> TeamMembership:
    fields = dict(
        id="m1",
        workspace_id="ws-1",
        team_id="team-1",
        user_id="u1",
        role="member",
    )
    fields.update(overrides)
    return TeamMembership(**fields)


def test_team_services_basics() -> None:
    team = _team()
    response = teams_services.team_to_response(team)
    assert response.id == "team-1"
    assert response.status == "active"

    user = User(id="u1", username="alice", name="Alice")
    membership = _team_membership(role="admin")
    member_response = teams_services.team_member_to_response(membership, user)
    assert member_response.role == "admin"
    assert member_response.user.username == "alice"

    teams_services.validate_team_member_role("member")
    teams_services.validate_team_member_role("admin")
    expect_http_error(lambda: teams_services.validate_team_member_role("owner"), 422)

    teams_services.require_manages_team_admins(True)
    expect_http_error(lambda: teams_services.require_manages_team_admins(False), 403)

    db = AsyncMock()
    with patch.object(teams_services.team_repository, "list_teams", new=AsyncMock(return_value=[team])):
        assert [item.id for item in run(teams_services.list_teams(db, "ws-1"))] == ["team-1"]

    with patch.object(teams_services.team_repository, "get_team_by_id", new=AsyncMock(return_value=team)):
        assert run(teams_services.get_team(db, "ws-1", "team-1")) is team

    with patch.object(teams_services.team_repository, "get_team_by_id", new=AsyncMock(return_value=None)):
        expect_http_error(lambda: run(teams_services.get_team(db, "ws-1", "team-1")), 404)

    cross = _team(workspace_id="other-ws")
    with patch.object(teams_services.team_repository, "get_team_by_id", new=AsyncMock(return_value=cross)):
        expect_http_error(lambda: run(teams_services.get_team(db, "ws-1", "team-1")), 404)

    # actor_manages_team_admins
    actor = User(id="u1", username="alice", name="Alice", is_global_admin=True)
    assert run(teams_services.actor_manages_team_admins(db, "ws-1", actor)) is True
    member_actor = User(id="u2", username="bob", name="Bob", is_global_admin=False)
    with patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="admin")),
    ):
        assert run(teams_services.actor_manages_team_admins(db, "ws-1", member_actor)) is True
    with patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="member")),
    ):
        assert run(teams_services.actor_manages_team_admins(db, "ws-1", member_actor)) is False
    with patch.object(
        teams_services.workspace_repository, "get_workspace_membership", new=AsyncMock(return_value=None)
    ):
        assert run(teams_services.actor_manages_team_admins(db, "ws-1", member_actor)) is False

    # ensure_not_last_team_admin
    admin_membership = _team_membership(role="admin")
    run(teams_services.ensure_not_last_team_admin(db, _team_membership(role="member")))
    with patch.object(teams_services.team_repository, "count_team_admins", new=AsyncMock(return_value=1)):
        expect_http_error(
            lambda: run(teams_services.ensure_not_last_team_admin(db, admin_membership)),
            400,
        )
    with patch.object(teams_services.team_repository, "count_team_admins", new=AsyncMock(return_value=2)):
        run(teams_services.ensure_not_last_team_admin(db, admin_membership))

    # list_team_members
    rows = [(_team_membership(), user)]
    with patch.object(teams_services.team_repository, "list_team_member_rows", new=AsyncMock(return_value=rows)):
        responses = run(teams_services.list_team_members(db, team))
        assert responses[0].role == "member"


def test_create_team() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    payload = TeamCreateRequest(name="Applied AI", description="desc", admin_user_id="u9")
    admin = User(id="u9", username="admin", name="Admin")
    team = _team(id="team-new", name="Applied AI", description="desc")

    with patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=admin)
    ), patch.object(teams_services.team_repository, "create_team", new=AsyncMock(return_value=team)), patch.object(
        teams_services.team_repository,
        "create_team_membership",
        new=AsyncMock(return_value=_team_membership(role="admin")),
    ), patch.object(
        teams_services.team_repository, "refresh_team", new=AsyncMock(return_value=team)
    ), patch.object(
        teams_services, "record_audit_log", return_value=None
    ):
        response = run(teams_services.create_team(db, "ws-1", payload, actor))
        assert response.name == "Applied AI"
        assert db.commit.await_count == 1

    with patch.object(teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=None)):
        expect_http_error(lambda: run(teams_services.create_team(db, "ws-1", payload, actor)), 404)

    with patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=admin)
    ), patch.object(teams_services.team_repository, "create_team", new=AsyncMock(return_value=team)), patch.object(
        teams_services.team_repository, "create_team_membership", new=AsyncMock(return_value=_team_membership())
    ), patch.object(teams_services, "record_audit_log", return_value=None):
        db.commit.side_effect = IntegrityError("dup", {}, Exception())
        try:
            expect_http_error(lambda: run(teams_services.create_team(db, "ws-1", payload, actor)), 409)
        finally:
            db.commit.side_effect = None


def test_update_team() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    team = _team()

    with patch.object(teams_services.team_repository, "save_team", new=AsyncMock(return_value=team)), patch.object(
        teams_services.team_repository, "refresh_team", new=AsyncMock(return_value=team)
    ), patch.object(teams_services, "record_audit_log", return_value=None) as audit:
        updated = run(
            teams_services.update_team(
                db,
                team,
                TeamUpdateRequest(name="Renamed", description="new desc"),
                actor,
            )
        )
        assert updated.name == "Renamed"
        assert team.description == "new desc"

    with patch.object(teams_services.team_repository, "save_team", new=AsyncMock(return_value=team)), patch.object(
        teams_services.team_repository, "refresh_team", new=AsyncMock(return_value=team)
    ), patch.object(teams_services, "record_audit_log", return_value=None) as audit:
        run(teams_services.update_team(db, team, TeamUpdateRequest(status="archived"), actor))
        audit.assert_called_once()
        assert audit.call_args[0][2] == "team.archive"

    with patch.object(teams_services.team_repository, "save_team", new=AsyncMock(return_value=team)), patch.object(
        teams_services.team_repository, "refresh_team", new=AsyncMock(return_value=team)
    ), patch.object(teams_services, "record_audit_log", return_value=None) as audit:
        run(teams_services.update_team(db, team, TeamUpdateRequest(status="active"), actor))
        assert audit.call_args[0][2] == "team.restore"

    expect_http_error(
        lambda: run(
            teams_services.update_team(
                db,
                team,
                TeamUpdateRequest(status="bogus"),
                actor,
            )
        ),
        422,
    )

    with patch.object(teams_services.team_repository, "save_team", new=AsyncMock(return_value=team)), patch.object(
        teams_services, "record_audit_log", return_value=None
    ):
        db.commit.side_effect = IntegrityError("dup", {}, Exception())
        try:
            expect_http_error(
                lambda: run(
                    teams_services.update_team(
                        db,
                        team,
                        TeamUpdateRequest(name="Other"),
                        actor,
                    )
                ),
                409,
            )
        finally:
            db.commit.side_effect = None


def test_delete_team_permanently() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    team = _team()
    with patch.object(teams_services.team_repository, "delete_team_graph", new=AsyncMock()), patch.object(
        teams_services, "record_audit_log", return_value=None
    ):
        run(teams_services.delete_team_permanently(db, team, actor))
        assert db.commit.await_count == 1


def test_add_team_member() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    team = _team()
    member = User(id="u2", username="bob", name="Bob")
    membership = _team_membership(user_id="u2", role="member")

    expect_http_error(lambda: run(teams_services.add_team_member(db, team, "u2", "owner", actor)), 422)

    # admin role without workspace admin -> 403
    with patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="member")),
    ):
        expect_http_error(lambda: run(teams_services.add_team_member(db, team, "u2", "admin", actor)), 403)

    # user not in workspace -> 404
    with patch.object(teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=None)):
        expect_http_error(lambda: run(teams_services.add_team_member(db, team, "u2", "member", actor)), 404)

    with patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=member)
    ), patch.object(
        teams_services.team_repository, "create_team_membership", new=AsyncMock(return_value=membership)
    ), patch.object(
        teams_services, "record_audit_log", return_value=None
    ):
        response = run(teams_services.add_team_member(db, team, "u2", "member", actor))
        assert response.role == "member"

    with patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=member)
    ), patch.object(
        teams_services.team_repository, "create_team_membership", new=AsyncMock(return_value=membership)
    ), patch.object(teams_services, "record_audit_log", return_value=None):
        db.commit.side_effect = IntegrityError("dup", {}, Exception())
        try:
            expect_http_error(lambda: run(teams_services.add_team_member(db, team, "u2", "member", actor)), 409)
        finally:
            db.commit.side_effect = None


def test_update_team_member_role() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    team = _team()
    member = User(id="u2", username="bob", name="Bob")
    membership = _team_membership(user_id="u2", role="member")
    saved = _team_membership(user_id="u2", role="admin")

    expect_http_error(
        lambda: run(teams_services.update_team_member_role(db, team, "u2", "owner", actor)),
        422,
    )

    with patch.object(teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=None)):
        expect_http_error(
            lambda: run(teams_services.update_team_member_role(db, team, "u2", "member", actor)),
            404,
        )

    # promoting to admin without workspace admin -> 403
    with patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=membership)
    ), patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="member")),
    ):
        expect_http_error(
            lambda: run(teams_services.update_team_member_role(db, team, "u2", "admin", actor)),
            403,
        )

    # demoting the last admin -> 400
    admin_membership = _team_membership(user_id="u2", role="admin")
    with patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=admin_membership)
    ), patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="admin")),
    ), patch.object(teams_services.team_repository, "count_team_admins", new=AsyncMock(return_value=1)):
        expect_http_error(
            lambda: run(teams_services.update_team_member_role(db, team, "u2", "member", actor)),
            400,
        )

    # member not found in workspace -> 404
    with patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=membership)
    ), patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=None)
    ):
        expect_http_error(
            lambda: run(teams_services.update_team_member_role(db, team, "u2", "member", actor)),
            404,
        )

    # success: promote member -> admin
    with patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=membership)
    ), patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="admin")),
    ), patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=member)
    ), patch.object(
        teams_services.team_repository, "save_team_membership", new=AsyncMock(return_value=saved)
    ), patch.object(
        teams_services, "record_audit_log", return_value=None
    ):
        response = run(teams_services.update_team_member_role(db, team, "u2", "admin", actor))
        assert response.role == "admin"

    # success: member -> member (no admin checks, count_team_admins untouched)
    member_membership = _team_membership(user_id="u2", role="member")
    with patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=member_membership)
    ), patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=member)
    ), patch.object(
        teams_services.team_repository, "save_team_membership", new=AsyncMock(return_value=member_membership)
    ), patch.object(
        teams_services, "record_audit_log", return_value=None
    ):
        response = run(teams_services.update_team_member_role(db, team, "u2", "member", actor))
        assert response.role == "member"


def test_remove_team_member() -> None:
    db = AsyncMock()
    actor = User(id="u1", username="alice", name="Alice")
    team = _team()
    member = User(id="u2", username="bob", name="Bob")
    membership = _team_membership(user_id="u2", role="member")

    with patch.object(teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=None)):
        expect_http_error(lambda: run(teams_services.remove_team_member(db, team, "u2", actor)), 404)

    admin_membership = _team_membership(user_id="u2", role="admin")
    with patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=admin_membership)
    ), patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="member")),
    ):
        expect_http_error(lambda: run(teams_services.remove_team_member(db, team, "u2", actor)), 403)

    with patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=admin_membership)
    ), patch.object(
        teams_services.workspace_repository,
        "get_workspace_membership",
        new=AsyncMock(return_value=SimpleNamespace(role="admin")),
    ), patch.object(teams_services.team_repository, "count_team_admins", new=AsyncMock(return_value=1)):
        expect_http_error(lambda: run(teams_services.remove_team_member(db, team, "u2", actor)), 400)

    with patch.object(
        teams_services.team_repository, "get_active_workspace_user", new=AsyncMock(return_value=member)
    ), patch.object(
        teams_services.team_repository, "get_team_membership", new=AsyncMock(return_value=membership)
    ), patch.object(teams_services.team_repository, "delete_team_membership", new=AsyncMock(return_value=1)), patch.object(
        teams_services, "record_audit_log", return_value=None
    ):
        run(teams_services.remove_team_member(db, team, "u2", actor))
        assert db.commit.await_count == 1


# ================================================================ mapping


def test_mapping_refresh_entity_missing_row() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    entity = Team(id="missing", name="x")
    result = run(mapping_repo.refresh_entity(db, TeamOrm, Team, entity))
    assert result is entity


# ================================================================ DB-backed section


def _make_model_entity(workspace_id: str, created_by: str, name: str = "DeepSeek Chat") -> RegisteredModel:
    runtime_settings = settings()
    return RegisteredModel(
        workspace_id=workspace_id,
        name=name,
        provider="model_deepseek_provider",
        provider_type="deepseek",
        api_base="https://api.deepseek.com",
        api_key_ciphertext=llm_credentials.encrypt_credential_secrets(
            {"api_key": "sk-db-test-1234"}, runtime_settings.model_secret_key
        ),
        credential_config={"api_base": "https://api.deepseek.com"},
        credential_secret_hints={"api_key": "****1234"},
        model_type="LLM",
        model_name="deepseek-chat",
        status="active",
        meta={},
        created_by_user_id=created_by,
    )


async def db_seed_tests() -> None:
    runtime_settings = settings()
    async with get_session_factory()() as db:
        await seed_mod.seed_bootstrap_admin(db, runtime_settings)
        count = await db.scalar(
            select(func.count()).select_from(UserOrm).where(UserOrm.username == "admin")
        )
        assert count == 1

        # existing admin is kept and re-marked global admin
        admin = await db.scalar(select(UserOrm).where(UserOrm.username == "admin"))
        assert admin is not None
        admin.is_global_admin = False
        await db.commit()
        await seed_mod.seed_bootstrap_admin(db, runtime_settings)
        await db.refresh(admin)
        assert admin.is_global_admin is True

        custom = replace(
            runtime_settings,
            bootstrap_admin_username="seed-custom",
            bootstrap_admin_email="seed-custom@app.local",
            bootstrap_admin_name="Seed Custom",
            bootstrap_admin_password="Seed@12345.",
        )
        await seed_mod.seed_bootstrap_admin(db, custom)
        await seed_mod.seed_bootstrap_admin(db, custom)  # idempotent
        count = await db.scalar(
            select(func.count()).select_from(UserOrm).where(UserOrm.username == "seed-custom")
        )
        assert count == 1
        created = await db.scalar(select(UserOrm).where(UserOrm.username == "seed-custom"))
        assert created.must_change_password is True
        assert verify_password("Seed@12345.", created.password_hash)


async def db_registry_repository_tests(workspace_id: str, created_by: str) -> None:
    async with get_session_factory()() as db:
        model_a = _make_model_entity(workspace_id, created_by, name="Alpha Model")
        model_b = _make_model_entity(workspace_id, created_by, name="Beta Model")
        db.add_all([model_a, model_b])
        await db.commit()
        await db.refresh(model_a)
        await db.refresh(model_b)

        listed = await llm_registry_repository.list_registered_models(db, workspace_id)
        assert {item.id for item in listed} == {model_a.id, model_b.id}
        paged = await llm_registry_repository.list_registered_models(db, workspace_id, limit=1, offset=1)
        assert len(paged) == 1
        assert await llm_registry_repository.get_registered_model_by_id(db, model_a.id) is not None
        assert await llm_registry_repository.get_registered_model_by_id(db, "missing") is None
        found = await llm_registry_repository.find_registered_model_id_by_name(db, workspace_id, "Alpha Model")
        assert found == model_a.id
        excluded = await llm_registry_repository.find_registered_model_id_by_name(
            db, workspace_id, "Alpha Model", excluded_model_id=model_a.id
        )
        assert excluded is None
        other_ws = await llm_registry_repository.find_registered_model_id_by_name(db, "other-ws", "Alpha Model")
        assert other_ws is None

        await llm_registry_repository.delete_registered_model_by_id(db, model_b.id)
        await db.commit()
        assert await llm_registry_repository.get_registered_model_by_id(db, model_b.id) is None

        # ports delegate to the same repository
        listed_again = await ports_model_registry.list_registered_models(db, workspace_id)
        assert len(listed_again) == 1
        assert await ports_model_registry.get_registered_model_by_id(db, model_a.id) is not None
        assert (
            await ports_model_registry.find_registered_model_id_by_name(db, workspace_id, "Alpha Model")
            == model_a.id
        )
        await ports_model_registry.delete_registered_models_in_workspace(db, workspace_id)
        await db.commit()
        remaining = await llm_registry_repository.list_registered_models(db, workspace_id)
        assert remaining == []


async def db_application_models_tests(workspace_id: str, admin_id: str, actor: User) -> None:
    runtime_settings = settings()
    response_model = _make_model_entity(workspace_id, admin_id)
    response_model.id = "model-response-1"
    response_model.created_at = utc_now()
    response_model.updated_at = utc_now()
    response = app_models.model_to_response(response_model)
    assert response.name == "DeepSeek Chat"
    assert response.has_api_key is True
    assert response.credential["api_key"] == "****1234"

    legacy_model = RegisteredModel(
        workspace_id=workspace_id,
        name="Legacy",
        provider="model_anthropic_provider",
        provider_type="anthropic",
        api_base="https://api.anthropic.com",
        model_type="LLM",
        model_name="claude",
        status="active",
        meta={},
        created_by_user_id=admin_id,
    )
    legacy_model.id = "model-response-2"
    legacy_model.created_at = utc_now()
    legacy_model.updated_at = utc_now()
    legacy_response = app_models.model_to_response(legacy_model)
    assert legacy_response.api_base == "https://api.anthropic.com"

    catalog = app_models.list_provider_catalog()
    assert any(entry.provider == "model_deepseek_provider" for entry in catalog)
    llm_catalog = app_models.list_provider_catalog("LLM")
    assert all("LLM" in entry.model_types for entry in llm_catalog)

    types = app_models.list_model_types("model_deepseek_provider")
    assert [(item.key, item.value) for item in types] == [("LLM", "LLM")]
    expect_http_error(lambda: app_models.list_model_types("nope"), 422)

    base_models = app_models.list_base_models("model_deepseek_provider", "LLM")
    assert all(item.model_type == "LLM" for item in base_models)
    expect_http_error(lambda: app_models.list_base_models("model_deepseek_provider", "EMBEDDING"), 422)

    form = app_models.get_model_credential_form("model_deepseek_provider")
    assert [item.field for item in form] == ["api_base", "api_key"]

    create_payload = RegisteredModelCreateRequest(
        name="Unit Created Model",
        provider="model_deepseek_provider",
        provider_type="deepseek",
        model_type="LLM",
        model_name="deepseek-chat",
        credential={"api_base": "https://api.deepseek.com", "api_key": "sk-create-5678"},
        meta={"source": "unit"},
    )

    async with get_session_factory()() as db:
        created = await app_models.create_registered_model(
            db, workspace_id, create_payload, actor, runtime_settings
        )
        assert created.name == "Unit Created Model"
        assert created.api_base == "https://api.deepseek.com"
        assert created.credential["api_key"] == "****5678"
        assert created.meta["stream_usage_supported"] is False
        created_id = created.id

        # duplicate name -> 409 via name availability
        duplicate = RegisteredModelCreateRequest(
            name="Unit Created Model",
            provider="model_deepseek_provider",
            provider_type="deepseek",
            model_type="LLM",
            model_name="deepseek-chat",
            credential={"api_base": "https://api.deepseek.com", "api_key": "sk-create-5678"},
        )
        await expect_http_error_async(
            app_models.create_registered_model(db, workspace_id, duplicate, actor, runtime_settings),
            409,
        )

        model = await app_models.get_registered_model(db, workspace_id, created_id)
        assert model.id == created_id
        await expect_http_error_async(app_models.get_registered_model(db, workspace_id, "missing"), 404)
        db.add(WorkspaceOrm(id="other-ws", name="Other WS", slug="other-ws", is_default=False))
        await db.commit()
        cross_model = _make_model_entity("other-ws", admin_id, name="Cross")
        db.add(cross_model)
        await db.commit()
        await db.refresh(cross_model)
        await expect_http_error_async(
            app_models.get_registered_model(db, workspace_id, cross_model.id),
            404,
        )

        listed = await app_models.list_registered_models(db, workspace_id)
        assert [item.name for item in listed] == ["Unit Created Model"]

        # empty model name -> 422
        empty_name = RegisteredModelCreateRequest(
            name="Empty Name Model",
            provider="model_deepseek_provider",
            provider_type="deepseek",
            model_type="LLM",
            model_name="   ",
            credential={"api_base": "https://api.deepseek.com", "api_key": "k"},
        )
        await expect_http_error_async(
            app_models.create_registered_model(db, workspace_id, empty_name, actor, runtime_settings),
            422,
        )

        # provider/type mismatch -> 422
        mismatched = RegisteredModelCreateRequest(
            name="Mismatched",
            provider="model_deepseek_provider",
            provider_type="anthropic",
            model_type="LLM",
            model_name="deepseek-chat",
            credential={"api_base": "https://api.deepseek.com", "api_key": "k"},
        )
        await expect_http_error_async(
            app_models.create_registered_model(db, workspace_id, mismatched, actor, runtime_settings),
            422,
        )

        # update: disable
        updated = await app_models.update_registered_model(
            db,
            model,
            RegisteredModelUpdateRequest(status="disabled"),
            actor,
            runtime_settings,
        )
        assert updated.status == "disabled"

        # update: rotate api key
        model = await app_models.get_registered_model(db, workspace_id, created_id)
        rotated = await app_models.update_registered_model(
            db,
            model,
            RegisteredModelUpdateRequest(credential={"api_key": "sk-rotated-9999"}),
            actor,
            runtime_settings,
        )
        assert rotated.credential["api_key"] == "****9999"

        # update: change provider (fresh credentials path)
        model = await app_models.get_registered_model(db, workspace_id, created_id)
        swapped = await app_models.update_registered_model(
            db,
            model,
            RegisteredModelUpdateRequest(
                provider="model_custom_provider",
                provider_type="openai_compatible",
                credential={"api_base": "https://api.example.com", "api_key": "sk-swap-1234"},
            ),
            actor,
            runtime_settings,
        )
        assert swapped.provider_type == "openai_compatible"
        assert swapped.api_base == "https://api.example.com"

        # update: empty model name -> 422
        model = await app_models.get_registered_model(db, workspace_id, created_id)
        await expect_http_error_async(
            app_models.update_registered_model(
                db,
                model,
                RegisteredModelUpdateRequest(model_name="   "),
                actor,
                runtime_settings,
            ),
            422,
        )

        # update: provider type mismatch -> 422
        await expect_http_error_async(
            app_models.update_registered_model(
                db,
                model,
                RegisteredModelUpdateRequest(provider_type="anthropic"),
                actor,
                runtime_settings,
            ),
            422,
        )

        # update: rename to existing name -> 409
        second = await app_models.create_registered_model(
            db,
            workspace_id,
            RegisteredModelCreateRequest(
                name="Second Model",
                provider="model_deepseek_provider",
                provider_type="deepseek",
                model_type="LLM",
                model_name="deepseek-chat",
                credential={"api_base": "https://api.deepseek.com", "api_key": "k"},
            ),
            actor,
            runtime_settings,
        )
        model = await app_models.get_registered_model(db, workspace_id, created_id)
        await expect_http_error_async(
            app_models.update_registered_model(
                db,
                model,
                RegisteredModelUpdateRequest(name="Second Model"),
                actor,
                runtime_settings,
            ),
            409,
        )

        await app_models.delete_registered_model(db, model, actor)
        await expect_http_error_async(
            app_models.get_registered_model(db, workspace_id, created_id),
            404,
        )

    # IntegrityError branches via mocked db
    mocked_db = AsyncMock()
    mocked_db.add = MagicMock()
    mocked_db.scalar.return_value = None
    mocked_db.commit.side_effect = IntegrityError("dup", {}, Exception())
    entity = _make_model_entity(workspace_id, admin_id, name="Conflict Model")
    await expect_http_error_async(
        app_models.create_registered_model(mocked_db, workspace_id, create_payload, actor, runtime_settings),
        409,
    )
    mocked_db2 = AsyncMock()
    mocked_db2.add = MagicMock()
    mocked_db2.commit.side_effect = IntegrityError("dup", {}, Exception())
    await expect_http_error_async(
        app_models.update_registered_model(
            mocked_db2,
            entity,
            RegisteredModelUpdateRequest(status="disabled"),
            actor,
            runtime_settings,
        ),
        409,
    )
    mocked_db3 = AsyncMock()
    mocked_db3.add = MagicMock()
    mocked_db3.commit.side_effect = IntegrityError("in-use", {}, Exception())
    await expect_http_error_async(app_models.delete_registered_model(mocked_db3, entity, actor), 409)


async def db_repositories_mcp_tests(workspace_id: str, admin_id: str) -> None:
    async with get_session_factory()() as db:
        entity = McpServer(
            workspace_id=workspace_id,
            name="Unit Server",
            transport="streamable_http",
            url="https://example.com/mcp",
            tools=[_mcp_tool_dict("echo")],
            status="active",
            created_by_user_id=admin_id,
        )
        created = await mcp_repo.create_mcp_server(db, entity)
        assert created.id is not None
        server_id = created.id

        fetched = await mcp_repo.get_mcp_server_by_id(db, server_id)
        assert fetched is not None and fetched.name == "Unit Server"
        assert await mcp_repo.get_mcp_server_by_id(db, "missing") is None

        listed = await mcp_repo.list_mcp_servers(db, workspace_id)
        assert [item.id for item in listed] == [server_id]
        assert await mcp_repo.list_mcp_servers_by_ids(db, workspace_id, []) == []
        by_ids = await mcp_repo.list_mcp_servers_by_ids(db, workspace_id, [server_id])
        assert [item.id for item in by_ids] == [server_id]

        created.name = "Renamed Server"
        await mcp_repo.save_mcp_server(db, created)
        refreshed = await mcp_repo.refresh_mcp_server(db, created)
        assert refreshed is created
        assert created.name == "Renamed Server"

        policy = McpToolPolicy(
            workspace_id=workspace_id,
            mcp_server_id=server_id,
            tool_name="echo",
            definition_hash="hash-v1",
            mode="read_only",
            reviewed_by_user_id=admin_id,
        )
        saved_policy = await mcp_repo.save_mcp_tool_policy(db, policy)
        assert saved_policy.id is not None
        policy_id = saved_policy.id

        fetched_policy = await mcp_repo.get_mcp_tool_policy(db, workspace_id, server_id, "echo")
        assert fetched_policy is not None and fetched_policy.mode == "read_only"
        assert (
            await mcp_repo.get_mcp_tool_policy(db, workspace_id, server_id, "other-tool")
            is None
        )
        policies = await mcp_repo.list_mcp_tool_policies(db, workspace_id)
        assert [item.id for item in policies] == [policy_id]

        # update existing policy
        saved_policy.mode = "disabled"
        updated_policy = await mcp_repo.save_mcp_tool_policy(db, saved_policy)
        assert updated_policy.id == policy_id
        assert updated_policy.mode == "disabled"

        # second server for workspace-scoped deletion
        second = McpServer(
            workspace_id=workspace_id,
            name="Second Server",
            transport="stdio",
            stdio_command="/bin/echo",
            stdio_config_ciphertext=encrypt_secret(
                '{"command": "/bin/echo", "args": [], "cwd": null, "env": {}}',
                settings().model_secret_key,
            ),
            tools=[],
            status="active",
            created_by_user_id=admin_id,
        )
        second_created = await mcp_repo.create_mcp_server(db, second)
        second_id = second_created.id

        # agent link for cascade cleanup on delete
        model_row = RegisteredModel(
            workspace_id=workspace_id,
            name="Repo Model",
            provider="model_custom_provider",
            provider_type="openai_compatible",
            api_base="",
            model_type="LLM",
            model_name="m",
            status="active",
            created_by_user_id=admin_id,
        )
        db.add(model_row)
        await db.flush()
        agent = AgentOrm(
            workspace_id=workspace_id,
            name="Repo Agent",
            instructions="",
            model_id=model_row.id,
            created_by_user_id=admin_id,
        )
        db.add(agent)
        await db.flush()
        link = AgentMcpToolOrm(
            workspace_id=workspace_id,
            agent_id=agent.id,
            mcp_server_id=server_id,
            tool_name="echo",
        )
        db.add(link)
        await db.commit()

        await mcp_repo.delete_mcp_server(db, created)
        await db.commit()
        assert await mcp_repo.get_mcp_server_by_id(db, server_id) is None
        remaining_links = await db.scalars(
            select(AgentMcpToolOrm).where(AgentMcpToolOrm.mcp_server_id == server_id)
        )
        assert remaining_links.all() == []

        await mcp_repo.delete_workspace_mcp_servers(db, workspace_id)
        await db.commit()
        assert await mcp_repo.get_mcp_server_by_id(db, second_id) is None
        assert await mcp_repo.list_mcp_tool_policies(db, workspace_id) == []


def test_save_mcp_tool_policy_race() -> None:
    db = AsyncMock()
    db.scalar.side_effect = [None, None]

    class _RaisingNested:
        async def __aenter__(self):
            raise IntegrityError("dup", {}, Exception())

        async def __aexit__(self, *exc_info):
            return False

    def raising_nested():
        return _RaisingNested()

    db.begin_nested = raising_nested
    entity = McpToolPolicy(
        workspace_id="ws-1",
        mcp_server_id="srv-1",
        tool_name="echo",
        definition_hash="h",
        mode="approval_required",
    )
    try:
        run(mcp_repo.save_mcp_tool_policy(db, entity))
    except IntegrityError:
        pass
    else:
        raise AssertionError("expected IntegrityError to propagate")
    assert db.scalar.await_count == 2


async def db_resource_permission_tests() -> None:
    async with get_session_factory()() as db:
        user = UserOrm(
            id="rp-user-1",
            username="rp-user",
            email="rp-user@example.com",
            name="RP User",
            password_hash="x",
            is_active=True,
        )
        workspace = WorkspaceOrm(
            id="rp-ws-1",
            name="RP Workspace",
            slug="rp-workspace",
            is_default=False,
        )
        membership = WorkspaceMembershipOrm(
            id="rp-mem-1",
            workspace_id="rp-ws-1",
            user_id="rp-user-1",
            role="member",
        )
        db.add_all([user, workspace, membership])
        await db.commit()

        assert (
            await rp_repo.get_user_grant(db, "rp-ws-1", "agent", "res-1", "rp-user-1")
            is None
        )
        assert (
            await rp_repo.get_active_workspace_member(db, "rp-ws-1", "rp-user-1")
            is not None
        )
        assert await rp_repo.get_active_workspace_member(db, "rp-ws-1", "nobody") is None

        entity = ResourcePermission(
            workspace_id="rp-ws-1",
            resource_type="agent",
            resource_id="res-1",
            user_id="rp-user-1",
            permission="view",
            created_by_user_id="rp-user-1",
        )
        created = await rp_repo.create_resource_permission(db, entity)
        assert created.id is not None

        grant = await rp_repo.get_user_grant(db, "rp-ws-1", "agent", "res-1", "rp-user-1")
        assert grant is not None and grant.permission == "view"

        created.permission = "edit"
        await rp_repo.save_resource_permission(db, created)

        rows = await rp_repo.list_resource_permission_rows(db, "rp-ws-1", "agent", "res-1")
        assert len(rows) == 1
        permission, grant_user = rows[0]
        assert permission.permission == "edit"
        assert grant_user.username == "rp-user"

        deleted = await rp_repo.delete_resource_permission(
            db, "rp-ws-1", "agent", "res-1", "rp-user-1"
        )
        assert deleted == 1
        deleted_again = await rp_repo.delete_resource_permission(
            db, "rp-ws-1", "agent", "res-1", "rp-user-1"
        )
        assert deleted_again == 0

        second = ResourcePermission(
            workspace_id="rp-ws-1",
            resource_type="knowledge_base",
            resource_id="kb-1",
            user_id="rp-user-1",
            permission="view",
            created_by_user_id="rp-user-1",
        )
        await rp_repo.create_resource_permission(db, second)
        await rp_repo.delete_resource_permissions(db, "rp-ws-1", "knowledge_base", "kb-1")
        await db.commit()
        assert (
            await rp_repo.get_user_grant(db, "rp-ws-1", "knowledge_base", "kb-1", "rp-user-1")
            is None
        )


# ================================================================ main


def main() -> None:
    test_runtime_error_helpers()
    test_openai_compatible_base()
    test_reasoning_content()
    test_provider_error_mixin_maps_errors()
    test_provider_error_mixin_success_paths()
    test_openai_compatible_chat_model_error_paths()
    test_openai_compatible_chat_model_reasoning()
    test_openai_compatible_chat_model_astream_success()
    test_checked_embeddings()
    test_openai_compatible_embeddings_construction()
    test_openai_compatible_reranker()
    test_bedrock_model_reranker()
    test_credential_helpers()
    test_build_chat_model_and_friends()
    test_registered_model_credentials()
    test_build_registered_models()
    test_test_model_connection()

    test_registry_basics()
    test_stored_model_credentials_fallbacks()
    test_normalize_provider_credentials()
    test_apply_model_credentials()
    test_run_model_test()
    test_test_registered_model()

    test_credentials_roundtrip()

    test_normalize_mcp_url_unit()
    test_is_private_address()
    test_validate_mcp_destination()
    test_hardened_http_client_factory()
    test_mcp_client_streamable_http()
    test_mcp_client_sse()
    test_mcp_client_stdio()
    test_mcp_client_error_paths()
    test_discover_mcp_tools()
    test_call_mcp_tool()
    test_multitransport_client()

    test_mcp_stdio_parse()
    test_mcp_stdio_runtime_validation()

    test_code_sandbox_program_wrapping()
    test_code_sandbox_execute()
    test_code_sandbox_write_failure()

    test_object_storage()

    test_load_env_file()
    test_settings_defaults_and_validation()
    test_settings_from_env()

    test_security_tokens()
    test_session_configuration()
    test_validation_normalizers()
    test_celery()
    test_configure_task_worker()

    test_deps()
    test_ports_mcp()
    test_ports_model_registry_build()

    test_mcp_tool_hash_and_policy_mode()
    test_mcp_server_to_response()
    test_bearer_token_and_stdio_config()
    test_tools_get_and_list_servers()
    test_create_mcp_server()
    test_refresh_mcp_server()
    test_delete_mcp_server()
    test_resolve_mcp_tools()
    test_mcp_tool_policy_services()

    test_team_services_basics()
    test_create_team()
    test_update_team()
    test_delete_team_permanently()
    test_add_team_member()
    test_update_team_member_role()
    test_remove_team_member()

    test_mapping_refresh_entity_missing_row()
    test_save_mcp_tool_policy_race()

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
        assert me.status_code == 200, me.text
        admin_id = me.json()["user"]["id"]
        actor = User(
            id=admin_id,
            username="admin",
            name="NexaFlow Admin",
            is_global_admin=True,
        )

        run(db_seed_tests())
        run(db_registry_repository_tests(workspace_id, admin_id))
        with patch.object(
            app_models,
            "test_registered_model",
            new=AsyncMock(return_value={"stream_usage_supported": False}),
        ):
            run(db_application_models_tests(workspace_id, admin_id, actor))
        run(db_repositories_mcp_tests(workspace_id, admin_id))
        run(db_resource_permission_tests())

    print("INFRA_UNIT_COVERAGE_SUITE_OK")


if __name__ == "__main__":
    main()

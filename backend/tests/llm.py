import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import text

from app.capabilities.llm.credentials import decrypt_credential_secrets
from app.capabilities.llm.models import RegisteredModel
from app.capabilities.llm.runtime import (
    build_chat_model,
    build_embeddings,
    build_registered_chat_model,
    build_registered_embeddings,
    build_registered_reranker,
    build_reranker,
)
from app.infrastructure.session import get_session_factory
from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    settings,
    test_client,
)

MEMBER_PASSWORD = "Member@12345."


class ModelTestHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []
    fail_next = False

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        ModelTestHandler.calls.append(
            {
                "path": self.path,
                "authorization": self.headers.get("authorization"),
                "body": body,
            }
        )
        if ModelTestHandler.fail_next:
            ModelTestHandler.fail_next = False
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"invalid key"}')
            return

        if self.path == "/v1/chat/completions" and body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {
                    "id": "test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "reasoning_content": "Inspect ",
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "ok"},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                },
            ]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.path == "/v1/embeddings":
            inputs = body.get("input", [])
            input_count = len(inputs) if isinstance(inputs, list) else 1
            self.wfile.write(
                json.dumps(
                    {
                        "object": "list",
                        "data": [
                            {"object": "embedding", "embedding": [0.0], "index": index}
                            for index in range(input_count)
                        ],
                        "model": "test",
                        "usage": {"prompt_tokens": input_count, "total_tokens": input_count},
                    }
                ).encode()
            )
        elif self.path == "/v1/rerank":
            self.wfile.write(b'{"results":[{"index":0,"relevance_score":1.0}]}')
        else:
            self.wfile.write(
                b'{"id":"test","object":"chat.completion","created":0,"model":"test",'
                b'"choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}'
            )

    def log_message(self, format: str, *args) -> None:
        return


@contextmanager
def model_test_server() -> Iterator[str]:
    ModelTestHandler.calls = []
    ModelTestHandler.fail_next = False
    server = HTTPServer(("127.0.0.1", 0), ModelTestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def models_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/models{suffix}"


def create_workspace_user(client, token: str, workspace_id: str, username: str) -> str:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members/users",
        headers=auth_headers(token),
        json={
            "username": username,
            "email": f"{username}@example.com",
            "name": username.replace("-", " ").title(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["initial_password"]


async def assert_model_deleted(model_id: str) -> None:
    async with get_session_factory()() as db:
        model = await db.get(RegisteredModel, model_id)
        assert model is None


async def assert_model_api_key(model_id: str, expected_api_key: str) -> None:
    async with get_session_factory()() as db:
        model = await db.get(RegisteredModel, model_id)
        assert model is not None
        assert model.api_key_ciphertext != expected_api_key
        assert model.api_key_hint == f"****{expected_api_key[-4:]}"
        assert decrypt_credential_secrets(
            model.api_key_ciphertext,
            settings().model_secret_key,
        ) == {"api_key": expected_api_key}
        assert model.credential_config == {"api_base": model.api_base}
        assert model.credential_secret_hints == {
            "api_key": f"****{expected_api_key[-4:]}"
        }


async def assert_registered_model_runtime_call(model_id: str, model_type: str) -> None:
    async with get_session_factory()() as db:
        model = await db.get(RegisteredModel, model_id)
        assert model is not None
        if model_type == "LLM":
            chat_model = build_registered_chat_model(model, settings())
            assert isinstance(chat_model, BaseChatModel)
            response = await chat_model.ainvoke(
                [("human", "Hello")],
                max_tokens=1,
            )
            assert response.text == "ok"
            chunks = [
                chunk
                async for chunk in chat_model.astream([("human", "Hello")])
            ]
            assert "".join(chunk.text for chunk in chunks) == "ok"
            assert "".join(
                str(chunk.additional_kwargs.get("reasoning_content", ""))
                for chunk in chunks
            ) == "Inspect "
        elif model_type == "EMBEDDING":
            embeddings = build_registered_embeddings(model, settings())
            assert isinstance(embeddings, Embeddings)
            assert embeddings.embed_documents(["Hello"]) == [[0.0]]
        elif model_type == "RERANKER":
            assert build_registered_reranker(model, settings()).rerank(
                "Hello",
                ["Hello"],
            ) == [{"index": 0, "relevance_score": 1.0}]
        else:
            raise AssertionError(f"Unexpected model type: {model_type}")


async def assert_openai_compatible_runtime(api_base: str) -> None:
    chat_model = build_chat_model(
        "openai_compatible",
        {"api_base": api_base, "api_key": "test"},
        "test",
    )
    response = await chat_model.ainvoke([("human", "Hello")], max_tokens=1)
    assert response.text == "ok"
    chunks = [
        chunk async for chunk in chat_model.astream([("human", "Hello")])
    ]
    assert "".join(chunk.text for chunk in chunks) == "ok"
    assert "".join(
        str(chunk.additional_kwargs.get("reasoning_content", ""))
        for chunk in chunks
    ) == "Inspect "


async def assert_model_count(expected: int) -> None:
    async with get_session_factory()() as db:
        result = await db.execute(text("select count(*) from model"))
        assert result.scalar_one() == expected


def model_payload(api_base: str, api_key: str = "sk-deepseek-test-1234") -> dict:
    return {
        "name": "DeepSeek Chat",
        "provider": "model_deepseek_provider",
        "provider_type": "deepseek",
        "model_type": "LLM",
        "model_name": "deepseek-chat",
        "credential": {"api_base": f"{api_base}/", "api_key": api_key},
        "meta": {"source": "test"},
    }


def assert_provider_factories() -> None:
    chat_cases = [
        (
            "openai_compatible",
            {"api_base": "http://localhost:8000/v1"},
            "local-model",
            "OpenAICompatibleChatModel",
        ),
        (
            "anthropic",
            {"api_base": "https://api.anthropic.com", "api_key": "test"},
            "claude-test",
            "AnthropicChatModel",
        ),
        (
            "bedrock",
            {
                "region_name": "us-east-1",
                "aws_access_key_id": "test",
                "aws_secret_access_key": "secret",
            },
            "amazon.nova-test-v1:0",
            "BedrockChatModel",
        ),
        (
            "azure_openai",
            {
                "azure_endpoint": "https://example.openai.azure.com",
                "api_version": "2024-10-21",
                "api_key": "test",
            },
            "deployment",
            "AzureChatModel",
        ),
        (
            "deepseek",
            {"api_base": "https://api.deepseek.com", "api_key": "test"},
            "deepseek-chat",
            "DeepSeekChatModel",
        ),
        (
            "google_genai",
            {"api_key": "test"},
            "gemini-test",
            "GoogleChatModel",
        ),
        (
            "ollama",
            {"api_base": "http://localhost:11434"},
            "llama3",
            "OllamaChatModel",
        ),
    ]
    for provider_type, credential, model_name, expected_type in chat_cases:
        assert (
            type(build_chat_model(provider_type, credential, model_name)).__name__
            == expected_type
        )

    embedding_cases = [
        (
            "bedrock",
            {
                "region_name": "us-east-1",
                "aws_access_key_id": "test",
                "aws_secret_access_key": "secret",
            },
            "amazon.titan-embed-text-v1",
        ),
        (
            "azure_openai",
            {
                "azure_endpoint": "https://example.openai.azure.com",
                "api_version": "2024-10-21",
                "api_key": "test",
            },
            "embedding-deployment",
        ),
        ("google_genai", {"api_key": "test"}, "models/embedding-001"),
        ("ollama", {"api_base": "http://localhost:11434"}, "nomic-embed-text"),
    ]
    for provider_type, credential, model_name in embedding_cases:
        assert isinstance(
            build_embeddings(provider_type, credential, model_name),
            Embeddings,
        )

    assert (
        type(
            build_reranker(
                "bedrock",
                {
                    "region_name": "us-east-1",
                    "aws_access_key_id": "test",
                    "aws_secret_access_key": "secret",
                },
                "cohere.rerank-v3-5:0",
            )
        ).__name__
        == "BedrockModelReranker"
    )


def main() -> None:
    assert_provider_factories()
    with test_client() as client, model_test_server() as model_base_url:
        admin_token, workspace_id = activate_admin(client)
        asyncio.run(assert_openai_compatible_runtime(model_base_url))
        member_password = create_workspace_user(client, admin_token, workspace_id, "model-user")
        member_token = activate_user(client, "model-user", member_password, MEMBER_PASSWORD)

        provider_catalog = client.get("/api/v1/model-providers", headers=auth_headers(admin_token))
        assert provider_catalog.status_code == 200, provider_catalog.text
        catalog_by_provider = {
            item["provider"]: item for item in provider_catalog.json()
        }
        assert catalog_by_provider["model_deepseek_provider"]["provider_type"] == "deepseek"
        assert catalog_by_provider["model_anthropic_provider"]["provider_type"] == "anthropic"
        assert catalog_by_provider["model_aws_bedrock_provider"]["provider_type"] == "bedrock"
        assert catalog_by_provider["model_azure_provider"]["provider_type"] == "azure_openai"
        assert catalog_by_provider["model_gemini_provider"]["provider_type"] == "google_genai"
        assert catalog_by_provider["model_ollama_provider"]["provider_type"] == "ollama"

        provider_model_types = client.get(
            "/api/v1/model-providers/model-types",
            headers=auth_headers(admin_token),
            params={"provider": "model_deepseek_provider"},
        )
        assert provider_model_types.status_code == 200, provider_model_types.text
        assert provider_model_types.json() == [{"key": "LLM", "value": "LLM"}]

        provider_form = client.get(
            "/api/v1/model-providers/credential-form",
            headers=auth_headers(admin_token),
            params={"provider": "model_deepseek_provider"},
        )
        assert provider_form.status_code == 200, provider_form.text
        assert [item["field"] for item in provider_form.json()] == ["api_base", "api_key"]

        custom_provider_form = client.get(
            "/api/v1/model-providers/credential-form",
            headers=auth_headers(admin_token),
            params={"provider": "model_custom_provider"},
        )
        assert custom_provider_form.status_code == 200, custom_provider_form.text
        assert custom_provider_form.json()[1]["field"] == "api_key"
        assert custom_provider_form.json()[1]["required"] is False

        bedrock_form = client.get(
            "/api/v1/model-providers/credential-form",
            headers=auth_headers(admin_token),
            params={"provider": "model_aws_bedrock_provider"},
        )
        assert bedrock_form.status_code == 200, bedrock_form.text
        assert [item["field"] for item in bedrock_form.json()] == [
            "region_name",
            "endpoint_url",
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
        ]

        partial_aws_credentials = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json={
                "name": "Invalid Bedrock",
                "provider": "model_aws_bedrock_provider",
                "provider_type": "bedrock",
                "model_type": "LLM",
                "model_name": "amazon.nova-test-v1:0",
                "credential": {
                    "region_name": "us-east-1",
                    "aws_access_key_id": "test",
                },
            },
        )
        assert partial_aws_credentials.status_code == 422, partial_aws_credentials.text

        empty = client.get(models_url(workspace_id), headers=auth_headers(admin_token))
        assert empty.status_code == 200, empty.text
        assert empty.json() == []

        invalid_url = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json={**model_payload("not-a-url"), "name": "Bad Model"},
        )
        assert invalid_url.status_code == 422, invalid_url.text

        member_create_denied = client.post(
            models_url(workspace_id),
            headers=auth_headers(member_token),
            json=model_payload(model_base_url),
        )
        assert member_create_denied.status_code == 403, member_create_denied.text

        ModelTestHandler.fail_next = True
        failed_test = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json={**model_payload(model_base_url, "sk-bad-key-0000"), "name": "Bad Key Model"},
        )
        assert failed_test.status_code == 400, failed_test.text
        asyncio.run(assert_model_count(0))

        model = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json=model_payload(model_base_url),
        )
        assert model.status_code == 201, model.text
        model_payload_response = model.json()
        model_id = model_payload_response["id"]
        assert model_payload_response["api_base"] == model_base_url
        assert model_payload_response["credential"] == {
            "api_base": model_base_url,
            "api_key": "****1234",
        }
        assert model_payload_response["model_type"] == "LLM"
        assert "currency" not in model_payload_response
        assert "supports_tool_calling" not in model_payload_response
        assert "model_params_form" not in model_payload_response
        assert "api_key" not in model_payload_response or model_payload_response["api_key"] != "sk-deepseek-test-1234"
        assert "api_key_ciphertext" not in model_payload_response
        assert ModelTestHandler.calls[-1]["path"] == "/v1/chat/completions"
        assert ModelTestHandler.calls[-1]["authorization"] == "Bearer sk-deepseek-test-1234"
        assert ModelTestHandler.calls[-1]["body"]["model"] == "deepseek-chat"
        assert ModelTestHandler.calls[-1]["body"]["messages"][0]["content"] == "Hello"
        asyncio.run(assert_model_api_key(model_id, "sk-deepseek-test-1234"))
        asyncio.run(assert_registered_model_runtime_call(model_id, "LLM"))
        assert ModelTestHandler.calls[-1]["path"] == "/v1/chat/completions"

        duplicate_model = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json=model_payload(model_base_url),
        )
        assert duplicate_model.status_code == 409, duplicate_model.text

        same_base_model = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json={**model_payload(model_base_url), "name": "DeepSeek Chat Backup"},
        )
        assert same_base_model.status_code == 201, same_base_model.text
        same_base_model_id = same_base_model.json()["id"]

        deleted_same_base_model = client.delete(
            models_url(workspace_id, f"/{same_base_model_id}"),
            headers=auth_headers(admin_token),
        )
        assert deleted_same_base_model.status_code == 204, deleted_same_base_model.text
        asyncio.run(assert_model_deleted(same_base_model_id))

        embedding_model = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json={
                **model_payload(model_base_url),
                "name": "Embedding Model",
                "provider": "model_openai_provider",
                "provider_type": "openai_compatible",
                "model_type": "EMBEDDING",
                "model_name": "text-embedding-3-small",
            },
        )
        assert embedding_model.status_code == 201, embedding_model.text
        assert ModelTestHandler.calls[-1]["path"] == "/v1/embeddings"
        embedding_model_id = embedding_model.json()["id"]
        asyncio.run(assert_registered_model_runtime_call(embedding_model_id, "EMBEDDING"))
        assert ModelTestHandler.calls[-1]["path"] == "/v1/embeddings"
        deleted_embedding_model = client.delete(
            models_url(workspace_id, f"/{embedding_model_id}"),
            headers=auth_headers(admin_token),
        )
        assert deleted_embedding_model.status_code == 204, deleted_embedding_model.text
        asyncio.run(assert_model_deleted(embedding_model_id))

        reranker_model = client.post(
            models_url(workspace_id),
            headers=auth_headers(admin_token),
            json={
                **model_payload(model_base_url),
                "name": "Reranker Model",
                "provider": "model_custom_provider",
                "provider_type": "openai_compatible",
                "model_type": "RERANKER",
                "model_name": "custom-reranker",
            },
        )
        assert reranker_model.status_code == 201, reranker_model.text
        assert ModelTestHandler.calls[-1]["path"] == "/v1/rerank"
        reranker_model_id = reranker_model.json()["id"]
        asyncio.run(assert_registered_model_runtime_call(reranker_model_id, "RERANKER"))
        assert ModelTestHandler.calls[-1]["path"] == "/v1/rerank"
        deleted_reranker_model = client.delete(
            models_url(workspace_id, f"/{reranker_model_id}"),
            headers=auth_headers(admin_token),
        )
        assert deleted_reranker_model.status_code == 204, deleted_reranker_model.text
        asyncio.run(assert_model_deleted(reranker_model_id))

        member_list = client.get(models_url(workspace_id), headers=auth_headers(member_token))
        assert member_list.status_code == 200, member_list.text
        assert [item["name"] for item in member_list.json()] == ["DeepSeek Chat"]
        assert member_list.json()[0]["credential"]["api_key"] == "****1234"

        member_update_denied = client.patch(
            models_url(workspace_id, f"/{model_id}"),
            headers=auth_headers(member_token),
            json={"status": "disabled"},
        )
        assert member_update_denied.status_code == 403, member_update_denied.text

        updated_model = client.patch(
            models_url(workspace_id, f"/{model_id}"),
            headers=auth_headers(admin_token),
            json={"status": "disabled"},
        )
        assert updated_model.status_code == 200, updated_model.text
        assert updated_model.json()["status"] == "disabled"
        assert ModelTestHandler.calls[-1]["authorization"] == "Bearer sk-deepseek-test-1234"

        rotated_model_key = client.patch(
            models_url(workspace_id, f"/{model_id}"),
            headers=auth_headers(admin_token),
            json={"credential": {"api_key": "sk-deepseek-rotated-5678"}},
        )
        assert rotated_model_key.status_code == 200, rotated_model_key.text
        assert rotated_model_key.json()["credential"]["api_key"] == "****5678"
        assert ModelTestHandler.calls[-1]["authorization"] == "Bearer sk-deepseek-rotated-5678"
        asyncio.run(assert_model_api_key(model_id, "sk-deepseek-rotated-5678"))

        deleted = client.delete(
            models_url(workspace_id, f"/{model_id}"),
            headers=auth_headers(admin_token),
        )
        assert deleted.status_code == 204, deleted.text

        asyncio.run(assert_model_deleted(model_id))

        audit_logs = client.get("/api/v1/admin/audit-logs", headers=auth_headers(admin_token))
        assert audit_logs.status_code == 200, audit_logs.text
        actions = [item["action"] for item in audit_logs.json()]
        assert "model.create" in actions
        assert "model.update" in actions
        assert "model.delete" in actions


if __name__ == "__main__":
    main()

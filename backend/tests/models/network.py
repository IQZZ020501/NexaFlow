"""Member model connections cannot reach host/private networks or host credentials."""

import asyncio
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.adapters.llm.network import (
    PUBLIC_ENDPOINT_CREDENTIAL,
    PublicAsyncBackend,
    PublicSyncBackend,
    _DeadlineStream,
    public_async_client,
    public_client,
    validate_member_connection,
)
from app.adapters.llm.response_limits import ResponseBudget
from app.adapters.llm.runtime import (
    build_chat_model,
    build_embeddings,
    build_reranker,
    test_model_connection,
)
from app.ports.llm import ModelProviderError


class ModelNetworkTests(unittest.TestCase):
    def test_private_and_mixed_dns_addresses_are_rejected(self):
        for addresses in (
            ("127.0.0.1",),
            ("169.254.169.254",),
            ("::1",),
            ("93.184.216.34", "10.0.0.2"),
        ):
            answers = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
                for address in addresses
            ]
            with patch(
                "app.adapters.llm.network.socket.getaddrinfo", return_value=answers
            ):
                with self.assertRaises(ModelProviderError):
                    validate_member_connection(
                        "openai_compatible",
                        {"api_base": "https://model.example.com"},
                        {},
                    )

    def test_credentials_and_transport_overrides_are_not_inherited(self):
        from fastapi import HTTPException

        from app.application.models.registry import normalize_model_request_params

        with self.assertRaisesRegex(ModelProviderError, "explicit AWS"):
            validate_member_connection("bedrock", {"region_name": "us-east-1"}, {})
        with self.assertRaisesRegex(ModelProviderError, "official regional"):
            validate_member_connection(
                "bedrock",
                {
                    "region_name": "us-east-1",
                    "endpoint_url": "https://evil.example.com",
                    "aws_access_key_id": "own",
                    "aws_secret_access_key": "own",
                },
                {},
            )
        for key in ("client_args", "http_options", "http_client", "vertexai"):
            with self.assertRaisesRegex(ModelProviderError, "override connection"):
                validate_member_connection("google_genai", {}, {key: {}})
        for key in ("credentials_profile_name", "bedrock_api_key", "openai_api_base"):
            with self.assertRaisesRegex(ModelProviderError, "override connection"):
                validate_member_connection("bedrock", {"region_name": "us-east-1", "aws_access_key_id": "own", "aws_secret_access_key": "own"}, {key: "evil"})
            with self.assertRaises(HTTPException) as exc_info:
                normalize_model_request_params({key: "evil"}, "chat")
            self.assertEqual(exc_info.exception.status_code, 422)

    def test_dns_is_checked_at_each_connection_and_only_validated_ips_are_used(self):
        from httpcore import SyncBackend

        with patch(
            "app.adapters.llm.network.public_addresses", return_value=("93.184.216.34",)
        ):
            with patch.object(
                SyncBackend, "connect_tcp", return_value="stream"
            ) as connect:
                self.assertEqual(
                    PublicSyncBackend().connect_tcp("model.example.com", 443), "stream"
                )
                self.assertEqual(connect.call_args.args[0], "93.184.216.34")
        with patch(
            "app.adapters.llm.network.public_addresses",
            side_effect=ModelProviderError("private"),
        ):
            with patch.object(SyncBackend, "connect_tcp") as connect:
                with self.assertRaises(ModelProviderError):
                    PublicSyncBackend().connect_tcp("model.example.com", 443)
                connect.assert_not_called()

    def test_public_reranker_rechecks_dns_after_endpoint_validation(self):
        credentials = {
            "api_base": "https://models.example.com",
            "api_key": "own-key",
            PUBLIC_ENDPOINT_CREDENTIAL: "true",
        }
        public_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        private_answer = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ]
        with patch(
            "app.adapters.llm.network.socket.getaddrinfo",
            side_effect=[public_answer, private_answer],
        ) as resolve:
            validate_member_connection("openai_compatible", credentials, {})
            reranker = build_reranker("openai_compatible", credentials, "rerank")
            with self.assertRaisesRegex(ModelProviderError, "public network"):
                reranker.rerank("question", ["document"])
            self.assertEqual(resolve.call_count, 2)

    def test_public_reranker_preserves_request_and_results(self):
        import json

        import httpx

        results = [{"index": 0, "relevance_score": 0.9}]

        def respond(request):
            self.assertEqual(str(request.url), "https://models.example.com/v1/rerank")
            self.assertEqual(request.headers["authorization"], "Bearer own-key")
            self.assertEqual(
                json.loads(request.content),
                {"model": "rerank", "query": "question", "documents": ["document"]},
            )
            return httpx.Response(200, json={"results": results})

        reranker = build_reranker(
            "openai_compatible",
            {
                "api_base": "https://models.example.com",
                "api_key": "own-key",
                PUBLIC_ENDPOINT_CREDENTIAL: "true",
            },
            "rerank",
        )
        with patch(
            "app.adapters.llm.runtime.public_client",
            return_value=httpx.Client(transport=httpx.MockTransport(respond)),
        ), patch(
            "app.adapters.llm.runtime.httpx.Client",
            side_effect=AssertionError("Public reranker bypassed its checked transport."),
        ):
            self.assertEqual(reranker.rerank("question", ["document"]), results)

    def test_public_probe_rejects_oversize_and_encoded_responses_before_parsing(self):
        for content_encoding in ("identity", "gzip"):
            chunks_read = []
            closed = []

            def chunks():
                for chunk in (b"12345", b"67890", b"unused"):
                    chunks_read.append(chunk)
                    yield chunk

            class TestStream(httpx.SyncByteStream):
                def __iter__(self):
                    return chunks()

                def close(self):
                    closed.append(True)

            def respond(request):
                self.assertEqual(request.headers["accept-encoding"], "identity")
                return httpx.Response(
                    200, headers={"content-encoding": content_encoding}, stream=TestStream()
                )

            with patch("app.adapters.llm.response_limits.MAX_PROBE_BYTES", 8), patch(
                "app.adapters.llm.network.public_transport",
                return_value=httpx.MockTransport(respond),
            ):
                with self.assertRaises(ModelProviderError):
                    test_model_connection(
                        "openai_compatible",
                        {
                            "api_base": "https://models.example.com",
                            PUBLIC_ENDPOINT_CREDENTIAL: "true",
                        },
                        "embedding",
                        "EMBEDDING",
                    )
            self.assertTrue(closed)
            expected = [b"12345", b"67890"] if content_encoding == "identity" else []
            self.assertEqual(chunks_read, expected)

    def test_transport_timeout_preserves_the_registration_timeout_status(self):
        from fastapi import HTTPException

        from app.application.models.registry import run_model_test
        from app.ports.llm import ModelProviderTimeoutError

        with patch(
            "app.application.models.registry.test_model_connection",
            side_effect=ModelProviderTimeoutError("Model request timed out."),
        ):
            with self.assertRaises(HTTPException) as error:
                run_model_test("openai_compatible", {}, "test", "LLM")
        self.assertEqual(error.exception.status_code, 504)

    def test_probe_fallback_has_the_same_event_budget_and_closes(self):
        from app.ports.llm import ModelProviderStatusError

        closed = []

        def events():
            try:
                for _ in range(4):
                    yield SimpleNamespace(usage_metadata={})
            finally:
                closed.append(True)

        rejecting = MagicMock()
        rejecting.stream.side_effect = ModelProviderStatusError(422)
        fallback = MagicMock()
        fallback.stream.return_value = events()
        with patch("app.adapters.llm.runtime.MAX_PROBE_EVENTS", 2), patch(
            "app.adapters.llm.runtime.build_chat_model", side_effect=[rejecting, fallback]
        ):
            with self.assertRaisesRegex(ModelProviderError, "too many events"):
                test_model_connection("openai_compatible", {}, "test", "LLM")
        self.assertEqual(closed, [True])

    def test_reranker_bounds_regular_body_as_well_as_probe(self):
        def chunks():
            yield b'{"results":'
            yield b'[]}'
            self.fail("Read continued beyond response budget.")

        credentials = {
            "api_base": "https://models.example.com",
            PUBLIC_ENDPOINT_CREDENTIAL: "true",
        }
        with patch("app.adapters.llm.runtime.MAX_RERANK_BYTES", 12), patch(
            "app.adapters.llm.network.public_transport",
            return_value=httpx.MockTransport(lambda _: httpx.Response(200, content=chunks())),
        ):
            with self.assertRaisesRegex(ModelProviderError, "size limit"):
                build_reranker("openai_compatible", credentials, "rerank").rerank("q", ["d"])

    def test_socket_reads_share_the_deadline_across_tls(self):
        from app.ports.llm import ModelProviderTimeoutError

        stream = MagicMock()
        with patch("app.adapters.llm.response_limits.monotonic", side_effect=[0, 1, 3, 5]):
            bounded = _DeadlineStream(stream, ResponseBudget(32, 5))
            secure = bounded.start_tls(None, "public.example", 6)
            stream.start_tls.assert_called_once_with(None, "public.example", 4)
            secure.read(128, 6)
            stream.start_tls.return_value.read.assert_called_once_with(128, 2)
            with self.assertRaises(ModelProviderTimeoutError):
                secure.read(128)
            secure.close()
            stream.start_tls.return_value.close.assert_called_once()

    def test_async_backend_pins_tcp_and_clients_ignore_environment_proxies(self):
        from httpcore import AnyIOBackend

        async def run():
            with patch(
                "app.adapters.llm.network.public_addresses",
                return_value=("93.184.216.34",),
            ):
                with patch.object(
                    AnyIOBackend, "connect_tcp", new=AsyncMock(return_value="stream")
                ) as connect:
                    self.assertEqual(
                        await PublicAsyncBackend().connect_tcp(
                            "model.example.com", 443
                        ),
                        "stream",
                    )
                    self.assertEqual(connect.call_args.args[0], "93.184.216.34")
            async with public_async_client() as client:
                self.assertFalse(client.follow_redirects)
                self.assertIsInstance(
                    client._transport._pool._network_backend, PublicAsyncBackend
                )
                with self.assertRaises(ModelProviderError):
                    await client.get("http://127.0.0.1:9")

        asyncio.run(run())
        with public_client() as client:
            self.assertFalse(client.follow_redirects)
            self.assertIsInstance(
                client._transport._pool._network_backend, PublicSyncBackend
            )
            with self.assertRaises(ModelProviderError):
                client.get("http://127.0.0.1:9")

    def test_every_supported_sdk_uses_hardened_transports(self):
        credentials = {
            "api_base": "https://models.example.com",
            "api_key": "own-key",
            "azure_endpoint": "https://models.example.com",
            "api_version": "2024-10-21",
            PUBLIC_ENDPOINT_CREDENTIAL: "true",
        }
        for provider, name in (
            ("openai_compatible", "chat"),
            ("deepseek", "deepseek-chat"),
            ("azure_openai", "chat"),
        ):
            model = build_chat_model(provider, credentials, name)
            self.assertIsInstance(
                model.http_client._transport._pool._network_backend, PublicSyncBackend
            )
            self.assertIsInstance(
                model.http_async_client._transport._pool._network_backend,
                PublicAsyncBackend,
            )
            model.http_client.close()
            asyncio.run(model.http_async_client.aclose())
        anthropic = build_chat_model("anthropic", credentials, "claude-test")
        self.assertIsInstance(
            anthropic._client._client._transport._pool._network_backend,
            PublicSyncBackend,
        )
        anthropic._client.close()
        asyncio.run(anthropic._async_client.close())
        google = build_chat_model("google_genai", credentials, "gemini-test")
        self.assertIsInstance(
            google.client._api_client._httpx_client._transport._pool._network_backend,
            PublicSyncBackend,
        )
        google.client.close()
        asyncio.run(google.client.aio.aclose())
        ollama = build_chat_model("ollama", credentials, "chat")
        self.assertIsInstance(
            ollama._client._client._transport._pool._network_backend, PublicSyncBackend
        )
        self.assertIsInstance(
            ollama._async_client._client._transport._pool._network_backend,
            PublicAsyncBackend,
        )
        ollama._client._client.close()
        asyncio.run(ollama._async_client._client.aclose())
        for provider in ("openai_compatible", "azure_openai", "google_genai", "ollama"):
            embedding = build_embeddings(provider, credentials, "embedding")._delegate
            if provider in {"openai_compatible", "azure_openai"}:
                client = embedding.http_client
            elif provider == "google_genai":
                client = embedding.client._api_client._httpx_client
            else:
                client = embedding._client._client
            self.assertIsInstance(
                client._transport._pool._network_backend, PublicSyncBackend
            )
            client.close()
        self.assertTrue(
            build_reranker(
                "openai_compatible", credentials, "rerank"
            ).public_endpoint_only
        )

    def test_request_params_and_url_credentials_reject_transport_injection(self):
        from fastapi import HTTPException

        from app.application.models.registry import (
            normalize_model_request_params,
            normalize_url_credential,
        )

        for key in ("http_client", "http_options", "vertexai", "openai_proxy"):
            with self.assertRaises(HTTPException) as exc_info:
                normalize_model_request_params({key: "evil"}, "LLM")
            self.assertEqual(exc_info.exception.status_code, 422)

        for bad_url in (
            "https://user:pass@models.example.com/v1",
            "https://models.example.com/v1?token=secret",
            "https://models.example.com/v1#frag",
            "https://models.example.com\\evil",
        ):
            with self.assertRaises(HTTPException) as exc_info:
                normalize_url_credential(bad_url, "api_base")
            self.assertEqual(exc_info.exception.status_code, 422)

        google_chat = build_chat_model("google_genai", {"api_key": "own-key"}, "gemini-test")
        self.assertFalse(google_chat.client._api_client.vertexai)
        google_chat.client.close()
        asyncio.run(google_chat.client.aio.aclose())


if __name__ == "__main__":
    unittest.main()

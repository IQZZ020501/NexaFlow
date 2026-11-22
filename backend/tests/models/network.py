"""Member model connections cannot reach host/private networks or host credentials."""

import asyncio
import socket
import unittest
from unittest.mock import AsyncMock, patch

from app.adapters.llm.network import (
    PUBLIC_ENDPOINT_CREDENTIAL,
    PublicAsyncBackend,
    PublicSyncBackend,
    public_async_client,
    public_client,
    validate_member_connection,
)
from app.adapters.llm.runtime import build_chat_model, build_embeddings, build_reranker
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


if __name__ == "__main__":
    unittest.main()

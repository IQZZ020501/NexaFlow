"""Real SDK response handling without paid requests or external networking."""

import asyncio
import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from app.adapters.llm import image as image_adapter
from app.ports.llm import ModelProviderError

PNG = image_adapter.PNG_SIGNATURE + b"response-fixture"


class ImageResponseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.close_budget = patch.object(
            image_adapter, "IMAGE_CLOSE_TIMEOUT_SECONDS", 0.02, create=True
        )
        self.close_budget.start()
        self.addCleanup(self.close_budget.stop)

    async def asyncTearDown(self):
        pending = list(getattr(image_adapter, "_image_cleanup_tasks", ()))
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 1)
        self.assertTrue(self.state["response_closed"])
        self.assertTrue(self.state["client_closed"])

    async def generate(
        self, payload=None, *, end_body=True, close_mode="normal", chunks=None
    ):
        wire = json.dumps(
            payload
            if payload is not None
            else {
                "data": [{"b64_json": base64.b64encode(PNG).decode()}],
                "revised_prompt": '一张测试图片，包含括号 } 和转义引号 "。',
            },
            ensure_ascii=False,
        ).encode()
        state = {"requests": 0, "response_closed": False, "client_closed": False}
        self.state = state

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks if chunks is not None else (wire[:31], wire[31:]):
                    yield chunk
                if not end_body:
                    await asyncio.Event().wait()

            async def aclose(self):
                state["response_closed"] = True
                if close_mode == "response_stalls":
                    await asyncio.Event().wait()

        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                state["requests"] += 1
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    stream=Body(),
                )

            async def aclose(self):
                state["client_closed"] = True
                if close_mode == "client_stalls":
                    await asyncio.Event().wait()
                if close_mode == "client_error":
                    raise OSError("fixture close failure")

        def client(**options):
            return AsyncOpenAI(
                **options, http_client=httpx.AsyncClient(transport=Transport())
            )

        with (
            patch.object(image_adapter, "AsyncOpenAI", client),
            patch.object(
                image_adapter,
                "_registered_model_credentials",
                return_value={
                    "api_key": "fixture-only",
                    "api_base": "https://image-fixture.invalid/v1",
                },
            ),
        ):
            async with asyncio.timeout(1):
                return await image_adapter.generate_registered_image(
                    SimpleNamespace(
                        id="image-model",
                        provider="model_openai_provider",
                        model_name="gpt-image-1",
                        meta={},
                    ),
                    SimpleNamespace(model_request_timeout_seconds=60),
                    "Test image",
                    "portrait",
                    "2K",
                )

    async def test_complete_json_response(self):
        self.assertEqual(await self.generate(), PNG)
        self.assertEqual(self.state["requests"], 1)

    async def test_complete_image_does_not_wait_for_body_eof(self):
        self.assertEqual(await self.generate(end_body=False), PNG)
        self.assertEqual(self.state["requests"], 1)

    async def test_complete_image_does_not_wait_for_client_close(self):
        self.assertEqual(await self.generate(close_mode="client_stalls"), PNG)

    async def test_complete_image_does_not_wait_for_response_close(self):
        self.assertEqual(await self.generate(close_mode="response_stalls"), PNG)

    async def test_close_errors_do_not_discard_a_completed_image(self):
        self.assertEqual(await self.generate(close_mode="client_error"), PNG)

    async def test_truncated_json_is_not_a_completed_image(self):
        with self.assertRaises(TimeoutError):
            await self.generate(
                end_body=False, chunks=[b'{"data":[{"b64_json":"iVBORw0KGgo=']
            )

    async def test_invalid_payloads_do_not_produce_images(self):
        for payload in (
            {},
            {"data": []},
            {"data": [None]},
            {"data": [{"b64_json": "invalid base64!"}]},
            {"data": [{"b64_json": base64.b64encode(b"not-png").decode()}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ModelProviderError):
                await self.generate(payload)

    async def test_response_size_limit_applies_before_eof(self):
        with patch.object(image_adapter, "MAX_IMAGE_RESPONSE_BYTES", 256, create=True):
            with self.assertRaises(ModelProviderError):
                await self.generate(chunks=[b" " * 257], end_body=False)

    async def test_eof_with_invalid_json_is_rejected(self):
        with self.assertRaises(ModelProviderError):
            await self.generate(chunks=[b'{"data":'])

    async def test_received_bytes_are_not_logged(self):
        with self.assertLogs("NexaFlow.app.adapters.llm.image", level="INFO") as logs:
            self.assertEqual(await self.generate(), PNG)
            await asyncio.sleep(0)
        text = "\n".join(logs.output)
        self.assertNotIn(base64.b64encode(PNG).decode(), text)
        self.assertNotIn("fixture-only", text)
        self.assertNotIn("Test image", text)


if __name__ == "__main__":
    unittest.main()

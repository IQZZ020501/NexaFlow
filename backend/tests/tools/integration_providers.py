"""HTTP contract checks without sending credentials to external providers."""

import base64
import hashlib
import json
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx2

from app.adapters.integrations import client
from app.ports.integrations import IntegrationProviderError
from app.ports.mcp import McpClientError


class ProviderContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.response = httpx2.Response(200, json={})

        async def handler(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def factory(**_kwargs):
            return httpx2.AsyncClient(
                transport=httpx2.MockTransport(handler),
                follow_redirects=False,
                trust_env=False,
            )

        self.destination = patch.object(
            client, "validate_mcp_destination", AsyncMock(return_value=object())
        )
        self.transport = patch.object(client, "_hardened_http_client_factory", factory)
        self.destination.start()
        self.transport.start()
        self.addCleanup(self.destination.stop)
        self.addCleanup(self.transport.stop)

    async def test_dida_registers_a_public_client_for_the_web_callback(self):
        redirect_uri = "https://nexaflow.example/app/tools/integrations/callback"
        self.response = httpx2.Response(
            201,
            json={
                "client_id": "registered-public-client",
                "token_endpoint_auth_method": "none",
                "redirect_uris": [redirect_uri],
            },
        )
        result = await client.register_public_client(
            "dida", redirect_uri, ["tasks:read", "tasks:write"]
        )
        self.assertEqual(result, "registered-public-client")
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://api.dida365.com/oauth/register")
        self.assertNotIn("authorization", request.headers)
        self.assertEqual(
            json.loads(request.content),
            {
                "client_name": "NexaFlow",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "tasks:read tasks:write",
            },
        )

    async def test_dida_rejects_invalid_or_confidential_registrations(self):
        callback = "https://nexaflow.example/callback"
        registration = {
            "client_id": "registered",
            "token_endpoint_auth_method": "none",
            "redirect_uris": [callback],
        }
        for changes in (
            {"client_id": ""},
            {"client_id": "x\nunsafe"},
            {"client_id": "x" * 257},
            {"token_endpoint_auth_method": "client_secret_basic"},
            {"redirect_uris": ["http://localhost:8766/callback"]},
        ):
            with self.subTest(changes=changes):
                self.response = httpx2.Response(201, json={**registration, **changes})
                with self.assertRaises(IntegrationProviderError):
                    await client.register_public_client(
                        "dida", callback, ["tasks:read", "tasks:write"]
                    )

    async def test_dida_exchanges_pkce_code_without_a_client_secret(self):
        self.response = httpx2.Response(200, json={"access_token": "access"})
        await client.exchange_tokens(
            "dida",
            "client",
            "",
            grant_type="authorization_code",
            code="short-code",
            code_verifier="private-verifier",
            redirect_uri="https://nexaflow.example/callback",
        )
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://api.dida365.com/oauth/token")
        self.assertNotIn("authorization", request.headers)
        self.assertEqual(
            parse_qs(request.content.decode()),
            {
                "grant_type": ["authorization_code"],
                "code": ["short-code"],
                "client_id": ["client"],
                "code_verifier": ["private-verifier"],
                "redirect_uri": ["https://nexaflow.example/callback"],
            },
        )
        query = parse_qs(
            urlparse(
                client.authorization_url(
                    "dida",
                    "client",
                    "https://nexaflow.example/callback",
                    "state",
                    "private-verifier",
                    ["tasks:read", "tasks:write"],
                )
            ).query
        )
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(
            query["code_challenge"],
            [
                base64.urlsafe_b64encode(hashlib.sha256(b"private-verifier").digest())
                .rstrip(b"=")
                .decode()
            ],
        )
        self.assertNotIn("code_verifier", query)

    async def test_dida_has_no_confidential_client_or_non_pkce_fallback(self):
        for secret, values in (
            (
                "old-secret",
                {"grant_type": "authorization_code", "code_verifier": "verifier"},
            ),
            ("", {"grant_type": "authorization_code"}),
            ("", {"grant_type": "refresh_token", "code_verifier": "verifier"}),
        ):
            with self.subTest(secret=secret, values=values):
                with self.assertRaises(IntegrationProviderError):
                    await client.exchange_tokens("dida", "client", secret, **values)
        self.assertEqual(self.requests, [])

    async def test_feishu_exchanges_code_and_refresh_through_registered_application(
        self,
    ):
        self.response = httpx2.Response(200, json={"access_token": "access"})
        await client.exchange_tokens(
            "feishu",
            "client",
            "secret",
            grant_type="authorization_code",
            code="short-code",
            code_verifier="pkce-verifier",
            redirect_uri="https://app.example/callback",
        )
        request = self.requests[0]
        values = json.loads(request.content)
        self.assertEqual(
            str(request.url), "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
        )
        self.assertEqual(values["client_secret"], "secret")
        self.assertEqual(values["code_verifier"], "pkce-verifier")
        await client.exchange_tokens(
            "feishu",
            "client",
            "secret",
            grant_type="refresh_token",
            refresh_token="refresh",
        )
        self.assertEqual(
            json.loads(self.requests[1].content)["grant_type"], "refresh_token"
        )

    async def test_tencent_device_authorization_uses_official_json_contract(self):
        self.response = httpx2.Response(
            200, json={"code": 0, "data": {"auth_code": "user-code"}}
        )
        result = await client.device_authorization(
            "init", {"device_id": "private-random-device"}
        )
        self.assertEqual(result, {"auth_code": "user-code"})
        self.assertEqual(
            str(self.requests[0].url),
            "https://work.medialab.qq.com/v2/oauth2/oauth/cli-oauth-init",
        )
        self.assertEqual(
            json.loads(self.requests[0].content), {"device_id": "private-random-device"}
        )

    async def test_application_operations_never_put_tokens_in_arguments_or_urls(self):
        await client.call_integration(
            "dida",
            "create_task",
            {"project_id": "work", "title": "Task"},
            {"access_token": "private-token"},
            "invocation",
        )
        request = self.requests[0]
        self.assertEqual(request.headers["authorization"], "Bearer private-token")
        self.assertNotIn("private-token", str(request.url))
        self.assertEqual(
            json.loads(request.content),
            {"projectId": "work", "title": "Task"},
        )
        await client.call_integration(
            "feishu",
            "send_message",
            {"open_id": "user", "text": "Message"},
            {"access_token": "private-token"},
            "same-invocation",
        )
        await client.call_integration(
            "feishu",
            "send_message",
            {"open_id": "user", "text": "Message"},
            {"access_token": "private-token"},
            "same-invocation",
        )
        self.assertEqual(
            json.loads(self.requests[1].content)["uuid"],
            json.loads(self.requests[2].content)["uuid"],
        )
        await client.call_integration(
            "tencent_meeting",
            "list_meetings",
            {},
            {
                "access_token": "meeting-token",
                "open_id": "owner",
                "device_id": "authorized-device",
            },
            "invocation",
        )
        self.assertEqual(self.requests[3].headers["AccessToken"], "meeting-token")
        self.assertEqual(self.requests[3].headers["OpenId"], "owner")

    async def test_tencent_reads_use_the_device_and_source_bound_to_authorization(self):
        credentials = {
            "access_token": "meeting-token",
            "open_id": "owner",
            "device_id": "authorized-device",
        }
        for operation, arguments in (
            ("list_meetings", {}),
            ("get_meeting", {"meeting_id": "meeting-123"}),
        ):
            await client.call_integration(
                "tencent_meeting", operation, arguments, credentials, operation
            )
            request = self.requests[-1]
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers["Tmeet-Open-Source"], "CLI")
            self.assertEqual(
                request.headers["Tmeet-Unique-ID"], "owner*authorized-device"
            )
            self.assertNotIn("authorized-device", str(request.url))

    async def test_tencent_expired_grants_are_detected_from_business_error_codes(self):
        for status, error_info in (
            (400, {"new_error_code": 200190303}),
            (400, {"error_code": 190303}),
            (200, {"new_error_code": 200190303}),
        ):
            with self.subTest(status=status, error_info=error_info):
                self.response = httpx2.Response(
                    status,
                    json={
                        "error_info": {
                            **error_info,
                            "message": "private-provider-details do-not-echo-token",
                        }
                    },
                )
                before = len(self.requests)
                with self.assertRaises(IntegrationProviderError) as error:
                    await client.call_integration(
                        "tencent_meeting",
                        "list_meetings",
                        {},
                        {
                            "access_token": "do-not-echo-token",
                            "open_id": "owner",
                            "device_id": "authorized-device",
                        },
                        "invocation",
                    )
                self.assertTrue(error.exception.unauthorized)
                self.assertFalse(error.exception.uncertain)
                self.assertEqual(
                    str(error.exception),
                    "Integration authorization expired. Please install again.",
                )
                self.assertEqual(len(self.requests), before + 1)

    async def test_rejects_resource_path_injection_before_dispatch(self):
        for identifier in ("../other", "x/y", "x?token=y", "x%2Fy"):
            with self.assertRaises(IntegrationProviderError):
                await client.call_integration(
                    "feishu",
                    "read_document",
                    {"document_id": identifier},
                    {"access_token": "token"},
                    "invocation",
                )
        self.assertEqual(self.requests, [])

    async def test_errors_are_sanitized_and_write_uncertainty_is_preserved(self):
        for status, uncertain in ((401, False), (403, False), (500, True)):
            self.response = httpx2.Response(
                status,
                json={
                    "access_token": "do-not-echo-token",
                    "diagnostic": "private-provider-details",
                },
            )
            with self.assertRaises(IntegrationProviderError) as error:
                await client._request("POST", "https://api.dida365.com/open/v1/task")
            self.assertEqual(error.exception.uncertain, uncertain)
            self.assertEqual(error.exception.unauthorized, status == 401)
            self.assertNotIn("do-not-echo-token", str(error.exception))
            self.assertNotIn("private-provider-details", str(error.exception))
        self.response = httpx2.ReadTimeout("provider timeout")
        with self.assertRaises(IntegrationProviderError) as error:
            await client._request("POST", "https://api.dida365.com/open/v1/task")
        self.assertTrue(error.exception.uncertain)
        self.response = httpx2.ConnectError("connection refused")
        with self.assertRaises(IntegrationProviderError) as error:
            await client._request("POST", "https://api.dida365.com/open/v1/task")
        self.assertFalse(error.exception.uncertain)

    async def test_disallowed_destination_is_a_confirmed_failure_before_http(self):
        with patch.object(
            client,
            "validate_mcp_destination",
            AsyncMock(side_effect=McpClientError("disallowed")),
        ):
            with self.assertRaises(IntegrationProviderError) as error:
                await client._request("POST", "https://api.dida365.com/open/v1/task")
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(self.requests, [])

    async def test_response_limit_does_not_claim_a_dispatched_write_failed_safely(self):
        self.response = httpx2.Response(200, content=b"x" * 2048)
        with self.assertRaises(IntegrationProviderError) as error:
            await client._request(
                "POST", "https://api.dida365.com/open/v1/task", limit=1024
            )
        self.assertTrue(error.exception.uncertain)


if __name__ == "__main__":
    unittest.main()

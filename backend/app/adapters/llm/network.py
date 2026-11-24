"""Public-only connections for member-configured model endpoints.

Resolve and validate at the TCP boundary, then connect to the validated IP.
TLS still uses the original hostname; SDK redirects and environment proxies
cannot bypass the destination check.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpcore
import httpx

from app.adapters.llm.response_limits import ResponseBudget, active_probe
from app.ports.llm import PUBLIC_ENDPOINT_CREDENTIAL, ModelProviderError

URL_FIELDS = ("api_base", "azure_endpoint", "endpoint_url")
TRANSPORT_PARAMS = {
    "anthropic_api_key",
    "anthropic_api_url",
    "anthropic_proxy",
    "async_client",
    "async_client_kwargs",
    "base_model_id",
    "bedrock_api_key",
    "bedrock_client",
    "cache",
    "client",
    "client_args",
    "credentials_profile_name",
    "http_async_client",
    "http_client",
    "http_options",
    "http_socket_options",
    "location",
    "model_id",
    "openai_api_base",
    "openai_api_key",
    "openai_organization",
    "openai_proxy",
    "profile",
    "project",
    "root_async_client",
    "root_client",
    "sync_client_kwargs",
    "transport",
    "validate_model_on_init",
    "vertexai",
}


def public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        addresses = tuple(
            dict.fromkeys(
                row[4][0]
                for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        )
        if not addresses or any(
            not ipaddress.ip_address(address).is_global
            or ipaddress.ip_address(address).is_multicast
            or ipaddress.ip_address(address).is_reserved
            for address in addresses
        ):
            raise ValueError("Non-public destination")
    except (ValueError, OSError) as exc:
        raise ModelProviderError(
            "Member model endpoints must use public network addresses."
        ) from exc
    return addresses


def validate_member_connection(provider_type, credentials, request_params):
    if TRANSPORT_PARAMS.intersection(request_params):
        raise ModelProviderError(
            "Member model parameters cannot override connection settings."
        )
    if provider_type == "bedrock":
        if not credentials.get("aws_access_key_id") or not credentials.get(
            "aws_secret_access_key"
        ):
            raise ModelProviderError(
                "Personal Bedrock models require explicit AWS credentials."
            )
        # Botocore has its own transport; only its official Bedrock endpoint is
        # accepted for untrusted configurations, never host credential discovery.
        region = credentials.get("region_name", "")
        if not region or any(
            c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in region
        ):
            raise ModelProviderError("Invalid Bedrock region.")
        endpoint = credentials.get("endpoint_url")
        suffix = "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com"
        if (
            endpoint
            and endpoint.rstrip("/") != f"https://bedrock-runtime.{region}.{suffix}"
        ):
            raise ModelProviderError(
                "Personal Bedrock models require the official regional endpoint."
            )
    for field in URL_FIELDS:
        url = credentials.get(field)
        if not url:
            continue
        parsed = urlparse(url)
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or any(ord(c) < 33 or c == "\\" for c in url)
            ):
                raise ValueError()
        except ValueError as exc:
            raise ModelProviderError("Invalid member model endpoint.") from exc
        public_addresses(parsed.hostname, port)


class _DeadlineStream(httpcore.NetworkStream):
    """Apply the same deadline to header, framing, and body reads at the socket."""

    def __init__(self, stream, budget: ResponseBudget):
        self.stream = stream
        self.budget = budget

    def read(self, max_bytes, timeout=None):
        return self.stream.read(max_bytes, self.budget.remaining_time(timeout))

    def write(self, buffer, timeout=None):
        self.stream.write(buffer, self.budget.remaining_time(timeout))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        try:
            stream = self.stream.start_tls(
                ssl_context, server_hostname, self.budget.remaining_time(timeout)
            )
        except BaseException:
            self.stream.close()
            raise
        return _DeadlineStream(stream, self.budget)

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)

    def close(self):
        self.stream.close()


class PublicSyncBackend(httpcore.SyncBackend):
    def __init__(self, budget: ResponseBudget | None = None):
        self.budget = budget

    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        addresses = public_addresses(host, port)
        error = None
        for address in addresses:
            try:
                remaining = self.budget.remaining_time(timeout) if self.budget else timeout
                stream = super().connect_tcp(
                    address, port, remaining, local_address, socket_options
                )
                return _DeadlineStream(stream, self.budget) if self.budget else stream
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error

    def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("Model Unix sockets are not allowed.")


class PublicAsyncBackend(httpcore.AnyIOBackend):
    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        addresses = await asyncio.to_thread(public_addresses, host, port)
        error = None
        for address in addresses:
            try:
                return await super().connect_tcp(
                    address, port, timeout, local_address, socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("Model Unix sockets are not allowed.")


def public_transport(*, asynchronous=False, budget=None):
    transport = (
        httpx.AsyncHTTPTransport(trust_env=False)
        if asynchronous
        else httpx.HTTPTransport(trust_env=False)
    )
    # Same pinned-backend approach as the MCP adapter, for the HTTPX version
    # required by the model SDKs. Covered by actual TCP target regressions.
    transport._pool._network_backend = (
        PublicAsyncBackend() if asynchronous else PublicSyncBackend(budget or active_probe.get())
    )
    return transport


def public_client(timeout=60, *, budget=None):
    probe = active_probe.get()
    budget = budget or probe
    client = httpx.Client(
        event_hooks=budget.hooks() if budget else None,
        transport=public_transport(budget=budget),
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
    )
    if probe:
        probe.resources.callback(client.close)
    return client


def public_async_client(timeout=60):
    return httpx.AsyncClient(
        transport=public_transport(asynchronous=True),
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
    )


def public_client_options(credentials, timeout=60):
    if credentials.get(PUBLIC_ENDPOINT_CREDENTIAL) != "true":
        probe = active_probe.get()
        if probe:
            client = httpx.Client(
                timeout=timeout, event_hooks=probe.hooks(), follow_redirects=True
            )
            probe.resources.callback(client.close)
            return {"http_client": client}
        return {}
    return {
        "http_client": public_client(timeout),
        "http_async_client": public_async_client(timeout),
    }

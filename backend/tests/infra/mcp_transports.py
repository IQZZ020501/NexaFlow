"""Real HTTP transports and isolated stdio execution-port regression checks."""

import asyncio
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import tests.support  # noqa: F401  (sets required env before app imports)
from tests.support import settings

from app.adapters.mcp.client import (
    McpClientError,
    McpConnection,
    call_mcp_tool,
    discover_mcp_tools,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_MODULE = "tests.support.mcp_test_server"
TOKEN = "transport-test-token"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def start_http_server(transport: str) -> tuple[subprocess.Popen[bytes], str]:
    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            TEST_MODULE,
            "--transport",
            transport,
            "--port",
            str(port),
            "--token",
            TOKEN,
        ],
        cwd=BACKEND_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(500):
        if process.poll() is not None:
            raise AssertionError(f"MCP test server exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                path = "/sse/" if transport == "sse" else "/mcp"
                return process, f"http://127.0.0.1:{port}{path}"
        except OSError:
            import time

            time.sleep(0.02)
    process.terminate()
    raise AssertionError("MCP test server did not start")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


async def assert_remote_transport(transport: str) -> None:
    process, url = start_http_server(transport)
    try:
        runtime_settings = replace(
            settings(),
            mcp_allow_private_networks=True,
            mcp_request_timeout_seconds=5,
        )
        connection = McpConnection(
            transport="sse" if transport == "sse" else "streamable_http",
            url=url,
            bearer_token=TOKEN,
            network_policy="deployment",
        )
        discovery = await discover_mcp_tools(connection, runtime_settings)
        assert {tool["name"] for tool in discovery.tools} == {"echo", "wait"}
        result = await call_mcp_tool(
            connection,
            runtime_settings,
            "echo",
            {"message": transport},
        )
        assert not result.is_error
        assert result.structured_content["message"] == transport

        try:
            await discover_mcp_tools(
                replace(connection, bearer_token="wrong"), runtime_settings
            )
        except McpClientError:
            pass
        else:
            raise AssertionError(f"{transport} accepted an invalid bearer token")
    finally:
        stop_process(process)


async def assert_stdio_transport() -> None:
    from tests.execution.unit import assert_stdio_dispatch

    await assert_stdio_dispatch()


async def assert_execution_cancellation() -> None:
    from tests.execution.unit import assert_failure_and_cancellation_cleanup

    await assert_failure_and_cancellation_cleanup()


async def run_suite() -> None:
    await assert_remote_transport("streamable-http")
    await assert_remote_transport("sse")
    await assert_stdio_transport()
    await assert_execution_cancellation()


def main() -> None:
    asyncio.run(run_suite())
    print("MCP_TRANSPORTS_SUITE_OK")


if __name__ == "__main__":
    main()

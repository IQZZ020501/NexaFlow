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


async def assert_run_session_reuse() -> None:
    from unittest.mock import patch

    from app.adapters.mcp import client as client_module
    from app.adapters.mcp import sessions
    from app.adapters.mcp.sessions import session_pool
    from app.ports.execution import ExecutionScope, execution_scope
    from app.ports.mcp import close_mcp_run_sessions

    process, url = start_http_server("streamable-http")
    original_client = client_module.Client
    opened: list[str] = []

    def counting_client(*args, **kwargs):
        opened.append(url)
        return original_client(*args, **kwargs)

    runtime_settings = replace(
        settings(),
        mcp_allow_private_networks=True,
        mcp_request_timeout_seconds=5,
    )
    connection = McpConnection(
        transport="streamable_http",
        url=url,
        bearer_token=TOKEN,
        network_policy="deployment",
    )

    async def echo(message: str, config=runtime_settings) -> str:
        result = await call_mcp_tool(connection, config, "echo", {"message": message})
        return result.structured_content["message"]

    try:
        with patch.object(client_module, "Client", side_effect=counting_client):
            scope = execution_scope.set(ExecutionScope("tenant-a", "call-1", "run-reuse"))
            try:
                assert await asyncio.gather(echo("one"), echo("two")) == ["one", "two"]
                assert await echo("three") == "three"
                assert len(opened) == 1

                try:
                    await call_mcp_tool(
                        connection,
                        replace(runtime_settings, mcp_request_timeout_seconds=0.2),
                        "wait",
                        {"seconds": 2},
                    )
                except McpClientError as exc:
                    assert exc.request_sent
                else:
                    raise AssertionError("A timed-out MCP call was accepted")
                assert await echo("four") == "four"
                assert len(opened) == 2
            finally:
                execution_scope.reset(scope)

            other = execution_scope.set(ExecutionScope("tenant-a", "call-2", "run-other"))
            try:
                assert await echo("other") == "other"
                assert len(opened) == 3
            finally:
                execution_scope.reset(other)

            with patch.object(sessions, "IDLE_SECONDS", 0.2):
                idle = execution_scope.set(ExecutionScope("tenant-a", "call-4", "run-idle"))
                try:
                    assert await echo("idle") == "idle"
                finally:
                    execution_scope.reset(idle)
                await asyncio.sleep(0.6)
                assert all(
                    key.run_id != "run-idle" for key in session_pool()._sessions
                )

            await close_mcp_run_sessions("run-reuse")
            await close_mcp_run_sessions("run-other")
            assert not session_pool()._sessions

        dead = replace(connection, url=f"http://127.0.0.1:{free_port()}/mcp")
        for run_id in (None, "run-dead"):
            scope = (
                execution_scope.set(ExecutionScope("tenant-a", "call-3", run_id))
                if run_id
                else None
            )
            try:
                await call_mcp_tool(dead, runtime_settings, "echo", {"message": "x"})
            except McpClientError as exc:
                assert not exc.request_sent
            else:
                raise AssertionError("An unreachable MCP server accepted a call")
            finally:
                if scope is not None:
                    execution_scope.reset(scope)
    finally:
        stop_process(process)


async def assert_execution_cancellation() -> None:
    from tests.execution.unit import assert_failure_and_cancellation_cleanup

    await assert_failure_and_cancellation_cleanup()


async def run_suite() -> None:
    await assert_remote_transport("streamable-http")
    await assert_remote_transport("sse")
    await assert_run_session_reuse()
    await assert_stdio_transport()
    await assert_execution_cancellation()


def main() -> None:
    asyncio.run(run_suite())
    print("MCP_TRANSPORTS_SUITE_OK")


if __name__ == "__main__":
    main()

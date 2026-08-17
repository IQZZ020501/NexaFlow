"""Real-process regression checks for all supported MCP transports."""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import tests.support  # noqa: F401  (sets required env before app imports)

from app.capabilities.mcp.client import (
    McpClientError,
    McpConnection,
    call_mcp_tool,
    discover_mcp_tools,
)
from app.infrastructure.mcp_stdio import McpStdioConfig, parse_mcp_stdio_config
from tests.support import settings


BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_MODULE = "tests.mcp_test_server"
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
        content, is_error = await call_mcp_tool(
            connection,
            runtime_settings,
            "echo",
            {"message": transport},
        )
        assert not is_error
        assert json.loads(content)["message"] == transport

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


def stdio_config(*extra_args: str, pid_file: str | None = None) -> McpStdioConfig:
    args = ["-m", TEST_MODULE, "--transport", "stdio", *extra_args]
    if pid_file is not None:
        args.extend(["--pid-file", pid_file])
    return parse_mcp_stdio_config(
        {
            "command": sys.executable,
            "args": args,
            "cwd": str(BACKEND_DIR),
            "env": {"NEXAFLOW_TEST_MCP_CONFIG_SECRET": "configured-in-form"},
        }
    )


async def assert_stdio_transport() -> None:
    env_name = "NEXAFLOW_TEST_MCP_CONFIG_SECRET"
    unlisted_env_name = "NEXAFLOW_TEST_MCP_UNLISTED_SECRET"
    previous_value = os.environ.get(env_name)
    previous_unlisted_value = os.environ.get(unlisted_env_name)
    os.environ[env_name] = "first-value"
    os.environ[unlisted_env_name] = "must-not-be-forwarded"
    try:
        runtime_settings = replace(
            settings(),
            mcp_request_timeout_seconds=5,
        )
        connection = McpConnection(transport="stdio", stdio_config=stdio_config())
        discovery = await discover_mcp_tools(connection, runtime_settings)
        assert {tool["name"] for tool in discovery.tools} == {"echo", "wait"}

        content, is_error = await call_mcp_tool(
            connection,
            runtime_settings,
            "echo",
            {"message": "stdio"},
        )
        assert not is_error
        assert json.loads(content) == {
            "message": "stdio",
            "config_secret_present": True,
            "unlisted_secret_present": False,
        }
    finally:
        if previous_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous_value
        if previous_unlisted_value is None:
            os.environ.pop(unlisted_env_name, None)
        else:
            os.environ[unlisted_env_name] = previous_unlisted_value


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def assert_stdio_timeout_reaps_process() -> None:
    env_name = "NEXAFLOW_TEST_MCP_CONFIG_SECRET"
    previous_value = os.environ.get(env_name)
    os.environ[env_name] = "timeout-test"
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = str(Path(temp_dir) / "server.pid")
            runtime_settings = replace(
                settings(),
                mcp_request_timeout_seconds=0.2,
            )
            try:
                await discover_mcp_tools(
                    McpConnection(
                        transport="stdio",
                        stdio_config=stdio_config(
                            "--startup-delay",
                            "10",
                            pid_file=pid_file,
                        ),
                    ),
                    runtime_settings,
                )
            except McpClientError:
                pass
            else:
                raise AssertionError("Slow stdio server did not time out")

            pid_path = Path(pid_file)
            for _ in range(100):
                if pid_path.exists():
                    break
                await asyncio.sleep(0.05)
            assert pid_path.exists(), "Slow stdio server did not start"
            pid = int(pid_path.read_text(encoding="utf-8"))
            for _ in range(40):
                if not process_exists(pid):
                    break
                await asyncio.sleep(0.05)
            assert not process_exists(pid), "Timed-out stdio process was not reaped"
    finally:
        if previous_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous_value


async def run_suite() -> None:
    await assert_remote_transport("streamable-http")
    await assert_remote_transport("sse")
    await assert_stdio_transport()
    await assert_stdio_timeout_reaps_process()


def main() -> None:
    asyncio.run(run_suite())
    print("MCP_TRANSPORTS_SUITE_OK")


if __name__ == "__main__":
    main()

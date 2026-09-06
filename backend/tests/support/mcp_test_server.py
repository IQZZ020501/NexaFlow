"""Small real MCP server used by the transport regression suite."""

import argparse
import asyncio
import os
import time
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer


class BearerAuth:
    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            if headers.get(b"authorization") != b"Bearer " + self.token:
                body = b"Unauthorized"
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-length", str(len(body)).encode())],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        required=True,
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default="")
    parser.add_argument("--pid-file")
    parser.add_argument("--startup-delay", type=float, default=0)
    args = parser.parse_args()

    if args.pid_file:
        Path(args.pid_file).write_text(str(os.getpid()), encoding="utf-8")
    if args.startup_delay:
        time.sleep(args.startup_delay)

    server = MCPServer("nexaflow-transport-test", log_level="ERROR")

    @server.tool()
    def echo(message: str) -> dict[str, object]:
        return {
            "message": message,
            "config_secret_present": bool(
                os.environ.get("NEXAFLOW_TEST_MCP_CONFIG_SECRET")
            ),
            "unlisted_secret_present": bool(
                os.environ.get("NEXAFLOW_TEST_MCP_UNLISTED_SECRET")
            ),
        }

    @server.tool()
    async def wait(seconds: float) -> str:
        await asyncio.sleep(seconds)
        return "done"

    if args.transport == "stdio":
        server.run("stdio")
        return

    app = (
        server.sse_app(sse_path="/sse/", message_path="/messages/")
        if args.transport == "sse"
        else server.streamable_http_app(stateless_http=True)
    )
    if args.token:
        app = BearerAuth(app, args.token)
    uvicorn.run(app, host=args.host, port=args.port, log_level="error")


if __name__ == "__main__":
    main()

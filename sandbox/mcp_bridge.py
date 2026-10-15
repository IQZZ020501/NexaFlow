"""One stdio server per guest, exposed only through authenticated MCP HTTP."""

import asyncio
import hmac
import json
import sys
from pathlib import Path

import uvicorn
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.lowlevel import Server
from starlette.responses import JSONResponse
from starlette.routing import Route

TOKEN_HEADER = b"x-nexaflow-mcp-token"


class TokenAuth:
    def __init__(self, app, token):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            value = dict(scope["headers"]).get(TOKEN_HEADER, b"")
            if not hmac.compare_digest(value, self.expected):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def serve(payload):
    config = payload["config"]
    token = payload["token"]
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise ValueError("Invalid bridge token.")
    transport = stdio_client(StdioServerParameters(command=config["command"], args=config.get("args", []), cwd=config.get("cwd"), env=config.get("env", {})))
    async with Client(transport, cache=None, read_timeout_seconds=300) as client:
        async def list_tools(_context, params):
            return await client.list_tools(cursor=params.cursor if params else None, cache_mode="reload")

        async def call_tool(_context, params):
            return await client.call_tool(params.name, params.arguments or {}, meta=params.meta, read_timeout_seconds=300)

        async def health(_request):
            return JSONResponse({"ready": True})

        server = Server("nexaflow-stdio-bridge", on_list_tools=list_tools, on_call_tool=call_tool)
        app = server.streamable_http_app(host="0.0.0.0", custom_starlette_routes=[Route("/health", health)], max_request_body_size=8 * 1024 * 1024)
        await uvicorn.Server(uvicorn.Config(TokenAuth(app, token), host="0.0.0.0", port=18081, log_level="error", access_log=False)).serve()


def main():
    payload = Path(sys.argv[1]).read_bytes()
    if len(payload) > 256 * 1024:
        raise ValueError("Bridge configuration is too large.")
    asyncio.run(serve(json.loads(payload)))


if __name__ == "__main__":
    main()

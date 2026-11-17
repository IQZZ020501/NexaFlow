"""Framework-free host example; run after installing the extension API."""

import asyncio

from nexaflow_extension_api import (
    AgentExtension,
    AgentToolResult,
    require_api_version,
)


async def add_context(messages: list[str]) -> list[str]:
    return [*messages, "Trusted host context"]


async def decorate(name, arguments, result):
    return AgentToolResult(content=result.content, summary=f"{name}: checked")


async def main():
    extension = AgentExtension[str, str](
        name="example", version="1.0.0", context=add_context, after_tool=decorate
    )
    require_api_version(extension.api_version)
    assert await extension.context(["Request"]) == ["Request", "Trusted host context"]
    result = await extension.after_tool(
        "echo", {}, AgentToolResult(content="Example", summary="Done")
    )
    assert result.summary == "echo: checked"
    print("TRUSTED_EXTENSION_HOST_OK")


if __name__ == "__main__":
    asyncio.run(main())

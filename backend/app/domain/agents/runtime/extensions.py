"""Trusted, code-owned extensions for the Agent harness.

Extensions supply capabilities and lifecycle hooks. Installing or executing
caller-supplied extension code is deliberately not part of this contract.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import StructuredTool

from app.domain.agents.runtime.tools import AgentToolResult


@dataclass(frozen=True)
class AgentExtension:
    name: str
    version: str
    tools: tuple[StructuredTool, ...] = ()
    context: Callable[[list[BaseMessage]], Awaitable[list[BaseMessage]]] | None = None
    before_tool: (
        Callable[[str, dict[str, Any]], Awaitable[AgentToolResult | None]] | None
    ) = None
    after_tool: (
        Callable[[str, dict[str, Any], AgentToolResult], Awaitable[AgentToolResult]]
        | None
    ) = None


class ExtensionRuntime:
    def __init__(self, extensions: list[AgentExtension]) -> None:
        if len({item.name for item in extensions}) != len(extensions):
            raise ValueError("Duplicate Agent extension names.")
        self.extensions = tuple(extensions)
        names = [tool.name for item in extensions for tool in item.tools]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate Agent capability names.")

    @property
    def tools(self) -> list[StructuredTool]:
        return [tool for item in self.extensions for tool in item.tools]

    async def prepare_context(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        for extension in self.extensions:
            if extension.context is not None:
                messages = await extension.context(list(messages))
        return messages

    async def before_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> AgentToolResult | None:
        for extension in self.extensions:
            if extension.before_tool is not None:
                result = await extension.before_tool(name, arguments)
                if result is not None:
                    return result
        return None

    async def after_tool(
        self, name: str, arguments: dict[str, Any], result: AgentToolResult
    ) -> AgentToolResult:
        for extension in self.extensions:
            if extension.after_tool is not None:
                result = await extension.after_tool(name, arguments, result)
        return result

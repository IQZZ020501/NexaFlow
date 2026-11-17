"""Stable contracts for trusted extensions, independent of the application."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

__version__ = "1.0.0"
API_VERSION = 1

Message = TypeVar("Message")
Tool = TypeVar("Tool")


def require_api_version(version: int) -> None:
    if type(version) is not int or version != API_VERSION:
        raise ValueError(f"Unsupported extension API version: {version!r}.")


@dataclass(frozen=True)
class AgentToolResult:
    content: str
    summary: str
    output: Any = None
    is_error: bool = False
    outcome_uncertain: bool = False
    evidence_ids: frozenset[str] = frozenset()
    full_result: str | None = None


class AgentExecutionPaused(Exception):
    """The host must persist state before continuing this call."""

    def __init__(self, call_id: str, reason: str) -> None:
        super().__init__(reason)
        self.call_id = call_id
        self.reason = reason


class AgentToolUncertain(AgentExecutionPaused):
    """A side effect may have happened without a durably recorded result."""


class AgentToolBusy(AgentExecutionPaused):
    """Another worker or resource currently owns the execution opportunity."""

    def __init__(
        self, call_id: str, reason: str, resource_wait: dict | None = None
    ) -> None:
        super().__init__(call_id, reason)
        self.resource_wait = resource_wait or {}


@dataclass(frozen=True)
class AgentExtension(Generic[Message, Tool]):
    name: str
    version: str
    tools: tuple[Tool, ...] = ()
    context: Callable[[list[Message]], Awaitable[list[Message]]] | None = None
    before_tool: (
        Callable[[str, dict[str, Any]], Awaitable[AgentToolResult | None]] | None
    ) = None
    after_tool: (
        Callable[[str, dict[str, Any], AgentToolResult], Awaitable[AgentToolResult]]
        | None
    ) = None
    api_version: int = API_VERSION


__all__ = [
    "API_VERSION",
    "AgentExecutionPaused",
    "AgentExtension",
    "AgentToolBusy",
    "AgentToolResult",
    "AgentToolUncertain",
    "require_api_version",
]

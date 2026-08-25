from collections.abc import Awaitable, Callable
from typing import Any

from app.shareddomain.agents.runtime.tools import AgentToolResult

MAX_EVENT_STRING_CHARS = 2000
MAX_EVENT_LIST_ITEMS = 20
SENSITIVE_FIELD_PARTS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
)

AgentEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


def safe_event_value(
    value: Any,
    field_name: str = "",
    *,
    max_string_chars: int = MAX_EVENT_STRING_CHARS,
) -> Any:
    normalized_field = field_name.lower()
    if any(part in normalized_field for part in SENSITIVE_FIELD_PARTS):
        return "[REDACTED]"
    if isinstance(value, str):
        return value[:max_string_chars]
    if isinstance(value, list):
        return [
            safe_event_value(item, max_string_chars=max_string_chars)
            for item in value[:MAX_EVENT_LIST_ITEMS]
        ]
    if isinstance(value, dict):
        return {
            str(key): safe_event_value(
                item,
                str(key),
                max_string_chars=max_string_chars,
            )
            for key, item in list(value.items())[:MAX_EVENT_LIST_ITEMS]
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_EVENT_STRING_CHARS]


class AgentEventBus:
    def __init__(self, subscribers: list[AgentEventHandler] | None = None) -> None:
        self._subscribers = tuple(subscribers or [])

    @property
    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    async def publish(self, event: dict[str, Any]) -> None:
        for subscriber in self._subscribers:
            await subscriber(event)


class NexaFlowCallback:
    def __init__(self, event_bus: AgentEventBus) -> None:
        self._event_bus = event_bus

    @property
    def enabled(self) -> bool:
        return self._event_bus.has_subscribers

    async def process(self, event: dict[str, Any]) -> None:
        await self._event_bus.publish({"type": "process", "event": event})

    async def answer_delta(self, delta: str) -> None:
        await self._event_bus.publish({"type": "answer_delta", "delta": delta})

    async def answer_reset(self) -> None:
        await self._event_bus.publish({"type": "answer_reset"})

    async def reasoning_delta(self, turn: int, delta: str) -> None:
        await self._event_bus.publish(
            {"type": "reasoning_delta", "turn": turn, "delta": delta}
        )

    async def tool_input_delta(
        self,
        *,
        turn: int,
        call_id: str,
        tool_name: str,
        field: str,
        delta: str,
        replace: bool,
    ) -> None:
        await self._event_bus.publish(
            {
                "type": "tool_input_delta",
                "turn": turn,
                "call_id": call_id,
                "tool_name": tool_name,
                "field": field,
                "delta": delta,
                "replace": replace,
            }
        )

    def thought(self, turn: int) -> dict[str, Any]:
        return {
            "type": "thought",
            "turn": turn,
            "tool_name": "",
            "status": "running",
            "summary": (
                "agent.analyzing" if turn == 1 else "agent.reviewing_tool_results"
            ),
            "call_id": "",
            "tool_label": "",
            "tool_kind": "unknown",
            "server_name": "",
            "input": {},
            "output": None,
            "reasoning": "",
        }

    def preparing_tool_event(
        self,
        *,
        turn: int,
        tool_name: str,
        call_id: str,
    ) -> dict[str, Any]:
        return {
            "type": "tool",
            "turn": turn,
            "tool_name": tool_name,
            "status": "running",
            "summary": "agent.preparing_tool_call",
            "call_id": call_id,
            "tool_label": tool_name,
            "tool_kind": "unknown",
            "server_name": "",
            "input": {},
            "output": None,
            "duration_ms": 0,
        }

    def tool_event(
        self,
        *,
        turn: int,
        tool_name: str,
        call_id: str,
        metadata: dict[str, str],
        input_value: Any,
        result: AgentToolResult | None = None,
    ) -> dict[str, Any]:
        if result is None:
            status = "running"
        elif result.is_error:
            status = "failed"
        else:
            status = "succeeded"
        return {
            "type": "tool",
            "turn": turn,
            "tool_name": tool_name,
            "status": status,
            "summary": "agent.tool_running" if result is None else result.summary,
            "call_id": call_id,
            "tool_label": metadata["display_name"],
            "tool_kind": metadata["kind"],
            "server_name": metadata["server_name"],
            "input": safe_event_value(input_value),
            "output": None if result is None else safe_event_value(result.output),
        }

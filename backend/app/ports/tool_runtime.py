"""Provider-neutral contracts for unified Tool execution."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from app.entities.tools import ToolKind, ToolRef, ToolSnapshot


@dataclass(frozen=True)
class ToolInvocationContext:
    workspace_id: str
    root_run_id: str
    run_id: str
    invocation_id: str
    execution_user_id: str
    access_source: str
    deadline_at: datetime
    idempotency_key: str


@dataclass(frozen=True)
class ToolRuntimeResult:
    ok: bool
    data: Any
    summary: str
    error_code: str | None
    error_message: str | None
    outcome: Literal["confirmed", "uncertain"]
    usage: dict[str, Any]


@runtime_checkable
class ToolAdapter(Protocol):
    kind: ToolKind

    async def invoke(
        self,
        snapshot: ToolSnapshot,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> ToolRuntimeResult: ...


__all__ = [
    "ToolAdapter",
    "ToolInvocationContext",
    "ToolRef",
    "ToolRuntimeResult",
    "ToolSnapshot",
]

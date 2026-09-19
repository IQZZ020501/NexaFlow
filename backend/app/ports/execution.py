"""Private execution capability; callers never select images or sandbox IDs."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.infra.config.settings import Settings


class ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionScope:
    workspace_id: str
    invocation_id: str
    run_id: str | None = None


execution_scope: ContextVar[ExecutionScope | None] = ContextVar(
    "execution_scope", default=None
)


class ExecutionPlatform(Protocol):
    async def execute(
        self, request: dict[str, Any], *, timeout_seconds: float, max_output_bytes: int
    ) -> dict[str, Any]: ...


def build_execution_platform(settings: "Settings") -> ExecutionPlatform:
    from app.adapters.execution.opensandbox import OpenSandboxExecution

    return OpenSandboxExecution(settings)

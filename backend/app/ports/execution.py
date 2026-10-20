"""Private execution capability; callers never select images or sandbox IDs."""

from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.infra.config.settings import Settings


class ExecutionError(RuntimeError):
    pass


class ExecutionNotStarted(ExecutionError):
    """Nothing ran: the request failed before the sandbox command started."""


class ExecutionOutcomeUnknown(ExecutionError):
    """The command may have run, but its result could not be confirmed."""


class ExecutionBusy(ExecutionNotStarted):
    """Sandbox capacity is exhausted; the same request may be retried later."""


@dataclass
class ExecutionAttempt:
    """Shared with the caller so an outer timeout retains dispatch evidence."""

    unconfirmed: bool = False


@dataclass(frozen=True)
class ExecutionScope:
    workspace_id: str
    invocation_id: str
    run_id: str | None = None
    worker_task_id: str | None = None
    attempt: ExecutionAttempt = field(default_factory=ExecutionAttempt, compare=False)


@dataclass(frozen=True)
class ExecutionBridge:
    url: str
    headers: dict[str, str]


execution_scope: ContextVar[ExecutionScope | None] = ContextVar(
    "execution_scope", default=None
)


class ExecutionPlatform(Protocol):
    async def execute(
        self, request: dict[str, Any], *, timeout_seconds: float, max_output_bytes: int
    ) -> dict[str, Any]: ...

    async def close_session(self, workspace_id: str, run_id: str) -> None: ...

    async def reclaim_sessions(self) -> None: ...

    def mcp_host(self, config: dict, domains: list[str], owner_key: str) -> AbstractAsyncContextManager[ExecutionBridge]: ...

    async def read_session_file(self, workspace_id: str, run_id: str, path: str, max_bytes: int) -> bytes: ...


def build_execution_platform(settings: "Settings") -> ExecutionPlatform:
    from app.adapters.execution.opensandbox import OpenSandboxExecution

    return OpenSandboxExecution(settings)


async def close_execution_session(
    settings: "Settings",
    workspace_id: str,
    run_id: str,
) -> None:
    await build_execution_platform(settings).close_session(workspace_id, run_id)

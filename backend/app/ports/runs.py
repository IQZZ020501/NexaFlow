"""Stable Run dispatch capability for API, Agent and Workflow producers."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.infra.config.settings import Settings


async def enqueue_agent_run(
    run_id: str,
    settings: "Settings",
    *,
    generation: str = "legacy",
) -> None:
    from app.bootstrap.runs import enqueue_agent_run as dispatch

    await dispatch(run_id, settings, generation=generation)


__all__ = [
    "enqueue_agent_run",
]

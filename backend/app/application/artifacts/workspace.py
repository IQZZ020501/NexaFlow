"""Restore authorized conversation files without retaining a live sandbox."""

import base64

from app.domain.artifacts.services import MAX_ARTIFACT_BYTES, artifact_workspace_path
from app.entities.runs import AgentRun
from app.infra.db.repositories.artifacts import repository
from app.infra.db.session import get_session_factory
from app.ports.execution import (
    ExecutionError,
    ExecutionNotStarted,
    ExecutionOutcomeUnknown,
    ExecutionPlatform,
)


async def restore_conversation_files(
    run: AgentRun, platform: ExecutionPlatform, *, timeout_seconds: float
) -> None:
    async with get_session_factory()() as db:
        files = await repository.list_conversation_files(db, run)
    # Fetch and transfer one bounded blob at a time, outside DB transactions.
    # The execution adapter stages each path once per guest, so another command
    # never overwrites in-progress edits or resurrects a deliberately removed file.
    for artifact_id, path, size in files:
        artifact_workspace_path(path)
        if not 0 < size <= MAX_ARTIFACT_BYTES:
            raise ExecutionError("Conversation file exceeds its size limit.")
        async with get_session_factory()() as db:
            artifact = await repository.get_conversation_file(db, run, artifact_id)
        if artifact is None:
            raise ExecutionError("Conversation file is no longer available.")
        try:
            response = await platform.execute(
                {
                    "execution_session": "agent_run",
                    "restore_files": {
                        path: base64.b64encode(artifact.content).decode("ascii")
                    },
                },
                timeout_seconds=timeout_seconds,
                max_output_bytes=4096,
            )
        except ExecutionOutcomeUnknown as exc:
            # Only a private, repeatable import was dispatched; no model command ran.
            raise ExecutionNotStarted(
                "File restoration failed before command execution."
            ) from exc
        if response.get("ok") is not True:
            raise ExecutionError("Conversation file could not be restored.")

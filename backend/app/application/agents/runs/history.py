"""Bounded reads of original conversation sources under the frozen Run identity."""

import json
from typing import Any

from app.domain.agents.runtime.tools import AgentToolResult
from app.entities.runs import AgentRun
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.artifacts import repository as artifacts
from app.infra.db.session import get_session_factory


def same_conversation(current: AgentRun, source: AgentRun | None) -> bool:
    return source is not None and all(
        getattr(current, field) == getattr(source, field)
        for field in (
            "workspace_id",
            "agent_id",
            "access_source",
            "consumer_id",
            "execution_user_id",
            "conversation_id",
        )
    )


async def conversation_references(run: AgentRun) -> dict[str, Any]:
    async with get_session_factory()() as db:
        files = await artifacts.list_conversation_files(db, run)
    return {
        "schema_version": 1,
        "source_run_id": run.id,
        "artifacts": {
            id: {"artifact_id": id, "relative_path": path, "size_bytes": size}
            for id, path, size in files
        },
        "results": {},
        **({"project": {"id": run.application_snapshot["project"]["id"], "revision": run.application_snapshot["project"]["revision"], "source_root": "/project/sources", "work_root": "/workspace/project", "output_root": "/workspace/outputs"}} if run.application_snapshot.get("project") else {}),
    }


async def read_conversation_history(
    run: AgentRun,
    source_run_id: str | None,
    field: str,
    offset: int,
    limit: int,
    result_id: str | None = None,
) -> AgentToolResult:
    if (
        field
        not in {
            "goal",
            "result",
            "attachment_context",
            "inputs",
            "references",
            "tool_result",
        }
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 12000
    ):
        raise ValueError("Invalid conversation source read range.")
    if field == "tool_result" and (
        not source_run_id
        or not isinstance(result_id, str)
        or not 1 <= len(result_id) <= 255
    ):
        raise ValueError("A source Run and result identity are required.")
    async with get_session_factory()() as db:
        if source_run_id is None:
            sources = await runs.list_conversation_source_runs(
                db, run, offset=offset, limit=min(limit, 20)
            )
            files = await artifacts.list_conversation_files(db, run)
            page = {
                "runs": sources,
                "artifacts": [
                    {"artifact_id": id, "relative_path": path, "size_bytes": size}
                    for id, path, size in files[offset : offset + min(limit, 20)]
                ],
                "next_artifact_offset": offset + min(limit, 20)
                if offset + min(limit, 20) < len(files)
                else None,
                "next_offset": offset + len(sources)
                if len(sources) == min(limit, 20)
                else None,
            }
        else:
            source = await runs.get_agent_run_by_id(db, source_run_id)
            if not same_conversation(run, source) or (
                source.id != run.id and source.status != "succeeded"
            ):
                return AgentToolResult(
                    content="Conversation source is unavailable.",
                    summary="Conversation source unavailable.",
                    is_error=True,
                )
            if field == "tool_result":
                from app.application.agents.tools.results import read_run_tool_result

                return await read_run_tool_result(source, result_id, offset, limit)
            if field == "inputs":
                value = json.dumps(
                    source.checkpoint.get("harness", {}).get("inputs", []),
                    ensure_ascii=False,
                )
            elif field == "references":
                value = json.dumps(
                    source.checkpoint.get("harness", {}).get("exact_references", {}),
                    ensure_ascii=False,
                )
            else:
                value = getattr(source, field) or ""
            page = {
                "run_id": source.id,
                "field": field,
                "content": value[offset : offset + limit],
                "offset": offset,
                "total_characters": len(value),
                "next_offset": offset + limit if offset + limit < len(value) else None,
            }
    return AgentToolResult(
        content=json.dumps(page, ensure_ascii=False),
        summary="Original conversation source read.",
        output=page,
    )

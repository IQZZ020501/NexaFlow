"""Python Tool draft, test-version, publication, and lifecycle rules."""

import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.tools import (
    Tool,
    ToolDraft,
    ToolPolicy,
    ToolSnapshot,
    ToolVersion,
    validate_python_tool_code,
    validate_tool_json_schema,
)
from app.entities.user import User
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import tools as repository
from app.infrastructure.validation import normalize_name
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.tools.catalog import canonical_definition_hash, stable_catalog_id
from app.shareddomain.tools.permissions import require_managed_tool
from app.shareddomain.tools.runtime import build_tool_snapshot


DEFAULT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


async def create_python_tool(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    *,
    display_name: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    code: str,
) -> tuple[Tool, ToolDraft]:
    if not actor.is_active or (
        not actor.is_global_admin and workspace_role not in {"admin", "member"}
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace membership required.")
    definition = _validated_definition(
        display_name,
        description,
        input_schema,
        output_schema,
        code,
    )
    source = await repository.get_tool_source(
        db,
        workspace_id,
        stable_catalog_id(f"source:{workspace_id}:python"),
    )
    if source is None or source.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Python Tool source is unavailable.")
    tool = Tool(
        workspace_id=workspace_id,
        source_id=source.id,
        kind="python",
        stable_key="",
        function_name="",
        created_by_user_id=actor.id,
    )
    tool.stable_key = tool.id
    tool.function_name = _python_function_name(definition["display_name"], tool.id)
    draft = ToolDraft(
        workspace_id=workspace_id,
        tool_id=tool.id,
        display_name=definition["display_name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        output_schema=definition["output_schema"],
        execution_spec={"code": definition["code"]},
        updated_by_user_id=actor.id,
    )
    try:
        tool = await repository.save_tool(db, tool)
        draft = await repository.save_tool_draft(db, draft)
        record_audit_log(
            db,
            actor,
            "tool.create",
            "tool",
            tool.id,
            draft.display_name,
            {"kind": "python"},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Python Tool could not be created.",
        ) from exc
    return tool, draft


async def update_python_tool_draft(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
    *,
    expected_revision: int,
    display_name: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    code: str,
) -> ToolDraft:
    tool = await _require_python_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=True,
    )
    draft = await repository.get_tool_draft(db, workspace_id, tool.id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool draft not found.")
    if draft.revision != expected_revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tool draft was updated.")
    definition = _validated_definition(
        display_name,
        description,
        input_schema,
        output_schema,
        code,
    )
    draft.display_name = definition["display_name"]
    draft.description = definition["description"]
    draft.input_schema = definition["input_schema"]
    draft.output_schema = definition["output_schema"]
    draft.execution_spec = {"code": definition["code"]}
    draft.revision += 1
    draft.updated_by_user_id = actor.id
    draft.updated_at = utc_now()
    draft = await repository.save_tool_draft(db, draft)
    record_audit_log(
        db,
        actor,
        "tool.draft.update",
        "tool",
        tool.id,
        draft.display_name,
        {"revision": draft.revision},
        workspace_id=workspace_id,
    )
    await db.commit()
    return draft


async def build_python_test_snapshot(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
) -> ToolSnapshot:
    tool = await _require_python_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=True,
    )
    draft = await repository.get_tool_draft(db, workspace_id, tool.id)
    source = await repository.get_tool_source(db, workspace_id, tool.source_id)
    if draft is None or source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool draft not found.")
    version = await _materialize_draft_version(db, tool, draft, actor.id)
    test_policy = ToolPolicy(
        id=stable_catalog_id(f"test-policy:{version.id}:{draft.revision}"),
        workspace_id=workspace_id,
        tool_id=tool.id,
        tool_version_id=version.id,
        definition_hash=version.definition_hash,
        revision=draft.revision,
        approval="auto",
        effect="pure",
        allowed_access_sources=["console"],
        workflow_callable=True,
        parallel_safe=False,
        reviewed_by_user_id=actor.id,
        reviewed_at=utc_now(),
    )
    snapshot = build_tool_snapshot(tool, source, version, test_policy, actor.id)
    return snapshot


async def publish_python_tool(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
) -> tuple[Tool, ToolVersion, ToolPolicy]:
    tool = await _require_python_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=True,
    )
    draft = await repository.get_tool_draft(db, workspace_id, tool.id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool draft not found.")
    version = await _materialize_draft_version(db, tool, draft, actor.id)
    policy = await repository.get_tool_policy(db, workspace_id, tool.id)
    if policy is None:
        policy = await repository.save_tool_policy(
            db,
            ToolPolicy(
                workspace_id=workspace_id,
                tool_id=tool.id,
                tool_version_id=version.id,
                definition_hash=version.definition_hash,
                approval="auto",
                effect="pure",
                allowed_access_sources=["console", "public", "api"],
                workflow_callable=True,
                parallel_safe=False,
                reviewed_by_user_id=actor.id,
                reviewed_at=utc_now(),
            ),
        )
    elif policy.tool_version_id != version.id or policy.definition_hash != version.definition_hash:
        expected_revision = policy.revision
        policy.tool_version_id = version.id
        policy.definition_hash = version.definition_hash
        policy.revision += 1
        policy.approval = "auto"
        policy.effect = "pure"
        policy.allowed_access_sources = ["console", "public", "api"]
        policy.workflow_callable = True
        policy.parallel_safe = False
        policy.reviewed_by_user_id = actor.id
        policy.reviewed_at = utc_now()
        policy.updated_at = policy.reviewed_at
        saved = await repository.update_tool_policy_if_revision(
            db,
            policy,
            expected_revision,
        )
        if saved is None:
            await db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Tool policy was updated.")
    tool.current_version_id = version.id
    tool.status = "active"
    tool.availability = "available"
    tool.updated_at = utc_now()
    tool = await repository.save_tool(db, tool)
    record_audit_log(
        db,
        actor,
        "tool.publish",
        "tool",
        tool.id,
        version.display_name,
        {"version_id": version.id, "revision": version.revision},
        workspace_id=workspace_id,
    )
    await db.commit()
    return tool, version, policy


async def set_python_tool_enabled(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    enabled: bool,
    actor: User,
    workspace_role: str | None,
) -> Tool:
    tool = await _require_python_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=True,
    )
    tool.status = "active" if enabled else "disabled"
    tool.updated_at = utc_now()
    tool = await repository.save_tool(db, tool)
    record_audit_log(
        db,
        actor,
        "tool.enable" if enabled else "tool.disable",
        "tool",
        tool.id,
        tool.function_name,
        workspace_id=workspace_id,
    )
    await db.commit()
    return tool


async def archive_python_tool(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
) -> None:
    tool = await _require_python_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=True,
    )
    tool.status = "archived"
    tool.availability = "unavailable"
    tool.updated_at = utc_now()
    await repository.save_tool(db, tool)
    record_audit_log(
        db,
        actor,
        "tool.delete",
        "tool",
        tool.id,
        tool.function_name,
        workspace_id=workspace_id,
    )
    await db.commit()


async def _require_python_tool(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
    *,
    lock: bool,
) -> Tool:
    tool = await require_managed_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=lock,
    )
    if tool.kind != "python":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Python Tool not found.")
    if tool.status == "archived":
        raise HTTPException(status.HTTP_409_CONFLICT, "Archived Tool cannot be changed.")
    return tool


async def _materialize_draft_version(
    db: AsyncSession,
    tool: Tool,
    draft: ToolDraft,
    actor_id: str,
) -> ToolVersion:
    definition_hash = canonical_definition_hash(
        {
            "display_name": draft.display_name,
            "description": draft.description,
            "input_schema": draft.input_schema,
            "output_schema": draft.output_schema,
            "execution_spec": draft.execution_spec,
        }
    )
    existing = await repository.get_tool_version_by_hash(
        db,
        tool.workspace_id,
        tool.id,
        definition_hash,
    )
    if existing is not None:
        return existing
    versions = await repository.list_tool_versions(db, tool.workspace_id, tool.id)
    return await repository.save_tool_version(
        db,
        ToolVersion(
            workspace_id=tool.workspace_id,
            tool_id=tool.id,
            revision=versions[0].revision + 1 if versions else 1,
            display_name=draft.display_name,
            description=draft.description,
            input_schema=draft.input_schema,
            output_schema=draft.output_schema,
            execution_spec=draft.execution_spec,
            definition_hash=definition_hash,
            created_by_user_id=actor_id,
        ),
    )


def _validated_definition(
    display_name: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    code: str,
) -> dict[str, Any]:
    name = normalize_name(display_name)
    if len(name) > 120 or len(description) > 4000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Tool text is too long.")
    try:
        validated_input = validate_tool_json_schema(input_schema)
        validated_output = validate_tool_json_schema(output_schema)
        validated_code = validate_python_tool_code(code)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(exc),
        ) from exc
    return {
        "display_name": name,
        "description": description.strip(),
        "input_schema": validated_input,
        "output_schema": validated_output,
        "code": validated_code,
    }


def _python_function_name(display_name: str, tool_id: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_]", "_", display_name).strip("_").lower()
    stem = stem[:36] or "tool"
    return f"python_{stem}_{tool_id.replace('-', '')[:12]}"


__all__ = [
    "DEFAULT_TOOL_SCHEMA",
    "archive_python_tool",
    "build_python_test_snapshot",
    "create_python_tool",
    "publish_python_tool",
    "set_python_tool_enabled",
    "update_python_tool_draft",
]

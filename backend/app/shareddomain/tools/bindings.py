"""Canonical Tool binding and frozen snapshot rules for applications."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.tools import (
    ApplicationToolBinding,
    Tool,
    ToolPolicy,
    ToolRef,
    ToolSnapshot,
    ToolSource,
    ToolVersion,
)
from app.entities.user import User
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import tools as repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.shareddomain.tools.catalog import get_tool_catalog_detail
from app.shareddomain.tools.permissions import require_tool_use
from app.shareddomain.tools.runtime import build_tool_snapshot


def build_bindable_tool_snapshot(
    tool: Tool,
    source: ToolSource,
    version: ToolVersion,
    policy: ToolPolicy,
    bound_by_user_id: str,
) -> ToolSnapshot:
    if (
        tool.status != "active"
        or tool.availability != "available"
        or source.status != "active"
        or tool.source_id != source.id
        or tool.current_version_id != version.id
        or version.tool_id != tool.id
        or policy.tool_id != tool.id
        or policy.tool_version_id != version.id
        or policy.definition_hash != version.definition_hash
        or policy.approval == "disabled"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Tool is not available for binding.",
        )
    return build_tool_snapshot(tool, source, version, policy, bound_by_user_id)


async def resolve_tool_refs_for_actor(
    db: AsyncSession,
    workspace_id: str,
    references: list[ToolRef],
    actor: User,
    workspace_role: str | None,
) -> list[ToolSnapshot]:
    if len({reference.tool_id for reference in references}) != len(references):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Agent Tools must be unique.",
        )
    snapshots: list[ToolSnapshot] = []
    for reference in references:
        detail = await get_tool_catalog_detail(
            db,
            workspace_id,
            reference.tool_id,
            actor,
            workspace_role,
        )
        require_tool_use(detail.authorization)
        if (
            detail.version is None
            or detail.policy is None
            or detail.version.id != reference.version_id
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Tool version is not available for binding.",
            )
        snapshots.append(
            build_bindable_tool_snapshot(
                detail.tool,
                detail.source,
                detail.version,
                detail.policy,
                actor.id,
            )
        )
    return sorted(snapshots, key=lambda item: (item.tool_id, item.version_id))


async def resolve_application_tool_snapshots(
    db: AsyncSession,
    workspace_id: str,
    application_id: str,
) -> list[ToolSnapshot]:
    bindings = await repository.list_application_tool_bindings(
        db,
        workspace_id,
        application_id,
    )
    snapshots: list[ToolSnapshot] = []
    for binding in bindings:
        binder = await user_repository.get_user_by_id(db, binding.bound_by_user_id)
        if binder is None or not binder.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Tool binding permission is no longer valid.",
            )
        membership = await workspace_repository.get_workspace_membership(
            db,
            workspace_id,
            binder.id,
        )
        if membership is None and not binder.is_global_admin:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Tool binding permission is no longer valid.",
            )
        detail = await get_tool_catalog_detail(
            db,
            workspace_id,
            binding.tool_id,
            binder,
            membership.role if membership is not None else None,
        )
        require_tool_use(detail.authorization)
        if (
            detail.version is None
            or detail.policy is None
            or detail.version.id != binding.tool_version_id
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Tool binding changed; save the application again.",
            )
        snapshots.append(
            build_bindable_tool_snapshot(
                detail.tool,
                detail.source,
                detail.version,
                detail.policy,
                binding.bound_by_user_id,
            )
        )
    return sorted(snapshots, key=lambda item: (item.tool_id, item.version_id))


async def sync_application_tool_bindings(
    db: AsyncSession,
    workspace_id: str,
    application_id: str,
    snapshots: list[ToolSnapshot],
    actor_id: str,
) -> list[ApplicationToolBinding]:
    current = await repository.list_application_tool_bindings(
        db,
        workspace_id,
        application_id,
    )
    current_by_tool = {binding.tool_id: binding for binding in current}
    desired: list[ApplicationToolBinding] = []
    for snapshot in snapshots:
        existing = current_by_tool.get(snapshot.tool_id)
        if existing is not None and existing.tool_version_id == snapshot.version_id:
            desired.append(existing)
            continue
        desired.append(
            ApplicationToolBinding(
                id=existing.id if existing is not None else new_id(),
                workspace_id=workspace_id,
                application_id=application_id,
                tool_id=snapshot.tool_id,
                tool_version_id=snapshot.version_id,
                bound_by_user_id=actor_id,
                created_at=utc_now(),
            )
        )
    await repository.sync_application_tool_bindings(
        db,
        workspace_id,
        application_id,
        desired,
    )
    return desired


__all__ = [
    "build_bindable_tool_snapshot",
    "resolve_application_tool_snapshots",
    "resolve_tool_refs_for_actor",
    "sync_application_tool_bindings",
]

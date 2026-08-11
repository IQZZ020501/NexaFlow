"""Knowledge base access permissions."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import KnowledgeBase
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User
from app.infrastructure.repositories import resource_permission as permission_repository
from app.schemas.knowledge import ResourcePermissionResponse
from app.schemas.user import user_to_response
from app.shareddomain.audit.services import record_audit_log

RESOURCE_TYPE = "knowledge_base"
RESOURCE_PERMISSIONS = {"view", "edit"}
ARCHIVED_STATUS = "archived"


def validate_permission(permission: str) -> None:
    if permission not in RESOURCE_PERMISSIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid resource permission.",
        )


def require_knowledge_base_active(knowledge_base: KnowledgeBase) -> None:
    if knowledge_base.status == ARCHIVED_STATUS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Knowledge base is archived.")


def effective_permission(
    knowledge_base: KnowledgeBase,
    user: User,
    workspace_role: str | None,
    grant: ResourcePermission | None = None,
) -> str:
    if workspace_role == "admin" or knowledge_base.created_by_user_id == user.id:
        return "edit"
    if grant is None:
        return "none"
    return grant.permission


async def get_user_grant(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    user_id: str,
) -> ResourcePermission | None:
    return await permission_repository.get_user_grant(
        db,
        knowledge_base.workspace_id,
        RESOURCE_TYPE,
        knowledge_base.id,
        user_id,
    )


async def require_knowledge_base_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    workspace_role: str | None,
    permissions: set[str],
) -> str:
    if (
        knowledge_base.status == ARCHIVED_STATUS
        and "edit" in permissions
        and "view" not in permissions
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Knowledge base is archived.")
    permission = effective_permission(
        knowledge_base,
        actor,
        workspace_role,
        await get_user_grant(db, knowledge_base, actor.id),
    )
    if permission == "edit" or permission in permissions:
        return permission
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Knowledge base access denied.")


async def list_resource_permissions(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    limit: int | None = None,
    offset: int = 0,
) -> list[ResourcePermissionResponse]:
    rows = await permission_repository.list_resource_permission_rows(
        db,
        knowledge_base.workspace_id,
        RESOURCE_TYPE,
        knowledge_base.id,
        limit,
        offset,
    )
    return [
        ResourcePermissionResponse(
            user=user_to_response(user, [], []),
            permission=permission.permission,
        )
        for permission, user in rows
    ]


async def upsert_resource_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    permission: str,
    actor: User,
) -> ResourcePermissionResponse:
    require_knowledge_base_active(knowledge_base)
    validate_permission(permission)
    target = await permission_repository.get_active_workspace_member(
        db,
        knowledge_base.workspace_id,
        target_user_id,
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")

    resource_permission = await get_user_grant(db, knowledge_base, target_user_id)
    if resource_permission is None:
        resource_permission = ResourcePermission(
            workspace_id=knowledge_base.workspace_id,
            resource_type=RESOURCE_TYPE,
            resource_id=knowledge_base.id,
            user_id=target_user_id,
            permission=permission,
            created_by_user_id=actor.id,
        )
        resource_permission = (
            await permission_repository.create_resource_permission(
                db,
                resource_permission,
            )
        )
    else:
        resource_permission.permission = permission
        await permission_repository.save_resource_permission(
            db,
            resource_permission,
        )

    record_audit_log(
        db,
        actor,
        "resource_permission.grant",
        RESOURCE_TYPE,
        knowledge_base.id,
        knowledge_base.name,
        {"user_id": target_user_id, "permission": permission},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    return ResourcePermissionResponse(
        user=user_to_response(target, [], []),
        permission=permission,
    )


async def revoke_resource_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    actor: User,
) -> None:
    require_knowledge_base_active(knowledge_base)
    deleted_count = await permission_repository.delete_resource_permission(
        db,
        knowledge_base.workspace_id,
        RESOURCE_TYPE,
        knowledge_base.id,
        target_user_id,
    )
    if deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource permission not found.")

    record_audit_log(
        db,
        actor,
        "resource_permission.revoke",
        RESOURCE_TYPE,
        knowledge_base.id,
        knowledge_base.name,
        {"user_id": target_user_id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()

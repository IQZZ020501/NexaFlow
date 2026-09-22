from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agent_skills.access import (
    AGENT_SKILL_GRANTS,
    AGENT_SKILL_RESOURCE_TYPE,
    AgentSkillAccess,
    evaluate_agent_skill_access,
    require_agent_skill_manage,
    require_agent_skill_use,
    require_agent_skill_view,
)
from app.domain.agent_skills.contracts import (
    AGENT_SKILL_SCHEMA_VERSION,
    agent_skill_definition_hash,
    build_agent_skill_snapshot,
    validate_agent_skill_version,
)
from app.domain.agent_skills.packages import canonical_skill_files
from app.domain.audit.services import record_audit_log
from app.domain.knowledge.service import (
    get_knowledge_base,
    require_knowledge_base_permission,
)
from app.domain.tools.access.bindings import resolve_tool_refs_for_actor
from app.entities.agent_skills import (
    AgentSkill,
    AgentSkillBinding,
    AgentSkillRef,
    AgentSkillSnapshot,
    AgentSkillVersion,
)
from app.entities.identity.user import User
from app.entities.tools import ToolRef
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.infra.db.repositories.agent_skills import repository
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.repositories.workspaces import repository as workspace_repository
from app.infra.db.repositories.workspaces import resource_permissions
from app.infra.runtime.validation import normalize_name
from app.schemas.agent_skills.contracts import (
    AgentSkillCreateRequest,
    AgentSkillDefinition,
    AgentSkillPermissionResponse,
    AgentSkillRefSchema,
    AgentSkillResponse,
    AgentSkillUpdateRequest,
    AgentSkillVersionResponse,
)
from app.schemas.identity.contracts import user_to_response

MAX_AGENT_SKILLS = 4


def _canonical_definition(name: str, description: str, definition: dict) -> dict:
    try:
        return {
            **definition,
            "instructions": definition["instructions"].strip(),
            "files": canonical_skill_files(
                name, description, definition["instructions"], definition.get("files", {})
            ),
        }
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@dataclass(frozen=True)
class AgentSkillDetail:
    skill: AgentSkill
    access: AgentSkillAccess
    current_version: AgentSkillVersion | None


async def _skill_access(
    db: AsyncSession,
    skill: AgentSkill,
    actor: User,
    workspace_role: str | None,
) -> AgentSkillAccess:
    grant = await resource_permissions.get_user_grant(
        db,
        skill.workspace_id,
        AGENT_SKILL_RESOURCE_TYPE,
        skill.id,
        actor.id,
    )
    return evaluate_agent_skill_access(skill, actor, workspace_role, grant)


def _version_response(version: AgentSkillVersion) -> AgentSkillVersionResponse:
    validate_agent_skill_version(version)
    return AgentSkillVersionResponse(
        id=version.id,
        workspace_id=version.workspace_id,
        skill_id=version.skill_id,
        version_number=version.version_number,
        schema_version=version.schema_version,
        name=version.name,
        description=version.description,
        definition=AgentSkillDefinition.model_validate(version.definition_snapshot),
        definition_hash=version.definition_hash,
        published_by_user_id=version.published_by_user_id,
        created_at=version.created_at,
    )


def _response(detail: AgentSkillDetail) -> AgentSkillResponse:
    skill = detail.skill
    version = detail.current_version
    draft = AgentSkillDefinition.model_validate(skill.draft_definition)
    current_hash = (
        agent_skill_definition_hash(
            version.name,
            version.description,
            version.definition_snapshot,
        )
        if version is not None
        else None
    )
    draft_hash = agent_skill_definition_hash(
        skill.name,
        skill.description,
        draft.model_dump(mode="json"),
    )
    permission = detail.access.permission
    if permission is None:  # pragma: no cover - callers require visibility first
        raise ValueError("Visible Agent Skill is missing an access label.")
    return AgentSkillResponse(
        id=skill.id,
        workspace_id=skill.workspace_id,
        name=skill.name,
        description=skill.description,
        definition=draft,
        status=skill.status,
        current_published_version_id=skill.current_published_version_id,
        current_version_number=version.version_number if version is not None else None,
        has_unpublished_changes=current_hash != draft_hash,
        permission=permission,
        can_manage=detail.access.can_manage,
        can_use=detail.access.can_use and skill.status == "active" and version is not None,
        created_by_user_id=skill.created_by_user_id,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


async def _detail(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    actor: User,
    workspace_role: str | None,
    *,
    lock: bool = False,
) -> AgentSkillDetail:
    getter = repository.lock_agent_skill if lock else repository.get_agent_skill
    skill = await getter(db, workspace_id, skill_id)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent Skill not found.")
    access = await _skill_access(db, skill, actor, workspace_role)
    require_agent_skill_view(access)
    version = None
    if skill.current_published_version_id is not None:
        version = await repository.get_agent_skill_version(
            db, workspace_id, skill.current_published_version_id
        )
        if version is None or version.skill_id != skill.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Agent Skill publication is invalid."
            )
        try:
            validate_agent_skill_version(version)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Agent Skill publication is invalid."
            ) from exc
    return AgentSkillDetail(skill=skill, access=access, current_version=version)


async def list_agent_skills(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int,
    offset: int,
) -> list[AgentSkillResponse]:
    include_all = workspace_role == "admin" or actor.is_global_admin
    rows = await repository.list_agent_skill_rows(
        db,
        workspace_id,
        actor.id,
        include_all=include_all,
        limit=limit,
        offset=offset,
    )
    responses: list[AgentSkillResponse] = []
    for skill, grant in rows:
        access = evaluate_agent_skill_access(skill, actor, workspace_role, grant)
        if not access.can_view:
            continue
        version = None
        if skill.current_published_version_id is not None:
            version = await repository.get_agent_skill_version(
                db, workspace_id, skill.current_published_version_id
            )
        responses.append(_response(AgentSkillDetail(skill, access, version)))
    return responses


async def get_agent_skill(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    actor: User,
    workspace_role: str | None,
) -> AgentSkillResponse:
    return _response(await _detail(db, workspace_id, skill_id, actor, workspace_role))


async def create_agent_skill(
    db: AsyncSession,
    workspace_id: str,
    payload: AgentSkillCreateRequest,
    actor: User,
    workspace_role: str | None,
) -> AgentSkillResponse:
    if not actor.is_global_admin and workspace_role not in {"admin", "member"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace membership required.")
    skill = AgentSkill(
        workspace_id=workspace_id,
        name=normalize_name(payload.name),
        description=payload.description.strip(),
        draft_definition=_canonical_definition(
            normalize_name(payload.name),
            payload.description.strip(),
            payload.definition.model_dump(mode="json"),
        ),
        created_by_user_id=actor.id,
    )
    try:
        skill = await repository.save_agent_skill(db, skill)
        record_audit_log(
            db,
            actor,
            "agent_skill.create",
            AGENT_SKILL_RESOURCE_TYPE,
            skill.id,
            skill.name,
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Agent Skill name already exists."
        ) from exc
    skill = await repository.refresh_agent_skill(db, skill)
    access = evaluate_agent_skill_access(skill, actor, workspace_role, None)
    return _response(AgentSkillDetail(skill, access, None))


async def update_agent_skill(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    payload: AgentSkillUpdateRequest,
    actor: User,
    workspace_role: str | None,
) -> AgentSkillResponse:
    detail = await _detail(
        db, workspace_id, skill_id, actor, workspace_role, lock=True
    )
    require_agent_skill_manage(detail.access)
    skill = detail.skill
    changed = payload.model_dump(exclude_unset=True)
    if payload.name is not None:
        skill.name = normalize_name(payload.name)
    if payload.description is not None:
        skill.description = payload.description.strip()
    if payload.definition is not None:
        skill.draft_definition = payload.definition.model_dump(mode="json")
    if any(value is not None for value in (payload.name, payload.description, payload.definition)):
        skill.draft_definition = _canonical_definition(
            skill.name, skill.description, skill.draft_definition
        )
    if payload.status is not None:
        skill.status = payload.status
    try:
        skill = await repository.save_agent_skill(db, skill)
        record_audit_log(
            db,
            actor,
            "agent_skill.update",
            AGENT_SKILL_RESOURCE_TYPE,
            skill.id,
            skill.name,
            {"fields": sorted(changed)},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Agent Skill name already exists."
        ) from exc
    skill = await repository.refresh_agent_skill(db, skill)
    return _response(AgentSkillDetail(skill, detail.access, detail.current_version))


async def _validate_definition_resources(
    db: AsyncSession,
    workspace_id: str,
    definition: AgentSkillDefinition,
    actor: User,
    workspace_role: str | None,
) -> None:
    for knowledge_base_id in definition.knowledge_base_ids:
        knowledge_base = await get_knowledge_base(db, workspace_id, knowledge_base_id)
        await require_knowledge_base_permission(db, knowledge_base, actor, {"view", "edit"})
        if knowledge_base.status != "active":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Agent Skill knowledge base is not active.",
            )
    snapshots = await resolve_tool_refs_for_actor(
        db,
        workspace_id,
        [ToolRef(tool_id=item.tool_id, version_id=item.version_id) for item in definition.tools],
        actor,
        workspace_role,
    )
    for snapshot in snapshots:
        if snapshot.effect == "external_read" and not definition.guardrails.allow_external_reads:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Agent Skill guardrails do not allow an external-read Tool.",
            )
        if snapshot.effect in {"external_write", "unknown"}:
            if not definition.guardrails.allow_external_writes:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Agent Skill guardrails do not allow a write-capable Tool.",
                )
            if snapshot.approval != "each_call":
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Write-capable Agent Skill Tools must require approval for each call.",
                )


async def publish_agent_skill(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    actor: User,
    workspace_role: str | None,
) -> AgentSkillVersionResponse:
    detail = await _detail(
        db, workspace_id, skill_id, actor, workspace_role, lock=True
    )
    require_agent_skill_manage(detail.access)
    skill = detail.skill
    if skill.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Disabled Agent Skills cannot be published."
        )
    definition = AgentSkillDefinition.model_validate(skill.draft_definition)
    await _validate_definition_resources(
        db, workspace_id, definition, actor, workspace_role
    )
    definition_payload = definition.model_dump(mode="json")
    version = AgentSkillVersion(
        workspace_id=workspace_id,
        skill_id=skill.id,
        version_number=await repository.next_agent_skill_version_number(db, skill.id),
        schema_version=AGENT_SKILL_SCHEMA_VERSION,
        name=skill.name,
        description=skill.description,
        definition_snapshot=definition_payload,
        definition_hash=agent_skill_definition_hash(
            skill.name, skill.description, definition_payload
        ),
        published_by_user_id=actor.id,
    )
    try:
        version = await repository.create_agent_skill_version(db, version)
        skill.current_published_version_id = version.id
        await repository.save_agent_skill(db, skill)
        record_audit_log(
            db,
            actor,
            "agent_skill.publish",
            AGENT_SKILL_RESOURCE_TYPE,
            skill.id,
            skill.name,
            {"version_id": version.id, "version_number": version.version_number},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Agent Skill publication conflicted."
        ) from exc
    return _version_response(version)


async def list_agent_skill_versions(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    actor: User,
    workspace_role: str | None,
) -> list[AgentSkillVersionResponse]:
    detail = await _detail(db, workspace_id, skill_id, actor, workspace_role)
    require_agent_skill_view(detail.access)
    return [
        _version_response(version)
        for version in await repository.list_agent_skill_versions(
            db, workspace_id, skill_id
        )
    ]


async def resolve_agent_skill_refs(
    db: AsyncSession,
    workspace_id: str,
    references: list[AgentSkillRefSchema],
    actor: User,
    workspace_role: str | None,
) -> list[AgentSkillSnapshot]:
    if len(references) > MAX_AGENT_SKILLS or len(
        {reference.skill_id for reference in references}
    ) != len(references):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Agent Skill references must be unique and within the configured limit.",
        )
    snapshots: list[AgentSkillSnapshot] = []
    for reference in references:
        detail = await _detail(
            db, workspace_id, reference.skill_id, actor, workspace_role
        )
        require_agent_skill_use(detail.access)
        if detail.skill.status != "active":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Agent Skill is disabled.",
            )
        version = await repository.get_agent_skill_version(
            db, workspace_id, reference.version_id
        )
        if version is None or version.skill_id != detail.skill.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Agent Skill version is not available for binding.",
            )
        snapshots.append(build_agent_skill_snapshot(version, actor.id))
    return sorted(snapshots, key=lambda item: (item.skill_id, item.version_id))


async def sync_agent_skill_bindings(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    snapshots: list[AgentSkillSnapshot],
    actor_id: str,
) -> None:
    await repository.replace_agent_skill_bindings(
        db,
        workspace_id,
        agent_id,
        [
            AgentSkillBinding(
                workspace_id=workspace_id,
                agent_id=agent_id,
                skill_id=snapshot.skill_id,
                skill_version_id=snapshot.version_id,
                bound_by_user_id=actor_id,
            )
            for snapshot in snapshots
        ],
    )


async def resolve_application_agent_skill_snapshots(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> list[AgentSkillSnapshot]:
    snapshots: list[AgentSkillSnapshot] = []
    for binding, skill, version in await repository.list_agent_skill_snapshot_rows(
        db, workspace_id, agent_id
    ):
        binder = await user_repository.get_user_by_id(db, binding.bound_by_user_id)
        if binder is None or not binder.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Agent Skill binding permission is no longer valid.",
            )
        membership = await workspace_repository.get_workspace_membership(
            db, workspace_id, binder.id
        )
        role = membership.role if membership is not None else None
        access = await _skill_access(db, skill, binder, role)
        require_agent_skill_use(access)
        if skill.status != "active":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A bound Agent Skill is disabled."
            )
        snapshots.append(build_agent_skill_snapshot(version, binding.bound_by_user_id))
    return sorted(snapshots, key=lambda item: (item.skill_id, item.version_id))


async def list_agent_skill_ref_map(
    db: AsyncSession,
    workspace_id: str,
    agent_ids: list[str],
) -> dict[str, list[AgentSkillRef]]:
    bindings = await repository.list_agent_skill_binding_map(
        db, workspace_id, agent_ids
    )
    return {
        agent_id: [
            AgentSkillRef(skill_id=item.skill_id, version_id=item.skill_version_id)
            for item in items
        ]
        for agent_id, items in bindings.items()
    }


async def list_agent_skill_permissions(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    actor: User,
    workspace_role: str | None,
) -> list[AgentSkillPermissionResponse]:
    detail = await _detail(db, workspace_id, skill_id, actor, workspace_role)
    require_agent_skill_manage(detail.access)
    rows = await resource_permissions.list_resource_permission_rows(
        db, workspace_id, AGENT_SKILL_RESOURCE_TYPE, skill_id
    )
    return [
        AgentSkillPermissionResponse(
            user=user_to_response(user, [], []), permission=grant.permission
        )
        for grant, user in rows
    ]


async def upsert_agent_skill_permission(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    target_user_id: str,
    permission: str,
    actor: User,
    workspace_role: str | None,
) -> AgentSkillPermissionResponse:
    detail = await _detail(
        db, workspace_id, skill_id, actor, workspace_role, lock=True
    )
    require_agent_skill_manage(detail.access)
    if permission not in AGENT_SKILL_GRANTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Invalid Agent Skill permission.",
        )
    target = await resource_permissions.get_active_workspace_member(
        db, workspace_id, target_user_id
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")
    if target.id == detail.skill.created_by_user_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Agent Skill owners do not require explicit permissions.",
        )
    grant = await resource_permissions.upsert_resource_permission(
        db,
        ResourcePermission(
            workspace_id=workspace_id,
            resource_type=AGENT_SKILL_RESOURCE_TYPE,
            resource_id=skill_id,
            user_id=target.id,
            permission=permission,
            created_by_user_id=actor.id,
        ),
    )
    record_audit_log(
        db,
        actor,
        "resource_permission.grant",
        AGENT_SKILL_RESOURCE_TYPE,
        skill_id,
        detail.skill.name,
        {"user_id": target.id, "permission": permission},
        workspace_id=workspace_id,
    )
    await db.commit()
    return AgentSkillPermissionResponse(
        user=user_to_response(target, [], []), permission=grant.permission
    )


async def revoke_agent_skill_permission(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    target_user_id: str,
    actor: User,
    workspace_role: str | None,
) -> None:
    detail = await _detail(
        db, workspace_id, skill_id, actor, workspace_role, lock=True
    )
    require_agent_skill_manage(detail.access)
    deleted = await resource_permissions.delete_resource_permission(
        db,
        workspace_id,
        AGENT_SKILL_RESOURCE_TYPE,
        skill_id,
        target_user_id,
    )
    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Agent Skill permission not found."
        )
    record_audit_log(
        db,
        actor,
        "resource_permission.revoke",
        AGENT_SKILL_RESOURCE_TYPE,
        skill_id,
        detail.skill.name,
        {"user_id": target_user_id},
        workspace_id=workspace_id,
    )
    await db.commit()


__all__ = [
    "create_agent_skill",
    "get_agent_skill",
    "list_agent_skill_permissions",
    "list_agent_skill_ref_map",
    "list_agent_skill_versions",
    "list_agent_skills",
    "publish_agent_skill",
    "resolve_agent_skill_refs",
    "resolve_application_agent_skill_snapshots",
    "revoke_agent_skill_permission",
    "sync_agent_skill_bindings",
    "update_agent_skill",
    "upsert_agent_skill_permission",
]

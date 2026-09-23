from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agent_skills.models import (
    AgentSkill as AgentSkillOrm,
)
from app.domain.agent_skills.models import (
    AgentSkillBinding as AgentSkillBindingOrm,
)
from app.domain.agent_skills.models import (
    AgentSkillVersion as AgentSkillVersionOrm,
)
from app.domain.platform.models import ResourcePermission as ResourcePermissionOrm
from app.entities.agent_skills import (
    AgentSkill,
    AgentSkillBinding,
    AgentSkillVersion,
)
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.infra.db.mapping import refresh_entity, save, to_entity, to_orm


async def list_agent_skill_rows(
    db: AsyncSession,
    workspace_id: str,
    actor_id: str,
    *,
    include_all: bool,
    limit: int,
    offset: int,
) -> list[tuple[AgentSkill, ResourcePermission | None]]:
    grant = ResourcePermissionOrm
    statement = (
        select(AgentSkillOrm, grant)
        .outerjoin(
            grant,
            and_(
                grant.workspace_id == AgentSkillOrm.workspace_id,
                grant.resource_type == "agent_skill",
                grant.resource_id == AgentSkillOrm.id,
                grant.user_id == actor_id,
            ),
        )
        .where(AgentSkillOrm.workspace_id == workspace_id)
    )
    if not include_all:
        statement = statement.where(
            or_(AgentSkillOrm.created_by_user_id == actor_id, grant.id.is_not(None))
        )
    result = await db.execute(
        statement.order_by(AgentSkillOrm.updated_at.desc(), AgentSkillOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        (
            to_entity(AgentSkill, skill),
            to_entity(ResourcePermission, permission) if permission is not None else None,
        )
        for skill, permission in result.all()
    ]


async def get_agent_skill(
    db: AsyncSession, workspace_id: str, skill_id: str
) -> AgentSkill | None:
    row = await db.scalar(
        select(AgentSkillOrm).where(
            AgentSkillOrm.workspace_id == workspace_id,
            AgentSkillOrm.id == skill_id,
        )
    )
    return to_entity(AgentSkill, row) if row is not None else None


async def lock_agent_skill(
    db: AsyncSession, workspace_id: str, skill_id: str
) -> AgentSkill | None:
    row = await db.scalar(
        select(AgentSkillOrm)
        .where(
            AgentSkillOrm.workspace_id == workspace_id,
            AgentSkillOrm.id == skill_id,
        )
        .with_for_update()
    )
    return to_entity(AgentSkill, row) if row is not None else None


async def save_agent_skill(db: AsyncSession, entity: AgentSkill) -> AgentSkill:
    row = await save(db, AgentSkillOrm, entity)
    return to_entity(AgentSkill, row)


async def refresh_agent_skill(db: AsyncSession, entity: AgentSkill) -> AgentSkill:
    return await refresh_entity(db, AgentSkillOrm, AgentSkill, entity)


async def next_agent_skill_version_number(
    db: AsyncSession, skill_id: str
) -> int:
    current = await db.scalar(
        select(func.max(AgentSkillVersionOrm.version_number)).where(
            AgentSkillVersionOrm.skill_id == skill_id
        )
    )
    return int(current or 0) + 1


async def create_agent_skill_version(
    db: AsyncSession, entity: AgentSkillVersion
) -> AgentSkillVersion:
    if await db.get(AgentSkillVersionOrm, entity.id) is not None:
        raise ValueError("Agent Skill versions are immutable.")
    row = to_orm(AgentSkillVersionOrm, entity)
    db.add(row)
    await db.flush()
    return to_entity(AgentSkillVersion, row)


async def get_agent_skill_version(
    db: AsyncSession,
    workspace_id: str,
    version_id: str,
) -> AgentSkillVersion | None:
    row = await db.scalar(
        select(AgentSkillVersionOrm).where(
            AgentSkillVersionOrm.workspace_id == workspace_id,
            AgentSkillVersionOrm.id == version_id,
        )
    )
    return to_entity(AgentSkillVersion, row) if row is not None else None


async def list_agent_skill_versions(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
) -> list[AgentSkillVersion]:
    rows = await db.scalars(
        select(AgentSkillVersionOrm)
        .where(
            AgentSkillVersionOrm.workspace_id == workspace_id,
            AgentSkillVersionOrm.skill_id == skill_id,
        )
        .order_by(AgentSkillVersionOrm.version_number.desc())
    )
    return [to_entity(AgentSkillVersion, row) for row in rows.all()]


async def replace_agent_skill_bindings(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    bindings: list[AgentSkillBinding],
) -> None:
    await db.execute(
        delete(AgentSkillBindingOrm).where(
            AgentSkillBindingOrm.workspace_id == workspace_id,
            AgentSkillBindingOrm.agent_id == agent_id,
        )
    )
    for binding in bindings:
        db.add(to_orm(AgentSkillBindingOrm, binding))
    await db.flush()


async def list_agent_skill_binding_map(
    db: AsyncSession,
    workspace_id: str,
    agent_ids: list[str],
) -> dict[str, list[AgentSkillBinding]]:
    result = {agent_id: [] for agent_id in agent_ids}
    if not agent_ids:
        return result
    rows = await db.scalars(
        select(AgentSkillBindingOrm)
        .where(
            AgentSkillBindingOrm.workspace_id == workspace_id,
            AgentSkillBindingOrm.agent_id.in_(agent_ids),
        )
        .order_by(AgentSkillBindingOrm.created_at, AgentSkillBindingOrm.id)
    )
    for row in rows.all():
        binding = to_entity(AgentSkillBinding, row)
        result[binding.agent_id].append(binding)
    return result


async def list_agent_skill_snapshot_rows(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> list[tuple[AgentSkillBinding, AgentSkill, AgentSkillVersion]]:
    rows = await db.execute(
        select(AgentSkillBindingOrm, AgentSkillOrm, AgentSkillVersionOrm)
        .join(
            AgentSkillOrm,
            and_(
                AgentSkillOrm.workspace_id == AgentSkillBindingOrm.workspace_id,
                AgentSkillOrm.id == AgentSkillBindingOrm.skill_id,
            ),
        )
        .join(
            AgentSkillVersionOrm,
            and_(
                AgentSkillVersionOrm.workspace_id == AgentSkillBindingOrm.workspace_id,
                AgentSkillVersionOrm.skill_id == AgentSkillBindingOrm.skill_id,
                AgentSkillVersionOrm.id == AgentSkillBindingOrm.skill_version_id,
            ),
        )
        .where(
            AgentSkillBindingOrm.workspace_id == workspace_id,
            AgentSkillBindingOrm.agent_id == agent_id,
        )
        .order_by(AgentSkillBindingOrm.created_at, AgentSkillBindingOrm.id)
    )
    return [
        (
            to_entity(AgentSkillBinding, binding),
            to_entity(AgentSkill, skill),
            to_entity(AgentSkillVersion, version),
        )
        for binding, skill, version in rows.all()
    ]


async def has_agent_skill_bindings(
    db: AsyncSession, workspace_id: str, skill_id: str
) -> bool:
    count = await db.scalar(
        select(func.count())
        .select_from(AgentSkillBindingOrm)
        .where(
            AgentSkillBindingOrm.workspace_id == workspace_id,
            AgentSkillBindingOrm.skill_id == skill_id,
        )
    )
    return bool(count)


async def delete_agent_skill_bindings_bound_by_user(
    db: AsyncSession,
    user_id: str,
) -> int:
    result = await db.execute(
        delete(AgentSkillBindingOrm).where(
            AgentSkillBindingOrm.bound_by_user_id == user_id,
        )
    )
    return result.rowcount or 0

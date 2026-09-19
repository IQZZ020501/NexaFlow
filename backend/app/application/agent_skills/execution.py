"""Live permission checks shared by lazy reads and ledger-backed script execution."""

from fastapi import HTTPException

from app.application.agent_skills.service import _skill_access
from app.domain.agent_skills.access import require_agent_skill_use
from app.domain.agent_skills.contracts import build_agent_skill_snapshot
from app.infra.db.repositories.agent_skills import repository
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.workspaces import repository as workspaces


async def require_pinned_skill_access(db, workspace_id, snapshot):
    skill = await repository.get_agent_skill(db, workspace_id, snapshot.skill_id)
    version = await repository.get_agent_skill_version(
        db, workspace_id, snapshot.version_id
    )
    binder = await users.get_user_by_id(db, snapshot.bound_by_user_id)
    if (
        skill is None
        or skill.status != "active"
        or version is None
        or version.skill_id != skill.id
        or binder is None
        or not binder.is_active
    ):
        raise HTTPException(409, "Skill execution access is no longer valid.")
    membership = await workspaces.get_workspace_membership(db, workspace_id, binder.id)
    if membership is None and not binder.is_global_admin:
        raise HTTPException(403, "Skill execution access was revoked.")
    require_agent_skill_use(
        await _skill_access(db, skill, binder, membership.role if membership else None)
    )
    pinned = build_agent_skill_snapshot(version, binder.id)
    if pinned != snapshot:
        raise HTTPException(409, "Pinned Skill definition changed.")
    return pinned

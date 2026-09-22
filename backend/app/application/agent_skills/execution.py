"""Live permission checks shared by lazy reads and ledger-backed script execution."""

from fastapi import HTTPException

from app.application.agent_skills.service import _skill_access
from app.domain.agent_skills.access import require_agent_skill_use
from app.domain.agent_skills.contracts import (
    agent_skill_snapshot_from_payload,
    build_agent_skill_snapshot,
)
from app.domain.agents.models import AGENT_RUN_RUNNING_STATUSES
from app.infra.db.repositories.agent_skills import repository
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.workspaces import repository as workspaces
from app.infra.db.session import get_session_factory
from app.infra.execution.profile import require_execution_profile


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


async def load_authorized_run_skill(settings, context, version_id: str):
    """Return one live-authorized pinned Skill from an active Agent Run."""

    async with get_session_factory()() as db:
        run = (
            await runs.get_agent_run_by_id(db, context.run_id)
            if context.run_id
            else None
        )
        if (
            run is None
            or run.workspace_id != context.workspace_id
            or run.execution_user_id != context.execution_user_id
            or run.status not in AGENT_RUN_RUNNING_STATUSES
        ):
            raise ValueError("Skill execution requires its authorized Agent run.")
        require_execution_profile(
            settings,
            run.application_snapshot.get("execution_profile"),
        )
        snapshot = next(
            (
                agent_skill_snapshot_from_payload(item)
                for item in run.skill_snapshots
                if item.get("version_id") == version_id
            ),
            None,
        )
        if snapshot is None:
            raise ValueError("Skill is not in the run's pinned catalog.")
        await require_pinned_skill_access(db, context.workspace_id, snapshot)
        return snapshot

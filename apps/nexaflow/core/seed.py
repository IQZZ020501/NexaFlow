from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.core.config import Settings
from nexaflow.identity.models import User
from nexaflow.identity.security import hash_password
from nexaflow.teams.models import Team, TeamMembership
from nexaflow.workspaces.models import Workspace, WorkspaceMembership


async def seed_defaults(db: AsyncSession, settings: Settings) -> None:
    admin = await db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
    if admin is None:
        admin = User(
            username=settings.bootstrap_admin_username,
            email=settings.bootstrap_admin_email,
            name=settings.bootstrap_admin_name,
            password_hash=hash_password(settings.bootstrap_admin_password),
            is_global_admin=True,
            must_change_password=True,
        )
        db.add(admin)
    else:
        admin.is_global_admin = True

    workspace = await db.scalar(select(Workspace).where(Workspace.slug == settings.default_workspace_slug))
    if workspace is None:
        workspace = Workspace(
            name=settings.default_workspace_name,
            slug=settings.default_workspace_slug,
            status="active",
            is_default=True,
        )
        db.add(workspace)
        await db.flush()

    await db.flush()

    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == admin.id,
        )
    )
    if membership is None:
        db.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=admin.id,
                role="admin",
            )
        )
    elif membership.role != "admin":
        membership.role = "admin"

    team = await db.scalar(
        select(Team).where(
            Team.workspace_id == workspace.id,
            Team.slug == settings.default_team_slug,
        )
    )
    if team is None:
        team = Team(
            workspace_id=workspace.id,
            name=settings.default_team_name,
            slug=settings.default_team_slug,
            status="active",
            is_default=True,
        )
        db.add(team)
        await db.flush()

    team_membership = await db.scalar(
        select(TeamMembership).where(
            TeamMembership.team_id == team.id,
            TeamMembership.user_id == admin.id,
        )
    )
    if team_membership is None:
        db.add(
            TeamMembership(
                workspace_id=workspace.id,
                team_id=team.id,
                user_id=admin.id,
                role="admin",
            )
        )
    elif team_membership.role != "admin":
        team_membership.role = "admin"

    await db.commit()

"""Resolve active publications and recheck workspace membership per access."""

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.workspaces.service import WorkspaceContext, build_workspace_context
from app.domain.agents.service import (
    ACTIVE_STATUS,
    AgentPublication,
    agent_publication_from_snapshot,
    agent_publication_from_version,
)
from app.entities.agents import Agent, AgentPublicationVersion
from app.entities.identity.user import User
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.repositories.identity import users as user_repository

ExternalAccessSource = Literal["public", "api"]


@dataclass(frozen=True)
class PublishedApplicationContext:
    agent: Agent
    publisher: User
    workspace: WorkspaceContext
    publication: AgentPublication | None = None
    publication_version: AgentPublicationVersion | None = None


async def get_published_agent_context(
    db: AsyncSession,
    agent_id: str,
) -> PublishedApplicationContext:
    return await get_published_application_context(db, agent_id, "agent")


async def get_published_workflow_context(
    db: AsyncSession,
    workflow_id: str,
) -> PublishedApplicationContext:
    return await get_published_application_context(db, workflow_id, "workflow")


async def get_published_application_context(
    db: AsyncSession,
    agent_id: str,
    application_type: Literal["agent", "workflow"],
) -> PublishedApplicationContext:
    agent = await agent_repository.get_agent_by_id(db, agent_id)
    if (
        agent is None
        or agent.app_type != application_type
        or agent.status != ACTIVE_STATUS
        or not agent.published
        or not agent.published_by_user_id
        or agent.published_at is None
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Published {application_type} not found.",
        )
    publication_version = None
    publication = None
    publisher_id = agent.published_by_user_id
    if application_type == "agent":
        if agent.current_published_version_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
        publication_version = await agent_repository.get_agent_publication_version(
            db,
            agent.workspace_id,
            agent.current_published_version_id,
        )
        if publication_version is None or publication_version.agent_id != agent.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
        try:
            publication = agent_publication_from_version(publication_version)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Published agent not found.",
            ) from exc
        publisher_id = publication_version.published_by_user_id
    else:
        publication = agent_publication_from_snapshot(agent)
    publisher = await user_repository.get_user_by_id(db, publisher_id)
    if publisher is None or not publisher.is_active:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Published {application_type} not found.",
        )
    try:
        workspace = await build_workspace_context(db, publisher, agent.workspace_id)
    except HTTPException as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Published {application_type} not found.",
        ) from exc
    return PublishedApplicationContext(
        agent=agent,
        publisher=publisher,
        workspace=workspace,
        publication=publication,
        publication_version=publication_version,
    )


async def get_workspace_published_agent_context(
    db: AsyncSession,
    agent_id: str,
    user: User,
) -> PublishedApplicationContext:
    return await get_workspace_published_application_context(
        db, agent_id, user, "agent"
    )


async def get_workspace_published_workflow_context(
    db: AsyncSession,
    workflow_id: str,
    user: User,
) -> PublishedApplicationContext:
    return await get_workspace_published_application_context(
        db, workflow_id, user, "workflow"
    )


async def get_workspace_published_application_context(
    db: AsyncSession,
    agent_id: str,
    user: User,
    application_type: Literal["agent", "workflow"],
) -> PublishedApplicationContext:
    context = await get_published_application_context(db, agent_id, application_type)
    try:
        await build_workspace_context(db, user, context.agent.workspace_id)
    except HTTPException as exc:
        if exc.status_code in {
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        }:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Published {application_type} not found.",
            ) from exc
        raise
    return context


__all__ = [
    "ExternalAccessSource",
    "PublishedApplicationContext",
    "get_published_agent_context",
    "get_published_workflow_context",
    "get_published_application_context",
    "get_workspace_published_agent_context",
    "get_workspace_published_workflow_context",
    "get_workspace_published_application_context",
]

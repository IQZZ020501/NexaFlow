"""Persistence for public users' project metadata and conversation membership."""

from sqlalchemy import delete, select, update

from app.domain.projects.models import AgentProject as FileTreeRow
from app.domain.projects.models import ChatConversation as ConversationRow
from app.domain.projects.models import ChatProject as ProjectRow
from app.entities.projects import ChatConversation, ChatProject
from app.infra.db import mapping


async def list_projects(db, workspace_id, agent_id, owner_id):
    rows = await db.scalars(
        select(ProjectRow)
        .where(
            ProjectRow.workspace_id == workspace_id,
            ProjectRow.agent_id == agent_id,
            ProjectRow.owner_user_id == owner_id,
            ProjectRow.dissolved_at.is_(None),
        )
        .order_by(ProjectRow.archived, ProjectRow.updated_at.desc())
    )
    return [mapping.to_entity(ChatProject, row) for row in rows]


async def get_project(db, project_id):
    row = await db.get(ProjectRow, project_id, populate_existing=True)
    return mapping.to_entity(ChatProject, row) if row else None


async def save_project(db, project):
    return mapping.to_entity(ChatProject, await mapping.save(db, ProjectRow, project))


async def list_conversations(db, workspace_id, agent_id, owner_id):
    rows = await db.scalars(
        select(ConversationRow)
        .where(
            ConversationRow.workspace_id == workspace_id,
            ConversationRow.agent_id == agent_id,
            ConversationRow.owner_user_id == owner_id,
        )
        .order_by(ConversationRow.created_at.desc())
    )
    return [mapping.to_entity(ChatConversation, row) for row in rows]


async def get_conversation(db, agent_id, owner_id, conversation_id):
    row = await db.scalar(
        select(ConversationRow).where(
            ConversationRow.agent_id == agent_id,
            ConversationRow.owner_user_id == owner_id,
            ConversationRow.conversation_id == conversation_id,
        )
    )
    return mapping.to_entity(ChatConversation, row) if row else None


async def save_conversation(db, conversation):
    return mapping.to_entity(
        ChatConversation, await mapping.save(db, ConversationRow, conversation)
    )


async def detach_project(db, project_id):
    await db.execute(
        update(ConversationRow)
        .where(ConversationRow.project_id == project_id)
        .values(project_id=None)
    )


async def delete_conversation(db, agent_id, owner_id, conversation_id):
    await db.execute(
        delete(ConversationRow).where(
            ConversationRow.agent_id == agent_id,
            ConversationRow.owner_user_id == owner_id,
            ConversationRow.conversation_id == conversation_id,
        )
    )


async def delete_application_projects(db, agent_id):
    tree_ids = list(
        await db.scalars(
            select(ProjectRow.file_tree_id).where(ProjectRow.agent_id == agent_id)
        )
    )
    await db.execute(
        delete(ConversationRow).where(ConversationRow.agent_id == agent_id)
    )
    await db.execute(delete(ProjectRow).where(ProjectRow.agent_id == agent_id))
    if tree_ids:
        await db.execute(delete(FileTreeRow).where(FileTreeRow.id.in_(tree_ids)))

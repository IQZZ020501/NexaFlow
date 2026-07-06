from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.llm.models import RegisteredModel


async def list_registered_models(
    db: AsyncSession,
    workspace_id: str,
) -> list[RegisteredModel]:
    result = await db.scalars(
        select(RegisteredModel)
        .where(RegisteredModel.workspace_id == workspace_id)
        .order_by(RegisteredModel.created_at)
    )
    return list(result.all())


async def get_registered_model_by_id(
    db: AsyncSession,
    model_id: str,
) -> RegisteredModel | None:
    return await db.get(RegisteredModel, model_id)


async def find_registered_model_id_by_name(
    db: AsyncSession,
    workspace_id: str,
    name: str,
    excluded_model_id: str | None = None,
) -> str | None:
    query = select(RegisteredModel.id).where(
        RegisteredModel.workspace_id == workspace_id,
        RegisteredModel.name == name,
    )
    if excluded_model_id is not None:
        query = query.where(RegisteredModel.id != excluded_model_id)
    return await db.scalar(query)


async def delete_registered_model_by_id(db: AsyncSession, model_id: str) -> None:
    await db.execute(delete(RegisteredModel).where(RegisteredModel.id == model_id))

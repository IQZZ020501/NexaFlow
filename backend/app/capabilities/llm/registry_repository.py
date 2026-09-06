from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.llm.models import RegisteredModel


async def list_registered_models(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
    folder_id: str | None = None,
    sort: str = "created_at",
) -> list[RegisteredModel]:
    statement = select(RegisteredModel).where(
        RegisteredModel.workspace_id == workspace_id
    )
    if folder_id is not None:
        statement = statement.where(
            RegisteredModel.folder_id.is_(None)
            if folder_id == ""
            else RegisteredModel.folder_id == folder_id
        )
    if sort == "updated_at":
        order_by = (RegisteredModel.updated_at.desc(), RegisteredModel.id.desc())
    elif sort == "name":
        order_by = (func.lower(RegisteredModel.name), RegisteredModel.id)
    else:
        order_by = (RegisteredModel.created_at.desc(), RegisteredModel.id.desc())
    result = await db.scalars(
        statement.order_by(*order_by).limit(limit).offset(offset)
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


async def delete_registered_models_in_workspace(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    await db.execute(
        delete(RegisteredModel).where(RegisteredModel.workspace_id == workspace_id)
    )

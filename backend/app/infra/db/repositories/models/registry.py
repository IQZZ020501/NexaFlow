from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.registered import RegisteredModel as ModelRow
from app.entities.defaults import utc_now
from app.entities.models import RegisteredModel
from app.infra.db.mapping import refresh_entity, save, to_entity, to_orm


def visible_models(user_id: str | None):
    return or_(
        ModelRow.visibility == "workspace",
        and_(ModelRow.visibility == "personal", ModelRow.created_by_user_id == user_id)
        if user_id is not None
        else False,
    )


async def list_registered_models(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
    folder_id: str | None = None,
    sort: str = "created_at",
    *,
    user_id: str | None = None,
    visibility: str | None = None,
) -> list[RegisteredModel]:
    statement = select(ModelRow).where(
        ModelRow.workspace_id == workspace_id,
        visible_models(user_id),
    )
    if visibility is not None:
        statement = statement.where(ModelRow.visibility == visibility)
    if folder_id is not None:
        statement = statement.where(
            ModelRow.folder_id.is_(None)
            if folder_id == ""
            else ModelRow.folder_id == folder_id
        )
    if sort == "updated_at":
        order_by = (ModelRow.updated_at.desc(), ModelRow.id.desc())
    elif sort == "name":
        order_by = (func.lower(ModelRow.name), ModelRow.id)
    else:
        order_by = (ModelRow.created_at.desc(), ModelRow.id.desc())
    result = await db.scalars(
        statement.order_by(*order_by).limit(limit).offset(offset)
    )
    return [to_entity(RegisteredModel, row) for row in result.all()]


async def get_registered_model_by_id(
    db: AsyncSession,
    model_id: str,
) -> RegisteredModel | None:
    row = await db.get(ModelRow, model_id)
    return to_entity(RegisteredModel, row) if row is not None else None


async def list_active_image_models(
    db: AsyncSession, workspace_id: str, *, user_id: str | None = None
) -> list[RegisteredModel]:
    result = await db.scalars(
        select(ModelRow)
        .where(
            ModelRow.workspace_id == workspace_id,
            ModelRow.model_type == "IMAGE",
            ModelRow.status == "active",
            visible_models(user_id),
        )
        .order_by(ModelRow.id)
        .limit(2)
    )
    return [to_entity(RegisteredModel, row) for row in result.all()]


async def find_registered_model_id_by_name(
    db: AsyncSession,
    workspace_id: str,
    name: str,
    excluded_model_id: str | None = None,
    *,
    visibility: str = "workspace",
    owner_id: str | None = None,
) -> str | None:
    query = select(ModelRow.id).where(
        ModelRow.workspace_id == workspace_id,
        ModelRow.name == name,
        ModelRow.visibility == visibility,
    )
    if visibility == "personal":
        query = query.where(ModelRow.created_by_user_id == owner_id)
    if excluded_model_id is not None:
        query = query.where(ModelRow.id != excluded_model_id)
    return await db.scalar(query)


async def delete_registered_model_by_id(db: AsyncSession, model_id: str) -> None:
    await db.execute(delete(ModelRow).where(ModelRow.id == model_id))


async def delete_registered_models_in_workspace(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    await db.execute(delete(ModelRow).where(ModelRow.workspace_id == workspace_id))


async def create_registered_model(
    db: AsyncSession, model: RegisteredModel
) -> RegisteredModel:
    row = to_orm(ModelRow, model)
    db.add(row)
    await db.flush()
    return to_entity(RegisteredModel, row)


async def save_registered_model(
    db: AsyncSession, model: RegisteredModel
) -> RegisteredModel:
    model.updated_at = utc_now()
    return to_entity(RegisteredModel, await save(db, ModelRow, model))


async def refresh_registered_model(
    db: AsyncSession, model: RegisteredModel
) -> RegisteredModel:
    return await refresh_entity(db, ModelRow, RegisteredModel, model)


async def retire_personal_models_for_user(db: AsyncSession, user_id: str) -> None:
    # Keep authored references/history, but never retain a departed account's credentials.
    await db.execute(
        update(ModelRow)
        .where(
            ModelRow.visibility == "personal", ModelRow.created_by_user_id == user_id
        )
        .values(
            status="disabled",
            api_key_ciphertext=None,
            api_key_hint=None,
            credential_config={},
            credential_secret_hints={},
            api_key_updated_at=utc_now(),
        )
    )

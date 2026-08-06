"""Model registry data-access port.

The registered-model table is owned by the LLM capability; business domains
read it through this contract instead of importing
``app.capabilities.llm.registry_repository`` directly.
"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.llm import registry_repository as _registry_repository
from app.capabilities.llm.models import RegisteredModel


class ModelRegistry(Protocol):
    async def list_registered_models(
        self,
        db: AsyncSession,
        workspace_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[RegisteredModel]: ...

    async def get_registered_model_by_id(
        self,
        db: AsyncSession,
        model_id: str,
    ) -> RegisteredModel | None: ...

    async def find_registered_model_id_by_name(
        self,
        db: AsyncSession,
        workspace_id: str,
        name: str,
        excluded_model_id: str | None = None,
    ) -> str | None: ...

    async def delete_registered_model_by_id(
        self,
        db: AsyncSession,
        model_id: str,
    ) -> None: ...


def build_model_registry() -> ModelRegistry:
    return _registry_repository


async def list_registered_models(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[RegisteredModel]:
    return await _registry_repository.list_registered_models(
        db,
        workspace_id,
        limit,
        offset,
    )


async def get_registered_model_by_id(
    db: AsyncSession,
    model_id: str,
) -> RegisteredModel | None:
    return await _registry_repository.get_registered_model_by_id(db, model_id)


async def find_registered_model_id_by_name(
    db: AsyncSession,
    workspace_id: str,
    name: str,
    excluded_model_id: str | None = None,
) -> str | None:
    return await _registry_repository.find_registered_model_id_by_name(
        db,
        workspace_id,
        name,
        excluded_model_id,
    )


async def delete_registered_model_by_id(
    db: AsyncSession,
    model_id: str,
) -> None:
    return await _registry_repository.delete_registered_model_by_id(db, model_id)


__all__ = [
    "ModelRegistry",
    "build_model_registry",
    "delete_registered_model_by_id",
    "find_registered_model_id_by_name",
    "get_registered_model_by_id",
    "list_registered_models",
]

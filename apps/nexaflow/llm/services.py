import asyncio
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.audit.services import record_audit_log
from nexaflow.core.config import Settings
from nexaflow.core.secrets import decrypt_secret, encrypt_secret, secret_hint
from nexaflow.core.validation import normalize_name
from nexaflow.db.model_utils import utc_now
from nexaflow.identity.models import User
from nexaflow.llm.models import RegisteredModel
from nexaflow.llm import repositories as model_repository
from nexaflow.llm.providers import PROVIDER_CATALOG
from nexaflow.llm.runtime import (
    ModelProviderError,
    ModelProviderStatusError,
    OpenAICompatibleModelProvider,
)
from nexaflow.llm.schemas import (
    BaseModelOptionResponse,
    ModelCredentialFieldResponse,
    ModelProviderCatalogResponse,
    RegisteredModelCreateRequest,
    RegisteredModelResponse,
    RegisteredModelUpdateRequest,
)

ACTIVE_STATUS = "active"
DISABLED_STATUS = "disabled"
STATUSES = {ACTIVE_STATUS, DISABLED_STATUS}
PROVIDER_TYPES = {"openai_compatible"}
MODEL_TYPES = {"LLM", "EMBEDDING", "RERANKER"}
MODEL_TYPE_ALIASES = {
    "chat": "LLM",
    "llm": "LLM",
    "embedding": "EMBEDDING",
    "embeddings": "EMBEDDING",
    "rerank": "RERANKER",
    "reranker": "RERANKER",
}


def provider_catalog_entry(provider: str) -> dict[str, Any]:
    for entry in PROVIDER_CATALOG:
        if entry["provider"] == provider:
            return entry
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid model provider.")


def normalize_model_type(model_type: str) -> str:
    value = model_type.strip()
    normalized = MODEL_TYPE_ALIASES.get(value.lower(), value.upper())
    if normalized not in MODEL_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid model type.")
    return normalized


def validate_provider_type(provider_type: str) -> str:
    if provider_type not in PROVIDER_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid model provider type.")
    return provider_type


def validate_status(value: str) -> str:
    if value not in STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid status.")
    return value


def normalize_api_base(value: object) -> str:
    if not isinstance(value, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "API URL is required.")
    api_base = value.strip().rstrip("/")
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid API URL.")
    return api_base


def normalize_api_key(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "API Key must be a string.")
    value = value.strip()
    return value or None


def is_masked_secret(value: str, hint: str | None) -> bool:
    if not hint:
        return False
    return value == hint or (value.startswith("****") and value.endswith(hint[-4:]))


def validate_provider_support(entry: dict[str, Any], model_type: str) -> None:
    if model_type not in entry["model_types"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Model type is not supported by this provider.")


def set_model_api_key(model: RegisteredModel, api_key: str, settings: Settings) -> None:
    model.api_key_ciphertext = encrypt_secret(api_key, settings.model_secret_key)
    model.api_key_hint = secret_hint(api_key)
    model.api_key_updated_at = utc_now()


def run_openai_compatible_model_test(
    api_base: str,
    api_key: str,
    model_name: str,
    model_type: str,
) -> None:
    try:
        OpenAICompatibleModelProvider(api_base, api_key, model_name).test(model_type)
    except ModelProviderStatusError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Model test failed with provider status {exc.status_code}.",
        ) from exc
    except ModelProviderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Model test request failed.") from exc


async def test_registered_model(
    provider_type: str,
    api_base: str,
    api_key: str,
    model_name: str,
    model_type: str,
) -> None:
    if provider_type != "openai_compatible":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Model test is only supported for OpenAI-compatible providers.",
        )
    await asyncio.to_thread(
        run_openai_compatible_model_test,
        api_base,
        api_key,
        model_name,
        model_type,
    )


def model_to_response(model: RegisteredModel) -> RegisteredModelResponse:
    credential = {
        "api_base": model.api_base,
        "api_key": model.api_key_hint or "",
    }
    return RegisteredModelResponse(
        id=model.id,
        workspace_id=model.workspace_id,
        name=model.name,
        provider=model.provider,
        provider_type=model.provider_type,
        model_type=model.model_type,
        model_name=model.model_name,
        status=model.status,
        credential=credential,
        api_base=model.api_base,
        has_api_key=model.api_key_ciphertext is not None,
        api_key_hint=model.api_key_hint,
        meta=model.meta,
        created_by_user_id=model.created_by_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def list_provider_catalog(model_type: str | None = None) -> list[ModelProviderCatalogResponse]:
    normalized_type = normalize_model_type(model_type) if model_type else None
    entries = [
        entry
        for entry in PROVIDER_CATALOG
        if normalized_type is None or normalized_type in entry["model_types"]
    ]
    return [
        ModelProviderCatalogResponse(
            provider=entry["provider"],
            name=entry["name"],
            provider_type=entry["provider_type"],
            icon=entry.get("icon", ""),
            model_types=entry["model_types"],
            default_api_base=entry["default_api_base"],
        )
        for entry in entries
    ]


def list_model_types(provider: str) -> list[dict[str, str]]:
    entry = provider_catalog_entry(provider)
    labels = {"LLM": "LLM", "EMBEDDING": "Embedding", "RERANKER": "Rerank"}
    return [{"key": labels[item], "value": item} for item in entry["model_types"]]


def list_base_models(provider: str, model_type: str) -> list[BaseModelOptionResponse]:
    entry = provider_catalog_entry(provider)
    normalized_type = normalize_model_type(model_type)
    validate_provider_support(entry, normalized_type)
    return [BaseModelOptionResponse(**item) for item in entry["models"].get(normalized_type, [])]


def get_model_credential_form(provider: str) -> list[ModelCredentialFieldResponse]:
    entry = provider_catalog_entry(provider)
    return [
        ModelCredentialFieldResponse(
            field="api_base",
            label="API URL",
            input_type="TextInput",
            required=True,
            default_value=entry["default_api_base"],
        ),
        ModelCredentialFieldResponse(
            field="api_key",
            label="API Key",
            input_type="PasswordInput",
            required=True,
            default_value="",
        ),
    ]


async def list_registered_models(db: AsyncSession, workspace_id: str) -> list[RegisteredModelResponse]:
    models = await model_repository.list_registered_models(db, workspace_id)
    return [model_to_response(item) for item in models]


async def get_registered_model(db: AsyncSession, workspace_id: str, model_id: str) -> RegisteredModel:
    model = await model_repository.get_registered_model_by_id(db, model_id)
    if model is None or model.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found.")
    return model


async def assert_model_name_available(
    db: AsyncSession,
    workspace_id: str,
    name: str,
    excluded_model_id: str | None = None,
) -> None:
    if await model_repository.find_registered_model_id_by_name(
        db,
        workspace_id,
        name,
        excluded_model_id,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Model name already exists.")


async def create_registered_model(
    db: AsyncSession,
    workspace_id: str,
    payload: RegisteredModelCreateRequest,
    actor: User,
    settings: Settings,
) -> RegisteredModelResponse:
    name = normalize_name(payload.name)
    await assert_model_name_available(db, workspace_id, name)

    entry = provider_catalog_entry(payload.provider)
    provider_type = validate_provider_type(payload.provider_type)
    if provider_type != entry["provider_type"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid provider type for provider.")
    model_type = normalize_model_type(payload.model_type)
    validate_provider_support(entry, model_type)
    api_base = normalize_api_base(payload.credential.get("api_base") or payload.credential.get("base_url"))
    api_key = normalize_api_key(payload.credential.get("api_key"))
    if api_key is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "API Key is required.")

    model_name = payload.model_name.strip()
    await test_registered_model(provider_type, api_base, api_key, model_name, model_type)

    model = RegisteredModel(
        workspace_id=workspace_id,
        name=name,
        provider=payload.provider,
        provider_type=provider_type,
        api_base=api_base,
        model_type=model_type,
        model_name=model_name,
        status=ACTIVE_STATUS,
        meta=payload.meta,
        created_by_user_id=actor.id,
    )
    set_model_api_key(model, api_key, settings)
    db.add(model)

    try:
        await db.flush()
        record_audit_log(
            db,
            actor,
            "model.create",
            "model",
            model.id,
            model.name,
            {"provider": model.provider, "model_type": model.model_type, "model_name": model.model_name},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Model already exists.") from exc

    await db.refresh(model)
    return model_to_response(model)


async def update_registered_model(
    db: AsyncSession,
    model: RegisteredModel,
    payload: RegisteredModelUpdateRequest,
    actor: User,
    settings: Settings,
) -> RegisteredModelResponse:
    details = payload.model_dump(exclude_unset=True)
    name = normalize_name(payload.name) if payload.name is not None else model.name
    if name != model.name:
        await assert_model_name_available(db, model.workspace_id, name, model.id)

    provider = payload.provider if payload.provider is not None else model.provider
    entry = provider_catalog_entry(provider)
    provider_type = (
        validate_provider_type(payload.provider_type)
        if payload.provider_type is not None
        else model.provider_type
    )
    if provider_type != entry["provider_type"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid provider type for provider.")

    model_type = normalize_model_type(payload.model_type) if payload.model_type is not None else model.model_type
    validate_provider_support(entry, model_type)
    model_name = payload.model_name.strip() if payload.model_name is not None else model.model_name

    credential = payload.credential or {}
    api_base = model.api_base
    if "api_base" in credential or "base_url" in credential:
        api_base = normalize_api_base(credential.get("api_base") or credential.get("base_url"))

    current_api_key = (
        decrypt_secret(model.api_key_ciphertext, settings.model_secret_key)
        if model.api_key_ciphertext is not None
        else None
    )
    api_key = current_api_key
    api_key_updated = False
    if "api_key" in credential:
        candidate_api_key = normalize_api_key(credential.get("api_key"))
        if candidate_api_key and not is_masked_secret(candidate_api_key, model.api_key_hint):
            api_key = candidate_api_key
            api_key_updated = True
    if api_key is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "API Key is required.")

    await test_registered_model(provider_type, api_base, api_key, model_name, model_type)

    model.name = name
    model.provider = provider
    model.provider_type = provider_type
    model.api_base = api_base
    model.model_type = model_type
    model.model_name = model_name
    if payload.status is not None:
        model.status = validate_status(payload.status)
    if payload.meta is not None:
        model.meta = payload.meta
    if api_key_updated:
        set_model_api_key(model, api_key, settings)

    if "credential" in details:
        details["credential"] = {"api_base": api_base, "api_key_updated": api_key_updated}

    record_audit_log(
        db,
        actor,
        "model.update",
        "model",
        model.id,
        model.name,
        details,
        workspace_id=model.workspace_id,
    )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Model already exists.") from exc

    await db.refresh(model)
    return model_to_response(model)


async def delete_registered_model(db: AsyncSession, model: RegisteredModel, actor: User) -> None:
    record_audit_log(
        db,
        actor,
        "model.delete",
        "model",
        model.id,
        model.name,
        {"provider": model.provider, "model_type": model.model_type, "model_name": model.model_name},
        workspace_id=model.workspace_id,
    )
    await model_repository.delete_registered_model_by_id(db, model.id)
    await db.commit()

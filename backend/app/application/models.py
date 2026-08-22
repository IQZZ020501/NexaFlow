"""Model registry use cases.

Owns the model-management workflow (validation orchestration, audit
recording, DTO assembly) on top of the LLM capability helpers in
``app.capabilities.llm.registry``. The capability layer itself stays free of
business-domain, audit, and API-schema imports.
"""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ports import model_registry as model_repository
from app.capabilities.llm.credentials import legacy_credential_config
from app.ports.llm import RegisteredModel
from app.capabilities.llm.providers import PROVIDER_CATALOG
from app.capabilities.llm.registry import (
    ACTIVE_STATUS,
    apply_model_credentials,
    credential_fields,
    normalize_model_request_params,
    normalize_model_type,
    normalize_provider_credentials,
    provider_catalog_entry,
    stored_model_credentials,
    test_registered_model,
    validate_provider_support,
    validate_provider_type,
    validate_status,
)
from app.capabilities.llm.runtime import (
    DEFAULT_MODEL_REQUEST_PARAMS,
    MODEL_REQUEST_PARAMS_META_KEY,
)
from app.domain.user import User
from app.infrastructure.config import Settings
from app.infrastructure.validation import normalize_name
from app.schemas.model import (
    BaseModelOptionResponse,
    ModelCredentialFieldResponse,
    ModelProviderCatalogResponse,
    ModelTypeOptionResponse,
    RegisteredModelCreateRequest,
    RegisteredModelResponse,
    RegisteredModelUpdateRequest,
)
from app.shareddomain.audit.services import record_audit_log


def model_to_response(model: RegisteredModel) -> RegisteredModelResponse:
    config = model.credential_config or legacy_credential_config(
        model.provider_type,
        model.api_base,
    )
    hints = model.credential_secret_hints or (
        {"api_key": model.api_key_hint} if model.api_key_hint else {}
    )
    request_params = (model.meta or {}).get(
        MODEL_REQUEST_PARAMS_META_KEY,
        DEFAULT_MODEL_REQUEST_PARAMS,
    )
    return RegisteredModelResponse(
        id=model.id,
        workspace_id=model.workspace_id,
        name=model.name,
        provider=model.provider,
        provider_type=model.provider_type,
        model_type=model.model_type,
        model_name=model.model_name,
        status=model.status,
        credential={**config, **hints},
        api_base=model.api_base,
        has_api_key=model.api_key_ciphertext is not None,
        api_key_hint=model.api_key_hint,
        meta=model.meta,
        request_params=request_params if isinstance(request_params, dict) else {},
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


def list_model_types(provider: str) -> list[ModelTypeOptionResponse]:
    entry = provider_catalog_entry(provider)
    labels = {"LLM": "LLM", "EMBEDDING": "Embedding", "RERANKER": "Rerank"}
    return [
        ModelTypeOptionResponse(key=labels[item], value=item)
        for item in entry["model_types"]
    ]


def list_base_models(provider: str, model_type: str) -> list[BaseModelOptionResponse]:
    entry = provider_catalog_entry(provider)
    normalized_type = normalize_model_type(model_type)
    validate_provider_support(entry, normalized_type)
    return [BaseModelOptionResponse(**item) for item in entry["models"].get(normalized_type, [])]


def get_model_credential_form(provider: str) -> list[ModelCredentialFieldResponse]:
    entry = provider_catalog_entry(provider)
    return [ModelCredentialFieldResponse(**field) for field in credential_fields(entry)]


async def list_registered_models(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[RegisteredModelResponse]:
    models = await model_repository.list_registered_models(
        db,
        workspace_id,
        limit,
        offset,
    )
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
    raw_request_params = payload.request_params
    if "request_params" not in payload.model_fields_set and model_type == "LLM":
        raw_request_params = DEFAULT_MODEL_REQUEST_PARAMS
    request_params = normalize_model_request_params(
        raw_request_params,
        model_type,
    )
    config, secrets, hints, _ = normalize_provider_credentials(
        entry,
        payload.credential,
    )

    model_name = payload.model_name.strip()
    if not model_name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Model name is required.",
        )
    capabilities = await test_registered_model(
        provider_type,
        {**config, **secrets},
        model_name,
        model_type,
        request_params,
    )

    model = RegisteredModel(
        workspace_id=workspace_id,
        name=name,
        provider=payload.provider,
        provider_type=provider_type,
        api_base="",
        model_type=model_type,
        model_name=model_name,
        status=ACTIVE_STATUS,
        meta={
            **payload.meta,
            MODEL_REQUEST_PARAMS_META_KEY: request_params,
            **capabilities,
        },
        created_by_user_id=actor.id,
    )
    apply_model_credentials(
        model,
        config,
        secrets,
        hints,
        settings,
        rewrite_secrets=True,
    )
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
    raw_request_params = payload.request_params
    if raw_request_params is None:
        if model_type != model.model_type:
            raw_request_params = (
                DEFAULT_MODEL_REQUEST_PARAMS if model_type == "LLM" else {}
            )
        else:
            raw_request_params = (model.meta or {}).get(
                MODEL_REQUEST_PARAMS_META_KEY,
                DEFAULT_MODEL_REQUEST_PARAMS if model_type == "LLM" else {},
            )
    request_params = normalize_model_request_params(
        raw_request_params,
        model_type,
    )
    model_name = payload.model_name.strip() if payload.model_name is not None else model.model_name
    if not model_name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Model name is required.",
        )

    provider_changed = provider != model.provider or provider_type != model.provider_type
    if provider_changed:
        current_config: dict[str, str] = {}
        current_secrets: dict[str, str] = {}
        current_hints: dict[str, str] = {}
    else:
        try:
            current_config, current_secrets, current_hints = stored_model_credentials(
                model,
                settings,
            )
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Stored model credentials are invalid.",
            ) from exc
    config, secrets, hints, changed_secrets = normalize_provider_credentials(
        entry,
        payload.credential or {},
        current_config=current_config,
        current_secrets=current_secrets,
        current_hints=current_hints,
    )
    capabilities = await test_registered_model(
        provider_type,
        {**config, **secrets},
        model_name,
        model_type,
        request_params,
    )

    model.name = name
    model.provider = provider
    model.provider_type = provider_type
    model.model_type = model_type
    model.model_name = model_name
    if payload.status is not None:
        model.status = validate_status(payload.status)
    model.meta = {
        **(payload.meta if payload.meta is not None else (model.meta or {})),
        MODEL_REQUEST_PARAMS_META_KEY: request_params,
        **capabilities,
    }
    apply_model_credentials(
        model,
        config,
        secrets,
        hints,
        settings,
        rewrite_secrets=provider_changed or bool(changed_secrets),
    )

    if "credential" in details:
        details["credential"] = {
            "config_fields": sorted(config),
            "secret_fields_updated": sorted(changed_secrets),
        }
    if "request_params" in details:
        details["request_params"] = {"keys": sorted(request_params)}

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
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Model is in use.") from exc

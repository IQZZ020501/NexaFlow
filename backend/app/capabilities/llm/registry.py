import asyncio
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.capabilities.llm.credentials import (
    decrypt_credential_secrets,
    encrypt_credential_secrets,
    legacy_credential_config,
)
from app.capabilities.llm.models import RegisteredModel
from app.capabilities.llm.providers import PROVIDER_CATALOG
from app.capabilities.llm.runtime import (
    SUPPORTED_PROVIDER_TYPES,
    ModelProviderError,
    ModelProviderStatusError,
    test_model_connection,
)
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.secrets import secret_hint

ACTIVE_STATUS = "active"
DISABLED_STATUS = "disabled"
STATUSES = {ACTIVE_STATUS, DISABLED_STATUS}
PROVIDER_TYPES = SUPPORTED_PROVIDER_TYPES
MODEL_TYPES = {"LLM", "EMBEDDING", "RERANKER"}
URL_CREDENTIAL_FIELDS = {"api_base", "azure_endpoint", "endpoint_url"}
DEFAULT_CREDENTIAL_FIELDS = [
    {
        "field": "api_base",
        "label": "API URL",
        "input_type": "TextInput",
        "required": True,
        "default_value": "",
    },
    {
        "field": "api_key",
        "label": "API Key",
        "input_type": "PasswordInput",
        "required": True,
        "default_value": "",
    },
]
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


def normalize_url_credential(value: str, field: str) -> str:
    api_base = value.rstrip("/")
    if not api_base:
        return ""
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Invalid URL for model credential {field}.",
        )
    return api_base


def normalize_credential_value(value: object, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Model credential {field} must be a string.",
        )
    normalized = value.strip()
    return (
        normalize_url_credential(normalized, field)
        if field in URL_CREDENTIAL_FIELDS
        else normalized
    )


def is_masked_secret(value: str, hint: str | None) -> bool:
    if not hint:
        return False
    return value == hint or (value.startswith("****") and value.endswith(hint[-4:]))


def validate_provider_support(entry: dict[str, Any], model_type: str) -> None:
    if model_type not in entry["model_types"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Model type is not supported by this provider.")


def credential_fields(entry: dict[str, Any]) -> list[dict[str, Any]]:
    fields = entry.get("credential_fields")
    if isinstance(fields, list):
        return fields
    return [
        {
            **field,
            "default_value": (
                entry["default_api_base"]
                if field["field"] == "api_base"
                else field["default_value"]
            ),
            "required": (
                entry.get("api_key_required", True)
                if field["field"] == "api_key"
                else field["required"]
            ),
        }
        for field in DEFAULT_CREDENTIAL_FIELDS
    ]


def stored_model_credentials(
    model: RegisteredModel,
    settings: Settings,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    config = {
        key: value
        for key, value in (model.credential_config or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    if not config:
        config = legacy_credential_config(model.provider_type, model.api_base)
    secrets = decrypt_credential_secrets(
        model.api_key_ciphertext,
        settings.model_secret_key,
    )
    hints = {
        key: value
        for key, value in (model.credential_secret_hints or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    if not hints and model.api_key_hint:
        hints = {"api_key": model.api_key_hint}
    return config, secrets, hints


def normalize_provider_credentials(
    entry: dict[str, Any],
    submitted: dict[str, Any],
    *,
    current_config: dict[str, str] | None = None,
    current_secrets: dict[str, str] | None = None,
    current_hints: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], set[str]]:
    values = dict(submitted)
    if "base_url" in values and "api_base" not in values:
        values["api_base"] = values.pop("base_url")
    fields = credential_fields(entry)
    allowed_fields = {field["field"] for field in fields}
    unknown_fields = set(values) - allowed_fields
    if unknown_fields:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unsupported model credential: {min(unknown_fields)}.",
        )

    config = dict(current_config or {})
    secrets = dict(current_secrets or {})
    hints = dict(current_hints or {})
    changed_secrets: set[str] = set()
    for field in fields:
        name = field["field"]
        is_secret = field["input_type"] == "PasswordInput"
        if is_secret:
            if name in values and values[name] is None:
                secrets.pop(name, None)
                hints.pop(name, None)
                changed_secrets.add(name)
            elif name in values:
                value = normalize_credential_value(values[name], name)
                if value and not is_masked_secret(value, hints.get(name)):
                    secrets[name] = value
                    hints[name] = secret_hint(value)
                    changed_secrets.add(name)
            if field.get("required", True) and not secrets.get(name):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Model credential {name} is required.",
                )
            continue

        if name in values:
            value = normalize_credential_value(values[name], name)
        elif name in config:
            value = config[name]
        else:
            value = normalize_credential_value(field.get("default_value"), name)
        if field.get("required", True) and not value:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Model credential {name} is required.",
            )
        if value:
            config[name] = value
        else:
            config.pop(name, None)

    access_key = secrets.get("aws_access_key_id")
    secret_key = secrets.get("aws_secret_access_key")
    if bool(access_key) != bool(secret_key):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "AWS access key ID and secret access key must be provided together.",
        )
    if secrets.get("aws_session_token") and not access_key:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "AWS session token requires access key credentials.",
        )
    return config, secrets, hints, changed_secrets


def legacy_connection_value(config: dict[str, str]) -> str:
    return next(
        (
            config[field]
            for field in ("api_base", "azure_endpoint", "endpoint_url", "region_name")
            if config.get(field)
        ),
        "",
    )


def primary_secret_hint(hints: dict[str, str]) -> str | None:
    for field in ("api_key", "aws_access_key_id", "aws_secret_access_key"):
        if hints.get(field):
            return hints[field]
    return next(iter(hints.values()), None)


def apply_model_credentials(
    model: RegisteredModel,
    config: dict[str, str],
    secrets: dict[str, str],
    hints: dict[str, str],
    settings: Settings,
    *,
    rewrite_secrets: bool,
) -> None:
    model.credential_config = config
    model.credential_secret_hints = hints
    model.api_base = legacy_connection_value(config)
    model.api_key_hint = primary_secret_hint(hints)
    if rewrite_secrets:
        model.api_key_ciphertext = encrypt_credential_secrets(
            secrets,
            settings.model_secret_key,
        )
        model.api_key_updated_at = utc_now()


def run_model_test(
    provider_type: str,
    credentials: dict[str, str],
    model_name: str,
    model_type: str,
) -> dict[str, bool]:
    try:
        return test_model_connection(
            provider_type,
            credentials,
            model_name,
            model_type,
        )
    except ModelProviderStatusError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Model test failed with provider status {exc.status_code}.",
        ) from exc
    except ModelProviderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Model test request failed.") from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Model test request failed.") from exc


async def test_registered_model(
    provider_type: str,
    credentials: dict[str, str],
    model_name: str,
    model_type: str,
) -> dict[str, bool]:
    return await asyncio.to_thread(
        run_model_test,
        provider_type,
        credentials,
        model_name,
        model_type,
    )

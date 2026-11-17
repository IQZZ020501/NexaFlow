"""Frozen, non-secret model configuration fingerprints shared by all callers."""

import hashlib
import hmac
import json
from typing import Any

from app.domain.models.registered import RegisteredModel
from app.ports.llm import DEFAULT_MODEL_REQUEST_PARAMS, MODEL_REQUEST_PARAMS_META_KEY

MODEL_RUNTIME_SNAPSHOT_SCHEMA_VERSION = 1


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def build_model_runtime_snapshot(model: RegisteredModel) -> dict[str, Any]:
    meta = model.meta if isinstance(model.meta, dict) else {}
    request_params = meta.get(
        MODEL_REQUEST_PARAMS_META_KEY,
        DEFAULT_MODEL_REQUEST_PARAMS,
    )
    payload: dict[str, Any] = {
        "schema_version": MODEL_RUNTIME_SNAPSHOT_SCHEMA_VERSION,
        "model_id": model.id,
        "provider_type": model.provider_type,
        "model_type": model.model_type,
        "model_name": model.model_name,
        "api_base": model.api_base,
        "credential_config": {
            key: value
            for key, value in sorted((model.credential_config or {}).items())
            if isinstance(key, str) and isinstance(value, str)
        },
        "credential_revision": _isoformat(model.api_key_updated_at),
        "request_params": request_params if isinstance(request_params, dict) else {},
        "stream_usage_supported": meta.get("stream_usage_supported") is True,
    }
    return {**payload, "fingerprint": _canonical_hash(payload)}


def require_model_runtime_snapshot(
    model: RegisteredModel,
    snapshot: dict[str, Any],
) -> None:
    """Fail closed when a versioned run would execute with different model settings."""
    if snapshot.get("schema_version") != MODEL_RUNTIME_SNAPSHOT_SCHEMA_VERSION:
        return
    expected = snapshot.get("fingerprint")
    current = build_model_runtime_snapshot(model).get("fingerprint")
    if (
        not isinstance(expected, str)
        or not isinstance(current, str)
        or not hmac.compare_digest(expected, current)
    ):
        raise ValueError("Agent model configuration changed after run creation.")


__all__ = [
    "build_model_runtime_snapshot",
    "require_model_runtime_snapshot",
]

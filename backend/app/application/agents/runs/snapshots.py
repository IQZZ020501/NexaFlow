"""Immutable execution policy and resource snapshots for Agent runs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any

from app.domain.models.registered import RegisteredModel
from app.entities.knowledge import KnowledgeBase
from app.infra.config.settings import Settings
from app.ports.llm import DEFAULT_MODEL_REQUEST_PARAMS, MODEL_REQUEST_PARAMS_META_KEY


MODEL_RUNTIME_SNAPSHOT_SCHEMA_VERSION = 1
KNOWLEDGE_RESOURCE_SNAPSHOT_SCHEMA_VERSION = 1


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class AgentRuntimePolicy:
    max_runtime_seconds: float
    max_turns: int
    max_tool_calls: int
    max_knowledge_calls: int
    max_knowledge_rounds: int
    max_model_tokens: int

    @classmethod
    def from_settings(cls, settings: Settings | None) -> AgentRuntimePolicy:
        if settings is None:
            return cls(300.0, 8, 12, 6, 3, 100_000)
        return cls(
            float(settings.agent_run_timeout_seconds),
            settings.agent_max_turns,
            settings.agent_max_tool_calls,
            settings.agent_max_knowledge_calls,
            settings.agent_max_knowledge_rounds,
            settings.agent_max_model_tokens,
        )


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


def build_knowledge_resource_snapshot(
    knowledge_bases: list[KnowledgeBase],
    content_revisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    revisions_by_knowledge_base: dict[str, list[dict[str, Any]]] = {}
    for revision in content_revisions or []:
        knowledge_base_id = revision.get("knowledge_base_id")
        document_id = revision.get("document_id")
        if not isinstance(knowledge_base_id, str) or not isinstance(
            document_id,
            str,
        ):
            continue
        revisions_by_knowledge_base.setdefault(knowledge_base_id, []).append(
            {
                "document_id": document_id,
                "document_updated_at": _isoformat(
                    revision.get("document_updated_at")
                ),
                "indexed_chunk_count": int(
                    revision.get("indexed_chunk_count") or 0
                ),
                "latest_chunk_updated_at": _isoformat(
                    revision.get("latest_chunk_updated_at")
                ),
            }
        )
    resources = [
        {
            "knowledge_base_id": item.id,
            "status": item.status,
            "embedding_model_id": item.embedding_model_id,
            "reranker_model_id": item.reranker_model_id,
            "active_graph_revision_id": item.active_graph_revision_id,
            "updated_at": _isoformat(item.updated_at),
            "content_fingerprint": _canonical_hash(
                {
                    "documents": sorted(
                        revisions_by_knowledge_base.get(item.id, []),
                        key=lambda value: value["document_id"],
                    )
                }
            ),
            "indexed_document_count": len(
                revisions_by_knowledge_base.get(item.id, [])
            ),
        }
        for item in sorted(knowledge_bases, key=lambda value: value.id)
    ]
    payload: dict[str, Any] = {
        "schema_version": KNOWLEDGE_RESOURCE_SNAPSHOT_SCHEMA_VERSION,
        "resources": resources,
    }
    return {**payload, "fingerprint": _canonical_hash(payload)}


def require_knowledge_resource_snapshot(
    knowledge_bases: list[KnowledgeBase],
    snapshot: dict[str, Any],
    content_revisions: list[dict[str, Any]] | None = None,
) -> None:
    """Fail closed when versioned knowledge resources changed before execution."""
    if snapshot.get("schema_version") != KNOWLEDGE_RESOURCE_SNAPSHOT_SCHEMA_VERSION:
        return
    expected = snapshot.get("fingerprint")
    current = build_knowledge_resource_snapshot(
        knowledge_bases,
        content_revisions,
    ).get("fingerprint")
    if (
        not isinstance(expected, str)
        or not isinstance(current, str)
        or not hmac.compare_digest(expected, current)
    ):
        raise ValueError("Agent knowledge configuration changed after run creation.")


__all__ = [
    "AgentRuntimePolicy",
    "build_knowledge_resource_snapshot",
    "build_model_runtime_snapshot",
    "require_knowledge_resource_snapshot",
    "require_model_runtime_snapshot",
]

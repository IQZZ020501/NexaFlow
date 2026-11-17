"""Immutable execution policy and resource snapshots for Agent runs."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from app.domain.models.runtime import (
    build_model_runtime_snapshot,
    require_model_runtime_snapshot,
)
from app.entities.knowledge import KnowledgeBase
from app.infra.config.settings import Settings

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
    # Retained in frozen snapshots for backward compatibility; adaptive
    # retrieval no longer enforces dedicated call or round caps.
    max_knowledge_calls: int
    max_knowledge_rounds: int
    # Retained in frozen snapshots for backward compatibility; Agent execution
    # no longer enforces a cumulative model-token cap.
    max_model_tokens: int

    @classmethod
    def from_settings(cls, settings: Settings | None, *, shell: bool = False) -> AgentRuntimePolicy:
        if settings is None:
            return cls(900.0, 24, 64, 6, 3, 100_000) if shell else cls(300.0, 8, 12, 6, 3, 100_000)
        return cls(
            float(settings.agent_shell_run_timeout_seconds if shell else settings.agent_run_timeout_seconds),
            settings.agent_shell_max_turns if shell else settings.agent_max_turns,
            settings.agent_shell_max_tool_calls if shell else settings.agent_max_tool_calls,
            settings.agent_max_knowledge_calls,
            settings.agent_max_knowledge_rounds,
            settings.agent_max_model_tokens,
        )


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

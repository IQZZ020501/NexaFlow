import hashlib
import json
from datetime import datetime
from typing import Any, Protocol

from app.entities.knowledge_graph import (
    GRAPH_CLAIM_ACTIVE,
    GRAPH_CLAIM_CANDIDATE,
    GRAPH_CLAIM_REJECTED,
)
from app.shareddomain.knowledge_graph.schema import normalize_graph_name


class EntityCandidate(Protocol):
    id: str
    external_key: str | None
    normalized_name: str


def claim_fingerprint(
    subject_entity_id: str,
    predicate: str,
    object_entity_id: str | None,
    object_value: Any | None,
    valid_from: datetime | None,
    valid_to: datetime | None,
) -> str:
    payload = {
        "subject": subject_entity_id,
        "predicate": predicate,
        "object_entity": object_entity_id,
        "object_value": object_value,
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def choose_automatic_entity_match(
    external_key: str | None,
    canonical_name: str,
    candidates: list[EntityCandidate],
    human_alias_entity_ids: set[str] | None = None,
) -> EntityCandidate | None:
    if external_key:
        external_matches = [
            item for item in candidates if item.external_key == external_key
        ]
        return external_matches[0] if len(external_matches) == 1 else None
    alias_matches = [
        item for item in candidates if item.id in (human_alias_entity_ids or set())
    ]
    if alias_matches:
        return alias_matches[0] if len(alias_matches) == 1 else None
    normalized_name = normalize_graph_name(canonical_name)
    name_matches = [
        item for item in candidates if item.normalized_name == normalized_name
    ]
    return name_matches[0] if len(name_matches) == 1 else None


def initial_claim_status(
    *,
    source_kind: str,
    relation_review_required: bool,
    subject_resolved: bool,
    object_resolved: bool,
    evidence_verified: bool,
) -> tuple[str, str | None]:
    if not evidence_verified:
        return GRAPH_CLAIM_REJECTED, "schema_violation"
    if relation_review_required:
        return GRAPH_CLAIM_CANDIDATE, "implicit_relation"
    if not subject_resolved or not object_resolved:
        return GRAPH_CLAIM_CANDIDATE, "ambiguous_entity"
    if source_kind in {
        "structured_import",
        "human",
        "document_reference",
        "explicit_text",
    }:
        return GRAPH_CLAIM_ACTIVE, None
    return GRAPH_CLAIM_CANDIDATE, "implicit_relation"

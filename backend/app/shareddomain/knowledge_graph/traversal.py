from dataclasses import dataclass, field
from typing import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import KnowledgeBase
from app.entities.knowledge_graph import (
    KnowledgeGraphClaim,
    KnowledgeGraphEntity,
    KnowledgeGraphRevision,
)
from app.infrastructure.repositories import knowledge_graph as graph_repository

MAX_GRAPH_NODES = 200
MAX_GRAPH_CLAIMS = 400
MAX_EVIDENCE_PER_CLAIM = 5


@dataclass(frozen=True)
class GraphEvidenceView:
    id: str
    document_id: str
    document_filename: str
    chunk_id: str
    quote: str
    start_offset: int
    end_offset: int
    source_kind: str


@dataclass(frozen=True)
class GraphNodeView:
    id: str
    entity_type: str
    canonical_name: str
    properties: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphPathStep:
    claim_id: str
    predicate: str
    source_entity_id: str
    target_entity_id: str
    semantic_direction: str
    quality_score: float
    support_count: int
    evidence: tuple[GraphEvidenceView, ...]


@dataclass(frozen=True)
class GraphPath:
    nodes: tuple[GraphNodeView, ...]
    steps: tuple[GraphPathStep, ...]


@dataclass(frozen=True)
class GraphTraversalResult:
    revision_id: str
    operation: str
    resolved_entities: tuple[GraphNodeView, ...]
    nodes: tuple[GraphNodeView, ...]
    claims: tuple[GraphPathStep, ...]
    paths: tuple[GraphPath, ...]
    evidence: tuple[GraphEvidenceView, ...]
    visited_nodes: int
    truncated: bool
    limit_reason: str | None = None


def _node_view(entity: KnowledgeGraphEntity) -> GraphNodeView:
    return GraphNodeView(
        id=entity.id,
        entity_type=entity.entity_type,
        canonical_name=entity.canonical_name,
        properties=dict(entity.properties_json or {}),
    )


def assemble_path(
    entity_path: list[str],
    claim_path: list[str],
    entities: Mapping[str, KnowledgeGraphEntity],
    claims: Mapping[str, KnowledgeGraphClaim],
    evidence_by_claim: Mapping[str, tuple[GraphEvidenceView, ...]],
) -> GraphPath | None:
    if len(entity_path) != len(claim_path) + 1:
        return None
    path_entities = [entities.get(entity_id) for entity_id in entity_path]
    if any(entity is None for entity in path_entities):
        return None
    steps: list[GraphPathStep] = []
    for index, claim_id in enumerate(claim_path):
        claim = claims.get(claim_id)
        traversed_from = entity_path[index]
        traversed_to = entity_path[index + 1]
        if claim is None or {
            claim.subject_entity_id,
            claim.object_entity_id,
        } != {traversed_from, traversed_to}:
            return None
        steps.append(
            GraphPathStep(
                claim_id=claim.id,
                predicate=claim.predicate,
                source_entity_id=claim.subject_entity_id,
                target_entity_id=claim.object_entity_id or "",
                semantic_direction=(
                    "forward"
                    if claim.subject_entity_id == traversed_from
                    else "reverse"
                ),
                quality_score=claim.quality_score,
                support_count=claim.support_count,
                evidence=evidence_by_claim.get(claim.id, ()),
            )
        )
    return GraphPath(
        nodes=tuple(_node_view(entity) for entity in path_entities if entity),
        steps=tuple(steps),
    )


async def _load_path_records(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    rows: list[tuple[list[str], list[str]]],
) -> tuple[
    dict[str, KnowledgeGraphEntity],
    dict[str, KnowledgeGraphClaim],
    dict[str, tuple[GraphEvidenceView, ...]],
]:
    entity_ids = {entity_id for entity_path, _ in rows for entity_id in entity_path}
    claim_ids = {claim_id for _, claim_path in rows for claim_id in claim_path}
    entities = {
        item.id: item
        for item in await graph_repository.list_active_entities_by_ids(
            db,
            knowledge_base,
            entity_ids,
        )
    }
    claims = {
        item.id: item
        for item in await graph_repository.list_active_claims_by_ids(
            db,
            knowledge_base,
            claim_ids,
        )
    }
    evidence: dict[str, list[GraphEvidenceView]] = {}
    for item, filename, source_kind, _quality, _updated_at in (
        await graph_repository.list_ranked_evidence_for_claim_ids(
            db,
            knowledge_base,
            claim_ids,
        )
    ):
        values = evidence.setdefault(item.claim_id, [])
        if len(values) >= MAX_EVIDENCE_PER_CLAIM:
            continue
        values.append(
            GraphEvidenceView(
                id=item.id,
                document_id=item.document_id,
                document_filename=filename,
                chunk_id=item.chunk_id,
                quote=item.quote,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                source_kind=source_kind,
            )
        )
    return entities, claims, {
        claim_id: tuple(values) for claim_id, values in evidence.items()
    }


def _collect_result_items(
    paths: list[GraphPath],
) -> tuple[
    tuple[GraphNodeView, ...],
    tuple[GraphPathStep, ...],
    tuple[GraphEvidenceView, ...],
]:
    nodes: dict[str, GraphNodeView] = {}
    claims: dict[str, GraphPathStep] = {}
    evidence: dict[str, GraphEvidenceView] = {}
    for path in paths:
        for node in path.nodes:
            nodes.setdefault(node.id, node)
        for step in path.steps:
            claims.setdefault(step.claim_id, step)
            for item in step.evidence:
                evidence.setdefault(item.id, item)
    return tuple(nodes.values()), tuple(claims.values()), tuple(evidence.values())


async def shortest_path(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    source_entity_id: str,
    target_entity_id: str,
    *,
    max_hops: int = 6,
    relation_filters: list[str] | None = None,
) -> GraphTraversalResult:
    if not 1 <= max_hops <= 8:
        raise ValueError("Graph path max_hops must be between 1 and 8.")
    endpoint_entities = {
        item.id: item
        for item in await graph_repository.list_active_entities_by_ids(
            db,
            knowledge_base,
            {source_entity_id, target_entity_id},
        )
    }
    resolved = tuple(
        _node_view(endpoint_entities[entity_id])
        for entity_id in dict.fromkeys((source_entity_id, target_entity_id))
        if entity_id in endpoint_entities
    )
    if (
        source_entity_id not in endpoint_entities
        or target_entity_id not in endpoint_entities
    ):
        return GraphTraversalResult(
            revision.id,
            "path",
            resolved,
            (),
            (),
            (),
            (),
            0,
            False,
        )
    rows, visited_nodes, timed_out = await graph_repository.query_shortest_path_rows(
        db,
        knowledge_base,
        source_entity_id,
        target_entity_id,
        max_hops,
        relation_filters,
    )
    if timed_out:
        return GraphTraversalResult(
            revision.id,
            "path",
            resolved,
            (),
            (),
            (),
            (),
            visited_nodes,
            True,
            "timeout",
        )
    entities, claims, evidence = await _load_path_records(db, knowledge_base, rows)
    paths = [
        path
        for entity_ids, claim_ids in rows
        if (
            path := assemble_path(
                entity_ids,
                claim_ids,
                entities,
                claims,
                evidence,
            )
        )
        is not None
    ]
    nodes, result_claims, result_evidence = _collect_result_items(paths)
    return GraphTraversalResult(
        revision.id,
        "path",
        resolved,
        nodes,
        result_claims,
        tuple(paths),
        result_evidence,
        visited_nodes,
        False,
    )


async def neighborhood(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    source_entity_id: str,
    *,
    max_hops: int = 2,
    relation_filters: list[str] | None = None,
) -> GraphTraversalResult:
    if not 1 <= max_hops <= 3:
        raise ValueError("Graph neighborhood max_hops must be between 1 and 3.")
    source_entities = await graph_repository.list_active_entities_by_ids(
        db,
        knowledge_base,
        {source_entity_id},
    )
    if not source_entities:
        return GraphTraversalResult(
            revision.id,
            "neighborhood",
            (),
            (),
            (),
            (),
            (),
            0,
            False,
        )
    resolved = (_node_view(source_entities[0]),)
    rows, visited_nodes, timed_out = await graph_repository.query_neighborhood_rows(
        db,
        knowledge_base,
        source_entity_id,
        max_hops,
        relation_filters,
    )
    if timed_out:
        return GraphTraversalResult(
            revision.id,
            "neighborhood",
            resolved,
            (),
            (),
            (),
            (),
            visited_nodes,
            True,
            "timeout",
        )

    selected: list[tuple[list[str], list[str]]] = []
    selected_nodes = {source_entity_id}
    selected_claims: set[str] = set()
    truncated = visited_nodes > MAX_GRAPH_NODES or len(rows) > MAX_GRAPH_NODES
    for entity_path, claim_path in rows:
        next_nodes = selected_nodes | set(entity_path)
        next_claims = selected_claims | set(claim_path)
        if len(next_nodes) > MAX_GRAPH_NODES or len(next_claims) > MAX_GRAPH_CLAIMS:
            truncated = True
            break
        selected.append((entity_path, claim_path))
        selected_nodes = next_nodes
        selected_claims = next_claims

    entities, claims, evidence = await _load_path_records(
        db,
        knowledge_base,
        selected,
    )
    paths = [
        path
        for entity_ids, claim_ids in selected
        if (
            path := assemble_path(
                entity_ids,
                claim_ids,
                entities,
                claims,
                evidence,
            )
        )
        is not None
    ]
    nodes, result_claims, result_evidence = _collect_result_items(paths)
    return GraphTraversalResult(
        revision.id,
        "neighborhood",
        resolved,
        nodes,
        result_claims,
        tuple(paths),
        result_evidence,
        visited_nodes,
        truncated,
        "size" if truncated else None,
    )

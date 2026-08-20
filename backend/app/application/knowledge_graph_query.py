import asyncio
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.rag.retrieval import reciprocal_rank_fusion
from app.entities.knowledge import KnowledgeBase
from app.entities.knowledge_graph import (
    KnowledgeGraphEntity,
    KnowledgeGraphRevision,
)
from app.infrastructure.config import Settings
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.ports.vector_store import (
    GraphProfileVectorHit,
    VectorHit,
    query_graph_profile_vectors,
)
from app.schemas.knowledge import KnowledgeQueryRequest
from app.schemas.knowledge_graph import (
    GraphQueryPlan,
    KnowledgeGraphClaimResponse,
    KnowledgeGraphEntityResponse,
    KnowledgeGraphEvidenceResponse,
    KnowledgeGraphPathResponse,
    KnowledgeGraphPathStepResponse,
    KnowledgeGraphQueryResultResponse,
)
from app.shareddomain.knowledge.orchestration import resolve_embedding_model
from app.shareddomain.knowledge_graph import traversal as graph_traversal
from app.shareddomain.knowledge_graph.schema import (
    GraphSchemaDefinition,
    normalize_graph_name,
)

EntityLinkStatus = Literal["selected", "ambiguous", "not_found"]
NEIGHBORHOOD_MARKERS = (
    "相关",
    "关联",
    "全部",
    "邻域",
    "related",
    "connected",
    "neighborhood",
)
ENTITY_CANDIDATE_LIMIT = 8


@dataclass(frozen=True)
class EntityLinkResult:
    status: EntityLinkStatus
    selected: KnowledgeGraphEntity | None
    candidates: tuple[KnowledgeGraphEntity, ...]
    entity_candidate_count: int
    profile_candidate_count: int


@dataclass(frozen=True)
class ResolvedGraphQueryPlan:
    plan: GraphQueryPlan
    operation: str
    selected_entities: tuple[KnowledgeGraphEntity, ...]
    candidate_entities: tuple[KnowledgeGraphEntity, ...]
    entity_candidate_count: int
    profile_candidate_count: int


@dataclass(frozen=True)
class GraphCandidateResult:
    chunk_ids: tuple[str, ...]
    claim_ids_by_chunk: dict[str, tuple[str, ...]]
    claim_hops: dict[str, int]
    traversal: graph_traversal.GraphTraversalResult | None
    operation: str
    revision_id: str | None
    visited_nodes: int
    truncated: bool
    limit_reason: str | None
    entity_candidate_count: int
    profile_candidate_count: int


def _dedupe_entities(
    entities: list[KnowledgeGraphEntity] | tuple[KnowledgeGraphEntity, ...],
) -> tuple[KnowledgeGraphEntity, ...]:
    return tuple({entity.id: entity for entity in entities}.values())


def _node_view(entity: KnowledgeGraphEntity) -> graph_traversal.GraphNodeView:
    return graph_traversal.GraphNodeView(
        id=entity.id,
        entity_type=entity.entity_type,
        canonical_name=entity.canonical_name,
        properties=dict(entity.properties_json or {}),
    )


async def _profile_candidates(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    query: str,
    settings: Settings,
) -> tuple[list[GraphProfileVectorHit], dict[str, KnowledgeGraphEntity]]:
    profile_model_id = str(
        (revision.stats_json or {}).get("profile_embedding_model_id") or ""
    )
    if not profile_model_id:
        return [], {}
    try:
        embedding_model = await resolve_embedding_model(db, knowledge_base)
        if embedding_model is None or embedding_model.id != profile_model_id:
            return [], {}
        hits = await asyncio.to_thread(
            query_graph_profile_vectors,
            settings,
            knowledge_base.id,
            knowledge_base.workspace_id,
            embedding_model,
            query,
            ENTITY_CANDIDATE_LIMIT,
        )
    except Exception:
        return [], {}
    entities = {
        entity.id: entity
        for entity in await graph_repository.list_active_entities_by_ids(
            db,
            knowledge_base,
            {hit.entity_id for hit in hits},
        )
    }
    valid_hits = [
        hit
        for hit in hits
        if (entity := entities.get(hit.entity_id)) is not None
        and entity.profile_hash == hit.profile_hash
    ]
    return valid_hits, entities


def _name_tokens_match_query(entity: KnowledgeGraphEntity, query: str) -> bool:
    normalized_query = normalize_graph_name(query)
    tokens = normalize_graph_name(entity.canonical_name).split()
    return bool(tokens) and all(token in normalized_query for token in tokens)


async def _link_entity_text(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    text: str,
    settings: Settings,
) -> EntityLinkResult:
    exact = await graph_repository.list_exact_entity_matches(
        db,
        knowledge_base,
        normalize_graph_name(text),
    )
    if len(exact) == 1:
        return EntityLinkResult("selected", exact[0], (exact[0],), 1, 0)
    if len(exact) > 1:
        return EntityLinkResult(
            "ambiguous",
            None,
            tuple(exact),
            len(exact),
            0,
        )

    bm25_ids = await graph_repository.query_entity_candidate_ids(
        db,
        knowledge_base,
        text,
        ENTITY_CANDIDATE_LIMIT,
    )
    profile_hits, profile_entities = await _profile_candidates(
        db,
        knowledge_base,
        revision,
        text,
        settings,
    )
    entity_ids = set(bm25_ids) | {hit.entity_id for hit in profile_hits}
    entities = {
        entity.id: entity
        for entity in await graph_repository.list_active_entities_by_ids(
            db,
            knowledge_base,
            entity_ids,
        )
    }
    entities.update(profile_entities)
    ranked = reciprocal_rank_fusion(
        [
            VectorHit(chunk_id=hit.entity_id, distance=hit.distance)
            for hit in profile_hits
            if hit.entity_id in entities
        ],
        [entity_id for entity_id in bm25_ids if entity_id in entities],
    )
    candidates = tuple(
        entities[hit.chunk_id]
        for hit in ranked
        if hit.chunk_id in entities
    )
    if not candidates:
        return EntityLinkResult("not_found", None, (), 0, 0)
    second_score = ranked[1].rrf_score if len(ranked) > 1 else 0.0
    selected = (
        candidates[0]
        if _name_tokens_match_query(candidates[0], text)
        and (second_score == 0 or ranked[0].rrf_score >= second_score * 1.5)
        else None
    )
    return EntityLinkResult(
        "selected" if selected else "ambiguous",
        selected,
        candidates,
        len(candidates),
        len(profile_hits),
    )


async def _validated_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    relation_filters: list[str],
) -> GraphSchemaDefinition | None:
    schema_entity = await graph_repository.get_schema(
        db,
        knowledge_base,
        revision.schema_id,
    )
    if schema_entity is None:
        return None
    schema = GraphSchemaDefinition.model_validate(schema_entity.schema_json)
    unknown = set(relation_filters) - {
        relation.name for relation in schema.relations
    }
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown graph relation filter.",
        )
    return schema


def _plan(
    intent: str,
    payload: KnowledgeQueryRequest,
    *,
    source_text: str | None = None,
    target_text: str | None = None,
    entity_terms: list[str] | None = None,
) -> GraphQueryPlan:
    return GraphQueryPlan(
        intent=intent,
        source_text=source_text,
        target_text=target_text,
        entity_terms=entity_terms or [],
        relation_filters=payload.relation_filters,
        max_hops=payload.max_hops,
    )


def _link_counts(links: list[EntityLinkResult]) -> tuple[int, int]:
    entity_ids = {
        entity.id
        for link in links
        for entity in link.candidates
    }
    profile_count = sum(link.profile_candidate_count for link in links)
    return len(entity_ids), profile_count


async def build_graph_query_plan(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    payload: KnowledgeQueryRequest,
    settings: Settings,
) -> ResolvedGraphQueryPlan:
    if await _validated_schema(
        db,
        knowledge_base,
        revision,
        payload.relation_filters,
    ) is None:
        return ResolvedGraphQueryPlan(
            _plan("none", payload),
            "unavailable",
            (),
            (),
            0,
            0,
        )

    normalized_query = normalize_graph_name(payload.query)
    needs_mentions = payload.graph_mode == "auto" or (
        payload.graph_mode == "path"
        and (not payload.source_entity or not payload.target_entity)
    ) or (payload.graph_mode == "neighborhood" and not payload.source_entity)
    mentions = (
        await graph_repository.list_query_entity_mentions(
            db,
            knowledge_base,
            normalized_query,
        )
        if needs_mentions
        else []
    )
    mentions.sort(
        key=lambda entity: (
            (
                position
                if (
                    position := normalized_query.find(entity.normalized_name)
                ) >= 0
                else len(normalized_query) + 1
            ),
            -len(entity.normalized_name),
            entity.id,
        )
    )
    duplicate_mentions = len({entity.normalized_name for entity in mentions}) < len(
        mentions
    )

    if payload.graph_mode == "path":
        source_text = payload.source_entity
        target_text = payload.target_entity
        if not source_text or not target_text:
            if len(mentions) == 2 and not duplicate_mentions:
                source_text, target_text = (
                    mentions[0].canonical_name,
                    mentions[1].canonical_name,
                )
            else:
                return ResolvedGraphQueryPlan(
                    _plan(
                        "path",
                        payload,
                        source_text=source_text,
                        target_text=target_text,
                    ),
                    "ambiguous" if mentions else "not_found",
                    (),
                    tuple(mentions),
                    len(mentions),
                    0,
                )
        links = [
            await _link_entity_text(
                db,
                knowledge_base,
                revision,
                source_text,
                settings,
            ),
            await _link_entity_text(
                db,
                knowledge_base,
                revision,
                target_text,
                settings,
            ),
        ]
        count, profile_count = _link_counts(links)
        operation = (
            "path"
            if all(link.status == "selected" for link in links)
            else "ambiguous"
            if any(link.status == "ambiguous" for link in links)
            else "not_found"
        )
        return ResolvedGraphQueryPlan(
            _plan(
                "path",
                payload,
                source_text=source_text,
                target_text=target_text,
                entity_terms=[source_text, target_text],
            ),
            operation,
            tuple(link.selected for link in links if link.selected),
            _dedupe_entities(
                [entity for link in links for entity in link.candidates]
            ),
            count,
            profile_count,
        )

    if payload.graph_mode == "neighborhood":
        source_text = payload.source_entity
        if not source_text:
            if len(mentions) == 1:
                source_text = mentions[0].canonical_name
            else:
                return ResolvedGraphQueryPlan(
                    _plan("neighborhood", payload),
                    "ambiguous" if mentions else "not_found",
                    (),
                    tuple(mentions),
                    len(mentions),
                    0,
                )
        link = await _link_entity_text(
            db,
            knowledge_base,
            revision,
            source_text,
            settings,
        )
        return ResolvedGraphQueryPlan(
            _plan(
                "neighborhood",
                payload,
                source_text=source_text,
                entity_terms=[source_text],
            ),
            "neighborhood" if link.selected else link.status,
            (link.selected,) if link.selected else (),
            link.candidates,
            link.entity_candidate_count,
            link.profile_candidate_count,
        )

    if duplicate_mentions:
        return ResolvedGraphQueryPlan(
            _plan(
                "path",
                payload,
                entity_terms=[entity.canonical_name for entity in mentions],
            ),
            "ambiguous",
            (),
            tuple(mentions),
            len(mentions),
            0,
        )
    if len(mentions) == 2:
        return ResolvedGraphQueryPlan(
            _plan(
                "path",
                payload,
                source_text=mentions[0].canonical_name,
                target_text=mentions[1].canonical_name,
                entity_terms=[entity.canonical_name for entity in mentions],
            ),
            "path",
            tuple(mentions),
            tuple(mentions),
            2,
            0,
        )
    if len(mentions) == 1:
        intent = (
            "neighborhood"
            if any(marker in normalized_query for marker in NEIGHBORHOOD_MARKERS)
            else "profile"
        )
        return ResolvedGraphQueryPlan(
            _plan(
                intent,
                payload,
                source_text=mentions[0].canonical_name,
                entity_terms=[mentions[0].canonical_name],
            ),
            intent,
            (mentions[0],),
            (mentions[0],),
            1,
            0,
        )
    if len(mentions) > 2:
        return ResolvedGraphQueryPlan(
            _plan(
                "synthesis",
                payload,
                entity_terms=[entity.canonical_name for entity in mentions],
            ),
            "synthesis",
            tuple(mentions[:3]),
            tuple(mentions),
            len(mentions),
            0,
        )

    link = await _link_entity_text(
        db,
        knowledge_base,
        revision,
        payload.query,
        settings,
    )
    if link.selected:
        return ResolvedGraphQueryPlan(
            _plan(
                "profile",
                payload,
                source_text=link.selected.canonical_name,
                entity_terms=[link.selected.canonical_name],
            ),
            "profile",
            (link.selected,),
            link.candidates,
            link.entity_candidate_count,
            link.profile_candidate_count,
        )
    if link.candidates:
        return ResolvedGraphQueryPlan(
            _plan(
                "synthesis",
                payload,
                entity_terms=[
                    entity.canonical_name for entity in link.candidates[:3]
                ],
            ),
            "synthesis",
            link.candidates[:3],
            link.candidates,
            link.entity_candidate_count,
            link.profile_candidate_count,
        )
    return ResolvedGraphQueryPlan(
        _plan("none", payload),
        "none",
        (),
        (),
        0,
        0,
    )


def _empty_traversal(
    revision: KnowledgeGraphRevision,
    operation: str,
    selected_entities: tuple[KnowledgeGraphEntity, ...],
    candidate_entities: tuple[KnowledgeGraphEntity, ...],
) -> graph_traversal.GraphTraversalResult:
    return graph_traversal.GraphTraversalResult(
        revision_id=revision.id,
        operation=operation,
        resolved_entities=tuple(_node_view(entity) for entity in selected_entities),
        nodes=tuple(_node_view(entity) for entity in candidate_entities),
        claims=(),
        paths=(),
        evidence=(),
        visited_nodes=0,
        truncated=False,
    )


def _merge_traversals(
    revision: KnowledgeGraphRevision,
    operation: str,
    resolved_entities: tuple[KnowledgeGraphEntity, ...],
    traversals: list[graph_traversal.GraphTraversalResult],
) -> graph_traversal.GraphTraversalResult:
    nodes = {
        node.id: node
        for traversal in traversals
        for node in (*traversal.resolved_entities, *traversal.nodes)
    }
    claims = {
        claim.claim_id: claim
        for traversal in traversals
        for claim in traversal.claims
    }
    evidence = {
        item.id: item
        for traversal in traversals
        for item in traversal.evidence
    }
    paths = {
        (
            tuple(node.id for node in path.nodes),
            tuple(step.claim_id for step in path.steps),
        ): path
        for traversal in traversals
        for path in traversal.paths
    }
    selected_nodes = tuple(nodes.values())[: graph_traversal.MAX_GRAPH_NODES]
    selected_claims = tuple(claims.values())[: graph_traversal.MAX_GRAPH_CLAIMS]
    selected_node_ids = {node.id for node in selected_nodes}
    selected_claim_ids = {claim.claim_id for claim in selected_claims}
    selected_paths = tuple(
        path
        for path in paths.values()
        if all(node.id in selected_node_ids for node in path.nodes)
        and all(step.claim_id in selected_claim_ids for step in path.steps)
    )
    selected_evidence_ids = {
        item.id for claim in selected_claims for item in claim.evidence
    }
    size_limited = (
        len(nodes) > len(selected_nodes)
        or len(claims) > len(selected_claims)
    )
    reasons = [traversal.limit_reason for traversal in traversals]
    limit_reason = (
        "timeout"
        if "timeout" in reasons
        else "size"
        if "size" in reasons
        else None
    )
    return graph_traversal.GraphTraversalResult(
        revision_id=revision.id,
        operation=operation,
        resolved_entities=tuple(_node_view(entity) for entity in resolved_entities),
        nodes=selected_nodes,
        claims=selected_claims,
        paths=selected_paths,
        evidence=tuple(
            item for item in evidence.values() if item.id in selected_evidence_ids
        ),
        visited_nodes=sum(item.visited_nodes for item in traversals),
        truncated=size_limited or any(item.truncated for item in traversals),
        limit_reason="size" if size_limited else limit_reason,
    )


async def execute_graph_query_plan(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
    resolved: ResolvedGraphQueryPlan,
) -> graph_traversal.GraphTraversalResult:
    if resolved.operation == "path" and len(resolved.selected_entities) == 2:
        return await graph_traversal.shortest_path(
            db,
            knowledge_base,
            revision,
            resolved.selected_entities[0].id,
            resolved.selected_entities[1].id,
            max_hops=resolved.plan.max_hops,
            relation_filters=resolved.plan.relation_filters,
        )
    if resolved.operation == "neighborhood" and resolved.selected_entities:
        return await graph_traversal.neighborhood(
            db,
            knowledge_base,
            revision,
            resolved.selected_entities[0].id,
            max_hops=min(resolved.plan.max_hops, 3),
            relation_filters=resolved.plan.relation_filters,
        )
    if resolved.operation in {"profile", "fact", "synthesis"}:
        traversals = [
            await graph_traversal.neighborhood(
                db,
                knowledge_base,
                revision,
                entity.id,
                max_hops=1,
                relation_filters=resolved.plan.relation_filters,
            )
            for entity in resolved.selected_entities[:3]
        ]
        return _merge_traversals(
            revision,
            resolved.operation,
            resolved.selected_entities if resolved.operation != "synthesis" else (),
            traversals,
        )
    return _empty_traversal(
        revision,
        resolved.operation,
        resolved.selected_entities,
        resolved.candidate_entities,
    )


def _candidate_evidence(
    traversal: graph_traversal.GraphTraversalResult,
    limit: int,
) -> tuple[
    tuple[str, ...],
    dict[str, tuple[str, ...]],
    dict[str, int],
]:
    claim_hops: dict[str, int] = {}
    for path in traversal.paths:
        for hop, step in enumerate(path.steps, start=1):
            claim_hops[step.claim_id] = min(
                hop,
                claim_hops.get(step.claim_id, hop),
            )
    claims_by_chunk: dict[str, list[str]] = {}
    for step in traversal.claims:
        claim_hops.setdefault(step.claim_id, 1)
        for evidence in step.evidence:
            if evidence.chunk_id not in claims_by_chunk:
                if len(claims_by_chunk) == limit:
                    continue
                claims_by_chunk[evidence.chunk_id] = []
            if step.claim_id not in claims_by_chunk[evidence.chunk_id]:
                claims_by_chunk[evidence.chunk_id].append(step.claim_id)
    return (
        tuple(claims_by_chunk),
        {
            chunk_id: tuple(claim_ids)
            for chunk_id, claim_ids in claims_by_chunk.items()
        },
        claim_hops,
    )


async def retrieve_graph_candidates(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeQueryRequest,
    settings: Settings,
    limit: int,
) -> GraphCandidateResult:
    if (
        not getattr(knowledge_base, "graph_enabled", False)
        or payload.graph_mode == "off"
    ):
        return GraphCandidateResult(
            (), {}, {}, None, "off", None, 0, False, None, 0, 0
        )
    revision = await graph_repository.get_active_revision(db, knowledge_base)
    if revision is None:
        return GraphCandidateResult(
            (), {}, {}, None, "unavailable", None, 0, False, None, 0, 0
        )
    resolved = await build_graph_query_plan(
        db,
        knowledge_base,
        revision,
        payload,
        settings,
    )
    traversal = await execute_graph_query_plan(
        db,
        knowledge_base,
        revision,
        resolved,
    )
    chunk_ids, claim_ids_by_chunk, claim_hops = _candidate_evidence(
        traversal,
        limit,
    )
    return GraphCandidateResult(
        chunk_ids=chunk_ids,
        claim_ids_by_chunk=claim_ids_by_chunk,
        claim_hops=claim_hops,
        traversal=traversal,
        operation=traversal.operation,
        revision_id=revision.id,
        visited_nodes=traversal.visited_nodes,
        truncated=traversal.truncated,
        limit_reason=traversal.limit_reason,
        entity_candidate_count=resolved.entity_candidate_count,
        profile_candidate_count=resolved.profile_candidate_count,
    )


def graph_query_result_response(
    traversal: graph_traversal.GraphTraversalResult | None,
) -> KnowledgeGraphQueryResultResponse | None:
    if traversal is None:
        return None
    evidence_claims: dict[str, str] = {}
    for claim in traversal.claims:
        for evidence in claim.evidence:
            evidence_claims.setdefault(evidence.id, claim.claim_id)

    def entity_response(
        entity: graph_traversal.GraphNodeView,
    ) -> KnowledgeGraphEntityResponse:
        return KnowledgeGraphEntityResponse(
            id=entity.id,
            entity_type=entity.entity_type,
            canonical_name=entity.canonical_name,
            properties=entity.properties,
        )

    def step_response(
        step: graph_traversal.GraphPathStep,
    ) -> KnowledgeGraphPathStepResponse:
        return KnowledgeGraphPathStepResponse(
            claim_id=step.claim_id,
            predicate=step.predicate,
            source_entity_id=step.source_entity_id,
            target_entity_id=step.target_entity_id,
            semantic_direction=step.semantic_direction,
            quality_score=step.quality_score,
            support_count=step.support_count,
            evidence_ids=[item.id for item in step.evidence],
        )

    return KnowledgeGraphQueryResultResponse(
        revision_id=traversal.revision_id,
        operation=traversal.operation,
        resolved_entities=[
            entity_response(entity) for entity in traversal.resolved_entities
        ],
        nodes=[entity_response(entity) for entity in traversal.nodes],
        claims=[
            KnowledgeGraphClaimResponse(
                id=claim.claim_id,
                subject_entity_id=claim.source_entity_id,
                predicate=claim.predicate,
                object_entity_id=claim.target_entity_id or None,
                object_value=None,
                quality_score=claim.quality_score,
                support_count=claim.support_count,
                evidence_ids=[item.id for item in claim.evidence],
            )
            for claim in traversal.claims
        ],
        paths=[
            KnowledgeGraphPathResponse(
                nodes=[entity_response(entity) for entity in path.nodes],
                steps=[step_response(step) for step in path.steps],
            )
            for path in traversal.paths
        ],
        evidence=[
            KnowledgeGraphEvidenceResponse(
                id=evidence.id,
                claim_id=evidence_claims.get(evidence.id, ""),
                document_id=evidence.document_id,
                document_filename=evidence.document_filename,
                chunk_id=evidence.chunk_id,
                quote=evidence.quote,
                start_offset=evidence.start_offset,
                end_offset=evidence.end_offset,
                source_kind=evidence.source_kind,
            )
            for evidence in traversal.evidence
            if evidence.id in evidence_claims
        ],
        visited_nodes=traversal.visited_nodes,
        truncated=traversal.truncated,
        limit_reason=traversal.limit_reason,
    )

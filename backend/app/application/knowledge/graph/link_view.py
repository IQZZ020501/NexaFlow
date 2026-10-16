import hashlib
import json
from collections import defaultdict
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentReference,
)
from app.entities.knowledge.graph import (
    KnowledgeGraphClaim,
    KnowledgeGraphClaimEvidence,
    KnowledgeGraphEntity,
)
from app.infra.db.repositories.knowledge import graph as graph_repository
from app.infra.db.repositories.knowledge import references as reference_repository
from app.infra.db.repositories.knowledge import repository as knowledge_repository
from app.schemas.knowledge.graph import (
    KnowledgeLinkGraphEdgeResponse,
    KnowledgeLinkGraphNodeResponse,
    KnowledgeLinkGraphResponse,
)

MAX_LINK_GRAPH_NODES = 2_000
MAX_LINK_GRAPH_EDGES = 10_000


def _document_label(filename: str) -> str:
    return PurePosixPath(filename).stem or filename


def _unresolved_node_id(target_label: str) -> str:
    fingerprint = hashlib.sha256(target_label.casefold().encode("utf-8")).hexdigest()
    return f"unresolved:{fingerprint[:24]}"


def _edge_id(source: str, target: str) -> str:
    fingerprint = hashlib.sha256(f"{source}\0{target}".encode("utf-8")).hexdigest()
    return f"link:{fingerprint[:24]}"


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return list(
            dict.fromkeys(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
        )
    if isinstance(value, str) and value:
        return [value]
    return []


def _positive_int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def build_evidence_link_graph(
    documents: list[KnowledgeDocument],
    entities: list[KnowledgeGraphEntity],
    claims: list[KnowledgeGraphClaim],
    evidence: list[KnowledgeGraphClaimEvidence],
    revision_id: str,
) -> KnowledgeLinkGraphResponse:
    """Project the published Evidence Graph into the link-graph contract."""
    documents_by_id = {
        document.id: document for document in documents if document.is_active
    }
    entities_by_id = {entity.id: entity for entity in entities}
    evidence_by_claim: defaultdict[str, list[str]] = defaultdict(list)
    for item in evidence:
        evidence_by_claim[item.claim_id].append(item.id)

    incoming: defaultdict[str, int] = defaultdict(int)
    outgoing: defaultdict[str, int] = defaultdict(int)
    edges: list[KnowledgeLinkGraphEdgeResponse] = []
    for claim in claims:
        target_id = claim.object_entity_id
        target = entities_by_id.get(target_id or "")
        if target is None or claim.subject_entity_id not in entities_by_id:
            continue
        properties = claim.properties_json or {}
        count = _positive_int(
            properties.get("occurrence_count"),
            max(1, claim.support_count),
        )
        outgoing[claim.subject_entity_id] += count
        incoming[target.id] += count
        target_sections = _string_list(properties.get("target_sections"))
        if not target_sections:
            target_sections = _string_list(properties.get("target_section"))
        edges.append(
            KnowledgeLinkGraphEdgeResponse(
                id=claim.id,
                source=claim.subject_entity_id,
                target=target.id,
                target_label=target.canonical_name,
                target_sections=target_sections,
                resolved=True,
                count=count,
                predicate=claim.predicate,
                source_kind=claim.source_kind,
                quality_score=claim.quality_score,
                support_count=claim.support_count,
                evidence_ids=sorted(evidence_by_claim[claim.id]),
            )
        )

    nodes: list[KnowledgeLinkGraphNodeResponse] = []
    document_count = 0
    for entity in entities:
        properties = entity.properties_json or {}
        document_id_value = properties.get("document_id")
        document_id = (
            str(document_id_value) if document_id_value is not None else None
        )
        document = documents_by_id.get(document_id or "")
        is_document = entity.entity_type == "Document" and document_id is not None
        if is_document:
            document_count += 1
        filename = document.filename if document is not None else entity.canonical_name
        nodes.append(
            KnowledgeLinkGraphNodeResponse(
                id=entity.id,
                kind="document" if is_document else "entity",
                document_id=document_id if is_document else None,
                label=_document_label(filename) if is_document else entity.canonical_name,
                filename=filename,
                content_type=document.content_type if document is not None else None,
                status=document.status if document is not None else entity.state,
                entity_type=entity.entity_type,
                properties=properties,
                incoming=incoming[entity.id],
                outgoing=outgoing[entity.id],
                degree=incoming[entity.id] + outgoing[entity.id],
            )
        )

    nodes.sort(key=lambda node: (-node.degree, node.filename.casefold(), node.id))
    edges.sort(key=lambda edge: (-edge.count, edge.source, edge.target, edge.id))
    selected_nodes = nodes[:MAX_LINK_GRAPH_NODES]
    selected_ids = {node.id for node in selected_nodes}
    selected_edges = [
        edge
        for edge in edges
        if edge.source in selected_ids and edge.target in selected_ids
    ][:MAX_LINK_GRAPH_EDGES]
    truncated = len(selected_nodes) < len(nodes) or len(selected_edges) < len(edges)
    revision_payload = json.dumps(
        {
            "graph_revision_id": revision_id,
            "nodes": [node.model_dump() for node in selected_nodes],
            "edges": [edge.model_dump() for edge in selected_edges],
            "truncated": truncated,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return KnowledgeLinkGraphResponse(
        revision=hashlib.sha256(revision_payload.encode("utf-8")).hexdigest(),
        nodes=selected_nodes,
        edges=selected_edges,
        document_count=document_count,
        entity_count=len(nodes),
        unresolved_count=0,
        edge_count=len(edges),
        graph_revision_id=revision_id,
        source="evidence_graph",
        truncated=truncated,
    )


def build_document_link_graph(
    documents: list[KnowledgeDocument],
    references: list[KnowledgeDocumentReference],
) -> KnowledgeLinkGraphResponse:
    active_documents = {document.id: document for document in documents if document.is_active}
    grouped_edges: dict[tuple[str, str], dict[str, object]] = {}

    for reference in references:
        if reference.source_document_id not in active_documents:
            continue
        resolved = reference.target_document_id in active_documents
        target = (
            reference.target_document_id
            if resolved
            else _unresolved_node_id(reference.target_label)
        )
        key = (reference.source_document_id, target)
        aggregate = grouped_edges.setdefault(
            key,
            {
                "target_label": reference.target_label,
                "resolved": resolved,
                "count": 0,
                "sections": set(),
            },
        )
        aggregate["count"] = int(aggregate["count"]) + reference.occurrence_count
        if reference.target_section:
            sections = aggregate["sections"]
            if isinstance(sections, set):
                sections.add(reference.target_section)

    incoming: defaultdict[str, int] = defaultdict(int)
    outgoing: defaultdict[str, int] = defaultdict(int)
    edges: list[KnowledgeLinkGraphEdgeResponse] = []
    for (source, target), aggregate in grouped_edges.items():
        count = int(aggregate["count"])
        outgoing[source] += count
        incoming[target] += count
        sections = aggregate["sections"]
        edges.append(
            KnowledgeLinkGraphEdgeResponse(
                id=_edge_id(source, target),
                source=source,
                target=target,
                target_label=str(aggregate["target_label"]),
                target_sections=sorted(sections) if isinstance(sections, set) else [],
                resolved=bool(aggregate["resolved"]),
                count=count,
            )
        )

    document_nodes = [
        KnowledgeLinkGraphNodeResponse(
            id=document.id,
            kind="document",
            document_id=document.id,
            label=_document_label(document.filename),
            filename=document.filename,
            content_type=document.content_type,
            status=document.status,
            incoming=incoming[document.id],
            outgoing=outgoing[document.id],
            degree=incoming[document.id] + outgoing[document.id],
        )
        for document in active_documents.values()
    ]
    unresolved_labels = {
        edge.target: edge.target_label for edge in edges if not edge.resolved
    }
    unresolved_nodes = [
        KnowledgeLinkGraphNodeResponse(
            id=node_id,
            kind="unresolved",
            label=_document_label(filename),
            filename=filename,
            incoming=incoming[node_id],
            outgoing=0,
            degree=incoming[node_id],
        )
        for node_id, filename in unresolved_labels.items()
    ]
    nodes = sorted(
        [*document_nodes, *unresolved_nodes],
        key=lambda node: (-node.degree, node.filename.casefold(), node.id),
    )
    sorted_edges = sorted(
        edges,
        key=lambda edge: (-edge.count, edge.source, edge.target),
    )
    selected_nodes = nodes[:MAX_LINK_GRAPH_NODES]
    selected_ids = {node.id for node in selected_nodes}
    selected_edges = [
        edge
        for edge in sorted_edges
        if edge.source in selected_ids and edge.target in selected_ids
    ][:MAX_LINK_GRAPH_EDGES]
    truncated = len(selected_nodes) < len(nodes) or len(selected_edges) < len(edges)
    revision_payload = json.dumps(
        {
            "nodes": [node.model_dump() for node in selected_nodes],
            "edges": [edge.model_dump() for edge in selected_edges],
            "document_count": len(document_nodes),
            "unresolved_count": len(unresolved_nodes),
            "edge_count": len(edges),
            "truncated": truncated,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return KnowledgeLinkGraphResponse(
        revision=hashlib.sha256(revision_payload.encode("utf-8")).hexdigest(),
        nodes=selected_nodes,
        edges=selected_edges,
        document_count=len(document_nodes),
        entity_count=len(document_nodes),
        unresolved_count=len(unresolved_nodes),
        edge_count=len(edges),
        source="legacy_references",
        truncated=truncated,
    )


async def get_document_link_graph(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeLinkGraphResponse:
    documents = await knowledge_repository.list_knowledge_documents(
        db,
        knowledge_base,
    )
    active_revision = await graph_repository.get_active_revision(db, knowledge_base)
    if active_revision is not None:
        entities = await graph_repository.list_active_entities(db, knowledge_base)
        claims = await graph_repository.list_active_claims(db, knowledge_base)
        evidence = await graph_repository.list_current_evidence_for_claim_ids(
            db,
            knowledge_base,
            {claim.id for claim in claims},
        )
        return build_evidence_link_graph(
            documents,
            entities,
            claims,
            evidence,
            active_revision.id,
        )
    references = await reference_repository.list_markdown_references(
        db,
        knowledge_base,
    )
    return build_document_link_graph(documents, references)

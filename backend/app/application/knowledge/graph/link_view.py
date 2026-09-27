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
        unresolved_count=len(unresolved_nodes),
        edge_count=len(edges),
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
    references = await reference_repository.list_markdown_references(
        db,
        knowledge_base,
    )
    return build_document_link_graph(documents, references)

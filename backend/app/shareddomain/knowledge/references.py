import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeDocumentReference,
)
from app.infrastructure.model_utils import new_id
from app.infrastructure.repositories import knowledge_reference as reference_repository

MAX_REFERENCES_PER_DOCUMENT = 100
MARKDOWN_REFERENCE_PATTERN = re.compile(
    r"(?<!!)\[[^\]\n]+\]\((?P<target>[^)\n]+)\)"
)
TEXT_REFERENCE_PATTERN = re.compile(
    r"(?:详见|参考|参见)\s*(?:"
    r"[《\"“](?P<quoted_label>[^》\"”\n，。；;]{1,120})[》\"”]"
    r"|(?P<plain_label>[^，。；;\n]{1,120}?))"
    r"(?:\s*(?P<section>第[^，。；;\n]{1,40}|[^，。；;\n]{1,40}章))?"
    r"(?=[，。；;\n]|$)"
)


@dataclass(frozen=True)
class ReferenceLabel:
    target_label: str
    target_section: str = ""
    reference_type: Literal["markdown", "text"] = "text"


def normalize_reference_label(value: str) -> str:
    path = unquote(value).strip().replace("\\", "/")
    return " ".join(PurePosixPath(path).name.split())[:255]


def _normalize_section(value: str | None) -> str:
    return " ".join(unquote(value or "").split())[:500]


def extract_reference_labels(content: str) -> list[ReferenceLabel]:
    candidates: list[tuple[int, ReferenceLabel]] = []
    for match in MARKDOWN_REFERENCE_PATTERN.finditer(content):
        target = match.group("target").strip()
        parsed = urlsplit(target)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or not parsed.path
            or parsed.path.startswith("/")
        ):
            continue
        label = normalize_reference_label(parsed.path)
        if label:
            candidates.append(
                (
                    match.start(),
                    ReferenceLabel(
                        target_label=label,
                        target_section=_normalize_section(parsed.fragment),
                        reference_type="markdown",
                    ),
                )
            )

    for match in TEXT_REFERENCE_PATTERN.finditer(content):
        raw_label = match.group("quoted_label") or match.group("plain_label") or ""
        if raw_label.lstrip().startswith("[") or "](" in raw_label:
            continue
        label = normalize_reference_label(raw_label)
        if label:
            candidates.append(
                (
                    match.start(),
                    ReferenceLabel(
                        target_label=label,
                        target_section=_normalize_section(match.group("section")),
                        reference_type="text",
                    ),
                )
            )

    labels: list[ReferenceLabel] = []
    seen: set[tuple[str, str]] = set()
    for _, label in sorted(candidates, key=lambda item: item[0]):
        key = (label.target_label.casefold(), label.target_section.casefold())
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
        if len(labels) == MAX_REFERENCES_PER_DOCUMENT:
            break
    return labels


def _document_aliases(document: KnowledgeDocument) -> set[str]:
    filename = normalize_reference_label(document.filename)
    stem = normalize_reference_label(PurePosixPath(filename).stem)
    return {alias for alias in (filename, stem) if alias}


def _resolution_context(
    documents: list[KnowledgeDocument],
    parents: list[KnowledgeDocumentParentChunk],
) -> tuple[
    dict[str, list[KnowledgeDocument]],
    dict[str, list[KnowledgeDocumentParentChunk]],
]:
    documents_by_alias: dict[str, list[KnowledgeDocument]] = {}
    for document in documents:
        for alias in _document_aliases(document):
            documents_by_alias.setdefault(alias.casefold(), []).append(document)
    parents_by_document: dict[str, list[KnowledgeDocumentParentChunk]] = {}
    for parent in parents:
        parents_by_document.setdefault(parent.document_id, []).append(parent)
    return documents_by_alias, parents_by_document


def _resolved_target(
    target_label: str,
    target_section: str,
    documents_by_alias: dict[str, list[KnowledgeDocument]],
    parents_by_document: dict[str, list[KnowledgeDocumentParentChunk]],
) -> tuple[str | None, str | None]:
    candidates = documents_by_alias.get(target_label.casefold(), [])
    if len(candidates) != 1:
        return None, None
    document = candidates[0]
    if not target_section:
        return document.id, None
    parent = next(
        (
            item
            for item in parents_by_document.get(document.id, [])
            if item.title == target_section
        ),
        None,
    )
    return document.id, parent.id if parent else None


async def prepare_document_reference_rebuild(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> None:
    await reference_repository.clear_target_parent_references(
        db,
        knowledge_base,
        document_id,
    )
    await reference_repository.delete_source_references(
        db,
        knowledge_base,
        document_id,
    )


async def resolve_references_matching_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
) -> None:
    references = await reference_repository.list_references_matching_aliases(
        db,
        knowledge_base,
        _document_aliases(document),
    )
    if not references:
        return
    documents = await reference_repository.list_active_documents(db, knowledge_base)
    parents = await reference_repository.list_parent_chunks_for_documents(
        db,
        knowledge_base,
        {item.id for item in documents},
    )
    documents_by_alias, parents_by_document = _resolution_context(
        documents,
        parents,
    )
    for reference in references:
        target_document_id, target_parent_id = _resolved_target(
            reference.target_label,
            reference.target_section,
            documents_by_alias,
            parents_by_document,
        )
        if (
            reference.target_document_id == target_document_id
            and reference.target_parent_id == target_parent_id
        ):
            continue
        reference.target_document_id = target_document_id
        reference.target_parent_id = target_parent_id
        await reference_repository.save_reference(db, reference)


async def rebuild_document_references(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    chunks: list[KnowledgeDocumentChunk],
) -> None:
    await reference_repository.delete_source_references(
        db,
        knowledge_base,
        document.id,
    )
    documents = await reference_repository.list_active_documents(db, knowledge_base)
    parents = await reference_repository.list_parent_chunks_for_documents(
        db,
        knowledge_base,
        {item.id for item in documents},
    )
    documents_by_alias, parents_by_document = _resolution_context(
        documents,
        parents,
    )
    references: list[KnowledgeDocumentReference] = []
    for chunk in sorted(chunks, key=lambda item: item.chunk_index):
        for label in extract_reference_labels(chunk.content):
            target_document_id, target_parent_id = _resolved_target(
                label.target_label,
                label.target_section,
                documents_by_alias,
                parents_by_document,
            )
            references.append(
                KnowledgeDocumentReference(
                    id=new_id(),
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    source_document_id=document.id,
                    source_chunk_id=chunk.id,
                    target_document_id=target_document_id,
                    target_parent_id=target_parent_id,
                    target_label=label.target_label,
                    target_section=label.target_section,
                    reference_type=label.reference_type,
                    source_ordinal=len(references),
                )
            )
            if len(references) == MAX_REFERENCES_PER_DOCUMENT:
                break
        if len(references) == MAX_REFERENCES_PER_DOCUMENT:
            break
    await reference_repository.add_references(db, references)
    await resolve_references_matching_document(db, knowledge_base, document)


async def detach_document_references(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> None:
    await reference_repository.clear_target_document_references(
        db,
        knowledge_base,
        document_id,
    )
    await reference_repository.delete_source_references(
        db,
        knowledge_base,
        document_id,
    )

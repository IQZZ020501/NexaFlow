from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    DOCUMENT_DELETED_STATUS,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentParentChunk,
    KnowledgeDocumentReference,
)
from app.infrastructure.repositories.mapping import save, to_entity, to_orm
from app.shareddomain.knowledge.models import (
    KnowledgeDocument as KnowledgeDocumentORM,
    KnowledgeDocumentParentChunk as KnowledgeDocumentParentChunkORM,
    KnowledgeDocumentReference as KnowledgeDocumentReferenceORM,
)


async def delete_source_references(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    source_document_id: str,
) -> None:
    await db.execute(
        delete(KnowledgeDocumentReferenceORM).where(
            KnowledgeDocumentReferenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentReferenceORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeDocumentReferenceORM.source_document_id
            == source_document_id,
        )
    )


async def clear_target_parent_references(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_document_id: str,
) -> None:
    await db.execute(
        update(KnowledgeDocumentReferenceORM)
        .where(
            KnowledgeDocumentReferenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentReferenceORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeDocumentReferenceORM.target_document_id
            == target_document_id,
        )
        .values(target_parent_id=None)
    )


async def clear_target_document_references(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_document_id: str,
) -> None:
    await db.execute(
        update(KnowledgeDocumentReferenceORM)
        .where(
            KnowledgeDocumentReferenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentReferenceORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeDocumentReferenceORM.target_document_id
            == target_document_id,
        )
        .values(target_document_id=None, target_parent_id=None)
    )


async def add_references(
    db: AsyncSession,
    references: list[KnowledgeDocumentReference],
) -> None:
    for reference in references:
        db.add(to_orm(KnowledgeDocumentReferenceORM, reference))
    if references:
        await db.flush()


async def save_reference(
    db: AsyncSession,
    reference: KnowledgeDocumentReference,
) -> None:
    await save(db, KnowledgeDocumentReferenceORM, reference)


async def list_active_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> list[KnowledgeDocument]:
    rows = await db.scalars(
        select(KnowledgeDocumentORM).where(
            KnowledgeDocumentORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentORM.status != DOCUMENT_DELETED_STATUS,
            KnowledgeDocumentORM.is_active.is_(True),
        )
    )
    return [to_entity(KnowledgeDocument, row) for row in rows]


async def list_parent_chunks_for_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str],
) -> list[KnowledgeDocumentParentChunk]:
    if not document_ids:
        return []
    rows = await db.scalars(
        select(KnowledgeDocumentParentChunkORM)
        .where(
            KnowledgeDocumentParentChunkORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentParentChunkORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeDocumentParentChunkORM.document_id.in_(document_ids),
        )
        .order_by(
            KnowledgeDocumentParentChunkORM.document_id,
            KnowledgeDocumentParentChunkORM.parent_index,
        )
    )
    return [to_entity(KnowledgeDocumentParentChunk, row) for row in rows]


async def list_references_matching_aliases(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    aliases: set[str],
) -> list[KnowledgeDocumentReference]:
    if not aliases:
        return []
    rows = await db.scalars(
        select(KnowledgeDocumentReferenceORM).where(
            KnowledgeDocumentReferenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentReferenceORM.knowledge_base_id
            == knowledge_base.id,
            func.lower(KnowledgeDocumentReferenceORM.target_label).in_(
                sorted(alias.casefold() for alias in aliases)
            ),
        )
    )
    return [to_entity(KnowledgeDocumentReference, row) for row in rows]


async def list_resolved_references_for_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    source_chunk_ids: list[str],
    limit: int = 100,
) -> list[KnowledgeDocumentReference]:
    if not source_chunk_ids or limit <= 0:
        return []
    rows = await db.scalars(
        select(KnowledgeDocumentReferenceORM).where(
            KnowledgeDocumentReferenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentReferenceORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeDocumentReferenceORM.source_chunk_id.in_(source_chunk_ids),
            KnowledgeDocumentReferenceORM.target_document_id.is_not(None),
        )
    )
    positions = {chunk_id: index for index, chunk_id in enumerate(source_chunk_ids)}
    references = [to_entity(KnowledgeDocumentReference, row) for row in rows]
    return sorted(
        references,
        key=lambda item: (
            positions.get(item.source_chunk_id, len(positions)),
            item.source_ordinal,
            item.id,
        ),
    )[:limit]


async def list_resolved_references(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> list[KnowledgeDocumentReference]:
    rows = await db.scalars(
        select(KnowledgeDocumentReferenceORM)
        .where(
            KnowledgeDocumentReferenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentReferenceORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeDocumentReferenceORM.target_document_id.is_not(None),
        )
        .order_by(
            KnowledgeDocumentReferenceORM.source_document_id,
            KnowledgeDocumentReferenceORM.source_ordinal,
            KnowledgeDocumentReferenceORM.id,
        )
    )
    return [to_entity(KnowledgeDocumentReference, row) for row in rows.all()]

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import KnowledgeBase
from app.entities.knowledge_graph import (
    GRAPH_SCHEMA_ACTIVE,
    GRAPH_SCHEMA_RETIRED,
    KnowledgeGraphAlias,
    KnowledgeGraphClaim,
    KnowledgeGraphClaimEvidence,
    KnowledgeGraphEntity,
    KnowledgeGraphMention,
    KnowledgeGraphReviewItem,
    KnowledgeGraphRevision,
    KnowledgeGraphRevisionChange,
    KnowledgeGraphSchema,
)
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories.mapping import save, to_entity
from app.shareddomain.knowledge_graph.models import (
    KnowledgeGraphAlias as KnowledgeGraphAliasORM,
    KnowledgeGraphClaim as KnowledgeGraphClaimORM,
    KnowledgeGraphClaimEvidence as KnowledgeGraphClaimEvidenceORM,
    KnowledgeGraphEntity as KnowledgeGraphEntityORM,
    KnowledgeGraphMention as KnowledgeGraphMentionORM,
    KnowledgeGraphReviewItem as KnowledgeGraphReviewItemORM,
    KnowledgeGraphRevision as KnowledgeGraphRevisionORM,
    KnowledgeGraphRevisionChange as KnowledgeGraphRevisionChangeORM,
    KnowledgeGraphSchema as KnowledgeGraphSchemaORM,
)


async def create_graph_schema(
    db: AsyncSession,
    entity: KnowledgeGraphSchema,
) -> KnowledgeGraphSchema:
    row = await save(db, KnowledgeGraphSchemaORM, entity)
    return to_entity(KnowledgeGraphSchema, row)


async def save_graph_schema(
    db: AsyncSession,
    entity: KnowledgeGraphSchema,
) -> KnowledgeGraphSchema:
    row = await save(db, KnowledgeGraphSchemaORM, entity)
    return to_entity(KnowledgeGraphSchema, row)


async def get_schema_by_hash(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    schema_hash: str,
) -> KnowledgeGraphSchema | None:
    row = await db.scalar(
        select(KnowledgeGraphSchemaORM).where(
            KnowledgeGraphSchemaORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphSchemaORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphSchemaORM.schema_hash == schema_hash,
        )
    )
    return to_entity(KnowledgeGraphSchema, row) if row else None


async def next_schema_version(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> int:
    current = await db.scalar(
        select(func.max(KnowledgeGraphSchemaORM.version)).where(
            KnowledgeGraphSchemaORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphSchemaORM.knowledge_base_id == knowledge_base.id,
        )
    )
    return int(current or 0) + 1


async def lock_graph_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    schema_id: str,
) -> KnowledgeGraphSchema | None:
    row = await db.scalar(
        select(KnowledgeGraphSchemaORM)
        .where(
            KnowledgeGraphSchemaORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphSchemaORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphSchemaORM.id == schema_id,
        )
        .with_for_update()
    )
    return to_entity(KnowledgeGraphSchema, row) if row else None


async def retire_active_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> None:
    await db.execute(
        update(KnowledgeGraphSchemaORM)
        .where(
            KnowledgeGraphSchemaORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphSchemaORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphSchemaORM.status == GRAPH_SCHEMA_ACTIVE,
        )
        .values(status=GRAPH_SCHEMA_RETIRED, updated_at=utc_now())
    )


async def create_revision(
    db: AsyncSession,
    entity: KnowledgeGraphRevision,
) -> KnowledgeGraphRevision:
    row = await save(db, KnowledgeGraphRevisionORM, entity)
    return to_entity(KnowledgeGraphRevision, row)


async def save_revision(db: AsyncSession, entity: KnowledgeGraphRevision) -> None:
    await save(db, KnowledgeGraphRevisionORM, entity)


async def create_revision_change(
    db: AsyncSession,
    entity: KnowledgeGraphRevisionChange,
) -> KnowledgeGraphRevisionChange:
    row = await save(db, KnowledgeGraphRevisionChangeORM, entity)
    return to_entity(KnowledgeGraphRevisionChange, row)


async def save_revision_change(
    db: AsyncSession,
    entity: KnowledgeGraphRevisionChange,
) -> None:
    await save(db, KnowledgeGraphRevisionChangeORM, entity)


async def create_entity(
    db: AsyncSession,
    entity: KnowledgeGraphEntity,
) -> KnowledgeGraphEntity:
    row = await save(db, KnowledgeGraphEntityORM, entity)
    return to_entity(KnowledgeGraphEntity, row)


async def save_entity(db: AsyncSession, entity: KnowledgeGraphEntity) -> None:
    await save(db, KnowledgeGraphEntityORM, entity)


async def create_alias(
    db: AsyncSession,
    entity: KnowledgeGraphAlias,
) -> KnowledgeGraphAlias:
    row = await save(db, KnowledgeGraphAliasORM, entity)
    return to_entity(KnowledgeGraphAlias, row)


async def save_alias(db: AsyncSession, entity: KnowledgeGraphAlias) -> None:
    await save(db, KnowledgeGraphAliasORM, entity)


async def create_mention(
    db: AsyncSession,
    entity: KnowledgeGraphMention,
) -> KnowledgeGraphMention:
    row = await save(db, KnowledgeGraphMentionORM, entity)
    return to_entity(KnowledgeGraphMention, row)


async def save_mention(db: AsyncSession, entity: KnowledgeGraphMention) -> None:
    await save(db, KnowledgeGraphMentionORM, entity)


async def create_claim(
    db: AsyncSession,
    entity: KnowledgeGraphClaim,
) -> KnowledgeGraphClaim:
    row = await save(db, KnowledgeGraphClaimORM, entity)
    return to_entity(KnowledgeGraphClaim, row)


async def save_claim(db: AsyncSession, entity: KnowledgeGraphClaim) -> None:
    await save(db, KnowledgeGraphClaimORM, entity)


async def create_evidence(
    db: AsyncSession,
    entity: KnowledgeGraphClaimEvidence,
) -> KnowledgeGraphClaimEvidence:
    row = await save(db, KnowledgeGraphClaimEvidenceORM, entity)
    return to_entity(KnowledgeGraphClaimEvidence, row)


async def save_evidence(
    db: AsyncSession,
    entity: KnowledgeGraphClaimEvidence,
) -> None:
    await save(db, KnowledgeGraphClaimEvidenceORM, entity)


async def create_review_item(
    db: AsyncSession,
    entity: KnowledgeGraphReviewItem,
) -> KnowledgeGraphReviewItem:
    row = await save(db, KnowledgeGraphReviewItemORM, entity)
    return to_entity(KnowledgeGraphReviewItem, row)


async def save_review_item(
    db: AsyncSession,
    entity: KnowledgeGraphReviewItem,
) -> None:
    await save(db, KnowledgeGraphReviewItemORM, entity)

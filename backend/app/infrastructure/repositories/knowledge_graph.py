from sqlalchemy import delete, false, func, or_, select, update
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
from app.shareddomain.knowledge.models import KnowledgeBase as KnowledgeBaseORM
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


async def get_revision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision_id: str,
) -> KnowledgeGraphRevision | None:
    row = await db.scalar(
        select(KnowledgeGraphRevisionORM).where(
            KnowledgeGraphRevisionORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphRevisionORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphRevisionORM.id == revision_id,
        )
    )
    return to_entity(KnowledgeGraphRevision, row) if row else None


async def get_active_revision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeGraphRevision | None:
    if not knowledge_base.active_graph_revision_id:
        return None
    return await get_revision(db, knowledge_base, knowledge_base.active_graph_revision_id)


async def next_revision_no(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> int:
    current = await db.scalar(
        select(func.max(KnowledgeGraphRevisionORM.revision_no)).where(
            KnowledgeGraphRevisionORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphRevisionORM.knowledge_base_id == knowledge_base.id,
        )
    )
    return int(current or 0) + 1


async def lock_revision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision_id: str,
) -> KnowledgeGraphRevision | None:
    row = await db.scalar(
        select(KnowledgeGraphRevisionORM)
        .where(
            KnowledgeGraphRevisionORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphRevisionORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphRevisionORM.id == revision_id,
        )
        .with_for_update()
    )
    return to_entity(KnowledgeGraphRevision, row) if row else None


async def save_revision(
    db: AsyncSession,
    entity: KnowledgeGraphRevision,
) -> KnowledgeGraphRevision:
    row = await save(db, KnowledgeGraphRevisionORM, entity)
    return to_entity(KnowledgeGraphRevision, row)


async def retire_active_revision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision_id: str | None,
) -> None:
    if revision_id is None:
        return
    await db.execute(
        update(KnowledgeGraphRevisionORM)
        .where(
            KnowledgeGraphRevisionORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphRevisionORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphRevisionORM.id == revision_id,
        )
        .values(status="retired", updated_at=utc_now())
    )


async def lock_knowledge_base_graph(
    db: AsyncSession,
    knowledge_base_id: str,
) -> KnowledgeBase | None:
    row = await db.scalar(
        select(KnowledgeBaseORM)
        .where(KnowledgeBaseORM.id == knowledge_base_id)
        .with_for_update()
    )
    return to_entity(KnowledgeBase, row) if row else None


async def save_knowledge_base_graph_fields(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeBase:
    row = await save(db, KnowledgeBaseORM, knowledge_base)
    return to_entity(KnowledgeBase, row)


async def create_revision_change(
    db: AsyncSession,
    entity: KnowledgeGraphRevisionChange,
) -> KnowledgeGraphRevisionChange:
    row = await save(db, KnowledgeGraphRevisionChangeORM, entity)
    return to_entity(KnowledgeGraphRevisionChange, row)


async def save_revision_change(
    db: AsyncSession,
    entity: KnowledgeGraphRevisionChange,
) -> KnowledgeGraphRevisionChange:
    row = await save(db, KnowledgeGraphRevisionChangeORM, entity)
    return to_entity(KnowledgeGraphRevisionChange, row)


async def get_revision_change(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_kind: str,
    record_key: str,
) -> KnowledgeGraphRevisionChange | None:
    row = await db.scalar(
        select(KnowledgeGraphRevisionChangeORM).where(
            KnowledgeGraphRevisionChangeORM.workspace_id == revision.workspace_id,
            KnowledgeGraphRevisionChangeORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphRevisionChangeORM.revision_id == revision.id,
            KnowledgeGraphRevisionChangeORM.record_kind == record_kind,
            KnowledgeGraphRevisionChangeORM.record_key == record_key,
        )
    )
    return to_entity(KnowledgeGraphRevisionChange, row) if row else None


async def next_revision_change_sequence(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
) -> int:
    current = await db.scalar(
        select(func.max(KnowledgeGraphRevisionChangeORM.sequence_no)).where(
            KnowledgeGraphRevisionChangeORM.workspace_id == revision.workspace_id,
            KnowledgeGraphRevisionChangeORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphRevisionChangeORM.revision_id == revision.id,
        )
    )
    return 0 if current is None else int(current) + 1


async def list_revision_changes(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
) -> list[KnowledgeGraphRevisionChange]:
    rows = await db.scalars(
        select(KnowledgeGraphRevisionChangeORM)
        .where(
            KnowledgeGraphRevisionChangeORM.workspace_id == revision.workspace_id,
            KnowledgeGraphRevisionChangeORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphRevisionChangeORM.revision_id == revision.id,
        )
        .order_by(
            KnowledgeGraphRevisionChangeORM.sequence_no,
            KnowledgeGraphRevisionChangeORM.id,
        )
    )
    return [to_entity(KnowledgeGraphRevisionChange, row) for row in rows.all()]


async def create_entity(
    db: AsyncSession,
    entity: KnowledgeGraphEntity,
) -> KnowledgeGraphEntity:
    row = await save(db, KnowledgeGraphEntityORM, entity)
    return to_entity(KnowledgeGraphEntity, row)


async def list_entity_identity_candidates(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    entity_type: str,
    external_key: str | None,
    normalized_names: set[str],
) -> list[KnowledgeGraphEntity]:
    human_alias_match = (
        select(KnowledgeGraphAliasORM.id)
        .where(
            KnowledgeGraphAliasORM.workspace_id
            == KnowledgeGraphEntityORM.workspace_id,
            KnowledgeGraphAliasORM.knowledge_base_id
            == KnowledgeGraphEntityORM.knowledge_base_id,
            KnowledgeGraphAliasORM.entity_id == KnowledgeGraphEntityORM.id,
            KnowledgeGraphAliasORM.source == "human",
            KnowledgeGraphAliasORM.retired_revision_id.is_(None),
            KnowledgeGraphAliasORM.normalized_alias.in_(sorted(normalized_names)),
        )
        .exists()
    )
    rows = await db.scalars(
        select(KnowledgeGraphEntityORM).where(
            KnowledgeGraphEntityORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphEntityORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphEntityORM.entity_type == entity_type,
            KnowledgeGraphEntityORM.state == "active",
            or_(
                KnowledgeGraphEntityORM.external_key == external_key
                if external_key is not None
                else false(),
                KnowledgeGraphEntityORM.normalized_name.in_(
                    sorted(normalized_names)
                ),
                human_alias_match,
            ),
        )
    )
    return [to_entity(KnowledgeGraphEntity, row) for row in rows.all()]


async def list_human_alias_entity_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    entity_type: str,
    normalized_names: set[str],
) -> set[str]:
    if not normalized_names:
        return set()
    rows = await db.scalars(
        select(KnowledgeGraphAliasORM.entity_id).where(
            KnowledgeGraphAliasORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphAliasORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphAliasORM.source == "human",
            KnowledgeGraphAliasORM.retired_revision_id.is_(None),
            KnowledgeGraphAliasORM.normalized_alias.in_(sorted(normalized_names)),
            KnowledgeGraphAliasORM.entity_id.in_(
                select(KnowledgeGraphEntityORM.id).where(
                    KnowledgeGraphEntityORM.workspace_id
                    == knowledge_base.workspace_id,
                    KnowledgeGraphEntityORM.knowledge_base_id == knowledge_base.id,
                    KnowledgeGraphEntityORM.entity_type == entity_type,
                    KnowledgeGraphEntityORM.state == "active",
                )
            ),
        )
    )
    return set(rows.all())


async def get_entity(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> KnowledgeGraphEntity | None:
    row = await db.scalar(
        select(KnowledgeGraphEntityORM).where(
            KnowledgeGraphEntityORM.workspace_id == revision.workspace_id,
            KnowledgeGraphEntityORM.knowledge_base_id == revision.knowledge_base_id,
            KnowledgeGraphEntityORM.id == record_key,
        )
    )
    return to_entity(KnowledgeGraphEntity, row) if row else None


async def save_entity(
    db: AsyncSession,
    entity: KnowledgeGraphEntity,
) -> KnowledgeGraphEntity:
    row = await save(db, KnowledgeGraphEntityORM, entity)
    return to_entity(KnowledgeGraphEntity, row)


async def delete_entity(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> None:
    await db.execute(
        delete(KnowledgeGraphEntityORM).where(
            KnowledgeGraphEntityORM.workspace_id == revision.workspace_id,
            KnowledgeGraphEntityORM.knowledge_base_id == revision.knowledge_base_id,
            KnowledgeGraphEntityORM.id == record_key,
        )
    )


async def create_alias(
    db: AsyncSession,
    entity: KnowledgeGraphAlias,
) -> KnowledgeGraphAlias:
    row = await save(db, KnowledgeGraphAliasORM, entity)
    return to_entity(KnowledgeGraphAlias, row)


async def get_alias(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> KnowledgeGraphAlias | None:
    row = await db.scalar(
        select(KnowledgeGraphAliasORM).where(
            KnowledgeGraphAliasORM.workspace_id == revision.workspace_id,
            KnowledgeGraphAliasORM.knowledge_base_id == revision.knowledge_base_id,
            KnowledgeGraphAliasORM.id == record_key,
        )
    )
    return to_entity(KnowledgeGraphAlias, row) if row else None


async def save_alias(
    db: AsyncSession,
    entity: KnowledgeGraphAlias,
) -> KnowledgeGraphAlias:
    row = await save(db, KnowledgeGraphAliasORM, entity)
    return to_entity(KnowledgeGraphAlias, row)


async def delete_alias(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> None:
    await db.execute(
        delete(KnowledgeGraphAliasORM).where(
            KnowledgeGraphAliasORM.workspace_id == revision.workspace_id,
            KnowledgeGraphAliasORM.knowledge_base_id == revision.knowledge_base_id,
            KnowledgeGraphAliasORM.id == record_key,
        )
    )


async def create_mention(
    db: AsyncSession,
    entity: KnowledgeGraphMention,
) -> KnowledgeGraphMention:
    row = await save(db, KnowledgeGraphMentionORM, entity)
    return to_entity(KnowledgeGraphMention, row)


async def get_mention(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> KnowledgeGraphMention | None:
    row = await db.scalar(
        select(KnowledgeGraphMentionORM).where(
            KnowledgeGraphMentionORM.workspace_id == revision.workspace_id,
            KnowledgeGraphMentionORM.knowledge_base_id == revision.knowledge_base_id,
            KnowledgeGraphMentionORM.id == record_key,
        )
    )
    return to_entity(KnowledgeGraphMention, row) if row else None


async def save_mention(
    db: AsyncSession,
    entity: KnowledgeGraphMention,
) -> KnowledgeGraphMention:
    row = await save(db, KnowledgeGraphMentionORM, entity)
    return to_entity(KnowledgeGraphMention, row)


async def delete_mention(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> None:
    await db.execute(
        delete(KnowledgeGraphMentionORM).where(
            KnowledgeGraphMentionORM.workspace_id == revision.workspace_id,
            KnowledgeGraphMentionORM.knowledge_base_id == revision.knowledge_base_id,
            KnowledgeGraphMentionORM.id == record_key,
        )
    )


async def create_claim(
    db: AsyncSession,
    entity: KnowledgeGraphClaim,
) -> KnowledgeGraphClaim:
    row = await save(db, KnowledgeGraphClaimORM, entity)
    return to_entity(KnowledgeGraphClaim, row)


async def get_claim(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> KnowledgeGraphClaim | None:
    row = await db.scalar(
        select(KnowledgeGraphClaimORM).where(
            KnowledgeGraphClaimORM.workspace_id == revision.workspace_id,
            KnowledgeGraphClaimORM.knowledge_base_id == revision.knowledge_base_id,
            or_(
                KnowledgeGraphClaimORM.id == record_key,
                KnowledgeGraphClaimORM.fingerprint == record_key,
            ),
        )
    )
    return to_entity(KnowledgeGraphClaim, row) if row else None


async def save_claim(
    db: AsyncSession,
    entity: KnowledgeGraphClaim,
) -> KnowledgeGraphClaim:
    row = await save(db, KnowledgeGraphClaimORM, entity)
    return to_entity(KnowledgeGraphClaim, row)


async def delete_claim(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> None:
    await db.execute(
        delete(KnowledgeGraphClaimORM).where(
            KnowledgeGraphClaimORM.workspace_id == revision.workspace_id,
            KnowledgeGraphClaimORM.knowledge_base_id == revision.knowledge_base_id,
            or_(
                KnowledgeGraphClaimORM.id == record_key,
                KnowledgeGraphClaimORM.fingerprint == record_key,
            ),
        )
    )


async def create_evidence(
    db: AsyncSession,
    entity: KnowledgeGraphClaimEvidence,
) -> KnowledgeGraphClaimEvidence:
    row = await save(db, KnowledgeGraphClaimEvidenceORM, entity)
    return to_entity(KnowledgeGraphClaimEvidence, row)


async def save_evidence(
    db: AsyncSession,
    entity: KnowledgeGraphClaimEvidence,
) -> KnowledgeGraphClaimEvidence:
    row = await save(db, KnowledgeGraphClaimEvidenceORM, entity)
    return to_entity(KnowledgeGraphClaimEvidence, row)


async def count_active_claim_evidence(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    claim_id: str,
) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(KnowledgeGraphClaimEvidenceORM)
        .where(
            KnowledgeGraphClaimEvidenceORM.workspace_id == revision.workspace_id,
            KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphClaimEvidenceORM.claim_id == claim_id,
            KnowledgeGraphClaimEvidenceORM.evidence_state == "active",
        )
    )
    return int(count or 0)


async def get_evidence(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> KnowledgeGraphClaimEvidence | None:
    row = await db.scalar(
        select(KnowledgeGraphClaimEvidenceORM).where(
            KnowledgeGraphClaimEvidenceORM.workspace_id == revision.workspace_id,
            KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphClaimEvidenceORM.id == record_key,
        )
    )
    return to_entity(KnowledgeGraphClaimEvidence, row) if row else None


async def delete_evidence(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> None:
    await db.execute(
        delete(KnowledgeGraphClaimEvidenceORM).where(
            KnowledgeGraphClaimEvidenceORM.workspace_id == revision.workspace_id,
            KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphClaimEvidenceORM.id == record_key,
        )
    )


async def create_review_item(
    db: AsyncSession,
    entity: KnowledgeGraphReviewItem,
) -> KnowledgeGraphReviewItem:
    row = await save(db, KnowledgeGraphReviewItemORM, entity)
    return to_entity(KnowledgeGraphReviewItem, row)


async def save_review_item(
    db: AsyncSession,
    entity: KnowledgeGraphReviewItem,
) -> KnowledgeGraphReviewItem:
    row = await save(db, KnowledgeGraphReviewItemORM, entity)
    return to_entity(KnowledgeGraphReviewItem, row)


async def get_review_item(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> KnowledgeGraphReviewItem | None:
    row = await db.scalar(
        select(KnowledgeGraphReviewItemORM).where(
            KnowledgeGraphReviewItemORM.workspace_id == revision.workspace_id,
            KnowledgeGraphReviewItemORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphReviewItemORM.id == record_key,
        )
    )
    return to_entity(KnowledgeGraphReviewItem, row) if row else None


async def delete_review_item(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    record_key: str,
) -> None:
    await db.execute(
        delete(KnowledgeGraphReviewItemORM).where(
            KnowledgeGraphReviewItemORM.workspace_id == revision.workspace_id,
            KnowledgeGraphReviewItemORM.knowledge_base_id
            == revision.knowledge_base_id,
            KnowledgeGraphReviewItemORM.id == record_key,
        )
    )

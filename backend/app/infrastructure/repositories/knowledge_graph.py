from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    case,
    delete,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    DOCUMENT_DELETED_STATUS,
    KnowledgeBase,
    KnowledgeDocumentChunk,
)
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
from app.shareddomain.knowledge.models import (
    KnowledgeDocument as KnowledgeDocumentORM,
    KnowledgeDocumentChunk as KnowledgeDocumentChunkORM,
)
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

_GRAPH_SQL_DIR = Path(__file__).parent.parent / "sql" / "knowledge_graph"
_SHORTEST_PATH_SQL = text(
    (_GRAPH_SQL_DIR / "shortest_path.sql").read_text(encoding="utf-8")
)
_NEIGHBORHOOD_SQL = text(
    (_GRAPH_SQL_DIR / "neighborhood.sql").read_text(encoding="utf-8")
)
_QUERY_ENTITY_CANDIDATES_SQL = text(
    (_GRAPH_SQL_DIR / "query_entity_candidates.sql").read_text(encoding="utf-8")
)
_SET_GRAPH_STATEMENT_TIMEOUT = text("SET LOCAL statement_timeout = '2000ms'")
_RESET_GRAPH_STATEMENT_TIMEOUT = text("SET LOCAL statement_timeout = 0")


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


async def get_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    schema_id: str,
) -> KnowledgeGraphSchema | None:
    row = await db.scalar(
        select(KnowledgeGraphSchemaORM).where(
            KnowledgeGraphSchemaORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphSchemaORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphSchemaORM.id == schema_id,
        )
    )
    return to_entity(KnowledgeGraphSchema, row) if row else None


async def get_active_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeGraphSchema | None:
    row = await db.scalar(
        select(KnowledgeGraphSchemaORM)
        .where(
            KnowledgeGraphSchemaORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphSchemaORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphSchemaORM.status == GRAPH_SCHEMA_ACTIVE,
        )
        .order_by(KnowledgeGraphSchemaORM.version.desc())
    )
    return to_entity(KnowledgeGraphSchema, row) if row else None


async def get_latest_draft_or_active_schema(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeGraphSchema | None:
    row = await db.scalar(
        select(KnowledgeGraphSchemaORM)
        .where(
            KnowledgeGraphSchemaORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphSchemaORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphSchemaORM.status.in_(["draft", GRAPH_SCHEMA_ACTIVE]),
        )
        .order_by(KnowledgeGraphSchemaORM.version.desc())
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


async def lock_revision_by_id(
    db: AsyncSession,
    revision_id: str,
) -> KnowledgeGraphRevision | None:
    row = await db.scalar(
        select(KnowledgeGraphRevisionORM)
        .where(KnowledgeGraphRevisionORM.id == revision_id)
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


async def list_active_entities(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> list[KnowledgeGraphEntity]:
    rows = await db.scalars(
        select(KnowledgeGraphEntityORM).where(
            KnowledgeGraphEntityORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphEntityORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphEntityORM.state == "active",
        )
    )
    return [to_entity(KnowledgeGraphEntity, row) for row in rows.all()]


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


async def list_active_mentions_for_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str] | None,
) -> list[KnowledgeGraphMention]:
    if document_ids == set():
        return []
    statement = select(KnowledgeGraphMentionORM).where(
            KnowledgeGraphMentionORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphMentionORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphMentionORM.retired_revision_id.is_(None),
        )
    if document_ids is not None:
        statement = statement.where(
            KnowledgeGraphMentionORM.document_id.in_(sorted(document_ids))
        )
    rows = await db.scalars(statement)
    return [to_entity(KnowledgeGraphMention, row) for row in rows.all()]


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


async def list_active_claims(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> list[KnowledgeGraphClaim]:
    rows = await db.scalars(
        select(KnowledgeGraphClaimORM).where(
            KnowledgeGraphClaimORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphClaimORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphClaimORM.status == "active",
            KnowledgeGraphClaimORM.retired_revision_id.is_(None),
        )
    )
    return [to_entity(KnowledgeGraphClaim, row) for row in rows.all()]


async def list_current_claims(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> list[KnowledgeGraphClaim]:
    rows = await db.scalars(
        select(KnowledgeGraphClaimORM).where(
            KnowledgeGraphClaimORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphClaimORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphClaimORM.status.in_(["active", "candidate", "rejected"]),
            KnowledgeGraphClaimORM.retired_revision_id.is_(None),
        )
    )
    return [to_entity(KnowledgeGraphClaim, row) for row in rows.all()]


async def list_traversable_claim_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> list[str]:
    accessible_evidence = exists(
        select(KnowledgeGraphClaimEvidenceORM.id)
        .join(
            KnowledgeDocumentORM,
            (
                KnowledgeDocumentORM.workspace_id
                == KnowledgeGraphClaimEvidenceORM.workspace_id
            )
            & (
                KnowledgeDocumentORM.knowledge_base_id
                == KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            )
            & (
                KnowledgeDocumentORM.id
                == KnowledgeGraphClaimEvidenceORM.document_id
            ),
        )
        .where(
            KnowledgeGraphClaimEvidenceORM.workspace_id
            == KnowledgeGraphClaimORM.workspace_id,
            KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            == KnowledgeGraphClaimORM.knowledge_base_id,
            KnowledgeGraphClaimEvidenceORM.claim_id == KnowledgeGraphClaimORM.id,
            KnowledgeGraphClaimEvidenceORM.evidence_state == "active",
            KnowledgeGraphClaimEvidenceORM.retired_revision_id.is_(None),
            KnowledgeDocumentORM.status != DOCUMENT_DELETED_STATUS,
            KnowledgeDocumentORM.is_active.is_(True),
        )
    )
    rows = await db.scalars(
        select(KnowledgeGraphClaimORM.id)
        .where(
            KnowledgeGraphClaimORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphClaimORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphClaimORM.status == "active",
            KnowledgeGraphClaimORM.retired_revision_id.is_(None),
            accessible_evidence,
        )
        .order_by(KnowledgeGraphClaimORM.id)
    )
    return list(rows)


async def list_active_claims_without_evidence_outside_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str] | None,
) -> list[KnowledgeGraphClaim]:
    if document_ids is None:
        return await list_active_claims(db, knowledge_base)
    remaining_evidence = exists(
        select(KnowledgeGraphClaimEvidenceORM.id).where(
            KnowledgeGraphClaimEvidenceORM.workspace_id
            == KnowledgeGraphClaimORM.workspace_id,
            KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            == KnowledgeGraphClaimORM.knowledge_base_id,
            KnowledgeGraphClaimEvidenceORM.claim_id == KnowledgeGraphClaimORM.id,
            KnowledgeGraphClaimEvidenceORM.evidence_state == "active",
            KnowledgeGraphClaimEvidenceORM.retired_revision_id.is_(None),
            KnowledgeGraphClaimEvidenceORM.document_id.not_in(
                sorted(document_ids)
            ),
        )
    )
    rows = await db.scalars(
        select(KnowledgeGraphClaimORM).where(
            KnowledgeGraphClaimORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphClaimORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphClaimORM.status == "active",
            KnowledgeGraphClaimORM.retired_revision_id.is_(None),
            ~remaining_evidence,
        )
    )
    return [to_entity(KnowledgeGraphClaim, row) for row in rows.all()]


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


async def list_active_evidence_for_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str] | None,
) -> list[KnowledgeGraphClaimEvidence]:
    if document_ids == set():
        return []
    statement = select(KnowledgeGraphClaimEvidenceORM).where(
            KnowledgeGraphClaimEvidenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeGraphClaimEvidenceORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphClaimEvidenceORM.evidence_state == "active",
            KnowledgeGraphClaimEvidenceORM.retired_revision_id.is_(None),
        )
    if document_ids is not None:
        statement = statement.where(
            KnowledgeGraphClaimEvidenceORM.document_id.in_(sorted(document_ids))
        )
    rows = await db.scalars(statement)
    return [to_entity(KnowledgeGraphClaimEvidence, row) for row in rows.all()]


async def list_graph_source_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str] | None = None,
) -> list[KnowledgeDocumentChunk]:
    statement = (
        select(KnowledgeDocumentChunkORM)
        .join(
            KnowledgeDocumentORM,
            (
                KnowledgeDocumentORM.workspace_id
                == KnowledgeDocumentChunkORM.workspace_id
            )
            & (
                KnowledgeDocumentORM.knowledge_base_id
                == KnowledgeDocumentChunkORM.knowledge_base_id
            )
            & (KnowledgeDocumentORM.id == KnowledgeDocumentChunkORM.document_id),
        )
        .where(
            KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentChunkORM.status == "indexed",
            KnowledgeDocumentORM.status == "indexed",
            KnowledgeDocumentORM.is_active.is_(True),
        )
    )
    if document_ids is not None:
        if not document_ids:
            return []
        statement = statement.where(
            KnowledgeDocumentChunkORM.document_id.in_(sorted(document_ids))
        )
    rows = await db.scalars(
        statement.order_by(
            KnowledgeDocumentChunkORM.document_id,
            KnowledgeDocumentChunkORM.chunk_index,
        )
    )
    return [to_entity(KnowledgeDocumentChunk, row) for row in rows.all()]


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


async def _query_traversal_rows(
    db: AsyncSession,
    statement,
    parameters: dict[str, object],
) -> tuple[list[tuple[list[str], list[str]]], int, bool]:
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Knowledge graph traversal requires PostgreSQL.")
    try:
        async with db.begin_nested():
            await db.execute(_SET_GRAPH_STATEMENT_TIMEOUT)
            result = await db.execute(statement, parameters)
            rows = result.mappings().all()
            await db.execute(_RESET_GRAPH_STATEMENT_TIMEOUT)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "57014":
            return [], 0, True
        raise
    visited_nodes = int(rows[0]["visited_nodes"] or 0) if rows else 0
    paths = [
        (
            [str(value) for value in row["entity_path"]],
            [str(value) for value in row["claim_path"]],
        )
        for row in rows
        if row["entity_path"] is not None and row["claim_path"] is not None
    ]
    return paths, visited_nodes, False


async def query_shortest_path_rows(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    source_entity_id: str,
    target_entity_id: str,
    max_hops: int,
    relation_filters: list[str] | None,
) -> tuple[list[tuple[list[str], list[str]]], int, bool]:
    return await _query_traversal_rows(
        db,
        _SHORTEST_PATH_SQL,
        {
            "workspace_id": knowledge_base.workspace_id,
            "knowledge_base_id": knowledge_base.id,
            "source_entity_id": source_entity_id,
            "target_entity_id": target_entity_id,
            "max_hops": max_hops,
            "relation_filters": relation_filters or None,
        },
    )


async def query_neighborhood_rows(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    source_entity_id: str,
    max_hops: int,
    relation_filters: list[str] | None,
) -> tuple[list[tuple[list[str], list[str]]], int, bool]:
    return await _query_traversal_rows(
        db,
        _NEIGHBORHOOD_SQL,
        {
            "workspace_id": knowledge_base.workspace_id,
            "knowledge_base_id": knowledge_base.id,
            "source_entity_id": source_entity_id,
            "max_hops": max_hops,
            "relation_filters": relation_filters or None,
        },
    )


async def list_active_entities_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    entity_ids: set[str],
) -> list[KnowledgeGraphEntity]:
    if not entity_ids:
        return []
    rows = await db.scalars(
        select(KnowledgeGraphEntityORM).where(
            KnowledgeGraphEntityORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphEntityORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphEntityORM.id.in_(sorted(entity_ids)),
            KnowledgeGraphEntityORM.state == "active",
            KnowledgeGraphEntityORM.retired_revision_id.is_(None),
        )
    )
    return [to_entity(KnowledgeGraphEntity, row) for row in rows.all()]


async def list_exact_entity_matches(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    normalized_text: str,
) -> list[KnowledgeGraphEntity]:
    if not normalized_text:
        return []
    alias_match = exists(
        select(KnowledgeGraphAliasORM.id).where(
            KnowledgeGraphAliasORM.workspace_id
            == KnowledgeGraphEntityORM.workspace_id,
            KnowledgeGraphAliasORM.knowledge_base_id
            == KnowledgeGraphEntityORM.knowledge_base_id,
            KnowledgeGraphAliasORM.entity_id == KnowledgeGraphEntityORM.id,
            KnowledgeGraphAliasORM.normalized_alias == normalized_text,
            KnowledgeGraphAliasORM.retired_revision_id.is_(None),
        )
    )
    rows = await db.scalars(
        select(KnowledgeGraphEntityORM)
        .where(
            KnowledgeGraphEntityORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphEntityORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphEntityORM.state == "active",
            KnowledgeGraphEntityORM.retired_revision_id.is_(None),
            or_(
                KnowledgeGraphEntityORM.normalized_name == normalized_text,
                alias_match,
            ),
        )
        .order_by(KnowledgeGraphEntityORM.id)
    )
    return [to_entity(KnowledgeGraphEntity, row) for row in rows.all()]


async def list_query_entity_mentions(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    normalized_query: str,
    limit: int = 16,
) -> list[KnowledgeGraphEntity]:
    if not normalized_query or limit <= 0:
        return []
    contains = (
        func.instr(literal(normalized_query), KnowledgeGraphEntityORM.normalized_name)
        if db.get_bind().dialect.name == "sqlite"
        else func.strpos(
            literal(normalized_query),
            KnowledgeGraphEntityORM.normalized_name,
        )
    )
    alias_contains = (
        func.instr(literal(normalized_query), KnowledgeGraphAliasORM.normalized_alias)
        if db.get_bind().dialect.name == "sqlite"
        else func.strpos(
            literal(normalized_query),
            KnowledgeGraphAliasORM.normalized_alias,
        )
    )
    alias_match = exists(
        select(KnowledgeGraphAliasORM.id).where(
            KnowledgeGraphAliasORM.workspace_id
            == KnowledgeGraphEntityORM.workspace_id,
            KnowledgeGraphAliasORM.knowledge_base_id
            == KnowledgeGraphEntityORM.knowledge_base_id,
            KnowledgeGraphAliasORM.entity_id == KnowledgeGraphEntityORM.id,
            KnowledgeGraphAliasORM.retired_revision_id.is_(None),
            alias_contains > 0,
        )
    )
    rows = await db.scalars(
        select(KnowledgeGraphEntityORM)
        .where(
            KnowledgeGraphEntityORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphEntityORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphEntityORM.state == "active",
            KnowledgeGraphEntityORM.retired_revision_id.is_(None),
            or_(contains > 0, alias_match),
        )
        .order_by(
            func.length(KnowledgeGraphEntityORM.normalized_name).desc(),
            KnowledgeGraphEntityORM.id,
        )
        .limit(limit)
    )
    return [to_entity(KnowledgeGraphEntity, row) for row in rows.all()]


async def query_entity_candidate_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    query: str,
    candidate_limit: int = 8,
    entity_types: set[str] | None = None,
) -> list[str]:
    if db.get_bind().dialect.name != "postgresql" or candidate_limit <= 0:
        return []
    result = await db.execute(
        _QUERY_ENTITY_CANDIDATES_SQL,
        {
            "workspace_id": knowledge_base.workspace_id,
            "knowledge_base_id": knowledge_base.id,
            "query": query,
            "candidate_limit": candidate_limit,
            "entity_types": sorted(entity_types) if entity_types else None,
        },
    )
    return list(result.scalars())


async def list_active_claims_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    claim_ids: set[str],
) -> list[KnowledgeGraphClaim]:
    if not claim_ids:
        return []
    rows = await db.scalars(
        select(KnowledgeGraphClaimORM).where(
            KnowledgeGraphClaimORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeGraphClaimORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphClaimORM.id.in_(sorted(claim_ids)),
            KnowledgeGraphClaimORM.status == "active",
            KnowledgeGraphClaimORM.retired_revision_id.is_(None),
        )
    )
    return [to_entity(KnowledgeGraphClaim, row) for row in rows.all()]


async def list_ranked_evidence_for_claim_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    claim_ids: set[str],
) -> list[tuple[KnowledgeGraphClaimEvidence, str, str, float, datetime]]:
    if not claim_ids:
        return []
    source_priority = case(
        (KnowledgeGraphClaimORM.source_kind == "structured_import", 0),
        (KnowledgeGraphClaimORM.source_kind == "document_reference", 1),
        else_=2,
    )
    rows = await db.execute(
        select(
            KnowledgeGraphClaimEvidenceORM,
            KnowledgeDocumentORM.filename,
            KnowledgeGraphClaimORM.source_kind,
            KnowledgeGraphClaimORM.quality_score,
            KnowledgeDocumentORM.updated_at,
        )
        .join(
            KnowledgeGraphClaimORM,
            (
                KnowledgeGraphClaimORM.workspace_id
                == KnowledgeGraphClaimEvidenceORM.workspace_id
            )
            & (
                KnowledgeGraphClaimORM.knowledge_base_id
                == KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            )
            & (
                KnowledgeGraphClaimORM.id
                == KnowledgeGraphClaimEvidenceORM.claim_id
            ),
        )
        .join(
            KnowledgeDocumentORM,
            (
                KnowledgeDocumentORM.workspace_id
                == KnowledgeGraphClaimEvidenceORM.workspace_id
            )
            & (
                KnowledgeDocumentORM.knowledge_base_id
                == KnowledgeGraphClaimEvidenceORM.knowledge_base_id
            )
            & (
                KnowledgeDocumentORM.id
                == KnowledgeGraphClaimEvidenceORM.document_id
            ),
        )
        .where(
            KnowledgeGraphClaimEvidenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeGraphClaimEvidenceORM.knowledge_base_id == knowledge_base.id,
            KnowledgeGraphClaimEvidenceORM.claim_id.in_(sorted(claim_ids)),
            KnowledgeGraphClaimEvidenceORM.evidence_state == "active",
            KnowledgeGraphClaimEvidenceORM.retired_revision_id.is_(None),
            KnowledgeGraphClaimORM.status == "active",
            KnowledgeGraphClaimORM.retired_revision_id.is_(None),
            KnowledgeDocumentORM.status != DOCUMENT_DELETED_STATUS,
            KnowledgeDocumentORM.is_active.is_(True),
        )
        .order_by(
            KnowledgeGraphClaimEvidenceORM.claim_id,
            source_priority,
            KnowledgeGraphClaimORM.quality_score.desc(),
            KnowledgeDocumentORM.updated_at.desc(),
            KnowledgeGraphClaimEvidenceORM.id,
        )
    )
    return [
        (
            to_entity(KnowledgeGraphClaimEvidence, evidence),
            str(filename),
            str(source_kind),
            float(quality_score),
            document_updated_at,
        )
        for evidence, filename, source_kind, quality_score, document_updated_at in rows
    ]

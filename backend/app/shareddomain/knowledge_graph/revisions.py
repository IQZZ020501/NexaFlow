from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import KnowledgeBase
from app.entities.knowledge_graph import (
    GRAPH_CLAIM_REJECTED,
    GRAPH_CLAIM_SUPERSEDED,
    GRAPH_ENTITY_ACTIVE,
    GRAPH_ENTITY_RETIRED,
    GRAPH_EVIDENCE_ACTIVE,
    GRAPH_EVIDENCE_DELETED,
    GRAPH_REVISION_BUILDING,
    GRAPH_REVISION_PUBLISHED,
    GRAPH_REVIEW_RESOLVED,
    GRAPH_SCHEMA_ACTIVE,
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
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.shareddomain.knowledge_graph.schema import GraphSchemaDefinition

RECORD_KINDS = {"entity", "alias", "mention", "claim", "evidence", "review"}
OPERATIONS = {"upsert", "retire", "delete"}


class GraphRevisionConflict(RuntimeError):
    pass


async def create_revision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    schema: KnowledgeGraphSchema,
    actor_id: str,
    source_watermark: str,
) -> KnowledgeGraphRevision:
    parent = await graph_repository.get_active_revision(db, knowledge_base)
    return await graph_repository.create_revision(
        db,
        KnowledgeGraphRevision(
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
            revision_no=await graph_repository.next_revision_no(db, knowledge_base),
            schema_id=schema.id,
            parent_revision_id=parent.id if parent else None,
            status=GRAPH_REVISION_BUILDING,
            source_watermark=source_watermark,
            created_by_user_id=actor_id,
            started_at=utc_now(),
        ),
    )


async def stage_revision_change(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    *,
    record_kind: str,
    record_key: str,
    operation: str,
    before_json: dict[str, Any] | None,
    after_json: dict[str, Any] | None,
) -> KnowledgeGraphRevisionChange:
    if revision.status != GRAPH_REVISION_BUILDING:
        raise ValueError("Only building graph revisions can be changed.")
    if record_kind not in RECORD_KINDS or operation not in OPERATIONS:
        raise ValueError("Unknown graph revision record kind or operation.")
    if not record_key:
        raise ValueError("Graph revision record key is required.")
    existing = await graph_repository.get_revision_change(
        db,
        revision,
        record_kind,
        record_key,
    )
    if existing is not None:
        existing.after_json = (
            {**(existing.after_json or {}), **(after_json or {})}
            if existing.operation == operation == "upsert"
            else after_json
        )
        existing.operation = operation
        return await graph_repository.save_revision_change(db, existing)
    return await graph_repository.create_revision_change(
        db,
        KnowledgeGraphRevisionChange(
            workspace_id=revision.workspace_id,
            knowledge_base_id=revision.knowledge_base_id,
            revision_id=revision.id,
            sequence_no=await graph_repository.next_revision_change_sequence(
                db, revision
            ),
            record_kind=record_kind,
            record_key=record_key,
            operation=operation,
            before_json=before_json,
            after_json=after_json,
        ),
    )


def _upsert_values(
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
    existing: Any | None,
    *,
    versioned: bool = True,
) -> dict[str, Any]:
    if change.after_json is None:
        raise ValueError("Graph upsert change requires after_json.")
    values = asdict(existing) if existing is not None else {}
    values.update(change.after_json)
    values["id"] = (
        existing.id if existing is not None else values.get("id") or change.record_key
    )
    values["workspace_id"] = revision.workspace_id
    values["knowledge_base_id"] = revision.knowledge_base_id
    values["updated_at"] = utc_now()
    if versioned:
        values["created_revision_id"] = (
            existing.created_revision_id if existing is not None else revision.id
        )
        values["last_published_revision_id"] = revision.id
        values["retired_revision_id"] = None
    return values


async def _upsert_entity(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    existing = await graph_repository.get_entity(db, revision, change.record_key)
    values = _upsert_values(revision, change, existing)
    values["state"] = GRAPH_ENTITY_ACTIVE
    await graph_repository.save_entity(db, KnowledgeGraphEntity(**values))


async def _upsert_alias(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    existing = await graph_repository.get_alias(db, revision, change.record_key)
    await graph_repository.save_alias(
        db,
        KnowledgeGraphAlias(**_upsert_values(revision, change, existing)),
    )


async def _upsert_mention(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    existing = await graph_repository.get_mention(db, revision, change.record_key)
    await graph_repository.save_mention(
        db,
        KnowledgeGraphMention(**_upsert_values(revision, change, existing)),
    )


async def _upsert_claim(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    existing = await graph_repository.get_claim(db, revision, change.record_key)
    values = _upsert_values(revision, change, existing)
    values.setdefault("fingerprint", change.record_key)
    for field_name in ("valid_from", "valid_to"):
        value = values.get(field_name)
        if isinstance(value, str):
            values[field_name] = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
    if (
        existing is not None
        and existing.status == GRAPH_CLAIM_REJECTED
        and values.get("source_kind") != "human"
    ):
        values["status"] = GRAPH_CLAIM_REJECTED
    await graph_repository.save_claim(db, KnowledgeGraphClaim(**values))


async def _upsert_evidence(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    existing = await graph_repository.get_evidence(db, revision, change.record_key)
    values = _upsert_values(revision, change, existing)
    values["evidence_state"] = GRAPH_EVIDENCE_ACTIVE
    evidence = await graph_repository.save_evidence(
        db,
        KnowledgeGraphClaimEvidence(**values),
    )
    await _refresh_claim_support_count(db, revision, evidence.claim_id)


async def _refresh_claim_support_count(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    claim_id: str,
) -> None:
    claim = await graph_repository.get_claim(db, revision, claim_id)
    if claim is None:
        return
    claim.support_count = await graph_repository.count_active_claim_evidence(
        db,
        revision,
        claim_id,
    )
    claim.updated_at = utc_now()
    await graph_repository.save_claim(db, claim)


async def _upsert_review(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    existing = await graph_repository.get_review_item(db, revision, change.record_key)
    values = _upsert_values(revision, change, existing, versioned=False)
    values["revision_id"] = revision.id
    await graph_repository.save_review_item(db, KnowledgeGraphReviewItem(**values))


async def _retire_revision_change(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    now = utc_now()
    if change.record_kind == "entity":
        entity = await graph_repository.get_entity(db, revision, change.record_key)
        if entity is not None:
            entity.state = GRAPH_ENTITY_RETIRED
            entity.last_published_revision_id = revision.id
            entity.retired_revision_id = revision.id
            entity.updated_at = now
            await graph_repository.save_entity(db, entity)
    elif change.record_kind == "alias":
        alias = await graph_repository.get_alias(db, revision, change.record_key)
        if alias is not None:
            alias.last_published_revision_id = revision.id
            alias.retired_revision_id = revision.id
            alias.updated_at = now
            await graph_repository.save_alias(db, alias)
    elif change.record_kind == "mention":
        mention = await graph_repository.get_mention(db, revision, change.record_key)
        if mention is not None:
            mention.last_published_revision_id = revision.id
            mention.retired_revision_id = revision.id
            mention.updated_at = now
            await graph_repository.save_mention(db, mention)
    elif change.record_kind == "claim":
        claim = await graph_repository.get_claim(db, revision, change.record_key)
        if claim is not None:
            claim.status = GRAPH_CLAIM_SUPERSEDED
            claim.last_published_revision_id = revision.id
            claim.retired_revision_id = revision.id
            claim.updated_at = now
            await graph_repository.save_claim(db, claim)
    elif change.record_kind == "evidence":
        evidence = await graph_repository.get_evidence(db, revision, change.record_key)
        if evidence is not None:
            evidence.evidence_state = GRAPH_EVIDENCE_DELETED
            evidence.last_published_revision_id = revision.id
            evidence.retired_revision_id = revision.id
            evidence.updated_at = now
            await graph_repository.save_evidence(db, evidence)
            await _refresh_claim_support_count(db, revision, evidence.claim_id)
    else:
        review = await graph_repository.get_review_item(db, revision, change.record_key)
        if review is not None:
            review.status = GRAPH_REVIEW_RESOLVED
            review.updated_at = now
            await graph_repository.save_review_item(db, review)


async def _delete_revision_change(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    if change.record_kind == "entity":
        await graph_repository.delete_entity(db, revision, change.record_key)
    elif change.record_kind == "alias":
        await graph_repository.delete_alias(db, revision, change.record_key)
    elif change.record_kind == "mention":
        await graph_repository.delete_mention(db, revision, change.record_key)
    elif change.record_kind == "claim":
        await graph_repository.delete_claim(db, revision, change.record_key)
    elif change.record_kind == "evidence":
        evidence = await graph_repository.get_evidence(db, revision, change.record_key)
        await graph_repository.delete_evidence(db, revision, change.record_key)
        if evidence is not None:
            await _refresh_claim_support_count(db, revision, evidence.claim_id)
    else:
        await graph_repository.delete_review_item(db, revision, change.record_key)


async def _apply_revision_change(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    change: KnowledgeGraphRevisionChange,
) -> None:
    if change.operation == "retire":
        await _retire_revision_change(db, revision, change)
    elif change.operation == "delete":
        await _delete_revision_change(db, revision, change)
    elif change.record_kind == "entity":
        await _upsert_entity(db, revision, change)
    elif change.record_kind == "alias":
        await _upsert_alias(db, revision, change)
    elif change.record_kind == "mention":
        await _upsert_mention(db, revision, change)
    elif change.record_kind == "claim":
        await _upsert_claim(db, revision, change)
    elif change.record_kind == "evidence":
        await _upsert_evidence(db, revision, change)
    else:
        await _upsert_review(db, revision, change)
    change.applied_at = utc_now()
    await graph_repository.save_revision_change(db, change)


async def publish_revision(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    revision: KnowledgeGraphRevision,
) -> KnowledgeGraphRevision:
    try:
        locked_base = await graph_repository.lock_knowledge_base_graph(
            db, knowledge_base.id
        )
        if locked_base is None or locked_base.workspace_id != knowledge_base.workspace_id:
            raise GraphRevisionConflict("Graph knowledge base disappeared.")
        locked_revision = await graph_repository.lock_revision(
            db,
            locked_base,
            revision.id,
        )
        if locked_revision is None or locked_revision.status != GRAPH_REVISION_BUILDING:
            raise GraphRevisionConflict("Graph revision is not publishable.")
        if locked_base.active_graph_revision_id != locked_revision.parent_revision_id:
            raise GraphRevisionConflict("Graph revision parent changed.")

        for change in await graph_repository.list_revision_changes(
            db, locked_revision
        ):
            await _apply_revision_change(db, locked_revision, change)

        await graph_repository.retire_active_revision(
            db,
            locked_base,
            locked_base.active_graph_revision_id,
        )
        schema = await graph_repository.lock_graph_schema(
            db,
            locked_base,
            locked_revision.schema_id,
        )
        if schema is None:
            raise GraphRevisionConflict("Graph revision schema disappeared.")
        GraphSchemaDefinition.model_validate(schema.schema_json)
        await graph_repository.retire_active_schema(db, locked_base)
        schema.status = GRAPH_SCHEMA_ACTIVE
        await graph_repository.save_graph_schema(db, schema)

        locked_revision.status = GRAPH_REVISION_PUBLISHED
        locked_revision.published_at = utc_now()
        published = await graph_repository.save_revision(db, locked_revision)
        locked_base.active_graph_schema_id = locked_revision.schema_id
        locked_base.active_graph_revision_id = locked_revision.id
        await graph_repository.save_knowledge_base_graph_fields(db, locked_base)
        await db.commit()
        return published
    except Exception:
        await db.rollback()
        raise

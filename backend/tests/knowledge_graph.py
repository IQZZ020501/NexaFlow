"""Persistent Evidence Graph RAG regression suite.

Run from backend/: uv run python -m tests.knowledge_graph
"""

import asyncio
from unittest.mock import patch

import tests.support  # noqa: F401
from sqlalchemy import select, text

from app.infrastructure.base import Base
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.infrastructure.session import get_engine, get_session_factory
from app.entities.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
)
from app.entities.knowledge_graph import (
    KnowledgeGraphAlias as GraphAliasRecord,
    KnowledgeGraphEntity as GraphEntityRecord,
)
from app.entities.user import User
from app.entities.workspace import Workspace
from app.shareddomain.knowledge_graph.schema import (
    GraphSchemaDefinition,
    default_policy_graph_schema,
    graph_schema_hash,
)
from app.shareddomain.knowledge_graph import revisions as graph_revisions
from app.shareddomain.knowledge_graph.revisions import GraphRevisionConflict
from app.shareddomain.knowledge_graph.resolution import claim_fingerprint
from app.shareddomain.knowledge_graph.services import create_graph_schema
from app.shareddomain.knowledge_graph.models import (
    KnowledgeGraphClaim,
    KnowledgeGraphEntity,
)


async def test_graph_database_constraints() -> None:
    async with get_engine().begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as db:
        entity = await db.scalar(select(KnowledgeGraphEntity).limit(1))
        claim = await db.scalar(select(KnowledgeGraphClaim).limit(1))
        assert entity is None
        assert claim is None


async def test_versioned_graph_schemas() -> None:
    async with get_session_factory()() as db:
        actor = await user_repository.create_user(
            db,
            User(
                id="graph-user",
                username="graph-user",
                email="graph-user@example.com",
                name="Graph User",
                password_hash="not-used",
            ),
        )
        workspace = await workspace_repository.create_workspace(
            db,
            Workspace(id="graph-workspace", name="Graph", slug="graph"),
        )
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-kb",
                workspace_id=workspace.id,
                name="Graph KB",
                created_by_user_id=actor.id,
            ),
        )

        definition = default_policy_graph_schema()
        first = await create_graph_schema(db, knowledge_base, definition, actor)
        duplicate = await create_graph_schema(db, knowledge_base, definition, actor)
        changed_payload = definition.model_dump(mode="json")
        changed_payload["entity_types"].append({"name": "Topic", "properties": []})
        second = await create_graph_schema(
            db,
            knowledge_base,
            GraphSchemaDefinition.model_validate(changed_payload),
            actor,
        )

        assert first.id == duplicate.id
        assert first.version == 1
        assert second.version == 2
        await db.commit()


async def _graph_fixture(db):
    knowledge_base = await knowledge_repository.get_knowledge_base_by_id(db, "graph-kb")
    actor = await user_repository.get_user_by_id(db, "graph-user")
    assert knowledge_base is not None
    assert actor is not None
    schema = await graph_repository.get_schema_by_hash(
        db,
        knowledge_base,
        graph_schema_hash(default_policy_graph_schema()),
    )
    assert schema is not None
    return knowledge_base, actor, schema


async def _stage_entity(db, revision, entity_id: str, name: str):
    return await graph_revisions.stage_revision_change(
        db,
        revision,
        record_kind="entity",
        record_key=entity_id,
        operation="upsert",
        before_json=None,
        after_json={
            "id": entity_id,
            "entity_type": "Document",
            "canonical_name": name,
            "normalized_name": name,
        },
    )


async def test_revision_publish_is_atomic() -> None:
    async with get_session_factory()() as db:
        knowledge_base, actor, schema = await _graph_fixture(db)
        first = await graph_revisions.create_revision(
            db,
            knowledge_base,
            schema,
            actor.id,
            "watermark-1",
        )
        initial = await _stage_entity(db, first, "entity-a", "制度草稿")
        final = await _stage_entity(db, first, "entity-a", "制度 A")
        assert final.id == initial.id
        assert final.sequence_no == initial.sequence_no == 0
        assert final.before_json is None
        assert final.after_json["canonical_name"] == "制度 A"
        await db.commit()

    async with get_session_factory()() as db:
        knowledge_base, _, _ = await _graph_fixture(db)
        first = await graph_repository.get_revision(db, knowledge_base, first.id)
        assert first is not None
        published = await graph_revisions.publish_revision(db, knowledge_base, first)
        assert published.status == "published"

    async with get_session_factory()() as db:
        knowledge_base, actor, schema = await _graph_fixture(db)
        second = await graph_revisions.create_revision(
            db,
            knowledge_base,
            schema,
            actor.id,
            "watermark-2",
        )
        await _stage_entity(db, second, "entity-b", "制度 B")
        await _stage_entity(db, second, "entity-failure", "失败记录")
        await db.commit()

    original_apply = graph_revisions._apply_revision_change

    async def fail_after_first_change(db, revision, change):
        if change.record_key == "entity-failure":
            raise RuntimeError("forced publish failure")
        await original_apply(db, revision, change)

    async with get_session_factory()() as db:
        knowledge_base, _, _ = await _graph_fixture(db)
        second = await graph_repository.get_revision(db, knowledge_base, second.id)
        assert second is not None
        with patch.object(
            graph_revisions,
            "_apply_revision_change",
            fail_after_first_change,
        ):
            try:
                await graph_revisions.publish_revision(db, knowledge_base, second)
            except RuntimeError:
                pass
            else:
                raise AssertionError("forced publish failure must roll back")

    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db, "graph-kb"
        )
        assert knowledge_base is not None
        assert knowledge_base.active_graph_revision_id == first.id
        names = await db.scalars(
            select(KnowledgeGraphEntity.canonical_name).where(
                KnowledgeGraphEntity.knowledge_base_id == knowledge_base.id,
                KnowledgeGraphEntity.state == "active",
            )
        )
        assert list(names.all()) == ["制度 A"]


async def test_entity_identity_candidates_are_scoped_and_ambiguous() -> None:
    async with get_session_factory()() as db:
        knowledge_base, actor, schema = await _graph_fixture(db)
        revision = await graph_repository.get_active_revision(db, knowledge_base)
        assert revision is not None
        records = [
            GraphEntityRecord(
                id="identity-external",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                entity_type="Account",
                canonical_name="账户 A",
                normalized_name="账户 a",
                external_key="acct-1",
                created_revision_id=revision.id,
                last_published_revision_id=revision.id,
            ),
            GraphEntityRecord(
                id="identity-name-1",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                entity_type="Person",
                canonical_name="张三",
                normalized_name="张三",
                created_revision_id=revision.id,
                last_published_revision_id=revision.id,
            ),
            GraphEntityRecord(
                id="identity-name-2",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                entity_type="Person",
                canonical_name="张三",
                normalized_name="张三",
                created_revision_id=revision.id,
                last_published_revision_id=revision.id,
            ),
        ]
        for record in records:
            await graph_repository.create_entity(db, record)
        await graph_repository.create_alias(
            db,
            GraphAliasRecord(
                id="identity-human-alias",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                entity_id="identity-external",
                alias="HR",
                normalized_alias="hr",
                source="human",
                created_revision_id=revision.id,
                last_published_revision_id=revision.id,
            ),
        )

        other_knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-other-kb",
                workspace_id=knowledge_base.workspace_id,
                name="Other Graph KB",
                created_by_user_id=actor.id,
            ),
        )
        other_schema = await create_graph_schema(
            db,
            other_knowledge_base,
            GraphSchemaDefinition.model_validate(schema.schema_json),
            actor,
        )
        other_revision = await graph_revisions.create_revision(
            db,
            other_knowledge_base,
            other_schema,
            actor.id,
            "identity-other",
        )
        await graph_repository.create_entity(
            db,
            GraphEntityRecord(
                id="identity-other",
                workspace_id=other_knowledge_base.workspace_id,
                knowledge_base_id=other_knowledge_base.id,
                entity_type="Account",
                canonical_name="账户 A",
                normalized_name="账户 a",
                external_key="acct-1",
                created_revision_id=other_revision.id,
                last_published_revision_id=other_revision.id,
            ),
        )
        await db.commit()

    async with get_session_factory()() as db:
        knowledge_base, _, _ = await _graph_fixture(db)
        external = await graph_repository.list_entity_identity_candidates(
            db,
            knowledge_base,
            "Account",
            "acct-1",
            {"账户 a"},
        )
        ambiguous = await graph_repository.list_entity_identity_candidates(
            db,
            knowledge_base,
            "Person",
            None,
            {"张三"},
        )
        alias_candidates = await graph_repository.list_entity_identity_candidates(
            db,
            knowledge_base,
            "Account",
            None,
            {"hr"},
        )
        human_alias_ids = await graph_repository.list_human_alias_entity_ids(
            db,
            knowledge_base,
            "Account",
            {"hr"},
        )
        assert [item.id for item in external] == ["identity-external"]
        assert {item.id for item in ambiguous} == {
            "identity-name-1",
            "identity-name-2",
        }
        assert [item.id for item in alias_candidates] == ["identity-external"]
        assert human_alias_ids == {"identity-external"}


async def test_stale_revision_cannot_overwrite_newer_graph() -> None:
    async with get_session_factory()() as db:
        knowledge_base, actor, schema = await _graph_fixture(db)
        stale = await graph_revisions.create_revision(
            db, knowledge_base, schema, actor.id, "watermark-stale"
        )
        winner = await graph_revisions.create_revision(
            db, knowledge_base, schema, actor.id, "watermark-winner"
        )
        await db.commit()

    async with get_session_factory()() as db:
        knowledge_base, _, _ = await _graph_fixture(db)
        winner = await graph_repository.get_revision(db, knowledge_base, winner.id)
        assert winner is not None
        await graph_revisions.publish_revision(db, knowledge_base, winner)

    async with get_session_factory()() as db:
        knowledge_base, _, _ = await _graph_fixture(db)
        stale = await graph_repository.get_revision(db, knowledge_base, stale.id)
        assert stale is not None
        try:
            await graph_revisions.publish_revision(db, knowledge_base, stale)
        except GraphRevisionConflict:
            pass
        else:
            raise AssertionError("stale revision must not publish")


async def test_claim_fingerprint_dedupes_without_reactivating_rejection() -> None:
    fingerprint = claim_fingerprint(
        "entity-a",
        "has_value",
        None,
        "value-a",
        None,
        None,
    )
    async with get_session_factory()() as db:
        knowledge_base, actor, schema = await _graph_fixture(db)
        await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-evidence-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="evidence.md",
                content_type="text/markdown",
                size_bytes=7,
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.save_knowledge_document_chunk(
            db,
            KnowledgeDocumentChunk(
                id="graph-evidence-chunk",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id="graph-evidence-doc",
                content="value-a",
                search_text="value-a",
                char_count=7,
                token_count=2,
                status="indexed",
            ),
        )
        rejected_revision = await graph_revisions.create_revision(
            db,
            knowledge_base,
            schema,
            actor.id,
            "claim-rejected",
        )
        await graph_revisions.stage_revision_change(
            db,
            rejected_revision,
            record_kind="claim",
            record_key=fingerprint,
            operation="upsert",
            before_json=None,
            after_json={
                "id": "claim-original",
                "subject_entity_id": "entity-a",
                "predicate": "has_value",
                "object_value_json": "value-a",
                "status": "rejected",
                "source_kind": "explicit_text",
                "fingerprint": fingerprint,
            },
        )
        await db.commit()

    async with get_session_factory()() as db:
        knowledge_base, _, _ = await _graph_fixture(db)
        revision = await graph_repository.get_revision(
            db,
            knowledge_base,
            rejected_revision.id,
        )
        assert revision is not None
        await graph_revisions.publish_revision(db, knowledge_base, revision)

    async with get_session_factory()() as db:
        knowledge_base, actor, schema = await _graph_fixture(db)
        retry_revision = await graph_revisions.create_revision(
            db,
            knowledge_base,
            schema,
            actor.id,
            "claim-retry",
        )
        await graph_revisions.stage_revision_change(
            db,
            retry_revision,
            record_kind="claim",
            record_key=fingerprint,
            operation="upsert",
            before_json=None,
            after_json={
                "id": "claim-duplicate",
                "subject_entity_id": "entity-a",
                "predicate": "has_value",
                "object_value_json": "value-a",
                "status": "active",
                "source_kind": "explicit_text",
                "fingerprint": fingerprint,
            },
        )
        await graph_revisions.stage_revision_change(
            db,
            retry_revision,
            record_kind="evidence",
            record_key="claim-original-evidence",
            operation="upsert",
            before_json=None,
            after_json={
                "claim_id": "claim-original",
                "document_id": "graph-evidence-doc",
                "chunk_id": "graph-evidence-chunk",
                "quote": "value-a",
                "start_offset": 0,
                "end_offset": 7,
                "extractor_type": "llm",
            },
        )
        await db.commit()

    async with get_session_factory()() as db:
        knowledge_base, _, _ = await _graph_fixture(db)
        revision = await graph_repository.get_revision(
            db,
            knowledge_base,
            retry_revision.id,
        )
        assert revision is not None
        await graph_revisions.publish_revision(db, knowledge_base, revision)

    async with get_session_factory()() as db:
        claims = list(
            (
                await db.scalars(
                    select(KnowledgeGraphClaim).where(
                        KnowledgeGraphClaim.fingerprint == fingerprint
                    )
                )
            ).all()
        )
        assert len(claims) == 1
        assert claims[0].id == "claim-original"
        assert claims[0].status == "rejected"
        assert claims[0].support_count == 1


async def main() -> None:
    await test_graph_database_constraints()
    await test_versioned_graph_schemas()
    await test_revision_publish_is_atomic()
    await test_entity_identity_candidates_are_scoped_and_ambiguous()
    await test_stale_revision_cannot_overwrite_newer_graph()
    await test_claim_fingerprint_dedupes_without_reactivating_rejection()
    print("OK: knowledge_graph")


if __name__ == "__main__":
    asyncio.run(main())

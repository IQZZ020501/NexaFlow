"""Persistent Evidence Graph RAG regression suite.

Run from backend/: uv run python -m tests.knowledge_graph
"""

import asyncio
from datetime import timedelta
import json
from types import SimpleNamespace
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
    KnowledgeTask,
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
    KnowledgeGraphClaimEvidence,
    KnowledgeGraphEntity,
    KnowledgeGraphRevision,
)
from app.infrastructure.model_utils import utc_now
from app.shareddomain.knowledge.orchestration import enqueue_graph_sync
from app.application import knowledge_graph_build
from app.shareddomain.knowledge import task_runner as knowledge_task_runner


def test_graph_profile_collection_is_knowledge_base_scoped() -> None:
    from app.capabilities.rag.vector_store import graph_profile_collection_name

    assert graph_profile_collection_name("kb-1") == "kb_kb1_graph"


def test_graph_profile_vectors_use_an_isolated_collection() -> None:
    from app.capabilities.rag import vector_store

    class Embeddings:
        def embed_documents(self, texts):
            assert texts == ["# Entity A"]
            return [[1.0, 0.0]]

        def embed_query(self, text):
            assert text == "Entity A"
            return [1.0, 0.0]

    settings = tests.support.settings()
    vector_store._build_qdrant_client.cache_clear()
    with patch.object(
        vector_store,
        "build_registered_embeddings",
        lambda *_args: Embeddings(),
    ):
        vector_store.upsert_graph_profile_vectors(
            settings,
            "profile-kb",
            "profile-workspace",
            object(),
            [
                vector_store.GraphProfileVector(
                    entity_id="00000000-0000-0000-0000-000000000101",
                    profile_hash="profile-hash",
                    content="# Entity A",
                )
            ],
        )
        client = vector_store._client(settings)
        graph_collection = vector_store.graph_profile_collection_name("profile-kb")
        assert client.collection_exists(graph_collection)
        assert not client.collection_exists(
            vector_store.vector_collection_name("profile-kb")
        )
        hits = vector_store.query_graph_profile_vectors(
            settings,
            "profile-kb",
            "profile-workspace",
            object(),
            "Entity A",
            3,
        )
        assert hits == [
            vector_store.GraphProfileVectorHit(
                entity_id="00000000-0000-0000-0000-000000000101",
                profile_hash="profile-hash",
                distance=0.0,
            )
        ]
        vector_store.delete_graph_profile_vectors(
            settings,
            "profile-kb",
            ["00000000-0000-0000-0000-000000000101"],
        )
        assert client.retrieve(
            graph_collection,
            ids=["00000000-0000-0000-0000-000000000101"],
        ) == []
        vector_store.delete_graph_profile_collection(settings, "profile-kb")
        assert not client.collection_exists(graph_collection)
        client.close()
    vector_store._build_qdrant_client.cache_clear()


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


async def test_graph_sync_coalesces_behind_running_build() -> None:
    async with get_session_factory()() as db:
        knowledge_base, actor, _ = await _graph_fixture(db)
        knowledge_base.graph_enabled = True
        await knowledge_repository.save_knowledge_base(db, knowledge_base)
        for index in range(1, 4):
            document_id = f"graph-task-doc-{index}"
            await knowledge_repository.create_knowledge_document(
                db,
                KnowledgeDocument(
                    id=document_id,
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    filename=f"task-{index}.md",
                    content_type="text/markdown",
                    size_bytes=10,
                    status="indexed",
                    created_by_user_id=actor.id,
                ),
            )
            await knowledge_repository.save_knowledge_document_chunk(
                db,
                KnowledgeDocumentChunk(
                    id=f"graph-task-chunk-{index}",
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    document_id=document_id,
                    content=f"document {index}",
                    search_text=f"document {index}",
                    char_count=10,
                    token_count=2,
                    status="indexed",
                ),
            )
        running = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-running-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="running",
                attempts=1,
                options={"changed_document_ids": ["graph-task-doc-1"]},
                created_by_user_id=actor.id,
                started_at=utc_now() - timedelta(seconds=10),
                lease_expires_at=utc_now() + timedelta(minutes=5),
                worker_task_id="graph-worker",
                created_at=utc_now() - timedelta(minutes=1),
            ),
        )
        await db.commit()

        follower_a = await enqueue_graph_sync(
            db,
            knowledge_base,
            actor,
            ["graph-task-doc-2"],
        )
        follower_b = await enqueue_graph_sync(
            db,
            knowledge_base,
            actor,
            ["graph-task-doc-3"],
        )
        assert follower_a.id == follower_b.id
        assert follower_a.id != running.id
        assert follower_b.options["changed_document_ids"] == [
            "graph-task-doc-2",
            "graph-task-doc-3",
        ]

        claimed = await knowledge_repository.claim_knowledge_task(
            db,
            follower_b.id,
            utc_now(),
            utc_now() + timedelta(minutes=5),
            "follower-worker",
        )
        assert claimed is False
        running.status = "succeeded"
        running.lease_expires_at = None
        running.worker_task_id = None
        await knowledge_repository.save_knowledge_task(db, running)
        await db.commit()
        claimed = await knowledge_repository.claim_knowledge_task(
            db,
            follower_b.id,
            utc_now(),
            utc_now() + timedelta(minutes=5),
            "follower-worker",
        )
        assert claimed is True
        await db.rollback()


async def test_structured_graph_build_publishes_evidence_and_profiles() -> None:
    content = json.dumps(
        {
            "subject": {
                "entity_type": "Document",
                "canonical_name": "制度 A",
                "external_key": "doc-a",
            },
            "predicate": "defines",
            "object": {
                "entity_type": "Concept",
                "canonical_name": "术语 A",
                "external_key": "concept-a",
            },
            "evidence": "制度 A 定义术语 A",
        },
        ensure_ascii=False,
    )
    async with get_session_factory()() as db:
        knowledge_base, actor, _ = await _graph_fixture(db)
        knowledge_base.graph_enabled = True
        await knowledge_repository.save_knowledge_base(db, knowledge_base)
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="structured-graph-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="graph.jsonl",
                content_type="application/jsonl",
                size_bytes=len(content.encode("utf-8")),
                meta={"import_mode": "graph"},
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.save_knowledge_document_chunk(
            db,
            KnowledgeDocumentChunk(
                id="structured-graph-chunk",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                content=content,
                kind="graph_record",
                search_text="制度 A defines 术语 A",
                char_count=len(content),
                token_count=10,
                status="indexed",
            ),
        )
        task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="structured-graph-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="running",
                attempts=1,
                total_items=1,
                options={
                    "changed_document_ids": [document.id],
                    "trusted_structured_import": True,
                },
                created_by_user_id=actor.id,
                worker_task_id="structured-worker",
            ),
        )
        await db.commit()

        captured_profiles = []

        async def fake_embedding_model(*_args, **_kwargs):
            return SimpleNamespace(id="embedding-1")

        def capture_profiles(*args):
            captured_profiles.extend(args[-1])

        with (
            patch.object(
                knowledge_graph_build,
                "resolve_embedding_model",
                fake_embedding_model,
            ),
            patch.object(
                knowledge_graph_build,
                "upsert_graph_profile_vectors",
                capture_profiles,
            ),
        ):
            await knowledge_graph_build.run_graph_build_task(
                db,
                task,
                knowledge_base,
                actor,
                tests.support.settings(),
                asyncio.Event(),
            )

    async with get_session_factory()() as db:
        entities = list(
            (
                await db.scalars(
                    select(KnowledgeGraphEntity).where(
                        KnowledgeGraphEntity.knowledge_base_id == "graph-kb",
                        KnowledgeGraphEntity.canonical_name.in_(["制度 A", "术语 A"]),
                        KnowledgeGraphEntity.state == "active",
                    )
                )
            ).all()
        )
        claim = await db.scalar(
            select(KnowledgeGraphClaim).where(
                KnowledgeGraphClaim.knowledge_base_id == "graph-kb",
                KnowledgeGraphClaim.predicate == "defines",
                KnowledgeGraphClaim.source_kind == "structured_import",
            )
        )
        assert {item.canonical_name for item in entities} == {"制度 A", "术语 A"}
        assert claim is not None
        assert claim.status == "active"
        assert claim.support_count == 1
        evidence = await db.scalar(
            select(KnowledgeGraphClaimEvidence).where(
                KnowledgeGraphClaimEvidence.claim_id == claim.id
            )
        )
        assert evidence is not None
        assert evidence.quote == "制度 A 定义术语 A"
        assert {item.entity_id for item in captured_profiles} == {
            item.id for item in entities
        }


async def test_index_success_queues_graph_sync_when_enabled() -> None:
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-chain-kb",
                workspace_id="graph-workspace",
                name="Graph Chain KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-chain-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="chain.md",
                content_type="text/markdown",
                size_bytes=7,
                status="parsed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.save_knowledge_document_chunk(
            db,
            KnowledgeDocumentChunk(
                id="graph-chain-chunk",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                content="content",
                search_text="content",
                char_count=7,
                token_count=1,
                status="preview",
            ),
        )
        index_task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-chain-index-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                task_type="index",
                status="queued",
                total_items=1,
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()

    async def fake_embedding_model(*_args, **_kwargs):
        return SimpleNamespace(id="embedding-1")

    async def skip_embedding_model_write(*_args, **_kwargs):
        return None

    dispatched: list[str] = []

    async def capture_dispatch(task_id, _settings):
        dispatched.append(task_id)

    with (
        patch.object(
            knowledge_task_runner,
            "resolve_embedding_model",
            fake_embedding_model,
        ),
        patch.object(
            knowledge_task_runner.knowledge_base_repository,
            "set_knowledge_base_embedding_model_id",
            skip_embedding_model_write,
        ),
        patch.object(knowledge_task_runner, "upsert_vectors", lambda *_args: None),
    ):
        await knowledge_task_runner.run_knowledge_task(
            index_task.id,
            tests.support.settings(),
            capture_dispatch,
        )

    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-chain-kb",
        )
        assert knowledge_base is not None
        tasks = await knowledge_repository.list_knowledge_tasks(db, knowledge_base)
        graph_tasks = [item for item in tasks if item.task_type == "graph_sync"]
        assert len(graph_tasks) == 1
        assert graph_tasks[0].options["changed_document_ids"] == ["graph-chain-doc"]
        assert dispatched == [graph_tasks[0].id]


async def test_failed_profile_write_keeps_revision_unpublished_for_repair() -> None:
    content = json.dumps(
        {
            "subject": {
                "entity_type": "Document",
                "canonical_name": "制度 F",
            },
            "predicate": "defines",
            "object": {
                "entity_type": "Concept",
                "canonical_name": "术语 F",
            },
            "evidence": "制度 F 定义术语 F",
        },
        ensure_ascii=False,
    )
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-failure-kb",
                workspace_id="graph-workspace",
                name="Graph Failure KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-failure-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="failure.jsonl",
                content_type="application/jsonl",
                size_bytes=len(content.encode("utf-8")),
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.save_knowledge_document_chunk(
            db,
            KnowledgeDocumentChunk(
                id="graph-failure-chunk",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                content=content,
                kind="graph_record",
                search_text="制度 F defines 术语 F",
                char_count=len(content),
                token_count=10,
                status="indexed",
            ),
        )
        task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-failure-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="running",
                attempts=1,
                options={
                    "changed_document_ids": [document.id],
                    "trusted_structured_import": True,
                },
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()

        async def fake_embedding_model(*_args, **_kwargs):
            return SimpleNamespace(id="embedding-failure")

        with (
            patch.object(
                knowledge_graph_build,
                "resolve_embedding_model",
                fake_embedding_model,
            ),
            patch.object(
                knowledge_graph_build,
                "upsert_graph_profile_vectors",
                side_effect=RuntimeError("qdrant unavailable"),
            ),
        ):
            try:
                await knowledge_graph_build.run_graph_build_task(
                    db,
                    task,
                    knowledge_base,
                    actor,
                    tests.support.settings(),
                    asyncio.Event(),
                )
            except RuntimeError as exc:
                assert "qdrant unavailable" in str(exc)
            else:
                raise AssertionError("profile write failure must fail the revision")

    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-failure-kb",
        )
        assert knowledge_base is not None
        assert knowledge_base.active_graph_revision_id is None
        revision = await db.scalar(
            select(KnowledgeGraphRevision).where(
                KnowledgeGraphRevision.knowledge_base_id == knowledge_base.id
            )
        )
        assert revision is not None
        assert revision.status == "failed"
        assert revision.stats_json["profile_repair_pending"] is True
        assert revision.stats_json["profile_repair_entity_ids"]


async def main() -> None:
    test_graph_profile_collection_is_knowledge_base_scoped()
    test_graph_profile_vectors_use_an_isolated_collection()
    await test_graph_database_constraints()
    await test_versioned_graph_schemas()
    await test_revision_publish_is_atomic()
    await test_entity_identity_candidates_are_scoped_and_ambiguous()
    await test_stale_revision_cannot_overwrite_newer_graph()
    await test_claim_fingerprint_dedupes_without_reactivating_rejection()
    await test_graph_sync_coalesces_behind_running_build()
    await test_structured_graph_build_publishes_evidence_and_profiles()
    await test_index_success_queues_graph_sync_when_enabled()
    await test_failed_profile_write_keeps_revision_unpublished_for_repair()
    print("OK: knowledge_graph")


if __name__ == "__main__":
    asyncio.run(main())

"""Persistent Evidence Graph RAG regression suite.

Run from backend/: uv run python -m tests.knowledge_graph
"""

import asyncio
from datetime import timedelta
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import tests.support  # noqa: F401
from fastapi import HTTPException, UploadFile
from sqlalchemy import select, text

from app.infrastructure.base import Base
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.infrastructure.repositories import workspace_governance as governance_repository
from app.infrastructure.session import get_engine, get_session_factory
from app.entities.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeTask,
)
from app.entities.knowledge_graph import (
    KnowledgeGraphAlias as GraphAliasRecord,
    KnowledgeGraphClaim as GraphClaimRecord,
    KnowledgeGraphClaimEvidence as GraphEvidenceRecord,
    KnowledgeGraphEntity as GraphEntityRecord,
    KnowledgeGraphMention as GraphMentionRecord,
    KnowledgeGraphRevision as GraphRevisionRecord,
    KnowledgeGraphReviewItem as GraphReviewRecord,
)
from app.entities.user import User
from app.entities.workspace import Workspace
from app.entities.workspace_governance import WorkspaceGovernance
from app.shareddomain.knowledge_graph.schema import (
    GraphSchemaDefinition,
    default_graph_schema,
    graph_schema_hash,
)
from app.schemas.knowledge import (
    KnowledgeGraphEvaluationExpectation,
    KnowledgeQueryRequest,
)
from app.schemas.knowledge_graph import KnowledgeGraphReviewDecisionRequest
from app.shareddomain.knowledge.evaluation import graph_evaluation_metrics
from app.shareddomain.knowledge_graph import revisions as graph_revisions
from app.shareddomain.knowledge_graph.revisions import GraphRevisionConflict
from app.shareddomain.knowledge_graph.resolution import claim_fingerprint
from app.shareddomain.knowledge_graph.services import create_graph_schema
from app.shareddomain.knowledge_graph import traversal as graph_traversal
from app.shareddomain.knowledge_graph.models import (
    KnowledgeGraphClaim,
    KnowledgeGraphClaimEvidence,
    KnowledgeGraphEntity,
    KnowledgeGraphRevision,
)
from app.shareddomain.audit.models import AuditLog
from app.infrastructure.model_utils import utc_now
from app.shareddomain.knowledge.orchestration import (
    delete_knowledge_task,
    delete_knowledge_tasks,
    enqueue_graph_rebuild,
    enqueue_graph_sync,
    enqueue_index_knowledge_document,
    retry_knowledge_task,
    stop_knowledge_task,
)
from app.application import (
    knowledge_graph,
    knowledge_graph_build,
    knowledge_graph_maintenance,
)
from app.application import knowledge_retrieval as knowledge_retrieval_application
from app.application import knowledge_graph_query as graph_query
from app.shareddomain.knowledge import lifecycle as knowledge_lifecycle
from app.shareddomain.knowledge import cleanup as knowledge_cleanup
from app.shareddomain.knowledge import task_runner as knowledge_task_runner


GRAPH_IMPORT_RECORD = {
    "subject": {
        "entity_type": "Document",
        "canonical_name": "制度 A",
        "external_key": "policy-a",
    },
    "predicate": "defines",
    "object": {
        "entity_type": "Concept",
        "canonical_name": "术语 A",
        "external_key": "term-a",
    },
    "evidence": "制度 A 定义术语 A。",
}

BANK_RECORDS = [
    {
        "subject": ("account-a", "Account", "账户 A"),
        "predicate": "uses_phone",
        "object": ("phone-p", "Phone", "手机号 P"),
        "evidence": "账户 A 和账户 B 共用同一个手机号 P。",
    },
    {
        "subject": ("account-b", "Account", "账户 B"),
        "predicate": "uses_phone",
        "object": ("phone-p", "Phone", "手机号 P"),
        "evidence": "账户 A 和账户 B 共用同一个手机号 P。",
    },
    {
        "subject": ("account-b", "Account", "账户 B"),
        "predicate": "logged_in_on",
        "object": ("device-d", "Device", "设备 D"),
        "evidence": "账户 B 和账户 C 在同一台设备 D 登录过。",
    },
    {
        "subject": ("account-c", "Account", "账户 C"),
        "predicate": "logged_in_on",
        "object": ("device-d", "Device", "设备 D"),
        "evidence": "账户 B 和账户 C 在同一台设备 D 登录过。",
    },
    {
        "subject": ("account-c", "Account", "账户 C"),
        "predicate": "legal_representative_of",
        "object": ("company-x", "Organization", "公司 X"),
        "evidence": "账户 C 是公司 X 的法定代表人。",
    },
]

POLICY_RECORDS = [
    {
        "subject": ("policy-a", "Document", "制度 A"),
        "predicate": "defines",
        "object": ("approval", "Clause", "离职审批"),
        "evidence": "制度 A 定义离职审批。",
        "document": "policy-a.md",
    },
    {
        "subject": ("approval", "Clause", "离职审批"),
        "predicate": "requires",
        "object": ("process", "Process", "离职流程"),
        "evidence": "离职审批要求执行离职流程。",
        "document": "policy-a.md",
    },
    {
        "subject": ("hr", "Department", "人力资源部"),
        "predicate": "responsible_for",
        "object": ("process", "Process", "离职流程"),
        "evidence": "人力资源部负责离职流程。",
        "document": "policy-a.md",
    },
    {
        "subject": ("policy-b", "Document", "制度 B"),
        "predicate": "references",
        "object": ("policy-a", "Document", "制度 A"),
        "evidence": "制度 B references 制度 A",
        "document": "policy-b.md",
    },
]


def test_graph_import_parser_is_atomic_and_bounded() -> None:
    content = (
        json.dumps(GRAPH_IMPORT_RECORD, ensure_ascii=False)
        + "\n"
        + json.dumps(
            {
                **GRAPH_IMPORT_RECORD,
                "subject": {
                    **GRAPH_IMPORT_RECORD["subject"],
                    "canonical_name": "制度 B",
                    "external_key": "policy-b",
                },
            },
            ensure_ascii=False,
        )
    ).encode()
    records = knowledge_graph.parse_graph_import_records("records.jsonl", content)
    assert [item.subject.canonical_name for item in records] == ["制度 A", "制度 B"]

    invalid = content + b"\n{}"
    try:
        knowledge_graph.parse_graph_import_records("records.jsonl", invalid)
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("one invalid record must reject the entire import")

    try:
        knowledge_graph.parse_graph_import_records("records.txt", content)
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("unsupported graph import extensions must fail")

    try:
        knowledge_graph.parse_graph_import_records(
            "records.json",
            b"x" * (knowledge_graph.MAX_GRAPH_IMPORT_BYTES + 1),
        )
    except HTTPException as exc:
        assert exc.status_code == 413
    else:
        raise AssertionError("oversized graph imports must fail")


def test_graph_source_batches_keep_structured_and_text_chunks_separate() -> None:
    structured_chunks = [
        KnowledgeDocumentChunk(id=f"graph-{index}", kind="graph_record")
        for index in range(51)
    ]
    chunks = [
        KnowledgeDocumentChunk(id="text-1", kind="document"),
        KnowledgeDocumentChunk(id="text-1b", kind="document"),
        *structured_chunks,
        KnowledgeDocumentChunk(id="text-2", kind="document"),
    ]
    batches = knowledge_graph_build._graph_source_batches(chunks)
    assert [(structured, len(batch)) for structured, batch in batches] == [
        (False, 1),
        (False, 1),
        (True, 50),
        (True, 1),
        (False, 1),
    ]
    assert [item.id for item in batches[2][1]] == [
        item.id for item in structured_chunks[:50]
    ]
    assert [item.id for item in batches[3][1]] == [structured_chunks[50].id]


def test_graph_source_versions_are_stable_and_diffable() -> None:
    document = KnowledgeDocument(
        status="indexed",
        is_active=True,
        meta={
            "document_version": 2,
            "normalized_content_hash": "hash-b",
        },
    )
    assert (
        knowledge_graph_build.graph_document_source_version(document)
        == "2:hash-b:1:indexed"
    )
    assert knowledge_graph_maintenance.diff_graph_source_versions(
        None,
        {"doc-1": "2:hash-b:1:indexed"},
    ) == knowledge_graph_maintenance.GraphSourceChanges(True, ())
    assert knowledge_graph_maintenance.diff_graph_source_versions(
        {
            "doc-1": "1:hash-a:1:indexed",
            "doc-deleted": "1:hash-old:1:indexed",
        },
        {
            "doc-1": "2:hash-b:1:indexed",
            "doc-added": "1:hash-new:1:indexed",
        },
    ) == knowledge_graph_maintenance.GraphSourceChanges(
        False,
        ("doc-1", "doc-added", "doc-deleted"),
    )


async def test_graph_source_reconcile_queues_sync_and_model_rebuild() -> None:
    knowledge_bases = [
        KnowledgeBase(
            id="reconcile-sync-kb",
            workspace_id="reconcile-workspace",
            graph_enabled=True,
            created_by_user_id="graph-user",
        ),
        KnowledgeBase(
            id="reconcile-rebuild-kb",
            workspace_id="reconcile-workspace",
            graph_enabled=True,
            created_by_user_id="graph-user",
        ),
        KnowledgeBase(
            id="reconcile-clean-kb",
            workspace_id="reconcile-workspace",
            graph_enabled=True,
            created_by_user_id="graph-user",
        ),
        KnowledgeBase(
            id="reconcile-empty-kb",
            workspace_id="reconcile-workspace",
            graph_enabled=True,
            created_by_user_id="graph-user",
        ),
        KnowledgeBase(
            id="reconcile-error-kb",
            workspace_id="reconcile-workspace",
            graph_enabled=True,
            created_by_user_id="graph-user",
        ),
    ]
    revisions = {
        "reconcile-sync-kb": SimpleNamespace(
            status="published",
            stats_json={
                "source_versions": {"doc-1": "1:hash-a:1:indexed"},
                "profile_embedding_model_id": "embedding-a",
            }
        ),
        "reconcile-rebuild-kb": SimpleNamespace(
            status="published",
            stats_json={
                "source_versions": {"doc-2": "1:hash-a:1:indexed"},
                "profile_embedding_model_id": "embedding-a",
            }
        ),
        "reconcile-clean-kb": SimpleNamespace(
            status="published",
            stats_json={
                "source_versions": {"doc-3": "1:hash-a:1:indexed"},
                "profile_embedding_model_id": "embedding-a",
            }
        ),
        "reconcile-empty-kb": None,
        "reconcile-error-kb": None,
    }
    current_versions = {
        "reconcile-sync-kb": {"doc-1": "2:hash-b:1:indexed"},
        "reconcile-rebuild-kb": {"doc-2": "1:hash-a:1:indexed"},
        "reconcile-clean-kb": {"doc-3": "1:hash-a:1:indexed"},
        "reconcile-empty-kb": {},
    }
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    sync_calls: list[list[str]] = []
    rebuild_calls: list[str] = []

    async def active_revision(_db, knowledge_base):
        return revisions[knowledge_base.id]

    async def source_versions(_db, knowledge_base):
        if knowledge_base.id == "reconcile-error-kb":
            raise RuntimeError("source query failed")
        return current_versions[knowledge_base.id]

    async def embedding_model(_db, knowledge_base):
        model_id = (
            "embedding-b"
            if knowledge_base.id == "reconcile-rebuild-kb"
            else "embedding-a"
        )
        return SimpleNamespace(id=model_id)

    async def enqueue_sync(_db, knowledge_base, _actor, document_ids):
        sync_calls.append(document_ids)
        return KnowledgeTask(
            id=f"{knowledge_base.id}-task",
            status="queued",
        )

    async def enqueue_rebuild(_db, knowledge_base, _actor):
        rebuild_calls.append(knowledge_base.id)
        return KnowledgeTask(
            id=f"{knowledge_base.id}-task",
            status="queued",
        )

    with (
        patch.object(
            graph_repository,
            "list_graph_enabled_knowledge_bases",
            AsyncMock(return_value=knowledge_bases),
        ),
        patch.object(graph_repository, "get_active_revision", active_revision),
        patch.object(
            knowledge_repository,
            "get_latest_graph_task",
            AsyncMock(return_value=None),
        ),
        patch.object(
            graph_repository,
            "get_latest_revision",
            active_revision,
        ),
        patch.object(
            graph_repository,
            "current_graph_source_versions",
            source_versions,
        ),
        patch.object(
            knowledge_graph_maintenance,
            "resolve_embedding_model",
            embedding_model,
        ),
        patch.object(
            user_repository,
            "get_user_by_id",
            AsyncMock(return_value=User(id="graph-user")),
        ),
        patch.object(
            knowledge_graph_maintenance,
            "enqueue_graph_sync",
            enqueue_sync,
        ),
        patch.object(
            knowledge_graph_maintenance,
            "enqueue_graph_rebuild",
            enqueue_rebuild,
        ),
        patch.object(knowledge_graph_maintenance, "log_error") as log_error,
    ):
        task_ids = await knowledge_graph_maintenance.enqueue_due_graph_tasks(db)

    assert task_ids == [
        "reconcile-sync-kb-task",
        "reconcile-rebuild-kb-task",
    ]
    assert sync_calls == [["doc-1"]]
    assert rebuild_calls == ["reconcile-rebuild-kb"]
    assert db.rollback.await_count == 1
    log_error.assert_called_once()


async def test_graph_source_reconcile_waits_for_active_and_failed_tasks() -> None:
    knowledge_base = KnowledgeBase(
        id="reconcile-failed-kb",
        workspace_id="reconcile-workspace",
        graph_enabled=True,
        created_by_user_id="graph-user",
    )
    failed_task = KnowledgeTask(
        id="reconcile-failed-task",
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        task_type="graph_rebuild",
        status="failed",
    )
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch.object(
            graph_repository,
            "list_graph_enabled_knowledge_bases",
            AsyncMock(return_value=[knowledge_base]),
        ),
        patch.object(
            knowledge_repository,
            "get_latest_graph_task",
            AsyncMock(return_value=failed_task),
        ),
        patch.object(
            knowledge_graph_maintenance,
            "enqueue_graph_rebuild",
            AsyncMock(),
        ) as enqueue_rebuild,
        patch.object(
            knowledge_graph_maintenance,
            "enqueue_graph_sync",
            AsyncMock(),
        ) as enqueue_sync,
    ):
        for status in ("queued", "running", "cancelling", "failed", "cancelled"):
            failed_task.status = status
            task_ids = await knowledge_graph_maintenance.enqueue_due_graph_tasks(db)
            assert task_ids == []

    enqueue_rebuild.assert_not_awaited()
    enqueue_sync.assert_not_awaited()


async def test_graph_source_reconcile_keeps_deleted_failed_task_stopped() -> None:
    knowledge_base = KnowledgeBase(
        id="reconcile-deleted-failed-task-kb",
        workspace_id="reconcile-workspace",
        graph_enabled=True,
        created_by_user_id="graph-user",
    )
    source_versions = {"doc-1": "1:hash-a:1:indexed"}
    failed_revision = GraphRevisionRecord(
        id="reconcile-deleted-failed-task-revision",
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        schema_id="reconcile-schema",
        revision_no=1,
        status="failed",
        stats_json={"source_versions": source_versions},
    )
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with (
        patch.object(
            graph_repository,
            "list_graph_enabled_knowledge_bases",
            AsyncMock(return_value=[knowledge_base]),
        ),
        patch.object(
            knowledge_repository,
            "get_latest_graph_task",
            AsyncMock(return_value=None),
        ),
        patch.object(
            graph_repository,
            "get_active_revision",
            AsyncMock(return_value=None),
        ),
        patch.object(
            graph_repository,
            "get_latest_revision",
            AsyncMock(return_value=failed_revision),
        ),
        patch.object(
            graph_repository,
            "current_graph_source_versions",
            AsyncMock(return_value=source_versions),
        ),
        patch.object(
            knowledge_graph_maintenance,
            "enqueue_graph_rebuild",
            AsyncMock(),
        ) as enqueue_rebuild,
    ):
        task_ids = await knowledge_graph_maintenance.enqueue_due_graph_tasks(db)

    assert task_ids == []
    enqueue_rebuild.assert_not_awaited()


def test_bank_path_preserves_relation_direction_and_evidence() -> None:
    entity_specs = {
        entity_id: (entity_type, name)
        for record in BANK_RECORDS
        for entity_id, entity_type, name in (
            record["subject"],
            record["object"],
        )
    }
    entities = {
        entity_id: GraphEntityRecord(
            id=entity_id,
            entity_type=entity_type,
            canonical_name=name,
            normalized_name=name.casefold(),
        )
        for entity_id, (entity_type, name) in entity_specs.items()
    }
    claims = {
        f"claim-{index}": GraphClaimRecord(
            id=f"claim-{index}",
            subject_entity_id=record["subject"][0],
            predicate=record["predicate"],
            object_entity_id=record["object"][0],
            status="active",
            quality_score=1.0,
            support_count=1,
        )
        for index, record in enumerate(BANK_RECORDS, start=1)
    }
    evidence = {
        claim_id: (
            graph_traversal.GraphEvidenceView(
                id=f"evidence-{claim_id}",
                document_id="bank-document",
                document_filename="bank.jsonl",
                chunk_id=f"chunk-{claim_id}",
                quote=record["evidence"],
                start_offset=0,
                end_offset=len(record["evidence"]),
                source_kind="structured_import",
            ),
        )
        for claim_id, record in zip(claims, BANK_RECORDS, strict=True)
    }
    path = graph_traversal.assemble_path(
        [
            "account-a",
            "phone-p",
            "account-b",
            "device-d",
            "account-c",
            "company-x",
        ],
        list(claims),
        entities,
        claims,
        evidence,
    )
    assert path is not None
    assert [step.predicate for step in path.steps] == [
        "uses_phone",
        "uses_phone",
        "logged_in_on",
        "logged_in_on",
        "legal_representative_of",
    ]
    assert [node.canonical_name for node in path.nodes] == [
        "账户 A",
        "手机号 P",
        "账户 B",
        "设备 D",
        "账户 C",
        "公司 X",
    ]
    assert [step.semantic_direction for step in path.steps] == [
        "forward",
        "reverse",
        "forward",
        "reverse",
        "forward",
    ]
    assert all(step.evidence for step in path.steps)
    assert not any(
        claim.subject_entity_id == "account-a"
        and claim.object_entity_id == "device-d"
        for claim in claims.values()
    )

    graph = graph_query.graph_query_result_response(
        graph_traversal.GraphTraversalResult(
            revision_id="bank-revision",
            operation="path",
            resolved_entities=path.nodes,
            nodes=path.nodes,
            claims=path.steps,
            paths=(path,),
            evidence=tuple(
                item
                for step in path.steps
                for item in step.evidence
            ),
            visited_nodes=len(path.nodes),
            truncated=False,
        )
    )
    assert graph is not None
    metrics = graph_evaluation_metrics(
        KnowledgeGraphEvaluationExpectation(
            path_entity_names=[node.canonical_name for node in path.nodes],
            path_predicates=[step.predicate for step in path.steps],
        ),
        graph,
    )
    assert metrics is not None
    assert metrics.entity_precision == 1
    assert metrics.entity_recall == 1
    assert metrics.claim_precision == 1
    assert metrics.claim_recall == 1
    assert metrics.path_exact_match == 1
    assert metrics.path_edge_accuracy == 1
    assert metrics.citation_coverage == 1
    assert graph_evaluation_metrics(None, graph) is None


def test_policy_graph_evaluation_preserves_fixed_citations() -> None:
    entity_specs = {
        entity_id: (entity_type, name)
        for record in POLICY_RECORDS
        for entity_id, entity_type, name in (
            record["subject"],
            record["object"],
        )
    }
    entities = {
        entity_id: GraphEntityRecord(
            id=entity_id,
            entity_type=entity_type,
            canonical_name=name,
            normalized_name=name.casefold(),
        )
        for entity_id, (entity_type, name) in entity_specs.items()
    }
    claims = {}
    evidence = {}
    for index, record in enumerate(POLICY_RECORDS, start=1):
        claim_id = f"policy-claim-{index}"
        subject_id = record["subject"][0]
        object_id = record["object"][0]
        claims[claim_id] = GraphClaimRecord(
            id=claim_id,
            subject_entity_id=subject_id,
            predicate=record["predicate"],
            object_entity_id=object_id,
            status="active",
            quality_score=1.0,
            support_count=1,
        )
        quote = record["evidence"]
        evidence[claim_id] = (
            graph_traversal.GraphEvidenceView(
                id=f"policy-evidence-{index}",
                document_id=record["document"].removesuffix(".md"),
                document_filename=record["document"],
                chunk_id=f"policy-chunk-{index}",
                quote=quote,
                start_offset=0,
                end_offset=len(quote),
                source_kind="structured_import",
            ),
        )

    policy_path = graph_traversal.assemble_path(
        ["policy-a", "approval", "process", "hr"],
        ["policy-claim-1", "policy-claim-2", "policy-claim-3"],
        entities,
        claims,
        evidence,
    )
    reference_path = graph_traversal.assemble_path(
        ["policy-b", "policy-a"],
        ["policy-claim-4"],
        entities,
        claims,
        evidence,
    )
    assert policy_path is not None
    assert reference_path is not None
    node_views = {
        node.id: node
        for path in (policy_path, reference_path)
        for node in path.nodes
    }
    graph = graph_query.graph_query_result_response(
        graph_traversal.GraphTraversalResult(
            revision_id="policy-revision",
            operation="synthesis",
            resolved_entities=policy_path.nodes,
            nodes=tuple(node_views.values()),
            claims=(*policy_path.steps, *reference_path.steps),
            paths=(policy_path, reference_path),
            evidence=tuple(
                item
                for claim_evidence in evidence.values()
                for item in claim_evidence
            ),
            visited_nodes=len(node_views),
            truncated=False,
        )
    )
    assert graph is not None
    metrics = graph_evaluation_metrics(
        KnowledgeGraphEvaluationExpectation(
            entity_names=[
                "制度 A",
                "制度 B",
                "离职审批",
                "离职流程",
                "人力资源部",
            ],
            predicates=[
                "defines",
                "requires",
                "responsible_for",
                "references",
            ],
            path_entity_names=[
                "制度 A",
                "离职审批",
                "离职流程",
                "人力资源部",
            ],
            path_predicates=["defines", "requires", "responsible_for"],
        ),
        graph,
    )
    assert metrics is not None
    assert metrics.entity_precision == metrics.entity_recall == 1
    assert metrics.claim_precision == metrics.claim_recall == 1
    assert metrics.path_exact_match == 1
    assert metrics.path_edge_accuracy == 1
    assert metrics.citation_coverage == 1
    assert {item.quote for item in graph.evidence} == {
        "制度 A 定义离职审批。",
        "离职审批要求执行离职流程。",
        "人力资源部负责离职流程。",
        "制度 B references 制度 A",
    }


def test_graph_traversal_sql_requires_acyclic_active_evidence() -> None:
    for statement in (
        graph_repository._SHORTEST_PATH_SQL,
        graph_repository._NEIGHBORHOOD_SQL,
    ):
        assert "next_step.entity_id <> ALL(walk.entity_path)" in statement.text
        assert "evidence.evidence_state = 'active'" in statement.text
        assert "document.status <> 'deleted'" in statement.text
        assert "document.is_active IS TRUE" in statement.text


async def test_graph_traversal_bounds_scoping_and_truncation() -> None:
    db = SimpleNamespace()
    knowledge_base = KnowledgeBase(id="traversal-kb", workspace_id="traversal-ws")
    revision = SimpleNamespace(id="traversal-revision")
    source = GraphEntityRecord(
        id="source",
        entity_type="Account",
        canonical_name="Source",
    )
    target = GraphEntityRecord(
        id="target",
        entity_type="Organization",
        canonical_name="Target",
    )

    for invalid_hops in (0, 9):
        try:
            await graph_traversal.shortest_path(
                db,
                knowledge_base,
                revision,
                source.id,
                target.id,
                max_hops=invalid_hops,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("path traversal must enforce the 8-hop ceiling")

    query_path = AsyncMock()
    with (
        patch.object(
            graph_repository,
            "list_active_entities_by_ids",
            AsyncMock(return_value=[source]),
        ),
        patch.object(graph_repository, "query_shortest_path_rows", query_path),
    ):
        scoped = await graph_traversal.shortest_path(
            db,
            knowledge_base,
            revision,
            source.id,
            target.id,
            max_hops=8,
        )
    assert scoped.paths == ()
    assert [item.id for item in scoped.resolved_entities] == [source.id]
    query_path.assert_not_awaited()

    query_path = AsyncMock(return_value=([], 2, False))
    with (
        patch.object(
            graph_repository,
            "list_active_entities_by_ids",
            AsyncMock(return_value=[source, target]),
        ),
        patch.object(graph_repository, "query_shortest_path_rows", query_path),
    ):
        no_path = await graph_traversal.shortest_path(
            db,
            knowledge_base,
            revision,
            source.id,
            target.id,
            max_hops=8,
            relation_filters=["uses_phone"],
        )
    assert no_path.paths == ()
    query_path.assert_awaited_once_with(
        db,
        knowledge_base,
        source.id,
        target.id,
        8,
        ["uses_phone"],
    )

    entities = {source.id: source}
    claims = {}
    rows = []
    for index in range(201):
        entity = GraphEntityRecord(
            id=f"neighbor-{index}",
            entity_type="Account",
            canonical_name=f"Neighbor {index}",
        )
        claim = GraphClaimRecord(
            id=f"neighbor-claim-{index}",
            subject_entity_id=source.id,
            predicate="connected_to",
            object_entity_id=entity.id,
            status="active",
        )
        entities[entity.id] = entity
        claims[claim.id] = claim
        rows.append(([source.id, entity.id], [claim.id]))

    async def list_entities(_db, _knowledge_base, entity_ids):
        return [entities[entity_id] for entity_id in sorted(entity_ids)]

    async def list_claims(_db, _knowledge_base, claim_ids):
        return [claims[claim_id] for claim_id in sorted(claim_ids)]

    with (
        patch.object(
            graph_repository,
            "list_active_entities_by_ids",
            list_entities,
        ),
        patch.object(
            graph_repository,
            "query_neighborhood_rows",
            AsyncMock(return_value=(rows, 202, False)),
        ),
        patch.object(
            graph_repository,
            "list_active_claims_by_ids",
            list_claims,
        ),
        patch.object(
            graph_repository,
            "list_ranked_evidence_for_claim_ids",
            AsyncMock(return_value=[]),
        ),
    ):
        neighborhood = await graph_traversal.neighborhood(
            db,
            knowledge_base,
            revision,
            source.id,
            max_hops=3,
        )
    assert neighborhood.truncated
    assert neighborhood.limit_reason == "size"
    assert len(neighborhood.nodes) == graph_traversal.MAX_GRAPH_NODES
    assert len(neighborhood.claims) == graph_traversal.MAX_GRAPH_NODES - 1


async def test_graph_query_candidates_require_unique_entities_and_keep_hops() -> None:
    knowledge_base = KnowledgeBase(
        id="query-kb",
        workspace_id="query-workspace",
        graph_enabled=True,
    )
    revision = SimpleNamespace(
        id="query-revision",
        schema_id="query-schema",
        stats_json={},
    )
    source = GraphEntityRecord(
        id="source",
        entity_type="Account",
        canonical_name="账户 A",
        normalized_name="账户 a",
    )
    target = GraphEntityRecord(
        id="target",
        entity_type="Organization",
        canonical_name="公司 X",
        normalized_name="公司 x",
    )
    claim = GraphClaimRecord(
        id="query-claim",
        subject_entity_id=source.id,
        predicate="connected_to",
        object_entity_id=target.id,
        status="active",
        quality_score=1.0,
        support_count=1,
    )
    evidence = graph_traversal.GraphEvidenceView(
        id="query-evidence",
        document_id="query-document",
        document_filename="query.md",
        chunk_id="query-chunk",
        quote="账户 A 与公司 X 相关。",
        start_offset=0,
        end_offset=13,
        source_kind="explicit_text",
    )
    path = graph_traversal.assemble_path(
        [source.id, target.id],
        [claim.id],
        {source.id: source, target.id: target},
        {claim.id: claim},
        {claim.id: (evidence,)},
    )
    assert path is not None
    traversal_result = graph_traversal.GraphTraversalResult(
        revision_id=revision.id,
        operation="path",
        resolved_entities=path.nodes,
        nodes=path.nodes,
        claims=path.steps,
        paths=(path,),
        evidence=(evidence,),
        visited_nodes=2,
        truncated=False,
    )

    async def exact_matches(_db, _knowledge_base, text):
        return [source] if text == "账户 a" else [target]

    with (
        patch.object(
            graph_repository,
            "get_active_revision",
            AsyncMock(return_value=revision),
        ),
        patch.object(
            graph_repository,
            "get_schema",
            AsyncMock(
                return_value=SimpleNamespace(
                    schema_json=default_graph_schema().model_dump(
                        mode="json"
                    )
                )
            ),
        ),
        patch.object(
            graph_repository,
            "list_exact_entity_matches",
            exact_matches,
        ),
        patch.object(
            graph_traversal,
            "shortest_path",
            AsyncMock(return_value=traversal_result),
        ) as shortest_path,
    ):
        result = await graph_query.retrieve_graph_candidates(
            SimpleNamespace(),
            knowledge_base,
            KnowledgeQueryRequest(
                query="账户 A 与公司 X 有什么关系",
                graph_mode="path",
                source_entity="账户 A",
                target_entity="公司 X",
            ),
            SimpleNamespace(),
            10,
        )
    assert result.operation == "path"
    assert result.chunk_ids == (evidence.chunk_id,)
    assert result.claim_ids_by_chunk == {evidence.chunk_id: (claim.id,)}
    assert result.claim_hops == {claim.id: 1}
    shortest_path.assert_awaited_once()

    duplicate = GraphEntityRecord(
        id="duplicate",
        entity_type="Account",
        canonical_name="张三",
        normalized_name="张三",
    )
    duplicate_two = GraphEntityRecord(
        id="duplicate-two",
        entity_type="Account",
        canonical_name="张三",
        normalized_name="张三",
    )
    with (
        patch.object(
            graph_repository,
            "get_active_revision",
            AsyncMock(return_value=revision),
        ),
        patch.object(
            graph_repository,
            "get_schema",
            AsyncMock(
                return_value=SimpleNamespace(
                    schema_json=default_graph_schema().model_dump(
                        mode="json"
                    )
                )
            ),
        ),
        patch.object(
            graph_repository,
            "list_query_entity_mentions",
            AsyncMock(return_value=[duplicate, duplicate_two, target]),
        ),
        patch.object(
            graph_traversal,
            "shortest_path",
            AsyncMock(side_effect=AssertionError("ambiguous path was guessed")),
        ),
    ):
        ambiguous = await graph_query.retrieve_graph_candidates(
            SimpleNamespace(),
            knowledge_base,
            KnowledgeQueryRequest(
                query="张三与公司 X 有什么关系",
            ),
            SimpleNamespace(),
            10,
        )
    assert ambiguous.operation == "ambiguous"
    assert ambiguous.traversal is not None
    assert ambiguous.traversal.paths == ()


async def test_graph_retrieval_fuses_evidence_without_changing_off_mode() -> None:
    text_chunk = KnowledgeDocumentChunk(
        id="text-chunk",
        workspace_id="retrieval-workspace",
        knowledge_base_id="retrieval-kb",
        document_id="text-document",
        content="Direct text evidence",
        search_text="Direct text evidence",
        status="indexed",
    )
    graph_chunk = KnowledgeDocumentChunk(
        id="graph-chunk",
        workspace_id="retrieval-workspace",
        knowledge_base_id="retrieval-kb",
        document_id="graph-document",
        content="Cross-document graph evidence",
        search_text="Cross-document graph evidence",
        status="indexed",
    )
    documents = {
        "text-document": KnowledgeDocument(
            id="text-document",
            workspace_id="retrieval-workspace",
            knowledge_base_id="retrieval-kb",
            filename="direct.md",
            status="indexed",
        ),
        "graph-document": KnowledgeDocument(
            id="graph-document",
            workspace_id="retrieval-workspace",
            knowledge_base_id="retrieval-kb",
            filename="related.md",
            status="indexed",
        ),
    }
    node = graph_traversal.GraphNodeView("entity", "Document", "制度 A")
    evidence = graph_traversal.GraphEvidenceView(
        id="retrieval-evidence",
        document_id="graph-document",
        document_filename="related.md",
        chunk_id=graph_chunk.id,
        quote="Cross-document graph evidence",
        start_offset=0,
        end_offset=29,
        source_kind="explicit_text",
    )
    step = graph_traversal.GraphPathStep(
        claim_id="retrieval-claim",
        predicate="references",
        source_entity_id="entity",
        target_entity_id="related-entity",
        semantic_direction="forward",
        quality_score=1.0,
        support_count=1,
        evidence=(evidence,),
    )
    path = graph_traversal.GraphPath(nodes=(node,), steps=(step,))
    traversal_result = graph_traversal.GraphTraversalResult(
        revision_id="retrieval-revision",
        operation="path",
        resolved_entities=(node,),
        nodes=(node,),
        claims=(step,),
        paths=(path,),
        evidence=(evidence,),
        visited_nodes=2,
        truncated=False,
    )
    graph_result = graph_query.GraphCandidateResult(
        chunk_ids=(graph_chunk.id,),
        claim_ids_by_chunk={graph_chunk.id: (step.claim_id,)},
        claim_hops={step.claim_id: 1},
        traversal=traversal_result,
        operation="path",
        revision_id=traversal_result.revision_id,
        visited_nodes=2,
        truncated=False,
        limit_reason=None,
        entity_candidate_count=2,
        profile_candidate_count=0,
    )
    off_result = graph_query.GraphCandidateResult(
        (), {}, {}, None, "off", None, 0, False, None, 0, 0
    )

    async def fake_graph(_db, knowledge_base, payload, _settings, _limit):
        if not knowledge_base.graph_enabled or payload.graph_mode == "off":
            return off_result
        return graph_result

    async def list_chunks(_db, _knowledge_base, chunk_ids):
        values = {text_chunk.id: text_chunk, graph_chunk.id: graph_chunk}
        return [values[chunk_id] for chunk_id in chunk_ids if chunk_id in values]

    async def list_documents(_db, _knowledge_base, document_ids):
        return [documents[document_id] for document_id in document_ids]

    with (
        patch.object(
            knowledge_repository,
            "query_keyword_chunk_ids",
            AsyncMock(return_value=[text_chunk.id]),
        ),
        patch.object(knowledge_repository, "list_chunks_by_ids", list_chunks),
        patch.object(
            knowledge_repository,
            "list_active_documents_by_ids",
            list_documents,
        ),
        patch.object(graph_query, "retrieve_graph_candidates", fake_graph),
    ):
        baseline = await knowledge_retrieval_application.retrieve_knowledge_base(
            SimpleNamespace(),
            SimpleNamespace(
                id="retrieval-kb",
                workspace_id="retrieval-workspace",
                graph_enabled=False,
                reranker_model_id=None,
            ),
            KnowledgeQueryRequest(
                query="制度 A",
                limit=2,
                search_mode="keywords",
            ),
            SimpleNamespace(),
        )
        explicit_off = await knowledge_retrieval_application.retrieve_knowledge_base(
            SimpleNamespace(),
            SimpleNamespace(
                id="retrieval-kb",
                workspace_id="retrieval-workspace",
                graph_enabled=True,
                reranker_model_id=None,
            ),
            KnowledgeQueryRequest(
                query="制度 A",
                limit=2,
                search_mode="keywords",
                graph_mode="off",
            ),
            SimpleNamespace(),
        )
        blended = await knowledge_retrieval_application.retrieve_knowledge_base(
            SimpleNamespace(),
            SimpleNamespace(
                id="retrieval-kb",
                workspace_id="retrieval-workspace",
                graph_enabled=True,
                reranker_model_id=None,
            ),
            KnowledgeQueryRequest(
                query="制度 A",
                limit=2,
                search_mode="keywords",
            ),
            SimpleNamespace(),
        )

    assert [hit.model_dump() for hit in explicit_off.hits] == [
        hit.model_dump() for hit in baseline.hits
    ]
    assert {hit.document_filename for hit in blended.hits} == {
        "direct.md",
        "related.md",
    }
    related = next(hit for hit in blended.hits if hit.document_id == "graph-document")
    assert related.sources == ["graph"]
    assert related.graph_claim_ids == [step.claim_id]
    assert related.graph_hops == 1
    assert blended.trace.graph_claim_candidates == 1
    assert baseline.trace.graph_intent is None
    assert explicit_off.trace.graph_intent is None
    assert all(
        explicit_off.trace.stage_duration_ms.get(stage, 0.0) == 0.0
        for stage in graph_query.GRAPH_QUERY_STAGE_KEYS
    )
    assert blended.graph is not None
    assert blended.graph.operation == "path"


async def test_graph_query_off_skips_graph_dependencies() -> None:
    knowledge_base = KnowledgeBase(
        id="graph-off-kb",
        workspace_id="graph-off-workspace",
        graph_enabled=False,
    )
    with (
        patch.object(
            graph_repository,
            "get_active_revision",
            AsyncMock(side_effect=AssertionError("off mode queried revisions")),
        ),
        patch.object(
            graph_query,
            "query_graph_profile_vectors",
            side_effect=AssertionError("off mode queried profiles"),
        ),
    ):
        result = await graph_query.retrieve_graph_candidates(
            SimpleNamespace(),
            knowledge_base,
            KnowledgeQueryRequest(query="anything", graph_mode="auto"),
            SimpleNamespace(),
            5,
        )
    assert result.operation == "off"
    assert result.stage_duration_ms == {
        stage: 0.0 for stage in graph_query.GRAPH_QUERY_STAGE_KEYS
    }


async def test_graph_query_drops_stale_profiles_and_rejects_unknown_relations() -> None:
    knowledge_base = KnowledgeBase(
        id="profile-query-kb",
        workspace_id="profile-query-workspace",
        graph_enabled=True,
    )
    revision = SimpleNamespace(
        id="profile-query-revision",
        schema_id="profile-query-schema",
        stats_json={"profile_embedding_model_id": "embedding-model"},
    )
    entity = GraphEntityRecord(
        id="profile-entity",
        entity_type="Document",
        canonical_name="制度 A",
        normalized_name="制度 a",
        profile_hash="current-profile-hash",
    )
    schema = SimpleNamespace(
        schema_json=default_graph_schema().model_dump(mode="json")
    )
    with (
        patch.object(
            graph_repository,
            "get_active_revision",
            AsyncMock(return_value=revision),
        ),
        patch.object(
            graph_repository,
            "get_schema",
            AsyncMock(return_value=schema),
        ),
        patch.object(
            graph_repository,
            "list_query_entity_mentions",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            graph_repository,
            "list_exact_entity_matches",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            graph_repository,
            "query_entity_candidate_ids",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            graph_repository,
            "list_active_entities_by_ids",
            AsyncMock(return_value=[entity]),
        ),
        patch.object(
            graph_query,
            "resolve_embedding_model",
            AsyncMock(return_value=SimpleNamespace(id="embedding-model")),
        ),
        patch.object(
            graph_query,
            "query_graph_profile_vectors",
            return_value=[
                graph_query.GraphProfileVectorHit(
                    entity_id=entity.id,
                    profile_hash="stale-profile-hash",
                    distance=0.0,
                )
            ],
        ),
    ):
        result = await graph_query.retrieve_graph_candidates(
            SimpleNamespace(),
            knowledge_base,
            KnowledgeQueryRequest(query="制度 A 的要求"),
            SimpleNamespace(),
            10,
        )
    assert result.operation == "none"
    assert result.profile_candidate_count == 0
    assert result.traversal is not None
    assert result.traversal.resolved_entities == ()

    with (
        patch.object(
            graph_repository,
            "get_active_revision",
            AsyncMock(return_value=revision),
        ),
        patch.object(
            graph_repository,
            "get_schema",
            AsyncMock(return_value=schema),
        ),
    ):
        try:
            await graph_query.retrieve_graph_candidates(
                SimpleNamespace(),
                knowledge_base,
                KnowledgeQueryRequest(
                    query="制度 A",
                    relation_filters=["drop_table"],
                ),
                SimpleNamespace(),
                10,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("unknown graph relations must be rejected")


async def test_graph_query_planning_edge_paths() -> None:
    knowledge_base = KnowledgeBase(
        id="query-edge-kb",
        workspace_id="query-edge-workspace",
        graph_enabled=True,
    )
    revision = SimpleNamespace(
        id="query-edge-revision",
        schema_id="query-edge-schema",
        stats_json={},
    )
    schema = SimpleNamespace(
        schema_json=default_graph_schema().model_dump(mode="json")
    )
    alpha = GraphEntityRecord(
        id="query-alpha",
        entity_type="Account",
        canonical_name="Alpha",
        normalized_name="alpha",
    )
    beta = GraphEntityRecord(
        id="query-beta",
        entity_type="Organization",
        canonical_name="Beta",
        normalized_name="beta",
    )
    gamma = GraphEntityRecord(
        id="query-gamma",
        entity_type="Concept",
        canonical_name="Gamma",
        normalized_name="gamma",
    )

    assert await graph_query._profile_candidates_impl(
        SimpleNamespace(),
        knowledge_base,
        revision,
        "Alpha",
        SimpleNamespace(),
    ) == ([], {})
    profile_revision = SimpleNamespace(
        id=revision.id,
        schema_id=revision.schema_id,
        stats_json={"profile_embedding_model_id": "embedding-a"},
    )
    with patch.object(
        graph_query,
        "resolve_embedding_model",
        AsyncMock(return_value=SimpleNamespace(id="embedding-b")),
    ):
        assert await graph_query._profile_candidates_impl(
            SimpleNamespace(),
            knowledge_base,
            profile_revision,
            "Alpha",
            SimpleNamespace(),
        ) == ([], {})
    with patch.object(
        graph_query,
        "resolve_embedding_model",
        AsyncMock(side_effect=RuntimeError("embedding unavailable")),
    ):
        assert await graph_query._profile_candidates_impl(
            SimpleNamespace(),
            knowledge_base,
            profile_revision,
            "Alpha",
            SimpleNamespace(),
        ) == ([], {})

    assert graph_query._name_tokens_match_query(alpha, "Alpha account")
    assert not graph_query._name_tokens_match_query(alpha, "Beta account")
    with patch.object(
        graph_repository,
        "list_exact_entity_matches",
        AsyncMock(return_value=[alpha, beta]),
    ):
        linked = await graph_query._link_entity_text_impl(
            SimpleNamespace(),
            knowledge_base,
            revision,
            "shared",
            SimpleNamespace(),
        )
    assert linked.status == "ambiguous"
    assert linked.candidates == (alpha, beta)

    async def link_from_candidates(candidates):
        with (
            patch.object(
                graph_repository,
                "list_exact_entity_matches",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                graph_repository,
                "query_entity_candidate_ids",
                AsyncMock(return_value=[entity.id for entity in candidates]),
            ),
            patch.object(
                graph_query,
                "_profile_candidates",
                AsyncMock(return_value=([], {})),
            ),
            patch.object(
                graph_repository,
                "list_active_entities_by_ids",
                AsyncMock(return_value=candidates),
            ),
        ):
            return await graph_query._link_entity_text_impl(
                SimpleNamespace(),
                knowledge_base,
                revision,
                "Alpha account",
                SimpleNamespace(),
            )

    assert (await link_from_candidates([alpha])).selected == alpha
    assert (await link_from_candidates([alpha, beta])).status == "ambiguous"
    assert (await link_from_candidates([])).status == "not_found"

    with patch.object(
        graph_repository,
        "get_schema",
        AsyncMock(return_value=None),
    ):
        unavailable = await graph_query._build_graph_query_plan_impl(
            SimpleNamespace(),
            knowledge_base,
            revision,
            KnowledgeQueryRequest(query="anything"),
            SimpleNamespace(),
        )
    assert unavailable.operation == "unavailable"

    async def build_plan(payload, mentions, link=None):
        patches = [
            patch.object(
                graph_repository,
                "get_schema",
                AsyncMock(return_value=schema),
            ),
            patch.object(
                graph_repository,
                "list_query_entity_mentions",
                AsyncMock(return_value=list(mentions)),
            ),
        ]
        if link is not None:
            patches.append(
                patch.object(
                    graph_query,
                    "_link_entity_text",
                    AsyncMock(return_value=link),
                )
            )
        with patches[0], patches[1]:
            if len(patches) == 3:
                with patches[2]:
                    return await graph_query._build_graph_query_plan_impl(
                        SimpleNamespace(),
                        knowledge_base,
                        revision,
                        payload,
                        SimpleNamespace(),
                    )
            return await graph_query._build_graph_query_plan_impl(
                SimpleNamespace(),
                knowledge_base,
                revision,
                payload,
                SimpleNamespace(),
            )

    selected = graph_query.EntityLinkResult("selected", alpha, (alpha,), 1, 0)
    ambiguous = graph_query.EntityLinkResult(
        "ambiguous", None, (alpha, beta), 2, 0
    )
    not_found = graph_query.EntityLinkResult("not_found", None, (), 0, 0)
    assert (
        await build_plan(
            KnowledgeQueryRequest(query="missing path", graph_mode="path"),
            [],
        )
    ).operation == "not_found"
    assert (
        await build_plan(
            KnowledgeQueryRequest(query="neighbors", graph_mode="neighborhood"),
            [],
        )
    ).operation == "not_found"
    assert (
        await build_plan(
            KnowledgeQueryRequest(query="Alpha related", graph_mode="neighborhood"),
            [alpha],
            selected,
        )
    ).operation == "neighborhood"
    assert (
        await build_plan(KnowledgeQueryRequest(query="Alpha Beta"), [alpha, beta])
    ).operation == "path"
    assert (
        await build_plan(KnowledgeQueryRequest(query="Alpha 相关"), [alpha])
    ).operation == "neighborhood"
    assert (
        await build_plan(KnowledgeQueryRequest(query="Alpha details"), [alpha])
    ).operation == "profile"
    assert (
        await build_plan(
            KnowledgeQueryRequest(query="Alpha Beta Gamma"),
            [alpha, beta, gamma],
        )
    ).operation == "synthesis"
    assert (
        await build_plan(KnowledgeQueryRequest(query="Alpha"), [], selected)
    ).operation == "profile"
    assert (
        await build_plan(KnowledgeQueryRequest(query="shared"), [], ambiguous)
    ).operation == "synthesis"
    assert (
        await build_plan(KnowledgeQueryRequest(query="missing"), [], not_found)
    ).operation == "none"

    empty_timeout = graph_traversal.GraphTraversalResult(
        revision_id=revision.id,
        operation="neighborhood",
        resolved_entities=(),
        nodes=(),
        claims=(),
        paths=(),
        evidence=(),
        visited_nodes=1,
        truncated=True,
        limit_reason="timeout",
    )
    merged = graph_query._merge_traversals(
        revision,
        "profile",
        (alpha,),
        [empty_timeout],
    )
    assert merged.limit_reason == "timeout"
    assert merged.visited_nodes == 1

    neighborhood_plan = graph_query.ResolvedGraphQueryPlan(
        graph_query._plan("neighborhood", KnowledgeQueryRequest(query="Alpha")),
        "neighborhood",
        (alpha,),
        (alpha,),
        1,
        0,
    )
    profile_plan = graph_query.ResolvedGraphQueryPlan(
        graph_query._plan("profile", KnowledgeQueryRequest(query="Alpha")),
        "profile",
        (alpha,),
        (alpha,),
        1,
        0,
    )
    with patch.object(
        graph_traversal,
        "neighborhood",
        AsyncMock(return_value=empty_timeout),
    ) as neighborhood:
        assert (
            await graph_query.execute_graph_query_plan(
                SimpleNamespace(), knowledge_base, revision, neighborhood_plan
            )
        ) is empty_timeout
        assert (
            await graph_query.execute_graph_query_plan(
                SimpleNamespace(), knowledge_base, revision, profile_plan
            )
        ).operation == "profile"
    assert neighborhood.await_count == 2

    evidence_a = graph_traversal.GraphEvidenceView(
        "query-edge-evidence-a", "doc-a", "a.md", "chunk-a", "A", 0, 1,
        "explicit_text",
    )
    evidence_b = graph_traversal.GraphEvidenceView(
        "query-edge-evidence-b", "doc-b", "b.md", "chunk-b", "B", 0, 1,
        "explicit_text",
    )
    step = graph_traversal.GraphPathStep(
        "query-edge-claim", "related_to", alpha.id, beta.id, "forward", 1.0, 2,
        (evidence_a, evidence_b),
    )
    limited = graph_query._candidate_evidence(
        graph_traversal.GraphTraversalResult(
            revision.id,
            "path",
            (),
            (),
            (step,),
            (),
            (evidence_a, evidence_b),
            0,
            False,
        ),
        1,
    )
    assert limited[0] == ("chunk-a",)

    with patch.object(
        graph_repository,
        "get_active_revision",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    ):
        try:
            await graph_query.retrieve_graph_candidates(
                SimpleNamespace(),
                knowledge_base,
                KnowledgeQueryRequest(query="Alpha"),
                SimpleNamespace(),
                5,
            )
        except HTTPException as exc:
            assert exc.status_code == 503
        else:
            raise AssertionError("unexpected graph failures must be normalized")


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


async def test_graph_storage_cleanup_removes_both_vector_collections() -> None:
    storage = SimpleNamespace(delete_prefix=MagicMock())
    with (
        patch.object(knowledge_cleanup, "delete_vector_collection") as delete_base,
        patch.object(
            knowledge_cleanup,
            "delete_graph_profile_collection",
        ) as delete_graph,
        patch.object(
            knowledge_cleanup,
            "knowledge_object_storage",
            return_value=storage,
        ),
    ):
        await knowledge_cleanup.purge_knowledge_base_storage(
            tests.support.settings(),
            "cleanup-workspace",
            "cleanup-kb",
        )
    delete_base.assert_called_once()
    delete_graph.assert_called_once()
    storage.delete_prefix.assert_called_once_with("cleanup-workspace/cleanup-kb")


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

        definition = default_graph_schema()
        first = await create_graph_schema(db, knowledge_base, definition, actor)
        duplicate = await create_graph_schema(db, knowledge_base, definition, actor)
        changed_payload = definition.model_dump(mode="json")
        changed_payload["entity_types"].append(
            {"name": "CustomEntity", "properties": []}
        )
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
        graph_schema_hash(default_graph_schema()),
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


async def test_graph_maintenance_repairs_orphans_profiles_and_sources() -> None:
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-maintenance-kb",
                workspace_id="graph-workspace",
                name="Graph Maintenance KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        schema = await create_graph_schema(
            db,
            knowledge_base,
            default_graph_schema(),
            actor,
        )
        active_revision = await graph_repository.create_revision(
            db,
            GraphRevisionRecord(
                id="graph-maintenance-active",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                revision_no=1,
                schema_id=schema.id,
                status="published",
                source_watermark="active",
                stats_json={
                    "source_versions": {
                        "graph-maintenance-doc": "1:hash-a:1:indexed"
                    },
                    "profile_embedding_model_id": "embedding-maintenance",
                },
                created_by_user_id=actor.id,
                published_at=utc_now(),
            ),
        )
        knowledge_base.active_graph_schema_id = schema.id
        knowledge_base.active_graph_revision_id = active_revision.id
        await knowledge_repository.save_knowledge_base(db, knowledge_base)
        await graph_repository.create_entity(
            db,
            GraphEntityRecord(
                id="graph-maintenance-active-entity",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                entity_type="Document",
                canonical_name="Maintenance Entity",
                normalized_name="maintenance entity",
                profile_markdown="# Current profile",
                profile_hash="current-profile-hash",
                state="active",
                created_revision_id=active_revision.id,
                last_published_revision_id=active_revision.id,
            ),
        )
        failed_revision = await graph_repository.create_revision(
            db,
            GraphRevisionRecord(
                id="graph-maintenance-failed",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                revision_no=2,
                schema_id=schema.id,
                parent_revision_id=active_revision.id,
                status="failed",
                source_watermark="failed",
                stats_json={
                    "profile_repair_pending": True,
                    "profile_repair_entity_ids": [
                        "graph-maintenance-active-entity",
                        "graph-maintenance-missing-entity",
                    ],
                    "profile_delete_pending": True,
                    "profile_delete_entity_ids": [
                        "graph-maintenance-retired-entity"
                    ],
                },
                created_by_user_id=actor.id,
            ),
        )
        orphan_revision = await graph_repository.create_revision(
            db,
            GraphRevisionRecord(
                id="graph-maintenance-orphan",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                revision_no=3,
                schema_id=schema.id,
                parent_revision_id=active_revision.id,
                status="building",
                source_watermark="orphan",
                stats_json={"task_id": "missing-graph-task"},
                created_by_user_id=actor.id,
                started_at=utc_now() - timedelta(minutes=12),
                created_at=utc_now() - timedelta(minutes=12),
                updated_at=utc_now() - timedelta(minutes=12),
            ),
        )
        await graph_revisions.stage_revision_change(
            db,
            orphan_revision,
            record_kind="entity",
            record_key="graph-maintenance-orphan-entity",
            operation="upsert",
            before_json=None,
            after_json={
                "id": "graph-maintenance-orphan-entity",
                "entity_type": "Document",
                "canonical_name": "Orphan Entity",
                "normalized_name": "orphan entity",
            },
        )
        await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-maintenance-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="maintenance.md",
                content_type="text/markdown",
                size_bytes=10,
                meta={
                    "document_version": 2,
                    "normalized_content_hash": "hash-b",
                },
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-maintenance-staged-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="staged.md",
                content_type="text/markdown",
                size_bytes=10,
                meta={"staged": True},
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()

        enabled = await graph_repository.list_graph_enabled_knowledge_bases(db)
        assert knowledge_base.id in {item.id for item in enabled}
        assert await graph_repository.current_graph_source_versions(
            db,
            knowledge_base,
        ) == {"graph-maintenance-doc": "2:hash-b:1:indexed"}

        await knowledge_graph_maintenance.recover_orphaned_graph_revisions(db)
        recovered = await graph_repository.get_revision(
            db,
            knowledge_base,
            orphan_revision.id,
        )
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.failure_reason == "Orphaned graph revision recovered."
        assert recovered.stats_json["profile_repair_entity_ids"] == [
            "graph-maintenance-orphan-entity"
        ]

        async def embedding_model(*_args, **_kwargs):
            return SimpleNamespace(id="embedding-maintenance")

        upsert_profiles = MagicMock()
        delete_profiles = MagicMock()
        with (
            patch.object(
                knowledge_graph_maintenance,
                "resolve_embedding_model",
                embedding_model,
            ),
            patch.object(
                knowledge_graph_maintenance,
                "upsert_graph_profile_vectors",
                upsert_profiles,
            ),
            patch.object(
                knowledge_graph_maintenance,
                "delete_graph_profile_vectors",
                delete_profiles,
            ),
        ):
            await knowledge_graph_maintenance.repair_pending_graph_profiles(
                db,
                tests.support.settings(),
            )

        assert [
            profile.entity_id
            for profile in upsert_profiles.call_args.args[-1]
        ] == ["graph-maintenance-active-entity"]
        deleted_ids = {
            entity_id
            for call in delete_profiles.call_args_list
            for entity_id in call.args[-1]
        }
        assert deleted_ids == {
            "graph-maintenance-missing-entity",
            "graph-maintenance-retired-entity",
            "graph-maintenance-orphan-entity",
        }
        for revision_id in (failed_revision.id, orphan_revision.id):
            refreshed = await graph_repository.get_revision(
                db,
                knowledge_base,
                revision_id,
            )
            assert refreshed is not None
            assert refreshed.stats_json["profile_repair_pending"] is False
            assert refreshed.stats_json["profile_delete_pending"] is False
            assert refreshed.stats_json["profile_repaired_at"]
            assert refreshed.stats_json["profile_deleted_at"]


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


async def test_review_decisions_publish_atomically_and_reset_on_failure() -> None:
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-review-kb",
                workspace_id="graph-workspace",
                name="Graph Review KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        schema = await create_graph_schema(
            db,
            knowledge_base,
            default_graph_schema(),
            actor,
        )
        initial = await graph_revisions.create_revision(
            db,
            knowledge_base,
            schema,
            actor.id,
            "review-initial",
        )
        await db.commit()
        initial = await graph_revisions.publish_revision(
            db,
            knowledge_base,
            initial,
        )
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            knowledge_base.id,
        )
        assert knowledge_base is not None
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-review-document",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="review.txt",
                content_type="text/plain",
                size_bytes=20,
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        chunk = KnowledgeDocumentChunk(
            id="graph-review-chunk",
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            content="旧制度、目标制度与拆分制度。",
            search_text="旧制度 目标制度 拆分制度",
            char_count=14,
            token_count=8,
            status="indexed",
        )
        await knowledge_repository.save_knowledge_document_chunk(db, chunk)

        entity_names = {
            "review-merge-source": "旧制度",
            "review-merge-target": "目标制度",
            "review-object": "对象",
            "review-split-source": "待拆分制度",
        }
        for entity_id, name in entity_names.items():
            await graph_repository.create_entity(
                db,
                GraphEntityRecord(
                    id=entity_id,
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    entity_type="Document",
                    canonical_name=name,
                    normalized_name=name,
                    search_text=name,
                    created_revision_id=initial.id,
                    last_published_revision_id=initial.id,
                ),
            )
        await graph_repository.create_alias(
            db,
            GraphAliasRecord(
                id="review-source-alias",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                entity_id="review-merge-source",
                alias="旧规",
                normalized_alias="旧规",
                created_revision_id=initial.id,
                last_published_revision_id=initial.id,
            ),
        )
        for mention_id, entity_id, start_offset in (
            ("review-merge-mention", "review-merge-source", 0),
            ("review-split-move-mention", "review-split-source", 4),
            ("review-split-keep-mention", "review-split-source", 8),
        ):
            await graph_repository.create_mention(
                db,
                GraphMentionRecord(
                    id=mention_id,
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    entity_id=entity_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    surface_text=entity_names[entity_id],
                    start_offset=start_offset,
                    end_offset=start_offset + 2,
                    quote=chunk.content,
                    resolution_method="exact",
                    created_revision_id=initial.id,
                    last_published_revision_id=initial.id,
                ),
            )

        claim_specs = (
            (
                "review-merge-claim",
                "review-merge-source",
                "applies_to",
                "active",
            ),
            (
                "review-approve-claim",
                "review-merge-target",
                "defines",
                "candidate",
            ),
            (
                "review-split-move-claim",
                "review-split-source",
                "contains",
                "active",
            ),
            (
                "review-split-keep-claim",
                "review-split-source",
                "references",
                "active",
            ),
        )
        for claim_id, subject_id, predicate, claim_status in claim_specs:
            await graph_repository.create_claim(
                db,
                GraphClaimRecord(
                    id=claim_id,
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    subject_entity_id=subject_id,
                    predicate=predicate,
                    object_entity_id="review-object",
                    status=claim_status,
                    source_kind="explicit_text",
                    quality_score=0.9,
                    fingerprint=claim_fingerprint(
                        subject_id,
                        predicate,
                        "review-object",
                        None,
                        None,
                        None,
                    ),
                    created_revision_id=initial.id,
                    last_published_revision_id=initial.id,
                ),
            )
        retired_fingerprint = claim_fingerprint(
            "review-merge-target",
            "applies_to",
            "review-object",
            None,
            None,
            None,
        )
        await graph_repository.create_claim(
            db,
            GraphClaimRecord(
                id="review-retired-duplicate",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                subject_entity_id="review-merge-target",
                predicate="applies_to",
                object_entity_id="review-object",
                status="superseded",
                source_kind="explicit_text",
                quality_score=0.8,
                fingerprint=retired_fingerprint,
                created_revision_id=initial.id,
                last_published_revision_id=initial.id,
                retired_revision_id=initial.id,
            ),
        )

        reviewed_at = utc_now()
        review_specs = (
            ("review-merge", "possible_duplicate", "approved"),
            ("review-approve", "conflict", "approved"),
            ("review-split", "ambiguous_entity", "approved"),
            ("review-reset", "conflict", "rejected"),
        )
        for review_id, kind, review_status in review_specs:
            await graph_repository.create_review_item(
                db,
                GraphReviewRecord(
                    id=review_id,
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    kind=kind,
                    status=review_status,
                    decision_json={"action": "reject_claim"},
                    revision_id=initial.id,
                    created_by_user_id=actor.id,
                    reviewed_by_user_id=actor.id,
                    reviewed_at=reviewed_at,
                ),
            )
        revision = await graph_revisions.create_revision(
            db,
            knowledge_base,
            schema,
            actor.id,
            "review-decisions",
        )
        try:
            await knowledge_graph._normalize_review_decision(
                db,
                knowledge_base,
                "review-split",
                "ambiguous_entity",
                {"entity_id": "review-split-source"},
                KnowledgeGraphReviewDecisionRequest(
                    action="split_entity",
                    canonical_name="非法拆分",
                    entity_type="Unknown",
                    mention_ids=["review-split-move-mention"],
                ),
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("split entity types must follow the active schema")
        decisions = (
            {
                "action": "merge_entities",
                "review_id": "review-merge",
                "source_entity_id": "review-merge-source",
                "target_entity_id": "review-merge-target",
                "reviewed_by_user_id": actor.id,
            },
            {
                "action": "approve_claim",
                "review_id": "review-approve",
                "claim_ids": ["review-approve-claim"],
                "reviewed_by_user_id": actor.id,
            },
            {
                "action": "split_entity",
                "review_id": "review-split",
                "source_entity_id": "review-split-source",
                "new_entity_id": "review-split-new",
                "canonical_name": "拆分制度",
                "entity_type": "Document",
                "mention_ids": ["review-split-move-mention"],
                "claim_ids": ["review-split-move-claim"],
                "reviewed_by_user_id": actor.id,
            },
        )
        affected: set[str] = set()
        for decision in decisions:
            affected.update(
                await knowledge_graph.stage_review_decision(
                    db,
                    knowledge_base,
                    revision,
                    decision,
                )
            )
        assert {
            "review-merge-source",
            "review-merge-target",
            "review-object",
            "review-split-source",
            "review-split-new",
        } <= affected
        for review_id in ("review-merge", "review-approve", "review-split"):
            review = await graph_repository.get_review_item(db, revision, review_id)
            assert review is not None
            assert review.status == "approved"
        await db.commit()

        revision = await graph_repository.get_revision(
            db,
            knowledge_base,
            revision.id,
        )
        assert revision is not None
        published = await graph_revisions.publish_revision(
            db,
            knowledge_base,
            revision,
        )

        merge_source = await graph_repository.get_entity(
            db,
            published,
            "review-merge-source",
        )
        split_entity = await graph_repository.get_entity(
            db,
            published,
            "review-split-new",
        )
        assert merge_source is not None and merge_source.state == "merged"
        assert split_entity is not None and split_entity.canonical_name == "拆分制度"
        aliases = await graph_repository.list_active_aliases_for_entity_ids(
            db,
            knowledge_base,
            {"review-merge-target"},
        )
        assert {item.alias for item in aliases} >= {"旧制度", "旧规"}

        merge_mention = await graph_repository.get_mention(
            db,
            published,
            "review-merge-mention",
        )
        split_move_mention = await graph_repository.get_mention(
            db,
            published,
            "review-split-move-mention",
        )
        split_keep_mention = await graph_repository.get_mention(
            db,
            published,
            "review-split-keep-mention",
        )
        assert merge_mention is not None
        assert merge_mention.entity_id == "review-merge-target"
        assert merge_mention.resolution_method == "human"
        assert split_move_mention is not None
        assert split_move_mention.entity_id == "review-split-new"
        assert split_keep_mention is not None
        assert split_keep_mention.entity_id == "review-split-source"

        merge_claim = await graph_repository.get_claim(
            db,
            published,
            "review-merge-claim",
        )
        merged_duplicate = await graph_repository.get_claim(
            db,
            published,
            "review-retired-duplicate",
        )
        approve_claim = await graph_repository.get_claim(
            db,
            published,
            "review-approve-claim",
        )
        split_move_claim = await graph_repository.get_claim(
            db,
            published,
            "review-split-move-claim",
        )
        split_keep_claim = await graph_repository.get_claim(
            db,
            published,
            "review-split-keep-claim",
        )
        assert merge_claim is not None
        assert merge_claim.status == "superseded"
        assert merge_claim.retired_revision_id == published.id
        assert merged_duplicate is not None
        assert merged_duplicate.subject_entity_id == "review-merge-target"
        assert merged_duplicate.status == "active"
        assert merged_duplicate.source_kind == "human"
        assert merged_duplicate.retired_revision_id is None
        assert approve_claim is not None
        assert approve_claim.status == "active"
        assert approve_claim.source_kind == "human"
        assert split_move_claim is not None
        assert split_move_claim.subject_entity_id == "review-split-new"
        assert split_keep_claim is not None
        assert split_keep_claim.subject_entity_id == "review-split-source"

        for review_id in ("review-merge", "review-approve", "review-split"):
            review = await graph_repository.get_review_item(
                db,
                published,
                review_id,
            )
            assert review is not None
            assert review.status == "resolved"
            assert review.revision_id == published.id

        await knowledge_graph.reset_review_decision(
            db,
            knowledge_base,
            {"review_id": "review-reset"},
        )
        reset_review = await graph_repository.get_review_item(
            db,
            published,
            "review-reset",
        )
        assert reset_review is not None
        assert reset_review.status == "open"
        assert reset_review.decision_json == {}
        assert reset_review.reviewed_by_user_id is None
        try:
            await knowledge_graph.stage_review_decision(
                db,
                knowledge_base,
                published,
                ["invalid"],  # type: ignore[arg-type]
            )
        except ValueError:
            pass
        else:
            raise AssertionError("non-object review decisions must fail")


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
            options={
                "trusted_structured_import": True,
                "structured_document_ids": ["graph-task-doc-2"],
            },
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
        assert follower_b.options["structured_document_ids"] == [
            "graph-task-doc-2"
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


async def test_graph_rebuild_follows_running_task_and_coalesces_sync() -> None:
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-rebuild-follower-kb",
                workspace_id="graph-workspace",
                name="Graph Rebuild Follower KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-rebuild-follower-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="rebuild.md",
                content_type="text/markdown",
                size_bytes=10,
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.save_knowledge_document_chunk(
            db,
            KnowledgeDocumentChunk(
                id="graph-rebuild-follower-chunk",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                content="rebuild",
                search_text="rebuild",
                char_count=7,
                token_count=1,
                status="indexed",
            ),
        )
        running = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-rebuild-running-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="running",
                attempts=1,
                options={"changed_document_ids": [document.id]},
                created_by_user_id=actor.id,
                started_at=utc_now() - timedelta(seconds=10),
                lease_expires_at=utc_now() + timedelta(minutes=5),
                worker_task_id="graph-rebuild-running-worker",
                created_at=utc_now() - timedelta(minutes=1),
            ),
        )
        queued_sync = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-rebuild-queued-sync",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="queued",
                options={"changed_document_ids": [document.id]},
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()

        rebuild = await enqueue_graph_rebuild(db, knowledge_base, actor)
        assert rebuild.task_type == "graph_rebuild"
        assert rebuild.status == "queued"
        assert rebuild.options["follower_of_task_id"] == running.id
        coalesced = await knowledge_repository.get_knowledge_task_by_id(
            db,
            queued_sync.id,
        )
        assert coalesced is not None
        assert coalesced.status == "succeeded"
        assert coalesced.last_error == f"Coalesced into graph rebuild {rebuild.id}."

        claimed = await knowledge_repository.claim_knowledge_task(
            db,
            rebuild.id,
            utc_now(),
            utc_now() + timedelta(minutes=5),
            "graph-rebuild-follower-worker",
        )
        assert claimed is False
        running.status = "succeeded"
        running.lease_expires_at = None
        running.worker_task_id = None
        await knowledge_repository.save_knowledge_task(db, running)
        await db.commit()
        claimed = await knowledge_repository.claim_knowledge_task(
            db,
            rebuild.id,
            utc_now(),
            utc_now() + timedelta(minutes=5),
            "graph-rebuild-follower-worker",
        )
        assert claimed is True
        await db.rollback()


async def test_graph_tasks_can_be_stopped_retried_and_deleted() -> None:
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-task-control-kb",
                workspace_id="graph-workspace",
                name="Graph Task Control KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-task-control",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_rebuild",
                status="running",
                attempts=1,
                total_items=175,
                processed_items=1,
                options={
                    "graph_retry_mode": "unfinished",
                    "graph_resume_revision_id": "old-revision",
                },
                worker_task_id="graph-task-worker",
                lease_expires_at=utc_now() + timedelta(minutes=5),
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()

        stopped = await stop_knowledge_task(db, knowledge_base, task.id, actor)
        assert stopped.status == "cancelling"
        assert (await knowledge_repository.get_open_graph_task(db, knowledge_base)).id == task.id
        assert not await knowledge_repository.update_owned_knowledge_task_progress(
            db,
            task.id,
            "graph-task-worker",
            175,
            2,
            utc_now() + timedelta(minutes=5),
        )
        current = await knowledge_repository.get_knowledge_task_by_id(db, task.id)
        assert current is not None
        assert current.status == "cancelling"
        assert current.processed_items == 1
        try:
            await delete_knowledge_task(db, knowledge_base, task.id, actor)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("cancelling tasks must not be deleted")

        await knowledge_task_runner.mark_knowledge_task_cancelled(
            db,
            task.id,
            "graph-task-worker",
        )
        try:
            await retry_knowledge_task(
                db,
                knowledge_base,
                task.id,
                actor,
                "unfinished",
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("missing graph checkpoints must not be resumed")
        retried = await retry_knowledge_task(db, knowledge_base, task.id, actor)
        assert retried.status == "queued"
        assert retried.processed_items == 0
        current = await knowledge_repository.get_knowledge_task_by_id(db, task.id)
        assert current is not None
        assert "graph_retry_mode" not in current.options
        assert "graph_resume_revision_id" not in current.options
        stopped = await stop_knowledge_task(db, knowledge_base, task.id, actor)
        assert stopped.status == "cancelled"
        await delete_knowledge_task(db, knowledge_base, task.id, actor)
        assert await knowledge_repository.get_knowledge_task_by_id(db, task.id) is None


async def test_knowledge_tasks_bulk_delete_is_atomic() -> None:
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-task-bulk-delete-kb",
                workspace_id="graph-workspace",
                name="Graph Task Bulk Delete KB",
                created_by_user_id=actor.id,
            ),
        )
        tasks = [
            await knowledge_repository.create_knowledge_task(
                db,
                KnowledgeTask(
                    id=f"graph-task-bulk-delete-{task_status}",
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    task_type="graph_rebuild",
                    status=task_status,
                    created_by_user_id=actor.id,
                ),
            )
            for task_status in ("failed", "succeeded", "running")
        ]
        await db.commit()

        try:
            await delete_knowledge_tasks(
                db,
                knowledge_base,
                [tasks[0].id, tasks[2].id],
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("a batch containing an open task must be atomic")
        remaining = [
            await knowledge_repository.get_knowledge_task_by_id(db, task.id)
            for task in tasks
        ]
        assert all(task is not None for task in remaining)

        tasks[2].status = "cancelled"
        await knowledge_repository.save_knowledge_task(db, tasks[2])
        await db.commit()
        deleted_ids = await delete_knowledge_tasks(
            db,
            knowledge_base,
            [tasks[1].id, tasks[0].id, tasks[2].id, tasks[0].id],
            actor,
        )
        assert deleted_ids == [tasks[1].id, tasks[0].id, tasks[2].id]
        remaining = [
            await knowledge_repository.get_knowledge_task_by_id(db, task.id)
            for task in tasks
        ]
        assert all(task is None for task in remaining)


async def test_graph_retry_can_resume_from_the_last_committed_chunk() -> None:
    contents = {
        "graph-resume-chunk-a": "制度 A 定义术语 A。",
        "graph-resume-chunk-b": "制度 B 定义术语 B。",
    }

    real_extract = knowledge_graph_build.extract_graph_batch
    first_chunk_ids: list[str] = []

    def failing_extract(schema, chunks, lexicon=()):
        chunk_id = chunks[0].chunk_id
        first_chunk_ids.append(chunk_id)
        if chunk_id == "graph-resume-chunk-b":
            raise RuntimeError("second chunk failed")
        return real_extract(schema, chunks, lexicon)

    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-resume-kb",
                workspace_id="graph-workspace",
                name="Graph Resume KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-resume-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="resume.md",
                content_type="text/markdown",
                size_bytes=sum(len(item.encode()) for item in contents.values()),
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        for index, (chunk_id, content) in enumerate(contents.items()):
            await knowledge_repository.save_knowledge_document_chunk(
                db,
                KnowledgeDocumentChunk(
                    id=chunk_id,
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    document_id=document.id,
                    chunk_index=index,
                    content=content,
                    search_text=content,
                    char_count=len(content),
                    token_count=8,
                    status="indexed",
                ),
            )
        task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-resume-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="running",
                attempts=1,
                options={"changed_document_ids": [document.id]},
                created_by_user_id=actor.id,
                worker_task_id="graph-resume-worker-1",
            ),
        )
        await db.commit()

        with (
            patch.object(
                knowledge_graph_build,
                "extract_graph_batch",
                side_effect=failing_extract,
            ),
            patch.object(
                knowledge_graph_build,
                "stage_entity_profiles",
                AsyncMock(),
            ),
            patch.object(
                graph_repository,
                "list_entity_identity_candidates",
                AsyncMock(
                    side_effect=AssertionError("entity resolution must use its batch cache")
                ),
            ),
            patch.object(
                graph_repository,
                "list_human_alias_entity_ids",
                AsyncMock(
                    side_effect=AssertionError("alias resolution must use its batch cache")
                ),
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
                assert str(exc) == "second chunk failed"
            else:
                raise AssertionError("the second chunk must fail the first build")
        assert first_chunk_ids == [
            "graph-resume-chunk-a",
            "graph-resume-chunk-b",
        ]

        failed_task = await knowledge_repository.get_knowledge_task_by_id(db, task.id)
        assert failed_task is not None
        assert failed_task.processed_items == 1
        failed_task.status = "failed"
        failed_task.worker_task_id = None
        failed_task.lease_expires_at = None
        await knowledge_repository.save_knowledge_task(db, failed_task)
        await db.commit()
        failed_revision = await graph_repository.get_latest_revision(
            db,
            knowledge_base,
        )
        assert failed_revision is not None
        assert failed_revision.status == "failed"

        retried = await retry_knowledge_task(
            db,
            knowledge_base,
            task.id,
            actor,
            "unfinished",
        )
        assert retried.status == "queued"
        assert retried.processed_items == 1
        resumed_task = await knowledge_repository.get_knowledge_task_by_id(db, task.id)
        assert resumed_task is not None
        assert resumed_task.options["graph_resume_revision_id"] == failed_revision.id
        resumed_task.status = "running"
        resumed_task.worker_task_id = "graph-resume-worker-2"
        resumed_task.attempts += 1
        await knowledge_repository.save_knowledge_task(db, resumed_task)
        await db.commit()

        resumed_chunk_ids: list[str] = []

        def resumed_extract(schema, chunks, lexicon=()):
            resumed_chunk_ids.append(chunks[0].chunk_id)
            return real_extract(schema, chunks, lexicon)

        async def fake_embedding_model(*_args, **_kwargs):
            return SimpleNamespace(id="graph-resume-embedding")

        with (
            patch.object(
                knowledge_graph_build,
                "extract_graph_batch",
                side_effect=resumed_extract,
            ),
            patch.object(
                knowledge_graph_build,
                "stage_entity_profiles",
                AsyncMock(),
            ),
            patch.object(
                knowledge_graph_build,
                "resolve_embedding_model",
                fake_embedding_model,
            ),
            patch.object(
                knowledge_graph_build,
                "upsert_graph_profile_vectors",
            ),
            patch.object(
                graph_repository,
                "list_entity_identity_candidates",
                AsyncMock(
                    side_effect=AssertionError("entity resolution must use its batch cache")
                ),
            ),
            patch.object(
                graph_repository,
                "list_human_alias_entity_ids",
                AsyncMock(
                    side_effect=AssertionError("alias resolution must use its batch cache")
                ),
            ),
        ):
            await knowledge_graph_build.run_graph_build_task(
                db,
                resumed_task,
                knowledge_base,
                actor,
                tests.support.settings(),
                asyncio.Event(),
            )
        assert resumed_chunk_ids == ["graph-resume-chunk-b"]

    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-resume-kb",
        )
        assert knowledge_base is not None
        published = await graph_repository.get_active_revision(db, knowledge_base)
        assert published is not None
        assert published.id == failed_revision.id
        claims = list(
            (
                await db.scalars(
                    select(KnowledgeGraphClaim).where(
                        KnowledgeGraphClaim.knowledge_base_id == knowledge_base.id
                    )
                )
            ).all()
        )
        assert len(claims) == 2


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
                meta={
                    "import_mode": "graph",
                    "document_version": 2,
                    "normalized_content_hash": "structured-content-hash",
                },
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
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-kb",
        )
        assert knowledge_base is not None
        revision = await graph_repository.get_active_revision(db, knowledge_base)
        assert revision is not None
        assert revision.stats_json["task_id"] == "structured-graph-task"
        assert revision.stats_json["source_versions"][document.id] == (
            "2:structured-content-hash:1:indexed"
        )
        assert revision.stats_json["documents_processed"] == 1
        assert revision.stats_json["chunks_processed"] == 1
        assert set(revision.stats_json["stage_duration_ms"]) == set(
            knowledge_graph_build.GRAPH_BUILD_STAGES
        )
        assert all(
            value >= 0
            for value in revision.stats_json["stage_duration_ms"].values()
        )
        publish_audit = await db.scalar(
            select(AuditLog)
            .where(
                AuditLog.workspace_id == knowledge_base.workspace_id,
                AuditLog.action == "knowledge_graph.revision.publish",
                AuditLog.resource_id == revision.id,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
        assert publish_audit is not None
        assert set(publish_audit.details) <= {
            "knowledge_base_id",
            "revision_id",
            "task_id",
            "action",
            "record_count",
            "status",
        }
        assert publish_audit.details["status"] == "published"


async def test_graph_build_does_not_consume_workspace_model_budget() -> None:
    content = "制度 A 定义术语 A。"
    async with get_session_factory()() as db:
        _, actor, _ = await _graph_fixture(db)
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-budget-limit-kb",
                workspace_id="graph-workspace",
                name="Graph Budget Limit KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        schema = await create_graph_schema(
            db,
            knowledge_base,
            default_graph_schema(),
            actor,
        )
        await graph_repository.create_revision(
            db,
            GraphRevisionRecord(
                id="graph-budget-prior-revision",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                revision_no=1,
                schema_id=schema.id,
                status="failed",
                source_watermark="prior",
                model_usage_json={"charged_tokens": 9_500},
                created_by_user_id=actor.id,
            ),
        )
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-budget-limit-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="budget.md",
                content_type="text/markdown",
                size_bytes=len(content.encode("utf-8")),
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.save_knowledge_document_chunk(
            db,
            KnowledgeDocumentChunk(
                id="graph-budget-limit-chunk",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                content=content,
                search_text=content,
                char_count=len(content),
                token_count=8,
                status="indexed",
            ),
        )
        task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-budget-limit-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="running",
                attempts=1,
                options={"changed_document_ids": [document.id]},
                created_by_user_id=actor.id,
            ),
        )
        await governance_repository.save(
            db,
            WorkspaceGovernance(
                workspace_id=knowledge_base.workspace_id,
                monthly_token_limit=10_000,
                updated_by_user_id=actor.id,
            ),
        )
        await db.commit()

        async def fake_embedding_model(*_args, **_kwargs):
            return SimpleNamespace(id="graph-budget-embedding")

        with (
            patch.object(
                knowledge_graph_build,
                "resolve_embedding_model",
                fake_embedding_model,
            ),
            patch.object(
                knowledge_graph_build,
                "upsert_graph_profile_vectors",
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
        await governance_repository.save(
            db,
            WorkspaceGovernance(
                workspace_id=knowledge_base.workspace_id,
                monthly_token_limit=None,
                updated_by_user_id=actor.id,
            ),
        )
        await db.commit()

    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-budget-limit-kb",
        )
        assert knowledge_base is not None
        revision = await graph_repository.get_active_revision(db, knowledge_base)
        assert revision is not None
        assert revision.status == "published"
        assert revision.model_usage_json == {}


async def test_rule_graph_build_persists_exact_evidence_without_model_usage() -> None:
    content = "制度 A 定义术语 A。"
    quote = content[:-1]
    async with get_session_factory()() as db:
        _, actor, _ = await _graph_fixture(db)
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-budget-usage-kb",
                workspace_id="graph-workspace",
                name="Graph Budget Usage KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        document = await knowledge_repository.create_knowledge_document(
            db,
            KnowledgeDocument(
                id="graph-budget-usage-doc",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                filename="usage.md",
                content_type="text/markdown",
                size_bytes=len(content.encode("utf-8")),
                status="indexed",
                created_by_user_id=actor.id,
            ),
        )
        await knowledge_repository.save_knowledge_document_chunk(
            db,
            KnowledgeDocumentChunk(
                id="graph-budget-usage-chunk",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                content=content,
                search_text=content,
                char_count=len(content),
                token_count=8,
                status="indexed",
            ),
        )
        task = await knowledge_repository.create_knowledge_task(
            db,
            KnowledgeTask(
                id="graph-budget-usage-task",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_type="graph_sync",
                status="running",
                attempts=1,
                options={"changed_document_ids": [document.id]},
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()

        runtime_settings = tests.support.settings()

        async def fake_embedding_model(*_args, **_kwargs):
            return SimpleNamespace(id="graph-budget-embedding")

        with (
            patch.object(
                knowledge_graph_build,
                "resolve_embedding_model",
                fake_embedding_model,
            ),
            patch.object(
                knowledge_graph_build,
                "upsert_graph_profile_vectors",
            ),
        ):
            await knowledge_graph_build.run_graph_build_task(
                db,
                task,
                knowledge_base,
                actor,
                runtime_settings,
                asyncio.Event(),
            )

    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-budget-usage-kb",
        )
        assert knowledge_base is not None
        revision = await graph_repository.get_active_revision(db, knowledge_base)
        assert revision is not None
        assert revision.model_usage_json == {}
        evidence = await db.scalar(
            select(KnowledgeGraphClaimEvidence).where(
                KnowledgeGraphClaimEvidence.knowledge_base_id == knowledge_base.id
            )
        )
        assert evidence is not None
        assert evidence.quote == quote
        assert (evidence.start_offset, evidence.end_offset) == (0, len(quote))
        assert evidence.extractor_type == "rules"
        assert evidence.model_name == ""


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
        assert set(revision.stats_json["stage_duration_ms"]) == set(
            knowledge_graph_build.GRAPH_BUILD_STAGES
        )


async def test_graph_import_persists_immutable_records_and_queues_sync() -> None:
    content = (
        json.dumps(GRAPH_IMPORT_RECORD, ensure_ascii=False)
        + "\n"
        + json.dumps(
            {
                **GRAPH_IMPORT_RECORD,
                "subject": {
                    **GRAPH_IMPORT_RECORD["subject"],
                    "canonical_name": "制度 B",
                    "external_key": "policy-b",
                },
            },
            ensure_ascii=False,
        )
    ).encode()
    settings = tests.support.settings()
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-import-kb",
                workspace_id="graph-workspace",
                name="Graph Import KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()
        task_response = await knowledge_graph.import_graph_records(
            db,
            knowledge_base,
            UploadFile(BytesIO(content), filename="records.jsonl"),
            actor,
            settings,
        )
        task = await knowledge_repository.get_knowledge_task_by_id(
            db,
            task_response.id,
        )
        assert task is not None
        assert task.task_type == "graph_sync"
        assert task.options["trusted_structured_import"] is True

        documents = await knowledge_repository.list_knowledge_documents(
            db,
            knowledge_base,
            include_staged=True,
        )
        assert len(documents) == 1
        document = documents[0]
        assert document.status == "indexed"
        assert document.meta["import_mode"] == "graph"
        assert document.meta["document_version"] == 1
        attachment = await knowledge_repository.get_knowledge_attachment_by_id(
            db,
            document.attachment_id or "",
        )
        assert attachment is not None
        assert attachment.status == "consumed"
        assert settings.knowledge_storage_dir.joinpath(document.storage_path).read_bytes() == content
        chunks = await knowledge_repository.list_document_chunks(
            db,
            knowledge_base,
            document.id,
        )
        assert len(chunks) == 2
        assert all(item.kind == "graph_record" for item in chunks)
        assert all(item.status == "indexed" for item in chunks)
        assert all(item.vector_id is None for item in chunks)
        assert "制度 A\ndefines\n术语 A" in chunks[0].search_text
        import_audit = await db.scalar(
            select(AuditLog)
            .where(
                AuditLog.workspace_id == knowledge_base.workspace_id,
                AuditLog.action == "knowledge_graph.records.import",
                AuditLog.resource_id == document.id,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
        assert import_audit is not None
        assert import_audit.details == {
            "knowledge_base_id": knowledge_base.id,
            "action": "import",
            "record_count": 2,
            "status": "queued",
        }
        try:
            await enqueue_index_knowledge_document(
                db,
                knowledge_base,
                document,
                actor,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("graph records must not enter the chunk vector index")


async def test_claim_survives_until_last_evidence_is_deleted() -> None:
    quote = "制度 A 定义术语 A。"
    settings = tests.support.settings()
    async with get_session_factory()() as db:
        actor = await user_repository.get_user_by_id(db, "graph-user")
        assert actor is not None
        knowledge_base = await knowledge_repository.create_knowledge_base(
            db,
            KnowledgeBase(
                id="graph-evidence-lifecycle-kb",
                workspace_id="graph-workspace",
                name="Graph Evidence Lifecycle KB",
                graph_enabled=True,
                created_by_user_id=actor.id,
            ),
        )
        schema = await create_graph_schema(
            db,
            knowledge_base,
            default_graph_schema(),
            actor,
        )
        revision = await graph_revisions.create_revision(
            db,
            knowledge_base,
            schema,
            actor.id,
            "evidence-lifecycle",
        )
        await db.commit()
        revision = await graph_revisions.publish_revision(
            db,
            knowledge_base,
            revision,
        )
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            knowledge_base.id,
        )
        assert knowledge_base is not None

        documents: list[KnowledgeDocument] = []
        chunks: list[KnowledgeDocumentChunk] = []
        for suffix in ("a", "b"):
            document = await knowledge_repository.create_knowledge_document(
                db,
                KnowledgeDocument(
                    id=f"graph-evidence-document-{suffix}",
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    filename=f"evidence-{suffix}.txt",
                    content_type="text/plain",
                    size_bytes=len(quote.encode()),
                    storage_path=f"missing/evidence-{suffix}.txt",
                    status="indexed",
                    created_by_user_id=actor.id,
                ),
            )
            chunk = KnowledgeDocumentChunk(
                id=f"graph-evidence-chunk-{suffix}",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                content=quote,
                search_text=quote,
                char_count=len(quote),
                token_count=8,
                status="indexed",
            )
            await knowledge_repository.save_knowledge_document_chunk(db, chunk)
            documents.append(document)
            chunks.append(chunk)

        subject_id = "graph-evidence-subject"
        object_id = "graph-evidence-object"
        for entity_id, entity_type, name in (
            (subject_id, "Document", "制度 A"),
            (object_id, "Concept", "术语 A"),
        ):
            await graph_repository.create_entity(
                db,
                GraphEntityRecord(
                    id=entity_id,
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    entity_type=entity_type,
                    canonical_name=name,
                    normalized_name=name.casefold(),
                    state="active",
                    created_revision_id=revision.id,
                    last_published_revision_id=revision.id,
                ),
            )
        fingerprint = claim_fingerprint(
            subject_id,
            "defines",
            object_id,
            None,
            None,
            None,
        )
        claim = await graph_repository.create_claim(
            db,
            GraphClaimRecord(
                id="graph-evidence-claim",
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                subject_entity_id=subject_id,
                predicate="defines",
                object_entity_id=object_id,
                status="active",
                source_kind="structured_import",
                quality_score=1.0,
                support_count=2,
                fingerprint=fingerprint,
                created_revision_id=revision.id,
                last_published_revision_id=revision.id,
            ),
        )
        for index, (document, chunk) in enumerate(zip(documents, chunks, strict=True)):
            await graph_repository.create_evidence(
                db,
                GraphEvidenceRecord(
                    id=f"graph-evidence-{index}",
                    workspace_id=knowledge_base.workspace_id,
                    knowledge_base_id=knowledge_base.id,
                    claim_id=claim.id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    quote=quote,
                    start_offset=0,
                    end_offset=len(quote),
                    extractor_type="structured",
                    prompt_hash="structured-import",
                    schema_hash=graph_schema_hash(default_graph_schema()),
                    created_revision_id=revision.id,
                    last_published_revision_id=revision.id,
                ),
            )
        await db.commit()
        assert await graph_repository.list_traversable_claim_ids(
            db,
            knowledge_base,
        ) == [claim.id]

    for index, document_id in enumerate(
        ["graph-evidence-document-a", "graph-evidence-document-b"]
    ):
        async with get_session_factory()() as db:
            knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
                db,
                "graph-evidence-lifecycle-kb",
            )
            actor = await user_repository.get_user_by_id(db, "graph-user")
            document = await knowledge_repository.get_knowledge_document_by_id(
                db,
                document_id,
            )
            assert knowledge_base is not None
            assert actor is not None
            assert document is not None
            await knowledge_lifecycle.set_knowledge_document_active(
                db,
                knowledge_base,
                document,
                actor,
                False,
            )
            traversable = await graph_repository.list_traversable_claim_ids(
                db,
                knowledge_base,
            )
            assert traversable == (["graph-evidence-claim"] if index == 0 else [])

    for document_id in (
        "graph-evidence-document-a",
        "graph-evidence-document-b",
    ):
        async with get_session_factory()() as db:
            knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
                db,
                "graph-evidence-lifecycle-kb",
            )
            actor = await user_repository.get_user_by_id(db, "graph-user")
            document = await knowledge_repository.get_knowledge_document_by_id(
                db,
                document_id,
            )
            assert knowledge_base is not None
            assert actor is not None
            assert document is not None
            await knowledge_lifecycle.set_knowledge_document_active(
                db,
                knowledge_base,
                document,
                actor,
                True,
            )
    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-evidence-lifecycle-kb",
        )
        assert knowledge_base is not None
        assert await graph_repository.list_traversable_claim_ids(
            db,
            knowledge_base,
        ) == ["graph-evidence-claim"]

    for index, document_id in enumerate(
        ["graph-evidence-document-a", "graph-evidence-document-b"]
    ):
        async with get_session_factory()() as db:
            knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
                db,
                "graph-evidence-lifecycle-kb",
            )
            actor = await user_repository.get_user_by_id(db, "graph-user")
            document = await knowledge_repository.get_knowledge_document_by_id(
                db,
                document_id,
            )
            assert knowledge_base is not None
            assert actor is not None
            assert document is not None
            await knowledge_lifecycle.delete_knowledge_document(
                db,
                knowledge_base,
                document,
                actor,
                settings,
            )
            traversable = await graph_repository.list_traversable_claim_ids(
                db,
                knowledge_base,
            )
            assert traversable == (["graph-evidence-claim"] if index == 0 else [])

    async with get_session_factory()() as db:
        knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
            db,
            "graph-evidence-lifecycle-kb",
        )
        assert knowledge_base is not None
        queued = await knowledge_repository.get_queued_graph_sync(db, knowledge_base)
        assert queued is not None
        assert queued.options["changed_document_ids"] == [
            "graph-evidence-document-a",
            "graph-evidence-document-b",
        ]


async def main() -> None:
    test_graph_import_parser_is_atomic_and_bounded()
    test_graph_source_batches_keep_structured_and_text_chunks_separate()
    test_graph_source_versions_are_stable_and_diffable()
    await test_graph_source_reconcile_queues_sync_and_model_rebuild()
    await test_graph_source_reconcile_waits_for_active_and_failed_tasks()
    await test_graph_source_reconcile_keeps_deleted_failed_task_stopped()
    test_bank_path_preserves_relation_direction_and_evidence()
    test_policy_graph_evaluation_preserves_fixed_citations()
    test_graph_traversal_sql_requires_acyclic_active_evidence()
    await test_graph_traversal_bounds_scoping_and_truncation()
    await test_graph_query_candidates_require_unique_entities_and_keep_hops()
    await test_graph_retrieval_fuses_evidence_without_changing_off_mode()
    await test_graph_query_off_skips_graph_dependencies()
    await test_graph_query_drops_stale_profiles_and_rejects_unknown_relations()
    await test_graph_query_planning_edge_paths()
    test_graph_profile_collection_is_knowledge_base_scoped()
    test_graph_profile_vectors_use_an_isolated_collection()
    await test_graph_storage_cleanup_removes_both_vector_collections()
    await test_graph_database_constraints()
    await test_versioned_graph_schemas()
    await test_graph_maintenance_repairs_orphans_profiles_and_sources()
    await test_revision_publish_is_atomic()
    await test_review_decisions_publish_atomically_and_reset_on_failure()
    await test_entity_identity_candidates_are_scoped_and_ambiguous()
    await test_stale_revision_cannot_overwrite_newer_graph()
    await test_claim_fingerprint_dedupes_without_reactivating_rejection()
    await test_graph_sync_coalesces_behind_running_build()
    await test_graph_rebuild_follows_running_task_and_coalesces_sync()
    await test_graph_tasks_can_be_stopped_retried_and_deleted()
    await test_knowledge_tasks_bulk_delete_is_atomic()
    await test_graph_retry_can_resume_from_the_last_committed_chunk()
    await test_structured_graph_build_publishes_evidence_and_profiles()
    await test_graph_build_does_not_consume_workspace_model_budget()
    await test_rule_graph_build_persists_exact_evidence_without_model_usage()
    await test_index_success_queues_graph_sync_when_enabled()
    await test_failed_profile_write_keeps_revision_unpublished_for_repair()
    await test_graph_import_persists_immutable_records_and_queues_sync()
    await test_claim_survives_until_last_evidence_is_deleted()
    print("OK: knowledge_graph")


if __name__ == "__main__":
    asyncio.run(main())

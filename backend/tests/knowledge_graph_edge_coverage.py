"""Additional persistent graph coverage edges.

Run from backend/: uv run python -m tests.knowledge_graph_edge_coverage
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import tests.support  # noqa: F401
from app.application import knowledge_graph
from app.entities.knowledge import KnowledgeBase, KnowledgeTask
from app.entities.knowledge_graph import (
    KnowledgeGraphAlias,
    KnowledgeGraphClaim,
    KnowledgeGraphClaimEvidence,
    KnowledgeGraphMention,
    KnowledgeGraphRevision,
    KnowledgeGraphRevisionChange,
    KnowledgeGraphReviewItem,
)
from app.entities.user import User
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.schemas.knowledge import KnowledgeQueryRequest
from app.schemas.knowledge_graph import (
    KnowledgeGraphNeighborhoodRequest,
    KnowledgeGraphPathRequest,
    KnowledgeGraphSchemaUpdateRequest,
    KnowledgeGraphSettingsUpdateRequest,
)
from app.shareddomain.knowledge_graph import revisions as graph_revisions
from app.shareddomain.knowledge_graph.revisions import GraphRevisionConflict
from app.shareddomain.knowledge_graph.schema import default_graph_schema


async def _expect_http(coroutine, status_code: int) -> None:
    try:
        await coroutine
    except HTTPException as exc:
        assert exc.status_code == status_code
    else:
        raise AssertionError(f"expected HTTP {status_code}")


async def test_graph_application_edge_paths() -> None:
    knowledge_base = KnowledgeBase(
        id="application-edge-kb",
        workspace_id="application-edge-workspace",
        name="Application Edge",
        embedding_model_id="embedding-model",
        graph_extraction_model_id="extraction-model",
    )
    actor = User(id="application-edge-user", name="Application Edge User")

    with patch(
        "app.application.knowledge.dispatch_knowledge_task",
        new=AsyncMock(),
    ) as dispatch:
        await knowledge_graph._dispatch_graph_task("dispatch-task", SimpleNamespace())
    dispatch.assert_awaited_once()

    initial_db = AsyncMock()
    initial_settings = SimpleNamespace()
    with (
        patch.object(
            knowledge_graph,
            "enqueue_graph_rebuild",
            AsyncMock(return_value=SimpleNamespace(id="initial-graph-task")),
        ) as enqueue_initial,
        patch.object(
            knowledge_graph,
            "_dispatch_graph_task",
            AsyncMock(),
        ) as dispatch_initial,
    ):
        await knowledge_graph._enqueue_initial_graph_build(
            initial_db,
            knowledge_base,
            actor,
            initial_settings,
        )
    enqueue_initial.assert_awaited_once_with(initial_db, knowledge_base, actor)
    dispatch_initial.assert_awaited_once_with(
        "initial-graph-task",
        initial_settings,
    )

    with (
        patch.object(
            knowledge_graph,
            "enqueue_graph_rebuild",
            AsyncMock(side_effect=RuntimeError("busy")),
        ),
        patch.object(knowledge_graph, "log_error") as log_initial_error,
    ):
        await knowledge_graph._enqueue_initial_graph_build(
            initial_db,
            knowledge_base,
            actor,
            initial_settings,
        )
    initial_db.rollback.assert_awaited_once()
    log_initial_error.assert_called_once()

    with (
        patch.object(
            knowledge_graph,
            "get_knowledge_base",
            AsyncMock(return_value=knowledge_base),
        ),
        patch.object(
            knowledge_graph,
            "require_knowledge_base_permission",
            AsyncMock(),
        ) as require_permission,
    ):
        assert (
            await knowledge_graph.require_graph_knowledge_base(
                SimpleNamespace(),
                knowledge_base.workspace_id,
                knowledge_base.id,
                actor,
                "member",
                {"read"},
            )
        ) is knowledge_base
    require_permission.assert_awaited_once()

    with patch.object(
        knowledge_graph,
        "get_knowledge_model",
        AsyncMock(
            side_effect=[
                SimpleNamespace(id="extraction-model"),
                None,
            ]
        ),
    ):
        await _expect_http(
            knowledge_graph._validate_graph_build_requirements(
                SimpleNamespace(), knowledge_base, "extraction-model"
            ),
            422,
        )
    with (
        patch.object(
            knowledge_graph,
            "get_knowledge_model",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id="extraction-model"),
                    SimpleNamespace(id="embedding-model"),
                ]
            ),
        ),
        patch.object(
            knowledge_repository,
            "has_indexed_knowledge_document",
            AsyncMock(return_value=False),
        ),
    ):
        await _expect_http(
            knowledge_graph._validate_graph_build_requirements(
                SimpleNamespace(), knowledge_base, "extraction-model"
            ),
            409,
        )

    with patch.object(
        knowledge_repository,
        "lock_knowledge_base",
        AsyncMock(return_value=None),
    ):
        await _expect_http(
            knowledge_graph.update_graph_settings(
                SimpleNamespace(),
                knowledge_base,
                KnowledgeGraphSettingsUpdateRequest(enabled=False),
                actor,
                SimpleNamespace(),
            ),
            404,
        )

    locked = KnowledgeBase(**knowledge_base.__dict__)
    db = AsyncMock()
    initial_settings = SimpleNamespace()
    with (
        patch.object(
            knowledge_repository,
            "lock_knowledge_base",
            AsyncMock(return_value=locked),
        ),
        patch.object(
            knowledge_graph,
            "get_knowledge_model",
            AsyncMock(return_value=None),
        ),
        patch.object(knowledge_repository, "save_knowledge_base", AsyncMock()),
        patch.object(
            knowledge_repository,
            "refresh_knowledge_base",
            AsyncMock(return_value=locked),
        ),
        patch.object(knowledge_graph, "record_audit_log"),
    ):
        settings_response = await knowledge_graph.update_graph_settings(
            db,
            knowledge_base,
            KnowledgeGraphSettingsUpdateRequest(
                enabled=False,
                extraction_model_id="missing-model",
            ),
            actor,
            initial_settings,
        )
    assert settings_response.extraction_model_id is None

    locked = KnowledgeBase(**knowledge_base.__dict__)
    db = AsyncMock()
    with (
        patch.object(
            knowledge_repository,
            "lock_knowledge_base",
            AsyncMock(return_value=locked),
        ),
        patch.object(
            knowledge_graph,
            "_validate_graph_build_requirements",
            AsyncMock(return_value=("extraction-model", "embedding-model")),
        ),
        patch.object(knowledge_repository, "save_knowledge_base", AsyncMock()),
        patch.object(
            knowledge_repository,
            "refresh_knowledge_base",
            AsyncMock(return_value=locked),
        ),
        patch.object(knowledge_graph, "record_audit_log"),
        patch.object(
            knowledge_graph,
            "_enqueue_initial_graph_build",
            AsyncMock(),
        ) as enqueue_initial,
    ):
        settings_response = await knowledge_graph.update_graph_settings(
            db,
            knowledge_base,
            KnowledgeGraphSettingsUpdateRequest(
                enabled=True,
                extraction_model_id="extraction-model",
            ),
            actor,
            initial_settings,
        )
    assert settings_response.enabled is True
    enqueue_initial.assert_awaited_once_with(
        db,
        locked,
        actor,
        initial_settings,
    )

    with patch.object(
        graph_repository,
        "get_latest_draft_or_active_schema",
        AsyncMock(return_value=None),
    ):
        assert (
            await knowledge_graph.get_graph_schema(
                SimpleNamespace(), knowledge_base
            )
            is None
        )
    await _expect_http(
        knowledge_graph.update_graph_schema(
            SimpleNamespace(),
            knowledge_base,
            KnowledgeGraphSchemaUpdateRequest(schema_json={}),
            actor,
        ),
        422,
    )

    with (
        patch.object(
            graph_repository,
            "get_latest_revision",
            AsyncMock(return_value=None),
        ),
        patch.object(
            graph_repository,
            "list_pending_review_page",
            AsyncMock(return_value=([], 0)),
        ),
        patch.object(
            knowledge_repository,
            "get_open_graph_task",
            AsyncMock(return_value=None),
        ),
    ):
        status_response = await knowledge_graph.get_graph_status(
            SimpleNamespace(), knowledge_base
        )
    assert status_response.revision_no is None
    await _expect_http(
        knowledge_graph.rebuild_graph(
            SimpleNamespace(), knowledge_base, actor, SimpleNamespace()
        ),
        409,
    )

    active_task = KnowledgeTask(
        id="active-graph-rebuild",
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        task_type="graph_rebuild",
        status="running",
        attempts=1,
        created_by_user_id=actor.id,
    )
    enabled_base = KnowledgeBase(
        id="active-graph-kb",
        workspace_id=knowledge_base.workspace_id,
        graph_enabled=True,
        graph_extraction_model_id="extraction-model",
        created_by_user_id=actor.id,
    )
    with (
        patch.object(
            knowledge_graph,
            "_validate_graph_build_requirements",
            AsyncMock(),
        ),
        patch.object(
            knowledge_repository,
            "get_queued_graph_rebuild",
            AsyncMock(return_value=None),
        ),
        patch.object(
            knowledge_repository,
            "get_running_graph_task",
            AsyncMock(return_value=active_task),
        ),
        patch.object(knowledge_graph, "_dispatch_graph_task", AsyncMock()) as dispatch,
    ):
        response = await knowledge_graph.rebuild_graph(
            AsyncMock(),
            enabled_base,
            actor,
            SimpleNamespace(),
        )
    assert response.id == active_task.id
    dispatch.assert_not_awaited()

    entity = SimpleNamespace(
        id="application-edge-entity",
        entity_type="Document",
        canonical_name="制度 A",
        properties_json={},
        profile_markdown="",
        component_id=None,
        degree=0,
    )
    alias = SimpleNamespace(entity_id=entity.id, alias="制度甲")
    with (
        patch.object(
            graph_repository,
            "list_active_entity_page",
            AsyncMock(return_value=([entity], 1)),
        ),
        patch.object(
            graph_repository,
            "list_active_aliases_for_entity_ids",
            AsyncMock(return_value=[alias]),
        ),
    ):
        entities = await knowledge_graph.list_graph_entities(
            SimpleNamespace(),
            knowledge_base,
            query=" 制度 ",
            entity_type=" Document ",
            limit=20,
            offset=0,
        )
    assert entities.items[0].aliases == [alias.alias]
    with patch.object(
        graph_repository,
        "get_active_entity",
        AsyncMock(return_value=None),
    ):
        await _expect_http(
            knowledge_graph.get_graph_entity(
                SimpleNamespace(), knowledge_base, "missing-entity"
            ),
            404,
        )

    traversal = SimpleNamespace(
        revision_id="application-edge-revision",
        operation="path",
        resolved_entities=(),
        nodes=(),
        claims=(),
        paths=(),
        evidence=(),
        visited_nodes=0,
        truncated=False,
        limit_reason=None,
    )
    candidate = SimpleNamespace(operation="path", traversal=traversal)
    with patch.object(
        knowledge_graph.knowledge_graph_query,
        "retrieve_graph_candidates",
        AsyncMock(return_value=candidate),
    ):
        path_response = await knowledge_graph.query_graph_path(
            SimpleNamespace(),
            knowledge_base,
            KnowledgeGraphPathRequest(
                source_entity="制度 A",
                target_entity="制度 B",
            ),
            SimpleNamespace(),
        )
        neighborhood_response = await knowledge_graph.query_graph_neighborhood(
            SimpleNamespace(),
            knowledge_base,
            KnowledgeGraphNeighborhoodRequest(entity="制度 A"),
            SimpleNamespace(),
        )
    assert path_response.revision_id == traversal.revision_id
    assert neighborhood_response.revision_id == traversal.revision_id
    for candidate in (
        SimpleNamespace(operation="off", traversal=None),
        SimpleNamespace(operation="none", traversal=None),
    ):
        with patch.object(
            knowledge_graph.knowledge_graph_query,
            "retrieve_graph_candidates",
            AsyncMock(return_value=candidate),
        ):
            await _expect_http(
                knowledge_graph._execute_graph_query(
                    SimpleNamespace(),
                    knowledge_base,
                    KnowledgeQueryRequest(query="x"),
                    SimpleNamespace(),
                ),
                409,
            )

    review = KnowledgeGraphReviewItem(
        id="application-edge-review",
        kind="ambiguous_entity",
        revision_id=traversal.revision_id,
    )
    with patch.object(
        graph_repository,
        "list_pending_review_page",
        AsyncMock(return_value=([review], 1)),
    ):
        reviews = await knowledge_graph.list_graph_reviews(
            SimpleNamespace(), knowledge_base, limit=20, offset=0
        )
    assert reviews.items[0].id == review.id

    for content in (b"\xff", b"{", b"[]"):
        try:
            knowledge_graph.parse_graph_import_records("records.json", content)
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("invalid graph imports must fail")
    value_record = (
        b'{"subject":{"entity_type":"Document","canonical_name":"A"},'
        b'"predicate":"defines","value":10,"evidence":"A defines 10"}'
    )
    record = knowledge_graph.parse_graph_import_records(
        "records.json", value_record
    )[0]
    assert "10" in knowledge_graph._record_search_text(record)
    assert knowledge_graph._record_content(record)

    await _expect_http(
        knowledge_graph.import_graph_records(
            SimpleNamespace(),
            knowledge_base,
            SimpleNamespace(),
            actor,
            SimpleNamespace(),
        ),
        409,
    )
    task = SimpleNamespace(id="application-edge-task")
    settings = SimpleNamespace()
    with (
        patch.object(
            knowledge_graph,
            "import_graph_records",
            AsyncMock(return_value=task),
        ),
        patch.object(
            knowledge_graph,
            "_dispatch_graph_task",
            AsyncMock(),
        ) as dispatch,
    ):
        assert (
            await knowledge_graph.import_and_dispatch_graph_records(
                SimpleNamespace(),
                knowledge_base,
                SimpleNamespace(),
                actor,
                settings,
            )
        ) is task
    dispatch.assert_awaited_once_with(task.id, settings)

    now = utc_now()
    assert knowledge_graph._jsonable({"at": now, "items": (now,)}) == {
        "at": now.isoformat(),
        "items": [now.isoformat()],
    }
    assert knowledge_graph._review_claim_ids(
        {"claim_id": "claim-a", "claim_ids": ["claim-b", ""]}
    ) == {"claim-a", "claim-b"}
    assert knowledge_graph._review_source_entity_id(
        {"new_entity_id": "new", "entity_id": "old"}
    ) == "new"

    assert await knowledge_graph.stage_review_decision(
        SimpleNamespace(), knowledge_base, KnowledgeGraphRevision(), {}
    ) == set()
    with patch.object(
        graph_repository,
        "get_review_item",
        AsyncMock(return_value=None),
    ):
        try:
            await knowledge_graph.stage_review_decision(
                SimpleNamespace(),
                knowledge_base,
                KnowledgeGraphRevision(),
                {
                    "review_id": "missing",
                    "action": "approve_claim",
                    "claim_ids": ["claim"],
                },
            )
        except ValueError:
            pass
        else:
            raise AssertionError("missing reviews must fail")

    with patch.object(
        knowledge_repository,
        "lock_knowledge_base",
        AsyncMock(return_value=None),
    ):
        await knowledge_graph.reset_review_decision(
            SimpleNamespace(), knowledge_base, {"review_id": review.id}
        )
    reset_db = AsyncMock()
    with (
        patch.object(
            knowledge_repository,
            "lock_knowledge_base",
            AsyncMock(return_value=knowledge_base),
        ),
        patch.object(
            graph_repository,
            "lock_review_item",
            AsyncMock(return_value=None),
        ),
    ):
        await knowledge_graph.reset_review_decision(
            reset_db, knowledge_base, {"review_id": review.id}
        )
    reset_db.rollback.assert_awaited_once()


async def test_revision_change_retirement_and_conflict_edges() -> None:
    building = KnowledgeGraphRevision(
        id="revision-edge",
        workspace_id="revision-edge-workspace",
        knowledge_base_id="revision-edge-kb",
        status="building",
    )
    for revision, record_kind, record_key in (
        (KnowledgeGraphRevision(status="published"), "entity", "entity"),
        (building, "unknown", "entity"),
        (building, "entity", ""),
    ):
        try:
            await graph_revisions.stage_revision_change(
                SimpleNamespace(),
                revision,
                record_kind=record_kind,
                record_key=record_key,
                operation="upsert",
                before_json=None,
                after_json={},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid revision changes must fail")

    try:
        graph_revisions._upsert_values(
            building,
            KnowledgeGraphRevisionChange(record_key="missing-after"),
            None,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("upserts require an after image")

    claim = KnowledgeGraphClaim(
        id="revision-date-claim",
        status="rejected",
        source_kind="llm",
    )
    with (
        patch.object(
            graph_repository,
            "get_claim",
            AsyncMock(return_value=claim),
        ),
        patch.object(
            graph_repository,
            "save_claim",
            AsyncMock(side_effect=lambda _db, value: value),
        ) as save_claim,
    ):
        await graph_revisions._upsert_claim(
            SimpleNamespace(),
            building,
            KnowledgeGraphRevisionChange(
                record_key=claim.id,
                after_json={
                    "valid_from": "2026-08-21T00:00:00Z",
                    "valid_to": "2026-08-22T00:00:00Z",
                    "status": "active",
                },
            ),
        )
    assert save_claim.await_args.args[1].status == "rejected"

    alias = KnowledgeGraphAlias(id="revision-alias")
    mention = KnowledgeGraphMention(id="revision-mention")
    retired_claim = KnowledgeGraphClaim(id="revision-claim")
    evidence = KnowledgeGraphClaimEvidence(
        id="revision-evidence",
        claim_id=retired_claim.id,
    )
    review = KnowledgeGraphReviewItem(id="revision-review")
    with (
        patch.object(graph_repository, "get_alias", AsyncMock(return_value=alias)),
        patch.object(
            graph_repository,
            "get_mention",
            AsyncMock(return_value=mention),
        ),
        patch.object(
            graph_repository,
            "get_claim",
            AsyncMock(side_effect=[retired_claim, None]),
        ),
        patch.object(
            graph_repository,
            "get_evidence",
            AsyncMock(return_value=evidence),
        ),
        patch.object(
            graph_repository,
            "get_review_item",
            AsyncMock(return_value=review),
        ),
        patch.object(graph_repository, "save_alias", AsyncMock()),
        patch.object(graph_repository, "save_mention", AsyncMock()),
        patch.object(graph_repository, "save_claim", AsyncMock()),
        patch.object(graph_repository, "save_evidence", AsyncMock()),
        patch.object(graph_repository, "save_review_item", AsyncMock()),
    ):
        for record_kind, record_key in (
            ("alias", alias.id),
            ("mention", mention.id),
            ("claim", retired_claim.id),
            ("evidence", evidence.id),
            ("review", review.id),
        ):
            await graph_revisions._retire_revision_change(
                SimpleNamespace(),
                building,
                KnowledgeGraphRevisionChange(
                    record_kind=record_kind,
                    record_key=record_key,
                    operation="retire",
                ),
            )
    assert alias.retired_revision_id == building.id
    assert mention.retired_revision_id == building.id
    assert retired_claim.status == "superseded"
    assert evidence.evidence_state == "deleted"
    assert review.status == "resolved"

    delete_names = (
        "delete_entity",
        "delete_alias",
        "delete_mention",
        "delete_claim",
        "delete_evidence",
        "delete_review_item",
    )
    delete_mocks = {name: AsyncMock() for name in delete_names}
    patches = [
        patch.object(graph_repository, name, mock)
        for name, mock in delete_mocks.items()
    ]
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patch.object(
            graph_repository,
            "get_evidence",
            AsyncMock(return_value=evidence),
        ),
        patch.object(
            graph_repository,
            "get_claim",
            AsyncMock(return_value=None),
        ),
        patch.object(
            graph_repository,
            "save_revision_change",
            AsyncMock(side_effect=lambda _db, value: value),
        ),
    ):
        for record_kind in (
            "entity",
            "alias",
            "mention",
            "claim",
            "evidence",
            "review",
        ):
            await graph_revisions._delete_revision_change(
                SimpleNamespace(),
                building,
                KnowledgeGraphRevisionChange(
                    record_kind=record_kind,
                    record_key=f"delete-{record_kind}",
                    operation="delete",
                ),
            )
        await graph_revisions._apply_revision_change(
            SimpleNamespace(),
            building,
            KnowledgeGraphRevisionChange(
                record_kind="alias",
                record_key="delete-alias-applied",
                operation="delete",
            ),
        )
    assert all(mock.await_count >= 1 for mock in delete_mocks.values())

    knowledge_base = KnowledgeBase(
        id=building.knowledge_base_id,
        workspace_id=building.workspace_id,
    )

    async def expect_publish_conflict(locked_base=None, locked_revision=None) -> None:
        db = AsyncMock()
        with (
            patch.object(
                graph_repository,
                "lock_knowledge_base_graph",
                AsyncMock(return_value=locked_base),
            ),
            patch.object(
                graph_repository,
                "lock_revision",
                AsyncMock(return_value=locked_revision),
            ),
            patch.object(
                graph_repository,
                "list_revision_changes",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                graph_repository,
                "retire_active_revision",
                AsyncMock(),
            ),
            patch.object(
                graph_repository,
                "lock_graph_schema",
                AsyncMock(return_value=None),
            ),
        ):
            try:
                await graph_revisions.publish_revision(
                    db, knowledge_base, building
                )
            except GraphRevisionConflict:
                pass
            else:
                raise AssertionError("stale graph publication must conflict")
        db.rollback.assert_awaited_once()

    await expect_publish_conflict()
    locked_base = KnowledgeBase(
        id=knowledge_base.id,
        workspace_id=knowledge_base.workspace_id,
        active_graph_revision_id="parent-revision",
    )
    await expect_publish_conflict(locked_base=locked_base)
    await expect_publish_conflict(
        locked_base=locked_base,
        locked_revision=KnowledgeGraphRevision(
            id=building.id,
            workspace_id=building.workspace_id,
            knowledge_base_id=building.knowledge_base_id,
            parent_revision_id=locked_base.active_graph_revision_id,
            schema_id="missing-schema",
            status="building",
        ),
    )


async def main() -> None:
    await test_graph_application_edge_paths()
    await test_revision_change_retirement_and_conflict_edges()
    print("OK: knowledge_graph_edge_coverage")


if __name__ == "__main__":
    asyncio.run(main())

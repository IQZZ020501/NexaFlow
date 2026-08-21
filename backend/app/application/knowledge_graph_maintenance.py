import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledge_graph_build import (
    finalize_abandoned_graph_reservations,
)
from app.entities.knowledge import (
    TASK_CANCELLED_STATUS,
    TASK_FAILED_STATUS,
    TASK_QUEUED_STATUS,
    TASK_RUNNING_STATUS,
)
from app.entities.knowledge_graph import (
    GRAPH_REVISION_BUILDING,
    GRAPH_REVISION_FAILED,
    KnowledgeGraphRevision,
)
from app.infrastructure.config import Settings
from app.infrastructure.errors import classify_error, log_error
from app.infrastructure.logger import get_logger
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.session import get_session_factory
from app.ports.vector_store import (
    GraphProfileVector,
    delete_graph_profile_vectors,
    upsert_graph_profile_vectors,
)
from app.shareddomain.knowledge.orchestration import (
    enqueue_graph_rebuild,
    enqueue_graph_sync,
    resolve_embedding_model,
)

logger = get_logger(__name__)

PROFILE_MAINTENANCE_BATCH_SIZE = 500
ORPHAN_REVISION_AGE = timedelta(minutes=10)


@dataclass(frozen=True)
class GraphSourceChanges:
    rebuild_required: bool
    document_ids: tuple[str, ...]


def diff_graph_source_versions(
    previous: dict[str, str] | None,
    current: dict[str, str],
) -> GraphSourceChanges:
    if previous is None:
        return GraphSourceChanges(rebuild_required=True, document_ids=())
    changed = {
        document_id
        for document_id in set(previous) | set(current)
        if previous.get(document_id) != current.get(document_id)
    }
    return GraphSourceChanges(False, tuple(sorted(changed)))


def _revision_source_versions(
    revision: KnowledgeGraphRevision | None,
) -> dict[str, str] | None:
    if revision is None or "source_versions" not in (revision.stats_json or {}):
        return None
    value = (revision.stats_json or {}).get("source_versions")
    if not isinstance(value, dict):
        return None
    return {
        str(document_id): str(version)
        for document_id, version in value.items()
    }


async def enqueue_due_graph_tasks(db: AsyncSession) -> list[str]:
    task_ids: list[str] = []
    knowledge_bases = await graph_repository.list_graph_enabled_knowledge_bases(db)
    for knowledge_base in knowledge_bases:
        try:
            latest_task = await knowledge_repository.get_latest_graph_task(
                db,
                knowledge_base,
            )
            if latest_task is not None and latest_task.status in {
                TASK_FAILED_STATUS,
                TASK_CANCELLED_STATUS,
            }:
                continue
            revision = await graph_repository.get_active_revision(db, knowledge_base)
            latest_revision = await graph_repository.get_latest_revision(
                db,
                knowledge_base,
            )
            current = await graph_repository.current_graph_source_versions(
                db,
                knowledge_base,
            )
            if (
                latest_revision is not None
                and latest_revision.status == GRAPH_REVISION_FAILED
                and _revision_source_versions(latest_revision) == current
            ):
                continue
            changes = diff_graph_source_versions(
                _revision_source_versions(revision),
                current,
            )
            embedding_model = await resolve_embedding_model(db, knowledge_base)
            active_profile_model_id = (
                str(
                    (revision.stats_json or {}).get(
                        "profile_embedding_model_id"
                    )
                    or ""
                )
                if revision is not None
                else ""
            )
            if (
                embedding_model is not None
                and revision is not None
                and active_profile_model_id
                and active_profile_model_id != embedding_model.id
            ):
                changes = GraphSourceChanges(True, ())
            if changes.rebuild_required and not current and revision is None:
                continue
            if not changes.rebuild_required and not changes.document_ids:
                continue
            actor = await user_repository.get_user_by_id(
                db,
                knowledge_base.created_by_user_id,
            )
            if actor is None:
                continue
            task = (
                await enqueue_graph_rebuild(db, knowledge_base, actor)
                if changes.rebuild_required
                else await enqueue_graph_sync(
                    db,
                    knowledge_base,
                    actor,
                    list(changes.document_ids),
                )
            )
            if task.status == TASK_QUEUED_STATUS:
                task_ids.append(task.id)
        except Exception as exc:
            await db.rollback()
            log_error(
                logger,
                "Knowledge graph source reconciliation failed.",
                None,
                source=classify_error(exc),
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                error_type=type(exc).__name__,
            )
    await db.commit()
    return list(dict.fromkeys(task_ids))


def _changed_entity_ids(changes: list[Any]) -> set[str]:
    entity_ids: set[str] = set()
    entity_fields = {
        "entity_id",
        "subject_entity_id",
        "object_entity_id",
        "source_entity_id",
        "target_entity_id",
    }
    for change in changes:
        if change.record_kind == "entity":
            entity_ids.add(change.record_key)
        for payload in (change.before_json, change.after_json):
            if not isinstance(payload, dict):
                continue
            entity_ids.update(
                str(payload[field])
                for field in entity_fields
                if isinstance(payload.get(field), str) and payload[field]
            )
    return entity_ids


async def recover_orphaned_graph_revisions(db: AsyncSession) -> None:
    revisions = await graph_repository.list_stale_building_revisions(
        db,
        utc_now() - ORPHAN_REVISION_AGE,
    )
    for revision in revisions:
        try:
            task_id = str((revision.stats_json or {}).get("task_id") or "")
            task = (
                await knowledge_repository.get_knowledge_task_by_id(db, task_id)
                if task_id
                else None
            )
            if task is not None and task.status in {
                TASK_QUEUED_STATUS,
                TASK_RUNNING_STATUS,
            }:
                continue
            changed_entity_ids = _changed_entity_ids(
                await graph_repository.list_revision_changes(db, revision)
            )
            locked = await graph_repository.lock_revision_by_id(db, revision.id)
            if locked is None or locked.status != GRAPH_REVISION_BUILDING:
                await db.rollback()
                continue
            stats = locked.stats_json or {}
            repair_ids = sorted(
                {
                    *_pending_ids(stats, "profile_repair_entity_ids"),
                    *changed_entity_ids,
                }
            )
            locked.status = GRAPH_REVISION_FAILED
            locked.failure_reason = "Orphaned graph revision recovered."
            locked.model_usage_json = finalize_abandoned_graph_reservations(
                locked.model_usage_json
            )
            locked.stats_json = {
                **stats,
                "profile_repair_pending": bool(repair_ids),
                "profile_repair_entity_ids": repair_ids,
            }
            await graph_repository.save_revision(db, locked)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log_error(
                logger,
                "Orphaned graph revision recovery failed.",
                None,
                source=classify_error(exc),
                revision_id=revision.id,
                knowledge_base_id=revision.knowledge_base_id,
                error_type=type(exc).__name__,
            )


def _pending_ids(stats: dict[str, Any], key: str) -> list[str]:
    value = stats.get(key)
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            str(item)
            for item in value
            if isinstance(item, str) and item
        )
    )


async def _repair_revision_profiles(
    db: AsyncSession,
    revision: KnowledgeGraphRevision,
    settings: Settings,
) -> None:
    stats = revision.stats_json or {}
    repair_ids = _pending_ids(stats, "profile_repair_entity_ids")[
        :PROFILE_MAINTENANCE_BATCH_SIZE
    ]
    delete_budget = PROFILE_MAINTENANCE_BATCH_SIZE - len(repair_ids)
    delete_ids = _pending_ids(stats, "profile_delete_entity_ids")[:delete_budget]
    knowledge_base = await knowledge_repository.get_knowledge_base_by_id(
        db,
        revision.knowledge_base_id,
    )
    if knowledge_base is None:
        return

    profiles: list[GraphProfileVector] = []
    active_profile_ids: set[str] = set()
    if repair_ids:
        entities = await graph_repository.list_active_entities_by_ids(
            db,
            knowledge_base,
            set(repair_ids),
        )
        profiles = [
            GraphProfileVector(
                entity_id=entity.id,
                profile_hash=entity.profile_hash,
                content=entity.profile_markdown,
            )
            for entity in entities
            if entity.profile_markdown and entity.profile_hash
        ]
        active_profile_ids = {profile.entity_id for profile in profiles}
        if profiles:
            embedding_model = await resolve_embedding_model(db, knowledge_base)
            if embedding_model is None:
                raise RuntimeError("Embedding model is required for graph repair.")
            await asyncio.to_thread(
                upsert_graph_profile_vectors,
                settings,
                knowledge_base.id,
                knowledge_base.workspace_id,
                embedding_model,
                profiles,
            )

    point_delete_ids = sorted(
        (set(repair_ids) - active_profile_ids) | set(delete_ids)
    )
    if point_delete_ids:
        await asyncio.to_thread(
            delete_graph_profile_vectors,
            settings,
            knowledge_base.id,
            point_delete_ids,
        )

    locked = await graph_repository.lock_revision_by_id(db, revision.id)
    if locked is None:
        await db.rollback()
        return
    current_stats = locked.stats_json or {}
    current_repair_ids = _pending_ids(
        current_stats,
        "profile_repair_entity_ids",
    )
    current_delete_ids = _pending_ids(
        current_stats,
        "profile_delete_entity_ids",
    )
    processed_repair_ids = set(repair_ids)
    processed_delete_ids = set(delete_ids)
    remaining_repair_ids = [
        item for item in current_repair_ids if item not in processed_repair_ids
    ]
    remaining_delete_ids = [
        item for item in current_delete_ids if item not in processed_delete_ids
    ]
    now = utc_now().isoformat()
    next_stats = {
        **current_stats,
        "profile_repair_pending": bool(remaining_repair_ids),
        "profile_repair_entity_ids": remaining_repair_ids,
        "profile_delete_pending": bool(remaining_delete_ids),
        "profile_delete_entity_ids": remaining_delete_ids,
    }
    if not remaining_repair_ids:
        next_stats["profile_repaired_at"] = now
    if not remaining_delete_ids:
        next_stats["profile_deleted_at"] = now
    locked.stats_json = next_stats
    await graph_repository.save_revision(db, locked)
    await db.commit()


async def repair_pending_graph_profiles(
    db: AsyncSession,
    settings: Settings,
) -> None:
    revisions = await graph_repository.list_profile_maintenance_revisions(db)
    for revision in revisions:
        try:
            await _repair_revision_profiles(db, revision, settings)
        except Exception as exc:
            await db.rollback()
            log_error(
                logger,
                "Knowledge graph profile reconciliation failed.",
                None,
                source=classify_error(exc),
                revision_id=revision.id,
                knowledge_base_id=revision.knowledge_base_id,
                error_type=type(exc).__name__,
            )


async def reconcile_knowledge_graphs(settings: Settings) -> list[str]:
    async with get_session_factory()() as db:
        await recover_orphaned_graph_revisions(db)
        await repair_pending_graph_profiles(db, settings)
        return await enqueue_due_graph_tasks(db)

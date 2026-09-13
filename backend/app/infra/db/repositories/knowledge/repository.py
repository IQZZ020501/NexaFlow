# ruff: noqa: F401
from datetime import datetime
from pathlib import Path

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.knowledge.models import (
    KnowledgeAsset as KnowledgeAssetORM,
)
from app.domain.knowledge.models import (
    KnowledgeAttachment as KnowledgeAttachmentORM,
)
from app.domain.knowledge.models import (
    KnowledgeBase as KnowledgeBaseORM,
)
from app.domain.knowledge.models import (
    KnowledgeChunkAsset as KnowledgeChunkAssetORM,
)
from app.domain.knowledge.models import (
    KnowledgeDocument as KnowledgeDocumentORM,
)
from app.domain.knowledge.models import (
    KnowledgeDocumentChunk as KnowledgeDocumentChunkORM,
)
from app.domain.knowledge.models import (
    KnowledgeDocumentParentChunk as KnowledgeDocumentParentChunkORM,
)
from app.domain.knowledge.models import (
    KnowledgeDocumentReference as KnowledgeDocumentReferenceORM,
)
from app.domain.knowledge.models import (
    KnowledgeEvaluationCase as KnowledgeEvaluationCaseORM,
)
from app.domain.knowledge.models import (
    KnowledgeStorageCleanup as KnowledgeStorageCleanupORM,
)
from app.domain.knowledge.models import (
    KnowledgeTask as KnowledgeTaskORM,
)
from app.domain.platform.models import ResourcePermission as ResourcePermissionORM
from app.entities.defaults import new_id, utc_now
from app.entities.knowledge import (
    CHUNK_INDEXED_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_STAGED_META_KEY,
    TASK_CANCELLING_STATUS,
    TASK_FAILED_STATUS,
    TASK_GRAPH_REBUILD,
    TASK_GRAPH_SYNC,
    TASK_QUEUED_STATUS,
    TASK_RUNNING_STATUS,
    VISIBLE_DOCUMENT_STATUSES,
    KnowledgeAsset,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeChunkAsset,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeStorageCleanup,
    KnowledgeTask,
)
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.infra.db.mapping import (
    refresh_entity,
    save,
    to_entity,
    to_orm,
)

_QUERY_KEYWORD_CHUNK_IDS = text(
    (
        Path(__file__).parent.parent.parent
        / "sql"
        / "knowledge"
        / "query_keyword_chunk_ids.sql"
    ).read_text(encoding="utf-8")
)




from app.infra.db.repositories.knowledge.bases import (
    create_knowledge_base,
    delete_knowledge_base,
    delete_knowledge_base_graph,
    get_knowledge_base_by_id,
    list_and_lock_knowledge_bases_in_workspace,
    list_knowledge_bases_with_user_grants,
    lock_knowledge_base,
    refresh_knowledge_base,
    save_knowledge_base,
    set_knowledge_base_embedding_model_id,
)
from app.infra.db.repositories.knowledge.documents import (
    _visible_document_conditions,
    count_document_chunks,
    create_knowledge_attachment,
    create_knowledge_document,
    delete_document_assets,
    delete_document_chunks,
    delete_knowledge_attachment,
    delete_knowledge_document,
    get_document_asset,
    get_knowledge_attachment_by_id,
    get_knowledge_document_by_id,
    get_queued_graph_rebuild,
    get_queued_graph_sync,
    has_indexed_knowledge_document,
    list_active_documents_by_ids,
    list_chunk_assets,
    list_chunks_by_ids,
    list_chunks_for_documents,
    list_document_assets,
    list_document_chunks,
    list_indexable_chunks,
    list_indexed_chunk_ids_for_parent_ids,
    list_knowledge_base_rows,
    list_knowledge_content_revisions,
    list_knowledge_documents,
    list_parent_chunks_by_ids,
    list_retrievable_document_ids,
    lock_knowledge_attachments,
    query_keyword_chunk_ids,
    refresh_knowledge_attachment,
    refresh_knowledge_document,
    replace_document_chunks,
    save_knowledge_attachment,
    save_knowledge_document,
    save_knowledge_document_chunk,
)
from app.infra.db.repositories.knowledge.storage import (
    create_knowledge_storage_cleanup,
    delete_knowledge_storage_cleanup,
    list_due_knowledge_storage_cleanup_ids,
    lock_knowledge_storage_cleanup,
    save_knowledge_storage_cleanup,
)
from app.infra.db.repositories.knowledge.tasks import (
    claim_knowledge_task,
    create_knowledge_task,
    delete_knowledge_task,
    fail_open_document_tasks,
    get_knowledge_task_by_id,
    get_latest_graph_task,
    get_open_document_task,
    get_open_graph_task,
    get_open_knowledge_base_task,
    get_open_knowledge_task,
    get_running_graph_task,
    list_knowledge_tasks,
    list_recoverable_tasks,
    lock_knowledge_task,
    refresh_knowledge_task,
    renew_knowledge_task_lease,
    save_knowledge_task,
    update_owned_knowledge_task_progress,
)

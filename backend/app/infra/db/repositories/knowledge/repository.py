from datetime import datetime
from pathlib import Path

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    CHUNK_INDEXED_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_STAGED_META_KEY,
    TASK_FAILED_STATUS,
    TASK_CANCELLING_STATUS,
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
from app.entities.defaults import new_id, utc_now
from app.infra.db.mapping import (
    refresh_entity,
    save,
    to_entity,
    to_orm,
)
from app.domain.platform.models import ResourcePermission as ResourcePermissionORM
from app.domain.knowledge.models import (
    KnowledgeAsset as KnowledgeAssetORM,
    KnowledgeAttachment as KnowledgeAttachmentORM,
    KnowledgeBase as KnowledgeBaseORM,
    KnowledgeChunkAsset as KnowledgeChunkAssetORM,
    KnowledgeDocument as KnowledgeDocumentORM,
    KnowledgeDocumentChunk as KnowledgeDocumentChunkORM,
    KnowledgeDocumentParentChunk as KnowledgeDocumentParentChunkORM,
    KnowledgeDocumentReference as KnowledgeDocumentReferenceORM,
    KnowledgeEvaluationCase as KnowledgeEvaluationCaseORM,
    KnowledgeStorageCleanup as KnowledgeStorageCleanupORM,
    KnowledgeTask as KnowledgeTaskORM,
)

_QUERY_KEYWORD_CHUNK_IDS = text(
    (
        Path(__file__).parent.parent.parent
        / "sql"
        / "knowledge"
        / "query_keyword_chunk_ids.sql"
    ).read_text(encoding="utf-8")
)



from app.infra.db.repositories.knowledge.documents import _visible_document_conditions
from app.infra.db.repositories.knowledge.documents import list_knowledge_base_rows
from app.infra.db.repositories.knowledge.documents import list_knowledge_documents
from app.infra.db.repositories.knowledge.documents import has_indexed_knowledge_document
from app.infra.db.repositories.knowledge.documents import list_knowledge_content_revisions
from app.infra.db.repositories.knowledge.documents import get_knowledge_document_by_id
from app.infra.db.repositories.knowledge.documents import create_knowledge_document
from app.infra.db.repositories.knowledge.documents import save_knowledge_document
from app.infra.db.repositories.knowledge.documents import refresh_knowledge_document
from app.infra.db.repositories.knowledge.documents import delete_knowledge_document
from app.infra.db.repositories.knowledge.documents import get_knowledge_attachment_by_id
from app.infra.db.repositories.knowledge.documents import create_knowledge_attachment
from app.infra.db.repositories.knowledge.documents import save_knowledge_attachment
from app.infra.db.repositories.knowledge.documents import refresh_knowledge_attachment
from app.infra.db.repositories.knowledge.documents import delete_knowledge_attachment
from app.infra.db.repositories.knowledge.documents import lock_knowledge_attachments
from app.infra.db.repositories.knowledge.documents import list_document_assets
from app.infra.db.repositories.knowledge.documents import get_document_asset
from app.infra.db.repositories.knowledge.documents import list_chunk_assets
from app.infra.db.repositories.knowledge.documents import delete_document_assets
from app.infra.db.repositories.knowledge.documents import count_document_chunks
from app.infra.db.repositories.knowledge.documents import list_document_chunks
from app.infra.db.repositories.knowledge.documents import list_indexable_chunks
from app.infra.db.repositories.knowledge.documents import list_chunks_for_documents
from app.infra.db.repositories.knowledge.documents import save_knowledge_document_chunk
from app.infra.db.repositories.knowledge.documents import replace_document_chunks
from app.infra.db.repositories.knowledge.documents import list_chunks_by_ids
from app.infra.db.repositories.knowledge.documents import list_parent_chunks_by_ids
from app.infra.db.repositories.knowledge.documents import list_active_documents_by_ids
from app.infra.db.repositories.knowledge.documents import list_retrievable_document_ids
from app.infra.db.repositories.knowledge.documents import query_keyword_chunk_ids
from app.infra.db.repositories.knowledge.documents import list_indexed_chunk_ids_for_parent_ids
from app.infra.db.repositories.knowledge.documents import delete_document_chunks
from app.infra.db.repositories.knowledge.documents import get_queued_graph_sync
from app.infra.db.repositories.knowledge.documents import get_queued_graph_rebuild
from app.infra.db.repositories.knowledge.bases import list_knowledge_bases_with_user_grants
from app.infra.db.repositories.knowledge.bases import list_and_lock_knowledge_bases_in_workspace
from app.infra.db.repositories.knowledge.bases import get_knowledge_base_by_id
from app.infra.db.repositories.knowledge.bases import lock_knowledge_base
from app.infra.db.repositories.knowledge.bases import create_knowledge_base
from app.infra.db.repositories.knowledge.bases import save_knowledge_base
from app.infra.db.repositories.knowledge.bases import set_knowledge_base_embedding_model_id
from app.infra.db.repositories.knowledge.bases import refresh_knowledge_base
from app.infra.db.repositories.knowledge.bases import delete_knowledge_base
from app.infra.db.repositories.knowledge.bases import delete_knowledge_base_graph
from app.infra.db.repositories.knowledge.storage import create_knowledge_storage_cleanup
from app.infra.db.repositories.knowledge.storage import lock_knowledge_storage_cleanup
from app.infra.db.repositories.knowledge.storage import list_due_knowledge_storage_cleanup_ids
from app.infra.db.repositories.knowledge.storage import save_knowledge_storage_cleanup
from app.infra.db.repositories.knowledge.storage import delete_knowledge_storage_cleanup
from app.infra.db.repositories.knowledge.tasks import list_knowledge_tasks
from app.infra.db.repositories.knowledge.tasks import list_recoverable_tasks
from app.infra.db.repositories.knowledge.tasks import get_knowledge_task_by_id
from app.infra.db.repositories.knowledge.tasks import lock_knowledge_task
from app.infra.db.repositories.knowledge.tasks import create_knowledge_task
from app.infra.db.repositories.knowledge.tasks import save_knowledge_task
from app.infra.db.repositories.knowledge.tasks import delete_knowledge_task
from app.infra.db.repositories.knowledge.tasks import refresh_knowledge_task
from app.infra.db.repositories.knowledge.tasks import claim_knowledge_task
from app.infra.db.repositories.knowledge.tasks import get_running_graph_task
from app.infra.db.repositories.knowledge.tasks import get_open_graph_task
from app.infra.db.repositories.knowledge.tasks import get_latest_graph_task
from app.infra.db.repositories.knowledge.tasks import renew_knowledge_task_lease
from app.infra.db.repositories.knowledge.tasks import update_owned_knowledge_task_progress
from app.infra.db.repositories.knowledge.tasks import get_open_knowledge_task
from app.infra.db.repositories.knowledge.tasks import get_open_knowledge_base_task
from app.infra.db.repositories.knowledge.tasks import get_open_document_task
from app.infra.db.repositories.knowledge.tasks import fail_open_document_tasks

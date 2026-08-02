import type { User } from "@/features/auth/types"

export type KnowledgeBase = {
  id: string
  workspace_id: string
  name: string
  description: string
  status: string
  embedding_model_id: string | null
  reranker_model_id: string | null
  created_by_user_id: string
  created_at: string
  updated_at: string
  permission: "view" | "edit" | "none"
}

export type ResourcePermission = {
  user: User
  permission: "view" | "edit"
}

export type KnowledgeDocument = {
  id: string
  workspace_id: string
  knowledge_base_id: string
  filename: string
  content_type: string
  size_bytes: number
  status: string
  is_active: boolean
  chunk_count: number
  last_error: string | null
  created_by_user_id: string
  created_at: string
  updated_at: string
}

export type KnowledgeDocumentChunk = {
  id: string
  workspace_id: string
  knowledge_base_id: string
  document_id: string
  chunk_index: number
  content: string
  char_count: number
  token_count: number
  vector_id: string | null
  status: string
  created_at: string
  updated_at: string
}

export type KnowledgeTask = {
  id: string
  workspace_id: string
  knowledge_base_id: string
  document_id: string | null
  task_type: string
  status: string
  attempts: number
  max_attempts: number
  total_items: number
  processed_items: number
  last_error: string | null
  created_by_user_id: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export type KnowledgeQueryHit = {
  chunk_id: string
  document_id: string
  document_filename: string
  chunk_index: number
  content: string
  distance: number | null
}

export type KnowledgeBaseForm = {
  name: string
  description: string
  embedding_model_id: string | null
  reranker_model_id: string | null
}

export type KnowledgeBaseEditForm = KnowledgeBaseForm & {
  id: string
}

export type KnowledgeBasePermissionForm = {
  knowledgeBase: KnowledgeBase
  userId: string
  permission: "view" | "edit"
}

export type KnowledgeBaseDetailTab =
  "documents" | "tasks" | "questions" | "hit-test" | "settings"

export type KnowledgeModelTestResult = {
  embedding_model_id: string
  embedding_dimensions: number
  reranker_model_id: string | null
  reranker_results: number
}

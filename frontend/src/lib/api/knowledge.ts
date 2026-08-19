import { ApiError, listQuery, request, requestBlob } from "@/lib/api-client"
import type { User } from "@/lib/api/auth"

export type { User } from "@/lib/api/auth"

export type KnowledgeSegmentationStrategy = "flat" | "hierarchical"

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

/** List-item variant: the list API always reports capacity stats. */
export type KnowledgeBaseListItem = KnowledgeBase & {
  document_count: number
  char_count: number
}

export type ResourcePermission = {
  user: User
  permission: "view" | "edit"
}

export type KnowledgeAttachment = {
  id: string
  workspace_id: string
  knowledge_base_id: string
  filename: string
  content_type: string
  size_bytes: number
  status: string
  created_by_user_id: string
  created_at: string
  updated_at: string
}


export type KnowledgeDocument = {
  id: string
  workspace_id: string
  knowledge_base_id: string
  filename: string
  content_type: string
  size_bytes: number
  attachment_id: string | null
  meta: Record<string, unknown>
  status: string
  is_active: boolean
  chunk_count: number
  last_error: string | null
  created_by_user_id: string
  created_at: string
  updated_at: string
}

export type KnowledgeAsset = {
  id: string
  kind: "image"
  filename: string
  content_type: string
  size_bytes: number
  alt_text: string
}


export type KnowledgeDocumentChunk = {
  id: string
  workspace_id: string
  knowledge_base_id: string
  document_id: string
  parent_id: string | null
  parent_title: string | null
  parent_index: number | null
  chunk_index: number
  start_offset: number | null
  end_offset: number | null
  content: string
  kind: "document" | "qa"
  question: string | null
  source: string | null
  row_number: number | null
  char_count: number
  token_count: number
  vector_id: string | null
  status: string
  images: KnowledgeAsset[]
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
  parent_id: string | null
  parent_title: string | null
  parent_index: number | null
  chunk_index: number
  content: string
  distance: number | null
  similarity: number | null
  kind: "document" | "qa"
  question: string | null
  source: string | null
  sources: Array<"vector" | "keywords" | "reference">
  reference_hops: 0 | 1
  rerank_score: number | null
}

export type KnowledgeSearchMode = "embedding" | "keywords" | "blend"

export type KnowledgeQueryInspectRequest = {
  query: string
  limit: number
  search_mode: KnowledgeSearchMode
  similarity: number | null
  include_references: boolean
}

export type KnowledgeRetrievalTrace = {
  trace_id: string
  search_mode: KnowledgeSearchMode
  limit: number
  min_similarity: number | null
  max_distance: number | null
  vector_candidates: number
  keyword_candidates: number
  reference_candidates: number
  fused_candidates: number
  rerank_status: "not_configured" | "applied" | "fallback" | "skipped"
  returned_hits: number
  duration_ms: number
  stage_duration_ms: Record<string, number>
}

export type KnowledgeQueryInspectResult = {
  hits: KnowledgeQueryHit[]
  trace: KnowledgeRetrievalTrace
}

export type KnowledgeEvaluationCase = {
  id: string
  workspace_id: string
  knowledge_base_id: string
  question: string
  expected_document_ids: string[]
  created_by_user_id: string
  created_at: string
  updated_at: string
}

export type KnowledgeEvaluationRunRequest = {
  case_ids: string[]
  limit: number
  search_mode: KnowledgeSearchMode
  similarity: number | null
  include_references: boolean
}

export type KnowledgeEvaluationResult = {
  id: string
  case_id: string
  question: string
  returned_document_ids: string[]
  returned_chunk_ids: string[]
  hit_at_k: number
  recall_at_k: number
  reciprocal_rank: number
  ndcg_at_k: number
  latency_ms: number
  trace: Record<string, unknown>
  error: string | null
  created_at: string
}

export type KnowledgeEvaluationSummary = {
  task: KnowledgeTask
  count: number
  failed_count: number
  mean_hit_at_k: number
  mean_recall_at_k: number
  mean_reciprocal_rank: number
  mean_ndcg_at_k: number
  p50_latency_ms: number
  p95_latency_ms: number
  results: KnowledgeEvaluationResult[]
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
  "documents" | "tasks" | "evaluation" | "settings"

export type KnowledgeModelTestResult = {
  embedding_model_id: string
  embedding_dimensions: number
  reranker_model_id: string | null
  reranker_results: number
}

export function listKnowledgeBases(
  token: string,
  workspaceId: string,
  options: { limit?: number; offset?: number } = {},
) {
  return request<KnowledgeBaseListItem[]>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases${listQuery(options)}`,
    { token },
  )
}

export function createKnowledgeBase(
  token: string,
  workspaceId: string,
  payload: {
    name: string
    description: string
    embedding_model_id?: string | null
    reranker_model_id?: string | null
  },
) {
  return request<KnowledgeBase>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  )
}

export function updateKnowledgeBase(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  payload: {
    name?: string
    description?: string
    status?: string
    embedding_model_id?: string | null
    reranker_model_id?: string | null
  },
) {
  return request<KnowledgeBase>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    },
  )
}

export function deleteKnowledgeBase(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  return request<void>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}`,
    {
      method: "DELETE",
      token,
    },
  )
}

export function listKnowledgeDocuments(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  options: { includeStaged?: boolean } = {},
) {
  const query = options.includeStaged ? "?include_staged=true" : ""
  return request<KnowledgeDocument[]>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents${query}`,
    { token },
  )
}

export function uploadKnowledgeAttachment(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  file: File,
) {
  const formData = new FormData()
  formData.append("file", file)
  return request<KnowledgeAttachment>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/attachments`,
    {
      method: "POST",
      token,
      body: formData,
    },
  )
}

export function deleteKnowledgeAttachment(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  attachmentId: string,
) {
  return request<void>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/attachments/${attachmentId}`,
    { method: "DELETE", token },
  )
}

export function createKnowledgeDocuments(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  attachmentIds: string[],
  staged = true,
  importMode?: "document" | "qa",
) {
  return request<KnowledgeDocument[]>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents`,
    {
      method: "POST",
      token,
      body: JSON.stringify({
        attachment_ids: attachmentIds,
        staged,
        ...(importMode ? { import_mode: importMode } : {}),
      }),
    },
  )
}

export function parseKnowledgeDocument(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
  payload?: {
    strategy?: KnowledgeSegmentationStrategy
    chunk_size: number
    chunk_overlap: number
    split_separator?: string
    cleaning_rules: string[]
    auto_index: boolean
  },
) {
  return request<KnowledgeTask>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/parse`,
    {
      method: "POST",
      token,
      body: payload ? JSON.stringify(payload) : undefined,
    },
  )
}


export function indexKnowledgeDocument(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
) {
  return request<KnowledgeTask>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index`,
    {
      method: "POST",
      token,
    },
  )
}

export function deleteKnowledgeDocument(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
) {
  return request<void>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`,
    {
      method: "DELETE",
      token,
    },
  )
}

export function setKnowledgeDocumentActive(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
  isActive: boolean,
) {
  return request<KnowledgeDocument>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify({ is_active: isActive }),
    },
  )
}

export async function downloadKnowledgeDocument(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
  filename: string,
) {
  const response = await fetch(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/download`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    },
  )
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText)
  }

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export async function listKnowledgeDocumentChunks(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
) {
  const chunks: KnowledgeDocumentChunk[] = []
  const limit = 200
  while (true) {
    const page = await request<KnowledgeDocumentChunk[]>(
      `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/chunks?limit=${limit}&offset=${chunks.length}`,
      { token },
    )
    chunks.push(...page)
    if (page.length < limit) {
      return chunks
    }
  }
}


export function loadKnowledgeAsset(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
  assetId: string,
) {
  return requestBlob(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/assets/${assetId}`,
    { token },
  )
}

export function listKnowledgeTasks(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId?: string,
) {
  const path = documentId
    ? `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/tasks`
    : `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/tasks`

  return request<KnowledgeTask[]>(path, { token })
}

export function retryKnowledgeTask(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  taskId: string,
) {
  return request<KnowledgeTask>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/tasks/${taskId}/retry`,
    {
      method: "POST",
      token,
    },
  )
}

export function rebuildKnowledgeIndex(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  return request<KnowledgeTask>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/rebuild-index`,
    {
      method: "POST",
      token,
    },
  )
}

export function queryKnowledgeBase(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  payload: { query: string; limit: number },
) {
  return request<KnowledgeQueryHit[]>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/query`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  )
}

export function inspectKnowledgeBase(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  payload: KnowledgeQueryInspectRequest,
) {
  return request<KnowledgeQueryInspectResult>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/query/inspect`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  )
}

function evaluationPath(
  workspaceId: string,
  knowledgeBaseId: string,
  suffix = "",
) {
  return `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/evaluations${suffix}`
}

export function listKnowledgeEvaluationCases(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  return request<KnowledgeEvaluationCase[]>(
    evaluationPath(workspaceId, knowledgeBaseId, "/cases"),
    { token },
  )
}

export function createKnowledgeEvaluationCase(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  payload: {
    question: string
    expected_document_ids: string[]
  },
) {
  return request<KnowledgeEvaluationCase>(
    evaluationPath(workspaceId, knowledgeBaseId, "/cases"),
    { method: "POST", token, body: JSON.stringify(payload) },
  )
}

export function deleteKnowledgeEvaluationCase(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  caseId: string,
) {
  return request<void>(
    evaluationPath(workspaceId, knowledgeBaseId, `/cases/${caseId}`),
    { method: "DELETE", token },
  )
}

export function listKnowledgeEvaluationRuns(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  return request<KnowledgeTask[]>(
    evaluationPath(workspaceId, knowledgeBaseId, "/runs"),
    { token },
  )
}

export function createKnowledgeEvaluationRun(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  payload: KnowledgeEvaluationRunRequest,
) {
  return request<KnowledgeTask>(
    evaluationPath(workspaceId, knowledgeBaseId, "/runs"),
    { method: "POST", token, body: JSON.stringify(payload) },
  )
}

export function getKnowledgeEvaluationRun(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  taskId: string,
) {
  return request<KnowledgeTask>(
    evaluationPath(workspaceId, knowledgeBaseId, `/runs/${taskId}`),
    { token },
  )
}

export function deleteKnowledgeEvaluationRun(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  taskId: string,
) {
  return request<void>(
    evaluationPath(workspaceId, knowledgeBaseId, `/runs/${taskId}`),
    { method: "DELETE", token },
  )
}

export function getKnowledgeEvaluationSummary(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  taskId: string,
) {
  return request<KnowledgeEvaluationSummary>(
    evaluationPath(workspaceId, knowledgeBaseId, `/runs/${taskId}/results`),
    { token },
  )
}

export function testKnowledgeBaseModels(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  return request<KnowledgeModelTestResult>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/model-test`,
    {
      method: "POST",
      token,
      body: JSON.stringify({ query: "Hello", documents: ["Hello"] }),
    },
  )
}

export function listKnowledgeBasePermissions(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  return request<ResourcePermission[]>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions`,
    { token },
  )
}

export function upsertKnowledgeBasePermission(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  userId: string,
  permission: "view" | "edit",
) {
  return request<ResourcePermission>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions/${userId}`,
    {
      method: "PUT",
      token,
      body: JSON.stringify({ permission }),
    },
  )
}

export function revokeKnowledgeBasePermission(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  userId: string,
) {
  return request<void>(
    `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions/${userId}`,
    {
      method: "DELETE",
      token,
    },
  )
}

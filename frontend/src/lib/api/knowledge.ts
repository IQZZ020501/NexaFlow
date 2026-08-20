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

/**
 * Lists knowledge bases in a workspace.
 *
 * @param token - Authentication token
 * @param workspaceId - Identifier of the workspace
 * @param options - Optional pagination parameters
 * @returns The workspace's knowledge bases
 */
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

/**
 * Creates a knowledge base in a workspace.
 *
 * @param workspaceId - The workspace that will contain the knowledge base
 * @param payload - The knowledge base name, description, and optional model configuration
 * @returns The created knowledge base
 */
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

/**
 * Updates the metadata, status, or models of a knowledge base.
 *
 * @param workspaceId - The workspace containing the knowledge base
 * @param knowledgeBaseId - The knowledge base to update
 * @param payload - The fields to update
 * @returns The updated knowledge base
 */
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

/**
 * Deletes a knowledge base from a workspace.
 */
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

/**
 * Lists documents in a knowledge base.
 *
 * @param options - Controls whether staged documents are included.
 * @returns The knowledge base documents.
 */
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

/**
 * Uploads a file attachment to a knowledge base.
 *
 * @param file - The file to upload.
 * @returns The uploaded knowledge attachment.
 */
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

/**
 * Deletes an uploaded knowledge-base attachment.
 *
 * @param workspaceId - The workspace containing the knowledge base
 * @param knowledgeBaseId - The knowledge base containing the attachment
 * @param attachmentId - The attachment to delete
 */
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

/**
 * Creates knowledge-base documents from uploaded attachments.
 *
 * @param attachmentIds - Identifiers of the attachments to convert into documents
 * @param staged - Whether to create the documents in staged mode
 * @param importMode - The import format for the documents
 * @returns The created knowledge-base documents
 */
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

/**
 * Starts parsing a knowledge document with optional segmentation, cleaning, and automatic indexing settings.
 *
 * @param workspaceId - The workspace containing the knowledge base
 * @param knowledgeBaseId - The knowledge base containing the document
 * @param documentId - The document to parse
 * @param payload - Parsing, chunking, cleaning, and indexing settings
 * @returns The parsing task
 */
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


/**
 * Starts indexing for a knowledge-base document.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Identifier of the workspace containing the knowledge base
 * @param knowledgeBaseId - Identifier of the knowledge base containing the document
 * @param documentId - Identifier of the document to index
 * @returns The indexing task
 */
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

/**
 * Deletes a document from a knowledge base.
 */
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

/**
 * Updates whether a knowledge document is active.
 *
 * @param isActive - Whether the document should be active.
 * @returns The updated knowledge document.
 */
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

/**
 * Downloads a knowledge document and saves it with the specified filename.
 *
 * @param filename - The name to use for the downloaded file.
 * @throws `ApiError` when the download request fails.
 */
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

/**
 * Lists all chunks for a knowledge document.
 *
 * @param documentId - The document whose chunks to retrieve
 * @returns All chunks belonging to the document
 */
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


/**
 * Loads an asset associated with a knowledge document.
 *
 * @param workspaceId - The workspace containing the knowledge base
 * @param knowledgeBaseId - The knowledge base containing the document
 * @param documentId - The document containing the asset
 * @param assetId - The asset to load
 * @returns The asset data as a blob
 */
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

/**
 * Lists tasks for a knowledge base, optionally limited to a document.
 *
 * @param documentId - The document whose tasks to list
 * @returns The matching knowledge-base tasks
 */
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

/**
 * Retries a knowledge-base task.
 *
 * @param token - Authentication token
 * @param workspaceId - Workspace containing the knowledge base
 * @param knowledgeBaseId - Knowledge base containing the task
 * @param taskId - Task to retry
 * @returns The retried knowledge-base task
 */
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

/**
 * Starts a full index rebuild for a knowledge base.
 *
 * @param workspaceId - The workspace containing the knowledge base
 * @param knowledgeBaseId - The knowledge base whose index should be rebuilt
 * @returns The task created for the index rebuild
 */
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

/**
 * Queries a knowledge base for relevant results.
 *
 * @param token - The authentication token
 * @param workspaceId - The workspace identifier
 * @param knowledgeBaseId - The knowledge base identifier
 * @param payload - The query text and maximum number of results
 * @returns The matching knowledge-base hits
 */
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

/**
 * Inspects knowledge-base retrieval for a query.
 *
 * @param payload - The query and retrieval configuration to inspect
 * @returns The matched results and detailed retrieval trace
 */
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

/**
 * Builds the API path for knowledge-base evaluation operations.
 *
 * @param workspaceId - The workspace identifier
 * @param knowledgeBaseId - The knowledge-base identifier
 * @param suffix - An optional path suffix appended to the evaluations path
 * @returns The evaluation API path
 */
function evaluationPath(
  workspaceId: string,
  knowledgeBaseId: string,
  suffix = "",
) {
  return `/api/v1/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/evaluations${suffix}`
}

/**
 * Lists evaluation cases for a knowledge base.
 *
 * @returns The knowledge base's evaluation cases
 */
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

/**
 * Creates an evaluation case for a knowledge base.
 *
 * @param payload - The question and document identifiers expected to support its answer
 * @returns The created evaluation case
 */
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

/**
 * Deletes an evaluation case from a knowledge base.
 *
 * @param token - Authentication token
 * @param workspaceId - Workspace containing the knowledge base
 * @param knowledgeBaseId - Knowledge base containing the evaluation case
 * @param caseId - Evaluation case to delete
 */
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

/**
 * Lists evaluation runs for a knowledge base.
 *
 * @returns The knowledge base's evaluation runs
 */
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

/**
 * Starts an evaluation run for a knowledge base.
 *
 * @param payload - The evaluation run configuration.
 * @returns The task created for the evaluation run.
 */
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

/**
 * Retrieves a knowledge-base evaluation run.
 *
 * @param token - The authentication token
 * @param workspaceId - The workspace identifier
 * @param knowledgeBaseId - The knowledge-base identifier
 * @param taskId - The evaluation run identifier
 * @returns The evaluation run task
 */
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

/**
 * Deletes a knowledge-base evaluation run.
 *
 * @param taskId - The identifier of the evaluation run to delete
 */
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

/**
 * Retrieves the summary and individual results for a knowledge-base evaluation run.
 *
 * @param taskId - The identifier of the evaluation run
 * @returns The evaluation summary, metrics, latency statistics, task details, and results
 */
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

/**
 * Tests the configured knowledge-base models with a sample query and document.
 *
 * @returns The model test result.
 */
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

/**
 * Lists permissions for a knowledge base.
 *
 * @param workspaceId - The workspace containing the knowledge base
 * @param knowledgeBaseId - The knowledge base whose permissions are listed
 * @returns The knowledge base permissions
 */
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

/**
 * Assigns or updates a user's permission for a knowledge base.
 *
 * @param token - Authentication token
 * @param workspaceId - Workspace identifier
 * @param knowledgeBaseId - Knowledge base identifier
 * @param userId - User whose permission is being assigned or updated
 * @param permission - Access level to grant
 * @returns The updated resource permission
 */
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

/**
 * Removes a user's permission from a knowledge base.
 *
 * @param userId - The ID of the user whose permission is removed
 */
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

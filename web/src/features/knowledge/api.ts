import { ApiError, request } from "@/lib/api-client"
import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeDocumentChunk,
  KnowledgeModelTestResult,
  KnowledgeQueryHit,
  KnowledgeTask,
  ResourcePermission,
} from "@/features/knowledge/types"

export function listKnowledgeBases(token: string, workspaceId: string) {
  return request<KnowledgeBase[]>(
    `/workspaces/${workspaceId}/knowledge-bases`,
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
  return request<KnowledgeBase>(`/workspaces/${workspaceId}/knowledge-bases`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents${query}`,
    { token },
  )
}

export function uploadKnowledgeDocument(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  file: File,
  options: { autoParse?: boolean } = {},
) {
  const formData = new FormData()
  formData.append("file", file)
  formData.append("auto_parse", String(options.autoParse ?? true))

  return request<KnowledgeDocument>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents`,
    {
      method: "POST",
      token,
      body: formData,
    },
  )
}

export function parseKnowledgeDocument(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
  payload?: {
    chunk_size: number
    chunk_overlap: number
    split_separator?: string
    cleaning_rules: string[]
    auto_index: boolean
  },
) {
  return request<KnowledgeTask>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/parse`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/download`,
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

export function listKnowledgeDocumentChunks(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  documentId: string,
) {
  return request<KnowledgeDocumentChunk[]>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/chunks`,
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
    ? `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/tasks`
    : `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/tasks`

  return request<KnowledgeTask[]>(path, { token })
}

export function retryKnowledgeTask(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  taskId: string,
) {
  return request<KnowledgeTask>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/tasks/${taskId}/retry`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/rebuild-index`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/query`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  )
}

export function testKnowledgeBaseModels(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
) {
  return request<KnowledgeModelTestResult>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/model-test`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions/${userId}`,
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
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions/${userId}`,
    {
      method: "DELETE",
      token,
    },
  )
}

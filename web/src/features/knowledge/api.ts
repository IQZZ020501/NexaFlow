import { request } from "@/lib/api-client"
import type {
  KnowledgeBase,
  KnowledgeDocument,
  ResourcePermission,
} from "@/features/knowledge/types"

export function listKnowledgeBases(token: string, workspaceId: string) {
  return request<KnowledgeBase[]>(
    `/workspaces/${workspaceId}/knowledge-bases`,
    { token }
  )
}

export function createKnowledgeBase(
  token: string,
  workspaceId: string,
  payload: {
    name: string
    description: string
  }
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
  }
) {
  return request<KnowledgeBase>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    }
  )
}

export function deleteKnowledgeBase(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string
) {
  return request<void>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}`,
    {
      method: "DELETE",
      token,
    }
  )
}

export function listKnowledgeDocuments(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string
) {
  return request<KnowledgeDocument[]>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents`,
    { token }
  )
}

export function uploadKnowledgeDocument(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  file: File
) {
  const formData = new FormData()
  formData.append("file", file)

  return request<KnowledgeDocument>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/documents`,
    {
      method: "POST",
      token,
      body: formData,
    }
  )
}

export function listKnowledgeBasePermissions(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string
) {
  return request<ResourcePermission[]>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions`,
    { token }
  )
}

export function upsertKnowledgeBasePermission(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  userId: string,
  permission: "view" | "edit"
) {
  return request<ResourcePermission>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions/${userId}`,
    {
      method: "PUT",
      token,
      body: JSON.stringify({ permission }),
    }
  )
}

export function revokeKnowledgeBasePermission(
  token: string,
  workspaceId: string,
  knowledgeBaseId: string,
  userId: string
) {
  return request<void>(
    `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/permissions/${userId}`,
    {
      method: "DELETE",
      token,
    }
  )
}

import { request } from "@/lib/api-client"

export type ResourceFolder = {
  id: string
  workspace_id: string
  resource_type: FolderResourceType
  parent_id: string | null
  name: string
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

export type FolderResourceType = "knowledge" | "application" | "tool"

function foldersPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/resource-folders${suffix}`
}

export function listResourceFolders(
  token: string,
  workspaceId: string,
  resourceType: FolderResourceType
) {
  return request<ResourceFolder[]>(
    `${foldersPath(workspaceId)}?resource_type=${resourceType}`,
    { token }
  )
}

export function createResourceFolder(
  token: string,
  workspaceId: string,
  payload: {
    name: string
    resource_type: FolderResourceType
    parent_id: string | null
  }
) {
  return request<ResourceFolder>(foldersPath(workspaceId), {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updateResourceFolder(
  token: string,
  workspaceId: string,
  folderId: string,
  payload: { name?: string; parent_id?: string | null }
) {
  return request<ResourceFolder>(foldersPath(workspaceId, `/${folderId}`), {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function deleteResourceFolder(
  token: string,
  workspaceId: string,
  folderId: string
) {
  return request<void>(foldersPath(workspaceId, `/${folderId}`), {
    method: "DELETE",
    token,
  })
}

export function moveResourceToFolder(
  token: string,
  workspaceId: string,
  payload: {
    resource_type: FolderResourceType
    resource_id: string
    folder_id: string | null
  }
) {
  return request<void>(foldersPath(workspaceId, "/resources/move"), {
    method: "PUT",
    token,
    body: JSON.stringify(payload),
  })
}

export function moveResourcesToFolder(
  token: string,
  workspaceId: string,
  payload: {
    resource_type: FolderResourceType
    resource_ids: string[]
    folder_id: string | null
  }
) {
  return request<void>(foldersPath(workspaceId, "/resources/move-batch"), {
    method: "PUT",
    token,
    body: JSON.stringify(payload),
  })
}

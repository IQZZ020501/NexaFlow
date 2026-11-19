import { request } from "@/lib/api-client"

export type MemoryCategory = "preference" | "background" | "goal" | "project"
export type MemoryDraft = {
  category: MemoryCategory
  key: string
  content: string
  project_id: string
  expires_at: string | null
}
export type UserMemory = MemoryDraft & {
  id: string
  origin: "manual" | "explicit" | "automatic"
  source_run_id: string | null
  source_quote: string
  source_conversation_id: string | null
  source_agent_id: string | null
  updated_at: string
}
export type MemoryProfile = {
  enabled: boolean
  automatic: boolean
  items: UserMemory[]
}
export type MemoryProject = {
  id: string
  name: string
  archived: boolean
  agent_id: string
}

function path(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/memories${suffix}`
}

export function getMemoryProfile(
  workspaceId: string,
  token: string,
  signal?: AbortSignal
) {
  return request<MemoryProfile>(path(workspaceId), { token, signal })
}

export function listMemoryProjects(
  workspaceId: string,
  token: string,
  signal?: AbortSignal
) {
  return request<{ items: MemoryProject[] }>(path(workspaceId, "/projects"), {
    token,
    signal,
  })
}

export function updateMemoryPreferences(
  workspaceId: string,
  token: string,
  preferences: Pick<MemoryProfile, "enabled" | "automatic">
) {
  return request<MemoryProfile>(path(workspaceId, "/preferences"), {
    method: "PUT",
    token,
    body: JSON.stringify(preferences),
  })
}

export function saveUserMemory(
  workspaceId: string,
  token: string,
  value: MemoryDraft,
  memoryId?: string
) {
  return request<MemoryProfile>(
    path(workspaceId, memoryId ? `/${encodeURIComponent(memoryId)}` : ""),
    {
      method: memoryId ? "PUT" : "POST",
      token,
      body: JSON.stringify(value),
    }
  )
}

export function deleteUserMemory(
  workspaceId: string,
  token: string,
  memoryId?: string
) {
  return request<void>(
    path(workspaceId, memoryId ? `/${encodeURIComponent(memoryId)}` : ""),
    { method: "DELETE", token }
  )
}

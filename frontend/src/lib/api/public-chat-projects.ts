import { agentUploadForm } from "@/lib/agent-upload"
import { request } from "@/lib/api-client"

export type ChatProject = {
  id: string
  name: string
  instructions: string
  archived: boolean
  created_at: string
  updated_at: string
}

export type ChatProjectFile = {
  id: string
  path: string
  size_bytes: number
  content_hash: string
}

function path(agentId: string, suffix = "") {
  return `/api/v1/public/agents/${agentId}/projects${suffix}`
}

export function publicChatUrl(
  agentId: string,
  conversationId?: string | null,
  projectId?: string | null
) {
  const base = `/chat/${encodeURIComponent(agentId)}${projectId ? `/projects/${encodeURIComponent(projectId)}` : ""}`
  return conversationId
    ? `${base}?conversation_id=${encodeURIComponent(conversationId)}`
    : base
}

export function listChatProjects(
  agentId: string,
  token: string,
  signal?: AbortSignal
) {
  return request<{ items: ChatProject[] }>(path(agentId), { token, signal })
}

export function createChatProject(
  agentId: string,
  token: string,
  name: string,
  instructions: string
) {
  return request<ChatProject>(path(agentId), {
    token,
    method: "POST",
    body: JSON.stringify({ name, instructions }),
  })
}

export function updateChatProject(
  agentId: string,
  token: string,
  project: ChatProject
) {
  return request<ChatProject>(path(agentId, `/${project.id}`), {
    token,
    method: "PUT",
    body: JSON.stringify({
      name: project.name,
      instructions: project.instructions,
      archived: project.archived,
    }),
  })
}

export function dissolveChatProject(
  agentId: string,
  token: string,
  projectId: string
) {
  return request<void>(path(agentId, `/${projectId}`), {
    token,
    method: "DELETE",
  })
}

export function createProjectConversation(
  agentId: string,
  token: string,
  projectId: string
) {
  return request<{ conversation_id: string; project_id: string }>(
    path(agentId, `/${projectId}/conversations`),
    { token, method: "POST" }
  )
}

export function moveChatConversation(
  agentId: string,
  token: string,
  conversationId: string,
  projectId: string | null
) {
  return request<{ conversation_id: string; project_id: string | null }>(
    `/api/v1/public/agents/${agentId}/conversations/${conversationId}/project`,
    { token, method: "PATCH", body: JSON.stringify({ project_id: projectId }) }
  )
}

export function listChatProjectFiles(
  agentId: string,
  token: string,
  projectId: string,
  signal?: AbortSignal
) {
  return request<{ items: ChatProjectFile[] }>(
    path(agentId, `/${projectId}/files`),
    { token, signal }
  )
}

export function uploadChatProjectFiles(
  agentId: string,
  token: string,
  projectId: string,
  files: File[]
) {
  return request<{ items: ChatProjectFile[] }>(
    path(agentId, `/${projectId}/files`),
    { token, method: "POST", body: agentUploadForm(files) }
  )
}

export function deleteChatProjectFile(
  agentId: string,
  token: string,
  projectId: string,
  fileId: string
) {
  return request<void>(path(agentId, `/${projectId}/files/${fileId}`), {
    token,
    method: "DELETE",
  })
}

export function chatProjectFileUrl(
  agentId: string,
  projectId: string,
  fileId: string
) {
  return path(agentId, `/${projectId}/files/${fileId}/content`)
}

export function saveChatProjectArtifact(
  agentId: string,
  token: string,
  projectId: string,
  artifactId: string
) {
  return request<{ items: ChatProjectFile[] }>(
    path(agentId, `/${projectId}/artifacts`),
    { token, method: "POST", body: JSON.stringify({ artifact_id: artifactId }) }
  )
}

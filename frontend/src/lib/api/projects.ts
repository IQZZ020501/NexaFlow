import { apiUrl, ApiError, request } from "@/lib/api-client"

export type AgentProject = {
  id: string
  workspace_id: string
  name: string
  revision: number
  created_at: string
  updated_at: string
}
export type ProjectFile = {
  id: string
  project_id: string
  path: string
  role: "source" | "work"
  revision: number
  previous_version_id: string | null
  deleted: boolean
  content_hash: string
  size_bytes: number
  run_id: string | null
  invocation_id: string | null
  created_at: string
}
const root = (workspace: string) =>
  `/api/v1/workspaces/${encodeURIComponent(workspace)}/projects`
const projectPath = (workspace: string, project: string) =>
  `${root(workspace)}/${encodeURIComponent(project)}`
export const listProjects = (token: string, workspace: string, offset = 0) =>
  request<AgentProject[]>(`${root(workspace)}?limit=100&offset=${offset}`, {
    token,
  })
export const getProject = (token: string, workspace: string, id: string) =>
  request<AgentProject>(projectPath(workspace, id), { token })
export const createProject = (token: string, workspace: string, name: string) =>
  request<AgentProject>(root(workspace), {
    token,
    method: "POST",
    body: JSON.stringify({ name }),
  })
export const renameProject = (
  token: string,
  workspace: string,
  id: string,
  name: string
) =>
  request<AgentProject>(projectPath(workspace, id), {
    token,
    method: "PATCH",
    body: JSON.stringify({ name }),
  })
export const deleteProject = (token: string, workspace: string, id: string) =>
  request<void>(projectPath(workspace, id), { token, method: "DELETE" })
export const listProjectFiles = (
  token: string,
  workspace: string,
  id: string
) => request<ProjectFile[]>(`${projectPath(workspace, id)}/files`, { token })
export const listProjectVersions = (
  token: string,
  workspace: string,
  id: string,
  path: string,
  offset = 0
) =>
  request<ProjectFile[]>(
    `${projectPath(workspace, id)}/versions?${new URLSearchParams({ path, offset: String(offset), limit: "50" })}`,
    { token }
  )
export function uploadProjectFile(
  token: string,
  workspace: string,
  id: string,
  path: string,
  role: ProjectFile["role"],
  file: File,
  expected?: string
) {
  const body = new FormData()
  body.set("path", path)
  body.set("role", role)
  body.set("file", file)
  if (expected) body.set("expected_version_id", expected)
  return request<ProjectFile>(`${projectPath(workspace, id)}/files`, {
    token,
    method: "POST",
    body,
  })
}
export const deleteProjectFile = (
  token: string,
  workspace: string,
  id: string,
  file: ProjectFile
) =>
  request<ProjectFile>(`${projectPath(workspace, id)}/files`, {
    token,
    method: "DELETE",
    body: JSON.stringify({ path: file.path, expected_version_id: file.id }),
  })
export const renameProjectFile = (
  token: string,
  workspace: string,
  id: string,
  file: ProjectFile,
  newPath: string
) =>
  request<ProjectFile>(`${projectPath(workspace, id)}/files/rename`, {
    token,
    method: "POST",
    body: JSON.stringify({
      path: file.path,
      expected_version_id: file.id,
      new_path: newPath,
    }),
  })
export async function downloadProjectVersion(
  token: string,
  workspace: string,
  id: string,
  file: ProjectFile
) {
  const response = await fetch(
    apiUrl(
      `${projectPath(workspace, id)}/versions/${encodeURIComponent(file.id)}/content`
    ),
    { headers: { Authorization: `Bearer ${token}` }, credentials: "include" }
  )
  if (!response.ok) throw new ApiError(response.status, response.statusText)
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = file.path.split("/").at(-1) ?? file.path
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

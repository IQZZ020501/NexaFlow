import { listQuery, request } from "@/lib/api-client"
import type { User } from "@/lib/api/auth"

export type ToolKind = "builtin" | "python" | "mcp"

export type ToolRef = {
  tool_id: string
  version_id: string
}

export type ToolSourceSummary = {
  id: string
  name: string
  kind: ToolKind
  transport: "streamable_http" | "sse" | "stdio" | null
}

export type ToolSourceDetail = ToolSourceSummary & {
  workspace_id: string
  status: "active" | "disabled" | string
  url: string | null
  stdio_command: string | null
  has_bearer_token: boolean
  bearer_token_hint: string | null
  last_error: string | null
  created_by_user_id: string
  created_at: string
  updated_at: string
  tool_count: number
}

export type McpTransport = "streamable_http" | "sse" | "stdio"

export type McpSourceCreatePayload =
  | {
      name: string
      transport: "streamable_http" | "sse"
      url: string
      bearer_token?: string
    }
  | {
      name: string
      transport: "stdio"
      stdio_config: {
        command: string
        args: string[]
        cwd?: string
        env: Record<string, string>
      }
    }

export type ToolSummary = {
  id: string
  workspace_id: string
  kind: ToolKind
  function_name: string
  display_name: string
  description: string
  current_version_id: string | null
  status: string
  availability: "available" | "unavailable"
  source: ToolSourceSummary
  created_by_user_id: string | null
  permission: "owner" | "admin" | "view" | "use" | null
  can_view: boolean
  can_use: boolean
  can_manage: boolean
}

export type ToolDraft = {
  display_name: string
  description: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  code: string
  revision: number
  updated_at: string
}

export type ToolDetail = ToolSummary & {
  version_id: string | null
  revision: number | null
  input_schema: Record<string, unknown> | null
  output_schema: Record<string, unknown> | null
  approval: "auto" | "each_call" | "disabled" | null
  effect: "pure" | "external_read" | "external_write" | "unknown" | null
  workflow_callable: boolean
  parallel_safe: boolean
  draft: ToolDraft | null
}

export type PythonToolPayload = {
  display_name: string
  description: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  code: string
}

export type ToolInvocation = {
  id: string
  tool_id: string
  tool_version_id: string
  status:
    | "queued"
    | "awaiting_approval"
    | "approved"
    | "running"
    | "succeeded"
    | "failed"
    | "rejected"
    | "uncertain"
    | "cancelled"
  attempts: number
  result_data: unknown
  result_summary: string
  outcome: "confirmed" | "uncertain" | null
  error_code: string | null
  error_message: string | null
  usage: Record<string, unknown>
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type ToolPermission = {
  user: User
  permission: "view" | "use"
}

export type ToolPolicyMode = "approval_required" | "read_only" | "disabled"

function toolsPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/tools${suffix}`
}

function toolSourcesPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/tool-sources${suffix}`
}

export function listTools(
  token: string,
  workspaceId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<ToolSummary[]>(
    `${toolsPath(workspaceId)}${listQuery(options)}`,
    { token }
  )
}

const TOOL_PAGE_SIZE = 200

export async function listAllTools(token: string, workspaceId: string) {
  const tools: ToolSummary[] = []
  let offset = 0

  while (true) {
    const page = await listTools(token, workspaceId, {
      limit: TOOL_PAGE_SIZE,
      offset,
    })
    tools.push(...page)
    if (page.length < TOOL_PAGE_SIZE) return tools
    offset += page.length
  }
}

export function getTool(token: string, workspaceId: string, toolId: string) {
  return request<ToolDetail>(toolsPath(workspaceId, `/${toolId}`), { token })
}

export function listToolSources(
  token: string,
  workspaceId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<ToolSourceDetail[]>(
    `${toolSourcesPath(workspaceId)}${listQuery(options)}`,
    { token }
  )
}

export async function listAllToolSources(token: string, workspaceId: string) {
  const sources: ToolSourceDetail[] = []
  let offset = 0

  while (true) {
    const page = await listToolSources(token, workspaceId, {
      limit: TOOL_PAGE_SIZE,
      offset,
    })
    sources.push(...page)
    if (page.length < TOOL_PAGE_SIZE) return sources
    offset += page.length
  }
}

export function createMcpSource(
  token: string,
  workspaceId: string,
  payload: McpSourceCreatePayload
) {
  return request<ToolSourceDetail>(toolSourcesPath(workspaceId, "/mcp"), {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function refreshToolSource(
  token: string,
  workspaceId: string,
  sourceId: string
) {
  return request<ToolSourceDetail>(
    toolSourcesPath(workspaceId, `/${sourceId}/refresh`),
    { method: "POST", token }
  )
}

export function setToolSourceEnabled(
  token: string,
  workspaceId: string,
  sourceId: string,
  enabled: boolean
) {
  return request<ToolSourceDetail>(
    toolSourcesPath(
      workspaceId,
      `/${sourceId}/${enabled ? "enable" : "disable"}`
    ),
    { method: "POST", token }
  )
}

export function deleteToolSource(
  token: string,
  workspaceId: string,
  sourceId: string
) {
  return request<void>(toolSourcesPath(workspaceId, `/${sourceId}`), {
    method: "DELETE",
    token,
  })
}

export function createPythonTool(
  token: string,
  workspaceId: string,
  payload: PythonToolPayload
) {
  return request<ToolDetail>(toolsPath(workspaceId, "/python"), {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updatePythonToolDraft(
  token: string,
  workspaceId: string,
  toolId: string,
  payload: PythonToolPayload & { expected_revision: number }
) {
  return request<ToolDraft>(toolsPath(workspaceId, `/${toolId}/draft`), {
    method: "PUT",
    token,
    body: JSON.stringify(payload),
  })
}

export function testPythonTool(
  token: string,
  workspaceId: string,
  toolId: string,
  argumentsValue: Record<string, unknown>
) {
  return request<ToolInvocation>(toolsPath(workspaceId, `/${toolId}/tests`), {
    method: "POST",
    token,
    body: JSON.stringify({ arguments: argumentsValue }),
  })
}

export function getPythonToolTest(
  token: string,
  workspaceId: string,
  toolId: string,
  invocationId: string
) {
  return request<ToolInvocation>(
    toolsPath(workspaceId, `/${toolId}/tests/${invocationId}`),
    { token }
  )
}

export function publishPythonTool(
  token: string,
  workspaceId: string,
  toolId: string
) {
  return request<ToolDetail>(toolsPath(workspaceId, `/${toolId}/publish`), {
    method: "POST",
    token,
  })
}

export function setPythonToolEnabled(
  token: string,
  workspaceId: string,
  toolId: string,
  enabled: boolean
) {
  return request<ToolDetail>(
    toolsPath(workspaceId, `/${toolId}/${enabled ? "enable" : "disable"}`),
    { method: "POST", token }
  )
}

export function archivePythonTool(
  token: string,
  workspaceId: string,
  toolId: string
) {
  return request<void>(toolsPath(workspaceId, `/${toolId}`), {
    method: "DELETE",
    token,
  })
}

export function updateToolPolicy(
  token: string,
  workspaceId: string,
  toolId: string,
  mode: ToolPolicyMode
) {
  return request<ToolDetail>(toolsPath(workspaceId, `/${toolId}/policy`), {
    method: "PUT",
    token,
    body: JSON.stringify({ mode }),
  })
}

export function listToolPermissions(
  token: string,
  workspaceId: string,
  toolId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<ToolPermission[]>(
    `${toolsPath(workspaceId, `/${toolId}/permissions`)}${listQuery(options)}`,
    { token }
  )
}

export async function listAllToolPermissions(
  token: string,
  workspaceId: string,
  toolId: string
) {
  const permissions: ToolPermission[] = []
  let offset = 0

  while (true) {
    const page = await listToolPermissions(token, workspaceId, toolId, {
      limit: TOOL_PAGE_SIZE,
      offset,
    })
    permissions.push(...page)
    if (page.length < TOOL_PAGE_SIZE) return permissions
    offset += page.length
  }
}

export function setToolPermission(
  token: string,
  workspaceId: string,
  toolId: string,
  userId: string,
  permission: "view" | "use"
) {
  return request<ToolPermission>(
    toolsPath(workspaceId, `/${toolId}/permissions/${userId}`),
    {
      method: "PUT",
      token,
      body: JSON.stringify({ permission }),
    }
  )
}

export function revokeToolPermission(
  token: string,
  workspaceId: string,
  toolId: string,
  userId: string
) {
  return request<void>(
    toolsPath(workspaceId, `/${toolId}/permissions/${userId}`),
    { method: "DELETE", token }
  )
}

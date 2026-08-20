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

/**
 * Builds the workspace-scoped API path for tool operations.
 *
 * @param workspaceId - The workspace identifier
 * @param suffix - An optional path suffix
 * @returns The workspace tool API path
 */
function toolsPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/tools${suffix}`
}

/**
 * Builds the workspace-scoped API path for tool sources.
 *
 * @param workspaceId - The workspace identifier
 * @param suffix - An optional path suffix
 * @returns The tool-sources API path
 */
function toolSourcesPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/tool-sources${suffix}`
}

/**
 * Retrieves a page of tools for a workspace.
 *
 * @param options - Optional pagination settings.
 * @returns The requested page of tool summaries.
 */
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

/**
 * Retrieves all tools available in a workspace.
 *
 * @returns The complete list of tools in the workspace
 */
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

/**
 * Retrieves detailed information about a workspace tool.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Workspace containing the tool
 * @param toolId - The identifier of the tool to retrieve
 * @returns The tool details
 */
export function getTool(token: string, workspaceId: string, toolId: string) {
  return request<ToolDetail>(toolsPath(workspaceId, `/${toolId}`), { token })
}

/**
 * Retrieves a paginated list of tool sources for a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Workspace containing the tool sources
 * @param options - Optional pagination settings.
 * @returns The matching tool source details.
 */
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

/**
 * Retrieves all tool sources in a workspace.
 *
 * @returns The complete list of tool source details.
 */
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

/**
 * Creates an MCP tool source for a workspace.
 *
 * @param payload - The MCP source configuration and connection details.
 * @returns Details of the created MCP tool source.
 */
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

/**
 * Refreshes an MCP tool source and retrieves its updated details.
 *
 * @param sourceId - The identifier of the tool source to refresh
 * @returns The refreshed tool source details
 */
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

/**
 * Enables or disables an MCP tool source.
 *
 * @param sourceId - The identifier of the tool source to update
 * @param enabled - Whether the tool source should be enabled
 * @returns The updated tool source details
 */
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

/**
 * Deletes a tool source from a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Workspace containing the tool source
 * @param sourceId - Identifier of the tool source to delete
 */
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

/**
 * Creates a Python tool in a workspace.
 *
 * @param payload - The Python tool configuration
 * @returns Details of the created tool
 */
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

/**
 * Updates a Python tool draft using an expected revision.
 *
 * @param toolId - The identifier of the Python tool to update
 * @param payload - The draft data and revision expected by the update
 * @returns The updated Python tool draft
 */
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

/**
 * Starts a test invocation of a Python tool.
 *
 * @param argumentsValue - Arguments supplied to the tool invocation
 * @returns The resulting tool invocation
 */
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

/**
 * Retrieves the result of a Python tool test invocation.
 *
 * @param toolId - The identifier of the Python tool
 * @param invocationId - The identifier of the test invocation
 * @returns The test invocation details
 */
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

/**
 * Publishes a Python tool.
 *
 * @param toolId - The identifier of the Python tool to publish
 * @returns The published tool details
 */
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

/**
 * Enables or disables a Python tool.
 *
 * @param toolId - The identifier of the Python tool
 * @param enabled - Whether the tool should be enabled
 * @returns The updated tool details
 */
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

/**
 * Archives a Python tool.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Workspace containing the tool
 * @param toolId - Identifier of the tool to archive
 */
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

/**
 * Updates the policy mode for a workspace tool.
 *
 * @param mode - The policy mode to apply to the tool
 * @returns The updated tool details
 */
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

/**
 * Lists users who have permission to access a tool.
 *
 * @param toolId - The identifier of the tool whose permissions are listed
 * @param options - Pagination options for limiting and offsetting the results
 * @returns The tool's user permissions
 */
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

/**
 * Retrieves all user permissions for a tool across paginated results.
 *
 * @param toolId - The identifier of the tool whose permissions are retrieved
 * @returns The complete list of user permissions for the tool
 */
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

/**
 * Assigns a permission level to a user for a tool.
 *
 * @param permission - The access level to assign: `view` or `use`
 * @returns The assigned tool permission
 */
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

/**
 * Removes a user's permission to access a tool.
 *
 * @param userId - The user whose tool permission is removed
 */
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

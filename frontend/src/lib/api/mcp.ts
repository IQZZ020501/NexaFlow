import { listQuery, request } from "@/lib/api-client"

export type McpTool = {
  name: string
  description: string
  input_schema: Record<string, unknown>
  annotations: Record<string, unknown> | null
  definition_hash: string
  policy_mode: McpToolPolicyMode
}

export type McpToolPolicyMode = "approval_required" | "read_only" | "disabled"
export type McpTransport = "streamable_http" | "sse" | "stdio"

export type McpOAuthConfiguration = {
  authorization_endpoint: string
  token_endpoint: string
  revocation_endpoint: string
  client_id: string
  client_auth_method: "none" | "client_secret_basic" | "client_secret_post"
  client_secret?: string
  scopes: string[]
}

export type McpOAuthStatus = {
  status:
    "disconnected" | "connected" | "refreshing" | "reauthorization_required"
  expires_at: string | null
  configuration: Omit<McpOAuthConfiguration, "client_secret">
}

export type McpTaskContract = {
  status_tool: string
  result_tool: string
  cancel_tool: string
  poll_seconds: number
}
export type McpTaskConfiguration = {
  tools: string[]
  contracts: Record<string, McpTaskContract>
}

export function getMcpTaskConfiguration(
  token: string,
  workspaceId: string,
  serverId: string
) {
  return request<McpTaskConfiguration>(
    mcpPath(workspaceId, `/${serverId}/long-tasks`),
    { token }
  )
}

export function configureMcpTasks(
  token: string,
  workspaceId: string,
  serverId: string,
  contracts: Record<string, McpTaskContract>
) {
  return request<McpTaskConfiguration>(
    mcpPath(workspaceId, `/${serverId}/long-tasks`),
    { token, method: "PUT", body: JSON.stringify({ contracts }) }
  )
}

export type McpServer = {
  id: string
  workspace_id: string
  name: string
  transport: McpTransport
  auth_mode?: "bearer" | "oauth"
  url: string | null
  stdio_command: string | null
  tools: McpTool[]
  status: "active" | "disabled"
  has_bearer_token: boolean
  bearer_token_hint: string | null
  last_error: string | null
  created_by_user_id: string
  created_at: string
  updated_at: string
}

/**
 * Builds the API path for MCP servers in a workspace.
 *
 * @param workspaceId - The workspace identifier
 * @param suffix - An optional path suffix
 * @returns The workspace-scoped MCP server API path
 */
function mcpPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/mcp-servers${suffix}`
}

export function getMcpOAuth(
  token: string,
  workspaceId: string,
  serverId: string
) {
  return request<McpOAuthStatus>(mcpPath(workspaceId, `/${serverId}/oauth`), {
    token,
  })
}

export function configureMcpOAuth(
  token: string,
  workspaceId: string,
  serverId: string,
  payload: McpOAuthConfiguration
) {
  return request<McpOAuthStatus>(mcpPath(workspaceId, `/${serverId}/oauth`), {
    token,
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

export function authorizeMcpOAuth(
  token: string,
  workspaceId: string,
  serverId: string
) {
  return request<{ authorization_url: string; redirect_uri: string }>(
    mcpPath(workspaceId, `/${serverId}/oauth/authorize`),
    { token, method: "POST" }
  )
}

export function completeMcpOAuth(
  token: string,
  workspaceId: string,
  serverId: string,
  state: string,
  code: string
) {
  return request<McpOAuthStatus>(
    mcpPath(workspaceId, `/${serverId}/oauth/callback`),
    { token, method: "POST", body: JSON.stringify({ state, code }) }
  )
}

export function disconnectMcpOAuth(
  token: string,
  workspaceId: string,
  serverId: string
) {
  return request<McpOAuthStatus>(
    mcpPath(workspaceId, `/${serverId}/oauth/disconnect`),
    { token, method: "POST" }
  )
}

/**
 * Retrieves MCP servers configured for a workspace.
 *
 * @param workspaceId - The workspace whose MCP servers to retrieve
 * @param options - Optional pagination parameters
 * @param options.limit - The maximum number of servers to return
 * @param options.offset - The number of servers to skip
 * @returns The workspace's MCP servers
 */
export function listMcpServers(
  token: string,
  workspaceId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<McpServer[]>(`${mcpPath(workspaceId)}${listQuery(options)}`, {
    token,
  })
}

/**
 * Refreshes an MCP server's configuration and available tools.
 *
 * @param serverId - The identifier of the MCP server to refresh
 * @returns The refreshed MCP server
 */
export function refreshMcpServer(
  token: string,
  workspaceId: string,
  serverId: string
) {
  return request<McpServer>(mcpPath(workspaceId, `/${serverId}/refresh`), {
    method: "POST",
    token,
  })
}

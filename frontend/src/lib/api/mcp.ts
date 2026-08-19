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

export type McpServer = {
  id: string
  workspace_id: string
  name: string
  transport: McpTransport
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

export type McpServerCreatePayload =
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
  options: { limit?: number; offset?: number } = {},
) {
  return request<McpServer[]>(`${mcpPath(workspaceId)}${listQuery(options)}`, {
    token,
  })
}

/**
 * Creates an MCP server in a workspace.
 *
 * @param workspaceId - The workspace containing the server
 * @param payload - The server configuration
 * @returns The created MCP server
 */
export function createMcpServer(
  token: string,
  workspaceId: string,
  payload: McpServerCreatePayload
) {
  return request<McpServer>(mcpPath(workspaceId), {
    method: "POST",
    token,
    body: JSON.stringify(payload),
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

/**
 * Deletes an MCP server from a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Identifier of the workspace containing the server
 * @param serverId - Identifier of the server to delete
 */
export function deleteMcpServer(
  token: string,
  workspaceId: string,
  serverId: string
) {
  return request<void>(mcpPath(workspaceId, `/${serverId}`), {
    method: "DELETE",
    token,
  })
}

/**
 * Updates the policy mode for an MCP server tool.
 *
 * @param toolName - The name of the tool whose policy to update
 * @param mode - The policy mode to apply to the tool
 * @returns The updated tool policy metadata
 */
export function updateMcpToolPolicy(
  token: string,
  workspaceId: string,
  serverId: string,
  toolName: string,
  mode: McpToolPolicyMode
) {
  return request<{
    workspace_id: string
    mcp_server_id: string
    tool_name: string
    definition_hash: string
    mode: McpToolPolicyMode
    reviewed_by_user_id: string | null
    reviewed_at: string | null
  }>(
    mcpPath(
      workspaceId,
      `/${serverId}/tools/${encodeURIComponent(toolName)}/policy`
    ),
    {
      method: "PUT",
      token,
      body: JSON.stringify({ mode }),
    }
  )
}

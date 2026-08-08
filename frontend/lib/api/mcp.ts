import { request } from "@/lib/api-client"

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

function mcpPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/mcp-servers${suffix}`
}

export function listMcpServers(token: string, workspaceId: string) {
  return request<McpServer[]>(mcpPath(workspaceId), { token })
}

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

import { request } from "@/lib/api-client"

export type McpTool = {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

export type McpServer = {
  id: string
  workspace_id: string
  name: string
  url: string
  tools: McpTool[]
  status: "active" | "disabled"
  has_bearer_token: boolean
  bearer_token_hint: string | null
  last_error: string | null
  created_by_user_id: string
  created_at: string
  updated_at: string
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
  payload: { name: string; url: string; bearer_token?: string }
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

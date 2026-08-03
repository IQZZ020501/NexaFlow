import { request } from "@/lib/api-client"

export type Agent = {
  id: string
  workspace_id: string
  name: string
  description: string
  instructions: string
  model_id: string
  knowledge_base_ids: string[]
  mcp_tools: AgentMcpToolRef[]
  status: "active" | "disabled"
  created_by_user_id: string
  can_edit: boolean
  created_at: string
  updated_at: string
}

export type AgentMcpToolRef = {
  server_id: string
  tool_name: string
}

export type AgentPayload = {
  name: string
  model_id: string
  knowledge_base_ids: string[]
  mcp_tools: AgentMcpToolRef[]
  description?: string
  instructions?: string
  status?: "active" | "disabled"
}

export type AgentPlanStep = {
  number: number
  title: string
  description: string
  status: "pending" | "completed" | "failed"
}

export type AgentRunEvent = {
  turn: number
  tool_name: string
  status: "succeeded" | "failed"
  summary: string
}

export type AgentCitation = {
  source_id: string
  knowledge_base_id: string
  knowledge_base_name: string
  document_id: string
  document_filename: string
  chunk_id: string
  chunk_index: number
  excerpt: string
}

export type AgentRun = {
  id: string
  workspace_id: string
  agent_id: string
  requested_by_user_id: string
  goal: string
  model_id: string
  model_name: string
  status: "planning" | "planned" | "running" | "succeeded" | "failed"
  plan: AgentPlanStep[]
  events: AgentRunEvent[]
  citations: AgentCitation[]
  result: string
  last_error: string | null
  planned_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

function agentsPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/agents${suffix}`
}

export function listAgents(token: string, workspaceId: string) {
  return request<Agent[]>(agentsPath(workspaceId), { token })
}

export function createAgent(
  token: string,
  workspaceId: string,
  payload: AgentPayload
) {
  return request<Agent>(agentsPath(workspaceId), {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updateAgent(
  token: string,
  workspaceId: string,
  agentId: string,
  payload: Partial<AgentPayload>
) {
  return request<Agent>(agentsPath(workspaceId, `/${agentId}`), {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function deleteAgent(
  token: string,
  workspaceId: string,
  agentId: string
) {
  return request<void>(agentsPath(workspaceId, `/${agentId}`), {
    method: "DELETE",
    token,
  })
}

export function listAgentRuns(
  token: string,
  workspaceId: string,
  agentId: string
) {
  return request<AgentRun[]>(agentsPath(workspaceId, `/${agentId}/runs`), {
    token,
  })
}

export function askAgent(
  token: string,
  workspaceId: string,
  agentId: string,
  goal: string
) {
  return request<AgentRun>(agentsPath(workspaceId, `/${agentId}/runs`), {
    method: "POST",
    token,
    body: JSON.stringify({ goal }),
  })
}

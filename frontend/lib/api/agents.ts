import { apiUrl, request } from "@/lib/api-client"

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
  published: boolean
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
  published?: boolean
}

export type AgentPlanStep = {
  number: number
  title: string
  description: string
  status: "pending" | "completed" | "failed"
}

export type AgentRunEvent = {
  type: "thought" | "tool"
  turn: number
  tool_name: string
  status: "running" | "succeeded" | "failed"
  summary: string
  call_id: string
  tool_label: string
  tool_kind: "knowledge" | "mcp" | "unknown"
  server_name: string
  input: Record<string, unknown>
  output: unknown
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
  result: string
  last_error: string | null
  planned_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export type AgentRunStreamEvent =
  | { type: "run"; run: AgentRun }
  | { type: "process"; event: AgentRunEvent }
  | { type: "answer_delta"; delta: string }
  | { type: "complete" | "error"; run: AgentRun }

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


export async function streamAgentRun(
  token: string,
  workspaceId: string,
  agentId: string,
  goal: string,
  onEvent: (event: AgentRunStreamEvent) => void,
  preview = false
) {
  const response = await fetch(
    apiUrl(agentsPath(workspaceId, `/${agentId}/runs/stream`)),
    {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ goal, preview }),
    }
  )
  if (!response.ok) {
    throw new Error(`Agent stream failed with status ${response.status}.`)
  }
  if (!response.body) {
    throw new Error("Agent stream did not return a response body.")
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line) as AgentRunStreamEvent)
    }
    if (done) break
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as AgentRunStreamEvent)
}

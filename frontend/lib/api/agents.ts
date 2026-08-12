import { apiUrl, listQuery, request } from "@/lib/api-client"
import { observeNdjsonStream } from "@/lib/api/run-stream"
import type { User } from "@/lib/api/auth"

export type KnowledgeQueryMode = "required" | "agentic"

export type AppType = "agent" | "workflow"

export type Agent = {
  id: string
  workspace_id: string
  name: string
  app_type: AppType
  description: string
  instructions: string
  model_id: string
  knowledge_query_mode: KnowledgeQueryMode
  knowledge_base_ids: string[]
  mcp_tools: AgentMcpToolRef[]
  status: "active" | "disabled"
  published: boolean
  has_unpublished_changes: boolean
  published_by_user_id: string | null
  published_at: string | null
  created_by_user_id: string
  can_edit: boolean
  created_at: string
  updated_at: string
}

export type AgentMcpToolRef = {
  server_id: string
  tool_name: string
}

export type AgentPermission = {
  user: User
  permission: "view"
}

export type AgentPayload = {
  name: string
  app_type?: AppType
  model_id: string
  knowledge_query_mode: KnowledgeQueryMode
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
  duration_ms: number
  reasoning?: string
}

export type AgentRunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "planning"
  | "planned"

export type AgentRun = {
  id: string
  workspace_id: string
  agent_id: string
  requested_by_user_id: string
  conversation_id: string
  goal: string
  model_id: string
  model_name: string
  knowledge_query_mode: KnowledgeQueryMode
  status: AgentRunStatus
  plan: AgentPlanStep[]
  events: AgentRunEvent[]
  result: string
  model_usage: Record<string, unknown>
  last_error: string | null
  planned_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  trace_id: string
  live_stream_epoch?: string
  live_stream_cursor?: string
}

export type AgentToolCall = {
  call_id: string
  turn: number
  tool_name: string
  tool_kind: "knowledge" | "mcp" | "unknown"
  server_name: string
  arguments: Record<string, unknown>
  status:
    | "pending"
    | "awaiting_approval"
    | "approved"
    | "running"
    | "succeeded"
    | "failed"
    | "rejected"
    | "uncertain"
  approval_required: boolean
  last_error: string | null
  approved_at: string | null
  started_at: string | null
  finished_at: string | null
}

export type AgentRunStreamEvent =
  | { type: "run"; sequence: number; run: AgentRun }
  | { type: "process"; sequence: number; event: AgentRunEvent }
  | {
      type: "reasoning_delta"
      sequence?: number
      live_sequence?: string
      stream_epoch?: string
      turn: number
      delta: string
    }
  | {
      type: "answer_delta"
      sequence?: number
      live_sequence?: string
      stream_epoch?: string
      delta: string
    }
  | {
      type: "approval_required"
      sequence: number
      call_id: string
      reason: string
    }
  | {
      type: "approval_resolved"
      sequence: number
      call_id: string
      decision: "approved" | "rejected"
    }
  | { type: "complete" | "error"; sequence: number; run: AgentRun }

export type AgentApiCredential = {
  id: string
  agent_id: string
  workspace_id: string
  name: string
  hint: string
  created_by_user_id: string
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export type AgentApiCredentialSecret = {
  credential: AgentApiCredential
  token: string
}

export type AgentApiDocumentation = {
  agent_id: string
  agent_name: string
  base_path: string
}

export type AgentAccessSource = "console" | "public" | "api"

export type AgentLog = {
  id: string
  conversation_id: string
  access_source: AgentAccessSource
  consumer_id: string
  display_name: string
  requested_by_user_id: string | null
  execution_user_id: string
  question: string
  status: string
  result: string
  last_error: string | null
  model_usage: Record<string, unknown>
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export type AgentConversationUser = {
  consumer_id: string
  access_source: AgentAccessSource
  display_name: string
  first_seen_at: string
  last_seen_at: string
  conversation_count: number
  run_count: number
}

export type AgentMonitoringValues = {
  active_users: number
  conversations: number
  runs: number
  succeeded: number
  failed: number
  total_tokens: number
}

export type AgentMonitoring = {
  days: 7 | 30 | 90
  summary: AgentMonitoringValues
  daily: Array<AgentMonitoringValues & { date: string }>
}

export type PaginatedResponse<T> = {
  items: T[]
  total: number
  offset: number
  limit: number
}

function agentsPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/agents${suffix}`
}

export function listAgents(
  token: string,
  workspaceId: string,
  options: { limit?: number; offset?: number } = {},
) {
  return request<Agent[]>(`${agentsPath(workspaceId)}${listQuery(options)}`, {
    token,
  })
}

export function getAgent(token: string, workspaceId: string, agentId: string) {
  return request<Agent>(agentsPath(workspaceId, `/${agentId}`), { token })
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

export function listAgentPermissions(
  token: string,
  workspaceId: string,
  agentId: string
) {
  return request<AgentPermission[]>(
    agentsPath(workspaceId, `/${agentId}/permissions`),
    { token }
  )
}

export function grantAgentPermission(
  token: string,
  workspaceId: string,
  agentId: string,
  userId: string
) {
  return request<AgentPermission>(
    agentsPath(workspaceId, `/${agentId}/permissions/${userId}`),
    {
      method: "PUT",
      token,
      body: JSON.stringify({ permission: "view" }),
    }
  )
}

export function revokeAgentPermission(
  token: string,
  workspaceId: string,
  agentId: string,
  userId: string
) {
  return request<void>(
    agentsPath(workspaceId, `/${agentId}/permissions/${userId}`),
    { method: "DELETE", token }
  )
}

export function listAgentApiCredentials(
  token: string,
  workspaceId: string,
  agentId: string
) {
  return request<{ items: AgentApiCredential[] }>(
    agentsPath(workspaceId, `/${agentId}/api-credentials`),
    { token }
  )
}

export function createAgentApiCredential(
  token: string,
  workspaceId: string,
  agentId: string,
  name: string
) {
  return request<AgentApiCredentialSecret>(
    agentsPath(workspaceId, `/${agentId}/api-credentials`),
    { method: "POST", token, body: JSON.stringify({ name }) }
  )
}

export function rotateAgentApiCredential(
  token: string,
  workspaceId: string,
  agentId: string,
  credentialId: string
) {
  return request<AgentApiCredentialSecret>(
    agentsPath(
      workspaceId,
      `/${agentId}/api-credentials/${credentialId}/rotate`
    ),
    { method: "POST", token }
  )
}

export function revokeAgentApiCredential(
  token: string,
  workspaceId: string,
  agentId: string,
  credentialId: string
) {
  return request<void>(
    agentsPath(workspaceId, `/${agentId}/api-credentials/${credentialId}`),
    { method: "DELETE", token }
  )
}

export function getAgentApiDocumentation(agentId: string, apiKey: string) {
  return request<AgentApiDocumentation>(
    `/api/v1/agent-api/${agentId}/documentation`,
    { token: apiKey }
  )
}

export function listAgentLogs(
  token: string,
  workspaceId: string,
  agentId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<PaginatedResponse<AgentLog>>(
    agentsPath(workspaceId, `/${agentId}/logs${listQuery(options)}`),
    { token }
  )
}

export function listAgentConversationUsers(
  token: string,
  workspaceId: string,
  agentId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<PaginatedResponse<AgentConversationUser>>(
    agentsPath(
      workspaceId,
      `/${agentId}/conversation-users${listQuery(options)}`
    ),
    { token }
  )
}

export function getAgentMonitoring(
  token: string,
  workspaceId: string,
  agentId: string,
  days: 7 | 30 | 90
) {
  return request<AgentMonitoring>(
    agentsPath(workspaceId, `/${agentId}/monitoring?days=${days}`),
    { token }
  )
}

export function listAgentRuns(
  token: string,
  workspaceId: string,
  agentId: string,
  conversationId?: string | null
) {
  const query = conversationId
    ? `?conversation_id=${encodeURIComponent(conversationId)}`
    : ""
  return request<AgentRun[]>(
    agentsPath(workspaceId, `/${agentId}/runs${query}`),
    {
      token,
    },
  )
}

export function createAgentRun(
  token: string,
  workspaceId: string,
  agentId: string,
  goal: string,
  signal?: AbortSignal,
  conversationId?: string | null
) {
  return request<AgentRun>(agentsPath(workspaceId, `/${agentId}/runs`), {
    method: "POST",
    token,
    body: JSON.stringify({
      goal,
      ...(conversationId ? { conversation_id: conversationId } : {}),
    }),
    signal,
  })
}

export function getAgentRun(
  token: string,
  workspaceId: string,
  agentId: string,
  runId: string
) {
  return request<AgentRun>(
    agentsPath(workspaceId, `/${agentId}/runs/${runId}`),
    { token }
  )
}

export function listAgentRunToolCalls(
  token: string,
  workspaceId: string,
  agentId: string,
  runId: string
) {
  return request<AgentToolCall[]>(
    agentsPath(workspaceId, `/${agentId}/runs/${runId}/tool-calls`),
    { token }
  )
}

export function resolveAgentToolCall(
  token: string,
  workspaceId: string,
  agentId: string,
  runId: string,
  callId: string,
  decision: "approve" | "reject"
) {
  return request<AgentRun>(
    agentsPath(
      workspaceId,
      `/${agentId}/runs/${runId}/tool-calls/${encodeURIComponent(callId)}/${decision}`
    ),
    { method: "POST", token }
  )
}

const TERMINAL_RUN_STATUSES = new Set<AgentRunStatus>([
  "succeeded",
  "failed",
  "cancelled",
])
export function compareLiveStreamIds(left: string, right: string) {
  const [leftMs, leftSequence] = left.split("-").map(Number)
  const [rightMs, rightSequence] = right.split("-").map(Number)
  return leftMs - rightMs || leftSequence - rightSequence
}

export async function observeAgentRun(
  token: string,
  workspaceId: string,
  agentId: string,
  runId: string,
  onEvent: (event: AgentRunStreamEvent) => void,
  signal?: AbortSignal,
  after = 0,
  liveAfter = "0-0"
) {
  return observeNdjsonStream<AgentRunStreamEvent>(
    (cursor, liveCursor, streamSignal) =>
      fetch(
        apiUrl(
          agentsPath(
            workspaceId,
            `/${agentId}/runs/${runId}/stream?after=${cursor}&live_after=${encodeURIComponent(liveCursor)}`
          )
        ),
        {
          headers: { Authorization: `Bearer ${token}` },
          credentials: "include",
          signal: streamSignal,
        },
      ),
    onEvent,
    { signal, after, liveAfter, errorLabel: "Agent stream" },
  )
}

export async function streamAgentRun(
  token: string,
  workspaceId: string,
  agentId: string,
  goal: string,
  onEvent: (event: AgentRunStreamEvent) => void,
  signal?: AbortSignal,
  conversationId?: string | null
) {
  const run = await createAgentRun(
    token,
    workspaceId,
    agentId,
    goal,
    signal,
    conversationId
  )
  onEvent({ type: "run", sequence: 0, run })
  if (TERMINAL_RUN_STATUSES.has(run.status)) return
  await observeAgentRun(token, workspaceId, agentId, run.id, onEvent, signal)
}

import { apiUrl, request } from "@/lib/api-client"

export type KnowledgeQueryMode = "required" | "agentic"

export type Agent = {
  id: string
  workspace_id: string
  name: string
  description: string
  instructions: string
  model_id: string
  knowledge_query_mode: KnowledgeQueryMode
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
  goal: string
  model_id: string
  model_name: string
  knowledge_query_mode: KnowledgeQueryMode
  status: AgentRunStatus
  plan: AgentPlanStep[]
  events: AgentRunEvent[]
  result: string
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

export function createAgentRun(
  token: string,
  workspaceId: string,
  agentId: string,
  goal: string,
  signal?: AbortSignal
) {
  return request<AgentRun>(agentsPath(workspaceId, `/${agentId}/runs`), {
    method: "POST",
    token,
    body: JSON.stringify({ goal }),
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
const INITIAL_RECONNECT_DELAY_MS = 250
const MAX_RECONNECT_DELAY_MS = 5_000

export function compareLiveStreamIds(left: string, right: string) {
  const [leftMs, leftSequence] = left.split("-").map(Number)
  const [rightMs, rightSequence] = right.split("-").map(Number)
  return leftMs - rightMs || leftSequence - rightSequence
}

function waitForReconnect(delayMs: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"))
      return
    }
    const onAbort = () => {
      clearTimeout(timeout)
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"))
    }
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort)
      resolve()
    }, delayMs)
    signal?.addEventListener("abort", onAbort, { once: true })
  })
}

async function consumeAgentRunStream(
  response: Response,
  onEvent: (event: AgentRunStreamEvent) => void,
  cursor: number,
  liveCursor: string,
  onCursor: (cursor: number, liveCursor: string) => void
) {
  if (!response.body) {
    throw new Error("Agent stream did not return a response body.")
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let terminal = false

  const consumeLine = (line: string) => {
    if (!line.trim()) return
    const event = JSON.parse(line) as AgentRunStreamEvent
    if ("sequence" in event && typeof event.sequence === "number") {
      cursor = Math.max(cursor, event.sequence)
    }
    if (
      "live_sequence" in event &&
      typeof event.live_sequence === "string"
    ) {
      liveCursor = event.live_sequence
    }
    onCursor(cursor, liveCursor)
    if (event.type === "complete" || event.type === "error") terminal = true
    onEvent(event)
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""
    lines.forEach(consumeLine)
    if (done) break
  }
  consumeLine(buffer)
  return { cursor, liveCursor, terminal }
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
  let cursor = after
  let liveCursor = liveAfter
  let reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS
  while (!signal?.aborted) {
    try {
      const response = await fetch(
        apiUrl(
          agentsPath(
            workspaceId,
            `/${agentId}/runs/${runId}/stream?after=${cursor}&live_after=${encodeURIComponent(liveCursor)}`
          )
        ),
        {
          headers: { Authorization: `Bearer ${token}` },
          credentials: "include",
          signal,
        }
      )
      if (!response.ok) {
        if (response.status < 500 && response.status !== 429) {
          throw new Error(`Agent stream failed with status ${response.status}.`)
        }
        await waitForReconnect(reconnectDelayMs, signal)
        reconnectDelayMs = Math.min(
          reconnectDelayMs * 2,
          MAX_RECONNECT_DELAY_MS
        )
        continue
      }
      reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS
      const consumed = await consumeAgentRunStream(
        response,
        onEvent,
        cursor,
        liveCursor,
        (nextCursor, nextLiveCursor) => {
          cursor = nextCursor
          liveCursor = nextLiveCursor
        }
      )
      cursor = consumed.cursor
      liveCursor = consumed.liveCursor
      if (consumed.terminal) return
    } catch (error) {
      if (signal?.aborted) throw signal.reason ?? error
      if (
        error instanceof Error &&
        error.message.startsWith("Agent stream failed with status")
      ) {
        throw error
      }
    }
    await waitForReconnect(reconnectDelayMs, signal)
    reconnectDelayMs = Math.min(
      reconnectDelayMs * 2,
      MAX_RECONNECT_DELAY_MS
    )
  }
}

export async function streamAgentRun(
  token: string,
  workspaceId: string,
  agentId: string,
  goal: string,
  onEvent: (event: AgentRunStreamEvent) => void,
  signal?: AbortSignal
) {
  const run = await createAgentRun(
    token,
    workspaceId,
    agentId,
    goal,
    signal
  )
  onEvent({ type: "run", sequence: 0, run })
  if (TERMINAL_RUN_STATUSES.has(run.status)) return
  await observeAgentRun(token, workspaceId, agentId, run.id, onEvent, signal)
}

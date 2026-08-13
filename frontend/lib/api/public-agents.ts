import { apiUrl, listQuery, request } from "@/lib/api-client"
import { observeNdjsonStream } from "@/lib/api/run-stream"
import type { AgentToolCall } from "@/lib/api/agents"
import type { AgentInteractionConfig } from "@/lib/api/agents"

export type PublicAgentProfile = {
  id: string
  name: string
  description: string
  interaction_config: AgentInteractionConfig
}

export type AgentUpload = {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  category: "document" | "image" | "audio"
}

export type PublicAgentConversation = {
  conversation_id: string
  question: string
  status: string
  result: string
  run_count: number
  created_at: string
  updated_at: string
}

export type ExternalAgentKnowledgeHit = {
  knowledge_base: string
  document: string
  content: string
}

export type ExternalAgentProgressEvent = {
  id: string
  type: "analysis" | "knowledge" | "tool" | "answer"
  status: "running" | "succeeded" | "failed"
  stage:
    | "analyzing"
    | "reviewing"
    | "completed"
    | "running"
    | "succeeded"
    | "failed"
  turn: number
  count: number | null
  reasoning?: string
  tool_name?: string
  tool_label?: string
  tool_kind?: "knowledge" | "mcp" | "unknown"
  server_name?: string
  input?: Record<string, unknown>
  output?: unknown
  input_truncated?: boolean
  hits: ExternalAgentKnowledgeHit[]
}

export type ExternalAgentRun = {
  id: string
  conversation_id: string
  question: string
  status: string
  result: string
  error: string | null
  progress: ExternalAgentProgressEvent[]
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
  live_stream_epoch?: string
  live_stream_cursor?: string
}

type PublicAgentStreamCursor = {
  sequence?: number
  live_sequence?: string
  stream_epoch?: string
}

export type PublicAgentRunStreamEvent =
  | (PublicAgentStreamCursor & { type: "run"; run: ExternalAgentRun })
  | (PublicAgentStreamCursor & {
      type: "answer_delta"
      delta: string
    })
  | (PublicAgentStreamCursor & {
      type: "reasoning_delta"
      turn: number
      delta: string
    })
  | (PublicAgentStreamCursor & {
      type: "progress"
      event: ExternalAgentProgressEvent
    })
  | (PublicAgentStreamCursor & {
      type: "approval_required"
      call_id: string
      reason: string
    })
  | (PublicAgentStreamCursor & {
      type: "complete" | "error"
      run: ExternalAgentRun
    })

export type PublicAgentRunList = {
  items: ExternalAgentRun[]
  total: number
  offset: number
  limit: number
}

function publicAgentPath(agentId: string, suffix = "") {
  return `/api/v1/public/agents/${agentId}${suffix}`
}

export function getPublicAgentProfile(agentId: string, token: string) {
  return request<PublicAgentProfile>(publicAgentPath(agentId, "/profile"), {
    token,
  })
}

export function listPublicAgentConversations(agentId: string, token: string) {
  return request<{ items: PublicAgentConversation[] }>(
    publicAgentPath(agentId, "/conversations"),
    { token }
  )
}

export async function initializePublicAgent(agentId: string, token: string) {
  const [profile, conversations] = await Promise.all([
    getPublicAgentProfile(agentId, token),
    listPublicAgentConversations(agentId, token),
  ])
  return { profile, conversations }
}

export function listPublicAgentRuns(
  agentId: string,
  conversationId: string,
  token: string,
  options: { limit?: number; offset?: number } = {}
) {
  const params = new URLSearchParams(listQuery(options).slice(1))
  params.set("conversation_id", conversationId)
  return request<PublicAgentRunList>(
    publicAgentPath(agentId, `/runs?${params.toString()}`),
    { token }
  )
}

export function createPublicAgentRun(
  agentId: string,
  token: string,
  goal: string,
  conversationId?: string | null,
  signal?: AbortSignal,
  fileIds: string[] = []
) {
  return request<ExternalAgentRun>(publicAgentPath(agentId, "/runs"), {
    method: "POST",
    body: JSON.stringify({
      goal,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      ...(fileIds.length ? { file_ids: fileIds } : {}),
    }),
    signal,
    token,
  })
}

export function uploadPublicAgentFiles(
  agentId: string,
  token: string,
  files: File[]
) {
  const body = new FormData()
  files.forEach((file) => body.append("files", file))
  return request<AgentUpload[]>(publicAgentPath(agentId, "/uploads"), {
    method: "POST",
    body,
    token,
  })
}

export function getPublicAgentRun(agentId: string, token: string, runId: string) {
  return request<ExternalAgentRun>(publicAgentPath(agentId, `/runs/${runId}`), {
    token,
  })
}

export function listPublicAgentRunToolCalls(
  agentId: string,
  token: string,
  runId: string
) {
  return request<AgentToolCall[]>(
    publicAgentPath(agentId, `/runs/${runId}/tool-calls`),
    { token }
  )
}

export function resolvePublicAgentRunToolCall(
  agentId: string,
  token: string,
  runId: string,
  callId: string,
  decision: "approve" | "reject"
) {
  return request<ExternalAgentRun>(
    publicAgentPath(agentId, `/runs/${runId}/tool-calls/${callId}/${decision}`),
    {
      method: "POST",
      token,
    }
  )
}

export function observePublicAgentRun(
  agentId: string,
  token: string,
  runId: string,
  onEvent: (event: PublicAgentRunStreamEvent) => void,
  signal?: AbortSignal,
  after = 0,
  liveAfter = "0-0"
) {
  return observeNdjsonStream<PublicAgentRunStreamEvent>(
    (cursor, liveCursor, streamSignal) =>
      fetch(
        apiUrl(
          publicAgentPath(
            agentId,
            `/runs/${runId}/stream?after=${cursor}&live_after=${encodeURIComponent(liveCursor)}`
          )
        ),
        {
          credentials: "include",
          headers: { Authorization: `Bearer ${token}` },
          signal: streamSignal,
        }
      ),
    onEvent,
    { signal, after, liveAfter, errorLabel: "Public Agent stream" }
  )
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"])

export async function streamPublicAgentRun(
  agentId: string,
  token: string,
  goal: string,
  onEvent: (event: PublicAgentRunStreamEvent) => void,
  signal?: AbortSignal,
  conversationId?: string | null,
  fileIds: string[] = []
) {
  const run = await createPublicAgentRun(
    agentId,
    token,
    goal,
    conversationId,
    signal,
    fileIds
  )
  onEvent({ type: "run", sequence: 0, run })
  if (TERMINAL_STATUSES.has(run.status)) {
    onEvent({ type: run.status === "succeeded" ? "complete" : "error", run })
    return
  }
  await observePublicAgentRun(agentId, token, run.id, onEvent, signal)
}

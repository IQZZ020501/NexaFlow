import { apiUrl, listQuery, request } from "@/lib/api-client"
import { observeNdjsonStream } from "@/lib/api/run-stream"

export type PublicAgentProfile = {
  id: string
  name: string
  description: string
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

export function createPublicAgentSession(agentId: string) {
  return request<void>(publicAgentPath(agentId, "/session"), {
    method: "POST",
  })
}

export function getPublicAgentProfile(agentId: string) {
  return request<PublicAgentProfile>(publicAgentPath(agentId, "/profile"))
}

export function listPublicAgentConversations(agentId: string) {
  return request<{ items: PublicAgentConversation[] }>(
    publicAgentPath(agentId, "/conversations")
  )
}

export async function initializePublicAgent(agentId: string) {
  await createPublicAgentSession(agentId)
  const [profile, conversations] = await Promise.all([
    getPublicAgentProfile(agentId),
    listPublicAgentConversations(agentId),
  ])
  return { profile, conversations }
}

export function listPublicAgentRuns(
  agentId: string,
  conversationId: string,
  options: { limit?: number; offset?: number } = {}
) {
  const params = new URLSearchParams(listQuery(options).slice(1))
  params.set("conversation_id", conversationId)
  return request<PublicAgentRunList>(
    publicAgentPath(agentId, `/runs?${params.toString()}`)
  )
}

export function createPublicAgentRun(
  agentId: string,
  goal: string,
  conversationId?: string | null,
  signal?: AbortSignal
) {
  return request<ExternalAgentRun>(publicAgentPath(agentId, "/runs"), {
    method: "POST",
    body: JSON.stringify({
      goal,
      ...(conversationId ? { conversation_id: conversationId } : {}),
    }),
    signal,
  })
}

export function getPublicAgentRun(agentId: string, runId: string) {
  return request<ExternalAgentRun>(publicAgentPath(agentId, `/runs/${runId}`))
}

export function observePublicAgentRun(
  agentId: string,
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
        { credentials: "include", signal: streamSignal }
      ),
    onEvent,
    { signal, after, liveAfter, errorLabel: "Public Agent stream" }
  )
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"])

export async function streamPublicAgentRun(
  agentId: string,
  goal: string,
  onEvent: (event: PublicAgentRunStreamEvent) => void,
  signal?: AbortSignal,
  conversationId?: string | null
) {
  const run = await createPublicAgentRun(agentId, goal, conversationId, signal)
  onEvent({ type: "run", sequence: 0, run })
  if (TERMINAL_STATUSES.has(run.status)) return
  await observePublicAgentRun(agentId, run.id, onEvent, signal)
}

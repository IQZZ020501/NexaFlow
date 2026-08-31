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
    | "preparing"
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
  created_at?: string | null
}

export type ExternalAgentRun = {
  id: string
  conversation_id: string
  regenerated_from_run_id?: string | null
  question: string
  status: string
  result: string
  error: string | null
  progress: ExternalAgentProgressEvent[]
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
  feedback?: "positive" | "negative" | null
  feedback_updated_at?: string | null
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
  | (PublicAgentStreamCursor & { type: "answer_reset" })
  | (PublicAgentStreamCursor & {
      type: "reasoning_delta"
      turn: number
      delta: string
    })
  | (PublicAgentStreamCursor & {
      type: "tool_input_delta"
      id: string
      turn: number
      tool_name: string
      field: string
      delta: string
      replace: boolean
      input_truncated?: boolean
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

/**
 * Builds the API path for a public agent resource.
 *
 * @param agentId - The public agent identifier
 * @param suffix - The optional resource path suffix
 * @returns The public agent API path
 */
function publicAgentPath(agentId: string, suffix = "") {
  return `/api/v1/public/agents/${agentId}${suffix}`
}

/**
 * Retrieves the public profile for an agent.
 *
 * @param agentId - The identifier of the agent
 * @param token - The authentication token
 * @returns The agent's public profile
 */
export function getPublicAgentProfile(agentId: string, token: string) {
  return request<PublicAgentProfile>(publicAgentPath(agentId, "/profile"), {
    token,
  })
}

/**
 * Lists the conversations available for a public agent.
 *
 * @param agentId - The public agent identifier
 * @param token - The authentication token
 * @returns The agent's conversations
 */
export function listPublicAgentConversations(agentId: string, token: string) {
  return request<{ items: PublicAgentConversation[] }>(
    publicAgentPath(agentId, "/conversations"),
    { token }
  )
}

/** Deletes one public Agent conversation and all of its runs. */
export function deletePublicAgentConversation(
  agentId: string,
  conversationId: string,
  token: string
) {
  return request<void>(
    publicAgentPath(agentId, `/conversations/${conversationId}`),
    { method: "DELETE", token }
  )
}

/**
 * Loads a public agent's profile and conversations.
 *
 * @param agentId - The public agent identifier
 * @param token - The authentication token
 * @returns The agent profile and its conversations
 */
export async function initializePublicAgent(agentId: string, token: string) {
  const [profile, conversations] = await Promise.all([
    getPublicAgentProfile(agentId, token),
    listPublicAgentConversations(agentId, token),
  ])
  return { profile, conversations }
}

/**
 * Lists runs for a public agent conversation.
 *
 * @param agentId - The public agent identifier
 * @param conversationId - The conversation identifier
 * @param token - The authentication token
 * @param options - Optional pagination settings
 * @returns The paginated list of runs
 */
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

/**
 * Starts a run for a public agent with the specified goal and optional conversation and file context.
 *
 * @param agentId - The public agent identifier
 * @param token - The authentication token
 * @param goal - The objective for the run
 * @param conversationId - The conversation to associate with the run
 * @param signal - The signal used to cancel the request
 * @param fileIds - The identifiers of files to include in the run
 * @returns The created agent run
 */
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

/**
 * Uploads files for a public agent.
 *
 * @param agentId - The public agent identifier
 * @param token - The authentication token
 * @param files - The files to upload
 * @returns The uploaded file records
 */
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

/**
 * Retrieves a public agent run.
 *
 * @returns The requested public agent run.
 */
export function getPublicAgentRun(
  agentId: string,
  token: string,
  runId: string
) {
  return request<ExternalAgentRun>(publicAgentPath(agentId, `/runs/${runId}`), {
    token,
  })
}

/** Cancels a running public agent run. */
export function cancelPublicAgentRun(
  agentId: string,
  token: string,
  runId: string
) {
  return request<ExternalAgentRun>(
    publicAgentPath(agentId, `/runs/${runId}/cancel`),
    { method: "POST", keepalive: true, token }
  )
}

/**
 * Regenerates a public agent run.
 *
 * @param agentId - The public agent identifier
 * @param token - The authentication token
 * @param runId - The run identifier
 * @returns The regenerated agent run
 */
export function regeneratePublicAgentRun(
  agentId: string,
  token: string,
  runId: string
) {
  return request<ExternalAgentRun>(
    publicAgentPath(agentId, `/runs/${runId}/regenerate`),
    { method: "POST", token }
  )
}

/**
 * Sets or clears feedback for a public agent run.
 *
 * @param agentId - The public agent identifier
 * @param token - The authentication token
 * @param runId - The run identifier
 * @param value - The feedback value, or `null` to clear existing feedback
 * @returns The updated agent run
 */
export function setPublicAgentRunFeedback(
  agentId: string,
  token: string,
  runId: string,
  value: "positive" | "negative" | null
) {
  return request<ExternalAgentRun>(
    publicAgentPath(agentId, `/runs/${runId}/feedback`),
    { method: "POST", token, body: JSON.stringify({ value }) }
  )
}

/**
 * Lists tool calls associated with a public agent run.
 *
 * @param agentId - The public agent identifier
 * @param token - The authentication token
 * @param runId - The run identifier
 * @returns The run's tool calls
 */
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

/**
 * Resolves a pending tool call for a public agent run.
 *
 * @param decision - Whether to approve or reject the tool call
 * @returns The updated agent run
 */
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

/**
 * Observes events emitted by a public agent run.
 *
 * @param onEvent - Callback invoked for each stream event
 * @param after - Event cursor from which to resume
 * @param liveAfter - Live stream cursor from which to resume
 * @returns A promise that settles when stream observation ends
 */
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

/**
 * Creates a public agent run and streams its progress events.
 *
 * @param goal - The objective for the agent run
 * @param onEvent - Callback invoked for each run stream event
 * @param conversationId - Optional conversation to associate with the run
 * @param fileIds - IDs of files to provide to the run
 */
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

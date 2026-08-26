import { apiUrl, listQuery, request } from "@/lib/api-client"
import { observeNdjsonStream } from "@/lib/api/run-stream"
import type { AgentInteractionConfig } from "@/lib/api/agents"
import type { WorkflowNodeType, WorkflowPendingForm } from "@/lib/api/workflows"

export type PublicWorkflowProfile = {
  id: string
  name: string
  description: string
  interaction_config: AgentInteractionConfig
}

export type WorkflowUpload = {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  category: "document" | "image" | "audio"
}

export type PublicWorkflowConversation = {
  conversation_id: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  status: string
  run_count: number
  created_at: string
  updated_at: string
}

export type ExternalWorkflowProgress = {
  id: string
  node_id: string
  node_type: WorkflowNodeType
  status: "running" | "awaiting_input" | "succeeded" | "failed" | "skipped"
  error: string | null
  duration_ms: number | null
}

export type ExternalWorkflowRun = {
  id: string
  conversation_id: string
  regenerated_from_run_id?: string | null
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  status: string
  error: string | null
  progress: ExternalWorkflowProgress[]
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
  pending_form: WorkflowPendingForm | null
  feedback?: "positive" | "negative" | null
  feedback_updated_at?: string | null
  live_stream_epoch?: string
  live_stream_cursor?: string
}

export type PublicWorkflowRunStreamEvent =
  | {
      type: "answer_delta"
      live_sequence?: string
      stream_epoch?: string
      node_id: string
      delta: string
    }
  | {
      type: "run" | "complete" | "error" | "workflow_input_required"
      sequence: number
      run: ExternalWorkflowRun
    }
  | { type: "progress"; sequence: number; event: ExternalWorkflowProgress }

export type WorkflowApiDocumentation = {
  workflow_id: string
  workflow_name: string
  base_path: string
  interaction_config: AgentInteractionConfig
}

const path = (workflowId: string, suffix = "") =>
  `/api/v1/public/workflows/${workflowId}${suffix}`

/**
 * Fetches the public profile for a workflow.
 *
 * @param workflowId - The workflow identifier
 * @param token - The access token for the workflow
 * @returns The workflow's public profile
 */
export function getPublicWorkflowProfile(workflowId: string, token: string) {
  return request<PublicWorkflowProfile>(path(workflowId, "/profile"), { token })
}

/**
 * Initializes a public workflow with its profile and conversations.
 *
 * @param workflowId - The identifier of the workflow to initialize
 * @param token - The access token for the workflow
 * @returns The workflow profile and its conversations
 */
export async function initializePublicWorkflow(
  workflowId: string,
  token: string
) {
  const [profile, conversations] = await Promise.all([
    getPublicWorkflowProfile(workflowId, token),
    listPublicWorkflowConversations(workflowId, token),
  ])
  return { profile, conversations }
}

/** Lists the conversations available for a public workflow. */
export function listPublicWorkflowConversations(
  workflowId: string,
  token: string
) {
  return request<{ items: PublicWorkflowConversation[] }>(
    path(workflowId, "/conversations"),
    { token }
  )
}

/** Deletes one public workflow conversation and all of its runs. */
export function deletePublicWorkflowConversation(
  workflowId: string,
  conversationId: string,
  token: string
) {
  return request<void>(path(workflowId, `/conversations/${conversationId}`), {
    method: "DELETE",
    token,
  })
}

/**
 * Lists runs for a public workflow conversation.
 *
 * @param workflowId - The workflow identifier
 * @param conversationId - The conversation whose runs to list
 * @param token - The authentication token
 * @returns The conversation's workflow runs
 */
export function listPublicWorkflowRuns(
  workflowId: string,
  conversationId: string,
  token: string,
  options: { limit?: number; offset?: number } = {}
) {
  const params = new URLSearchParams(
    listQuery({ limit: options.limit ?? 200, offset: options.offset }).slice(1)
  )
  params.set("conversation_id", conversationId)
  return request<{
    items: ExternalWorkflowRun[]
    total: number
    offset: number
    limit: number
  }>(
    path(workflowId, `/runs?${params.toString()}`),
    { token }
  )
}

/**
 * Creates a run for a public workflow.
 *
 * @param workflowId - The workflow identifier
 * @param token - The authentication token
 * @param question - The question submitted to the workflow
 * @param conversationId - The conversation to continue, if applicable
 * @param fileIds - The identifiers of files attached to the run
 * @returns The created workflow run
 */
export function createPublicWorkflowRun(
  workflowId: string,
  token: string,
  question: string,
  conversationId?: string | null,
  fileIds: string[] = []
) {
  return request<ExternalWorkflowRun>(path(workflowId, "/runs"), {
    method: "POST",
    token,
    body: JSON.stringify({
      question,
      ...(fileIds.length ? { file_ids: fileIds } : {}),
      ...(conversationId ? { conversation_id: conversationId } : {}),
    }),
  })
}

/**
 * Uploads files for a public workflow.
 *
 * @param workflowId - The workflow identifier
 * @param token - The access token for the workflow
 * @param files - The files to upload
 * @returns The uploaded file records
 */
export function uploadPublicWorkflowFiles(
  workflowId: string,
  token: string,
  files: File[]
) {
  const body = new FormData()
  files.forEach((file) => body.append("files", file))
  return request<WorkflowUpload[]>(path(workflowId, "/uploads"), {
    method: "POST",
    token,
    body,
  })
}

/**
 * Submits form data for a runtime node in a workflow run.
 *
 * @param workflowId - The workflow containing the run
 * @param runId - The run receiving the form submission
 * @param runtimeNodeId - The runtime node associated with the form
 * @param formData - The values submitted for the form
 * @returns The updated workflow run
 */
export function submitPublicWorkflowForm(
  workflowId: string,
  token: string,
  runId: string,
  runtimeNodeId: string,
  formData: Record<string, unknown>
) {
  return request<ExternalWorkflowRun>(path(workflowId, `/runs/${runId}/form`), {
    method: "POST",
    token,
    body: JSON.stringify({
      runtime_node_id: runtimeNodeId,
      form_data: formData,
    }),
  })
}

/**
 * Requests regeneration of an existing public workflow run.
 *
 * @param workflowId - The workflow identifier
 * @param token - The authentication token
 * @param runId - The run identifier
 * @returns The regenerated workflow run
 */
export function regeneratePublicWorkflowRun(
  workflowId: string,
  token: string,
  runId: string
) {
  return request<ExternalWorkflowRun>(
    path(workflowId, `/runs/${runId}/regenerate`),
    { method: "POST", token }
  )
}

/**
 * Sets or clears feedback for a public workflow run.
 *
 * @param value - The feedback value, or `null` to clear existing feedback.
 * @returns The updated workflow run.
 */
export function setPublicWorkflowRunFeedback(
  workflowId: string,
  token: string,
  runId: string,
  value: "positive" | "negative" | null
) {
  return request<ExternalWorkflowRun>(
    path(workflowId, `/runs/${runId}/feedback`),
    { method: "POST", token, body: JSON.stringify({ value }) }
  )
}

/**
 * Observes events emitted for a public workflow run.
 *
 * @param workflowId - The workflow identifier.
 * @param token - The bearer token used to authenticate the request.
 * @param runId - The run identifier.
 * @param onEvent - Callback invoked for each received stream event.
 * @param signal - Optional signal used to abort observation.
 * @returns Completion of the run event stream.
 */
export function observePublicWorkflowRun(
  workflowId: string,
  token: string,
  runId: string,
  onEvent: (event: PublicWorkflowRunStreamEvent) => void,
  signal?: AbortSignal
) {
  return observeNdjsonStream<PublicWorkflowRunStreamEvent>(
    (cursor, liveCursor, streamSignal) =>
      fetch(
        apiUrl(
          path(
            workflowId,
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
    { signal, errorLabel: "Public Workflow stream" }
  )
}

/**
 * Fetches API documentation for a workflow.
 *
 * @param workflowId - The identifier of the workflow
 * @param apiKey - The API key used to authenticate the request
 * @returns The workflow's API documentation
 */
export function getWorkflowApiDocumentation(
  workflowId: string,
  apiKey: string
) {
  return request<WorkflowApiDocumentation>(
    `/api/v1/workflow-api/${workflowId}/documentation`,
    { token: apiKey }
  )
}

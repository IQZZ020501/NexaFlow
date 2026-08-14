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
}

export type PublicWorkflowRunStreamEvent =
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

export function getPublicWorkflowProfile(workflowId: string, token: string) {
  return request<PublicWorkflowProfile>(path(workflowId, "/profile"), { token })
}

export async function initializePublicWorkflow(
  workflowId: string,
  token: string
) {
  const [profile, conversations] = await Promise.all([
    getPublicWorkflowProfile(workflowId, token),
    request<{ items: PublicWorkflowConversation[] }>(
      path(workflowId, "/conversations"),
      { token }
    ),
  ])
  return { profile, conversations }
}

export function listPublicWorkflowRuns(
  workflowId: string,
  conversationId: string,
  token: string
) {
  const params = new URLSearchParams(listQuery({ limit: 200 }).slice(1))
  params.set("conversation_id", conversationId)
  return request<{ items: ExternalWorkflowRun[] }>(
    path(workflowId, `/runs?${params.toString()}`),
    { token }
  )
}

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

export function observePublicWorkflowRun(
  workflowId: string,
  token: string,
  runId: string,
  onEvent: (event: PublicWorkflowRunStreamEvent) => void,
  signal?: AbortSignal
) {
  return observeNdjsonStream<PublicWorkflowRunStreamEvent>(
    (cursor, _liveCursor, streamSignal) =>
      fetch(apiUrl(path(workflowId, `/runs/${runId}/stream?after=${cursor}`)), {
        credentials: "include",
        headers: { Authorization: `Bearer ${token}` },
        signal: streamSignal,
      }),
    onEvent,
    { signal, errorLabel: "Public Workflow stream" }
  )
}

export function getWorkflowApiDocumentation(
  workflowId: string,
  apiKey: string
) {
  return request<WorkflowApiDocumentation>(
    `/api/v1/workflow-api/${workflowId}/documentation`,
    { token: apiKey }
  )
}

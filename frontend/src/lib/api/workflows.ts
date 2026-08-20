import { apiUrl, listQuery, request } from "@/lib/api-client"
import { observeNdjsonStream } from "@/lib/api/run-stream"
import type { Agent } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import type { ToolDetail } from "@/lib/api/tools"

export type WorkflowNodeType =
  | "start"
  | "end"
  | "llm"
  | "classifier"
  | "knowledge"
  | "reranker-node"
  | "form-node"
  | "document-extract-node"
  | "condition"
  | "reply-node"
  | "template"
  | "variable"
  | "tool"
  | "agent"
  | "mcp"
  | "code"

export type WorkflowNodeData = Record<string, unknown> & {
  type: WorkflowNodeType
  title: string
  config: Record<string, unknown>
  runtimeStatus?: WorkflowNodeExecution["status"]
  readOnly?: boolean
  onCopy?: (nodeId: string) => void
  onDelete?: (nodeId: string) => void
  onRename?: (nodeId: string, title: string) => void
  onUpdate?: (data: WorkflowNodeData) => void
  agent?: Agent
  models?: RegisteredModel[]
  knowledgeBases?: KnowledgeBase[]
  mcpServers?: McpServer[]
  tools?: ToolDetail[]
  agents?: Agent[]
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
}

export type WorkflowNode = {
  id: string
  type: "workflow"
  position: { x: number; y: number }
  data: WorkflowNodeData
}

export type WorkflowEdge = {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
}

export type WorkflowGraph = {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  viewport: { x: number; y: number; zoom: number }
}

export type WorkflowDefinition = {
  id: string
  workspace_id: string
  agent_id: string
  revision: number
  graph: WorkflowGraph
  graph_hash: string
  updated_by_user_id: string
  created_at: string
  updated_at: string
}

export type WorkflowVersion = {
  id: string
  workspace_id: string
  agent_id: string
  definition_id: string
  definition_revision: number
  version_number: number
  default_model_id: string
  graph: WorkflowGraph
  graph_hash: string
  published_by_user_id: string
  created_at: string
}

export type WorkflowRunStatus =
  | "queued"
  | "running"
  | "awaiting_input"
  | "awaiting_child"
  | "succeeded"
  | "failed"
  | "cancelled"

export type WorkflowUpload = {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  category: "document" | "image" | "audio"
}

export type WorkflowFormField = {
  variable: string
  name: string
  type: "input" | "textarea" | "select" | "date" | "number"
  is_required: boolean
  default_value: unknown
  show_default_value: boolean
  optionList: string[]
}

export type WorkflowPendingForm = {
  runtime_node_id: string
  content: string
  fields: WorkflowFormField[]
}

export type WorkflowRun = {
  id: string
  conversation_id: string
  regenerated_from_run_id?: string | null
  workspace_id: string
  agent_id: string
  requested_by_user_id: string | null
  status: WorkflowRunStatus
  source: "draft" | "published"
  definition_revision: number
  version_number: number | null
  graph_hash: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  max_steps: number
  max_model_tokens: number
  step_count: number
  token_usage: number
  last_error: string | null
  trace_id: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  pending_form: WorkflowPendingForm | null
  feedback?: "positive" | "negative" | null
  feedback_updated_at?: string | null
  live_stream_epoch?: string
  live_stream_cursor?: string
}

export type WorkflowNodeExecution = {
  id: string
  run_id: string
  node_id: string
  node_type: WorkflowNodeType
  status:
    | "running"
    | "awaiting_input"
    | "awaiting_child"
    | "succeeded"
    | "failed"
    | "skipped"
  sequence: number
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  model_usage: Record<string, unknown>
  error: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
}

export type WorkflowRunStreamEvent =
  | { type: "run"; sequence: number; run: WorkflowRun }
  | {
      type: "answer_delta"
      live_sequence?: string
      stream_epoch?: string
      node_id: string
      delta: string
    }
  | {
      type: "workflow_node_started"
      sequence: number
      node_id: string
      node_type: WorkflowNodeType
      execution_sequence: number
    }
  | {
      type: "workflow_node"
      sequence: number
      node_id: string
      node_type: WorkflowNodeType
      status: WorkflowNodeExecution["status"]
      execution_sequence: number
      inputs: Record<string, unknown>
      outputs: Record<string, unknown>
      model_usage: Record<string, unknown>
      error: string | null
      duration_ms: number
    }
  | {
      type: "complete" | "error" | "workflow_input_required"
      sequence: number
      run: WorkflowRun
    }

/**
 * Builds the API path for a workspace's workflows.
 *
 * @param workspaceId - The workspace identifier.
 * @param suffix - An optional path suffix.
 * @returns The workspace-scoped workflows API path.
 */
function workflowPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/workflows${suffix}`
}

/**
 * Retrieves the definition of a workflow.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Identifier of the workspace containing the workflow
 * @param workflowId - Identifier of the workflow
 * @returns The workflow definition
 */
export function getWorkflowDefinition(
  token: string,
  workspaceId: string,
  workflowId: string
) {
  return request<WorkflowDefinition>(
    workflowPath(workspaceId, `/${workflowId}/definition`),
    { token }
  )
}

/**
 * Updates a workflow definition with the supplied graph.
 *
 * @param expectedRevision - The revision that must match the current workflow definition.
 * @param graph - The workflow graph to save.
 * @returns The updated workflow definition.
 */
export function updateWorkflowDefinition(
  token: string,
  workspaceId: string,
  workflowId: string,
  expectedRevision: number,
  graph: WorkflowGraph
) {
  return request<WorkflowDefinition>(
    workflowPath(workspaceId, `/${workflowId}/definition`),
    {
      method: "PUT",
      token,
      body: JSON.stringify({ expected_revision: expectedRevision, graph }),
    }
  )
}

/**
 * Validates a workflow graph and computes its content hash.
 *
 * @param graph - The workflow graph to validate
 * @returns An object confirming validity and containing the graph hash
 */
export function validateWorkflowDefinition(
  token: string,
  workspaceId: string,
  workflowId: string,
  graph: WorkflowGraph
) {
  return request<{ valid: true; graph_hash: string }>(
    workflowPath(workspaceId, `/${workflowId}/validate`),
    { method: "POST", token, body: JSON.stringify({ graph }) }
  )
}

/**
 * Publishes the current workflow definition.
 *
 * @returns The published workflow version.
 */
export function publishWorkflow(
  token: string,
  workspaceId: string,
  workflowId: string
) {
  return request<WorkflowVersion>(
    workflowPath(workspaceId, `/${workflowId}/publish`),
    { method: "POST", token }
  )
}

/**
 * Lists the published versions of a workflow.
 *
 * @param token - Authentication token
 * @param workspaceId - Workspace containing the workflow
 * @param workflowId - Workflow whose versions are requested
 * @returns An object containing the workflow versions
 */
export function listWorkflowVersions(
  token: string,
  workspaceId: string,
  workflowId: string
) {
  return request<{ items: WorkflowVersion[] }>(
    workflowPath(workspaceId, `/${workflowId}/versions`),
    { token }
  )
}

/**
 * Restores a published workflow version as the current definition.
 *
 * @param versionNumber - The published version to restore
 * @param expectedRevision - The current revision expected by the restore operation
 * @returns The restored workflow definition
 */
export function restoreWorkflowVersion(
  token: string,
  workspaceId: string,
  workflowId: string,
  versionNumber: number,
  expectedRevision: number
) {
  return request<WorkflowDefinition>(
    workflowPath(
      workspaceId,
      `/${workflowId}/versions/${versionNumber}/restore`
    ),
    {
      method: "POST",
      token,
      body: JSON.stringify({ expected_revision: expectedRevision }),
    }
  )
}

/**
 * Starts a workflow run using a draft or published workflow.
 *
 * @param question - The question or input to process
 * @param source - Whether to run the draft or published workflow
 * @param versionNumber - The published workflow version to run
 * @param fileIds - IDs of files to include in the run
 * @returns The created workflow run
 */
export function createWorkflowRun(
  token: string,
  workspaceId: string,
  workflowId: string,
  question: string,
  source: "draft" | "published" = "draft",
  versionNumber?: number,
  fileIds: string[] = []
) {
  return request<WorkflowRun>(
    workflowPath(workspaceId, `/${workflowId}/runs`),
    {
      method: "POST",
      token,
      body: JSON.stringify({
        question,
        source,
        ...(versionNumber ? { version_number: versionNumber } : {}),
        ...(fileIds.length ? { file_ids: fileIds } : {}),
      }),
    }
  )
}

/**
 * Uploads files for a workflow.
 *
 * @param files - The files to upload.
 * @returns The uploaded file metadata.
 */
export function uploadWorkflowFiles(
  token: string,
  workspaceId: string,
  workflowId: string,
  files: File[]
) {
  const body = new FormData()
  files.forEach((file) => body.append("files", file))
  return request<WorkflowUpload[]>(
    workflowPath(workspaceId, `/${workflowId}/uploads`),
    {
      method: "POST",
      token,
      body,
    }
  )
}

/**
 * Submits data for a pending workflow runtime form.
 *
 * @param runtimeNodeId - The identifier of the runtime node whose form is being submitted
 * @param formData - The form values to submit
 * @returns The updated workflow run
 */
export function submitWorkflowForm(
  token: string,
  workspaceId: string,
  workflowId: string,
  runId: string,
  runtimeNodeId: string,
  formData: Record<string, unknown>
) {
  return request<WorkflowRun>(
    workflowPath(workspaceId, `/${workflowId}/runs/${runId}/form`),
    {
      method: "POST",
      token,
      body: JSON.stringify({
        runtime_node_id: runtimeNodeId,
        form_data: formData,
      }),
    }
  )
}

/**
 * Regenerates an existing workflow run.
 *
 * @param token - Authentication token
 * @param workspaceId - Workspace containing the workflow
 * @param workflowId - Workflow whose run should be regenerated
 * @param runId - Run to regenerate
 * @returns The regenerated workflow run
 */
export function regenerateWorkflowRun(
  token: string,
  workspaceId: string,
  workflowId: string,
  runId: string
) {
  return request<WorkflowRun>(
    workflowPath(workspaceId, `/${workflowId}/runs/${runId}/regenerate`),
    { method: "POST", token }
  )
}

/**
 * Sets or clears feedback for a workflow run.
 *
 * @param value - The feedback value, or `null` to clear existing feedback
 * @returns The updated workflow run
 */
export function setWorkflowRunFeedback(
  token: string,
  workspaceId: string,
  workflowId: string,
  runId: string,
  value: "positive" | "negative" | null
) {
  return request<WorkflowRun>(
    workflowPath(workspaceId, `/${workflowId}/runs/${runId}/feedback`),
    { method: "POST", token, body: JSON.stringify({ value }) }
  )
}

/**
 * Lists runs for a workflow.
 *
 * @param options - Optional pagination settings for limiting and offsetting the results.
 * @returns The workflow runs matching the requested pagination settings.
 */
export function listWorkflowRuns(
  token: string,
  workspaceId: string,
  workflowId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<WorkflowRun[]>(
    workflowPath(workspaceId, `/${workflowId}/runs${listQuery(options)}`),
    { token }
  )
}

/**
 * Retrieves the node executions for a workflow run.
 *
 * @param workspaceId - The workspace containing the workflow
 * @param workflowId - The workflow whose run is being queried
 * @param runId - The run whose node executions are retrieved
 * @returns An object containing the workflow node executions
 */
export function listWorkflowNodeExecutions(
  token: string,
  workspaceId: string,
  workflowId: string,
  runId: string
) {
  return request<{ items: WorkflowNodeExecution[] }>(
    workflowPath(workspaceId, `/${workflowId}/runs/${runId}/nodes`),
    { token }
  )
}

/**
 * Observes workflow run events from the authenticated event stream.
 *
 * @param onEvent - Callback invoked for each received workflow event
 * @param after - Event cursor from which to resume observation
 * @returns Completion of stream observation
 */
export function observeWorkflowRun(
  token: string,
  workspaceId: string,
  workflowId: string,
  runId: string,
  onEvent: (event: WorkflowRunStreamEvent) => void,
  signal?: AbortSignal,
  after = 0
) {
  return observeNdjsonStream<WorkflowRunStreamEvent>(
    (cursor, liveCursor, streamSignal) =>
      fetch(
        apiUrl(
          workflowPath(
            workspaceId,
            `/${workflowId}/runs/${runId}/stream?after=${cursor}&live_after=${encodeURIComponent(liveCursor)}`
          )
        ),
        {
          headers: { Authorization: `Bearer ${token}` },
          credentials: "include",
          signal: streamSignal,
        }
      ),
    onEvent,
    { signal, after, errorLabel: "Workflow stream" }
  )
}

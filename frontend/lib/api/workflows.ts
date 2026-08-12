import { apiUrl, listQuery, request } from "@/lib/api-client"
import { observeNdjsonStream } from "@/lib/api/run-stream"

export type WorkflowNodeType =
  | "start"
  | "end"
  | "llm"
  | "classifier"
  | "knowledge"
  | "condition"
  | "template"
  | "variable"
  | "mcp"
  | "code"

export type WorkflowNodeData = Record<string, unknown> & {
  type: WorkflowNodeType
  title: string
  config: Record<string, unknown>
  runtimeStatus?: WorkflowNodeExecution["status"]
  readOnly?: boolean
  onAddConnectedNode?: (
    sourceId: string,
    sourceHandle: string | null | undefined,
    type: WorkflowNodeType
  ) => void
  onCopy?: (nodeId: string) => void
  onDelete?: (nodeId: string) => void
  onRename?: (nodeId: string, title: string) => void
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
  | "succeeded"
  | "failed"
  | "cancelled"

export type WorkflowRun = {
  id: string
  conversation_id: string
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
}

export type WorkflowNodeExecution = {
  id: string
  run_id: string
  node_id: string
  node_type: WorkflowNodeType
  status: "running" | "succeeded" | "failed" | "skipped"
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
  | { type: "complete" | "error"; sequence: number; run: WorkflowRun }

function workflowPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/workflows${suffix}`
}

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

export function restoreWorkflowVersion(
  token: string,
  workspaceId: string,
  workflowId: string,
  versionNumber: number
) {
  return request<WorkflowDefinition>(
    workflowPath(
      workspaceId,
      `/${workflowId}/versions/${versionNumber}/restore`
    ),
    { method: "POST", token }
  )
}

export function createWorkflowRun(
  token: string,
  workspaceId: string,
  workflowId: string,
  inputs: Record<string, unknown>,
  source: "draft" | "published" = "draft",
  versionNumber?: number
) {
  return request<WorkflowRun>(
    workflowPath(workspaceId, `/${workflowId}/runs`),
    {
      method: "POST",
      token,
      body: JSON.stringify({
        inputs,
        source,
        ...(versionNumber ? { version_number: versionNumber } : {}),
      }),
    }
  )
}

export function listWorkflowRuns(
  token: string,
  workspaceId: string,
  workflowId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<WorkflowRun[]>(
    workflowPath(
      workspaceId,
      `/${workflowId}/runs${listQuery(options)}`
    ),
    { token }
  )
}

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
    (cursor, _liveCursor, streamSignal) =>
      fetch(
        apiUrl(
          workflowPath(
            workspaceId,
            `/${workflowId}/runs/${runId}/stream?after=${cursor}`
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

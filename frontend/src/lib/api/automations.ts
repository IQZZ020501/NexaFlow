import { request, requestPage } from "@/lib/api-client"
import type { AgentRun, AgentToolCall } from "@/lib/api/agents"
import type { WorkflowRun } from "@/lib/api/workflows"

export type WorkflowFormSubmitInput = {
  runtime_node_id: string
  data: Record<string, unknown>
}

export type AutomationTargetAppType = "agent" | "workflow"
export type AutomationTriggerType = "once" | "daily" | "weekly" | "webhook"
export type AutomationStatus = "active" | "paused" | "completed"
export type AutomationInputMode = "text" | "json"
export type AutomationApprovalMode = "always_ask" | "ask_risky" | "full_access"
export type AutomationDispatchStatus =
  "queued" | "pending_dispatch" | "dispatched" | "skipped" | "rejected"

export type AutomationTriggerConfig = {
  run_at?: string
  hour?: number
  minute?: number
  weekdays?: number[]
  max_pending?: number
  timezone?: string
}

export type AutomationInputConfig = {
  mode: AutomationInputMode
  text: string
  json_payload: Record<string, unknown>
  webhook_input_path: string | null
  webhook_prompt_template: string | null
}

export type AutomationNotificationPreferences = {
  on_succeeded: boolean
  on_failed: boolean
  on_cancelled: boolean
  on_awaiting_approval: boolean
  on_awaiting_input: boolean
}

export type AutomationExecutionSummary = {
  id: string
  automation_id: string
  workspace_id: string
  trigger_source: "schedule" | "webhook" | "manual"
  dedup_key: string
  config_revision: number
  scheduled_at: string | null
  received_at: string
  dispatched_at: string | null
  dispatch_status: AutomationDispatchStatus
  skip_reason: string | null
  run_id: string | null
  run_status: string | null
  missed_count_before: number
  created_at: string
  updated_at: string
}

export type AutomationArtifactLink = {
  artifact_id: string
  format: string
  filename: string
  media_type: string
  download_url: string
  expires_at: string
  size_bytes: number
  relative_path: string | null
}

export type AutomationExecutionDetail = AutomationExecutionSummary & {
  frozen_input: Record<string, unknown>
  frozen_config: Record<string, unknown>
  agent_run: AgentRun | null
  workflow_run: WorkflowRun | null
  tool_calls: AgentToolCall[]
  artifacts: AutomationArtifactLink[]
}

export type Automation = {
  id: string
  workspace_id: string
  owner_user_id: string
  name: string
  description: string
  target_app_id: string
  target_app_name: string
  target_app_type: AutomationTargetAppType
  publication_version_id: string | null
  workflow_version_id: string | null
  target_version_number: number
  approval_mode: AutomationApprovalMode
  trigger_type: AutomationTriggerType
  trigger_config: AutomationTriggerConfig
  input_config: AutomationInputConfig
  notification_config: AutomationNotificationPreferences
  webhook_hook_id: string | null
  webhook_url: string | null
  webhook_secret_hint: string | null
  webhook_secret_updated_at: string | null
  status: AutomationStatus
  config_revision: number
  next_run_at: string | null
  last_triggered_at: string | null
  missed_run_count: number
  latest_execution: AutomationExecutionSummary | null
  created_at: string
  updated_at: string
}

export type AutomationCreateResponse = Automation & {
  webhook_secret: string | null
}

export type AutomationCreateInput = {
  name: string
  description?: string
  target_app_id: string
  publication_version_id?: string | null
  workflow_version_id?: string | null
  approval_mode?: AutomationApprovalMode
  trigger_type: AutomationTriggerType
  trigger_config: AutomationTriggerConfig
  input_config: {
    mode: AutomationInputMode
    text?: string
    json_payload?: Record<string, unknown>
    webhook_input_path?: string | null
    webhook_prompt_template?: string | null
  }
  notification_config?: Partial<AutomationNotificationPreferences>
}

export type AutomationUpdateInput = Partial<
  Omit<AutomationCreateInput, "target_app_id">
>

export type AutomationWebhookSecretRotateResponse = {
  automation_id: string
  webhook_hook_id: string
  webhook_url: string
  webhook_secret: string
  webhook_secret_hint: string
  webhook_secret_updated_at: string
}

export type AgentPublicationVersionItem = {
  id: string
  agent_id: string
  version_number: number
  published_by_user_id: string
  created_at: string
}

export function listAutomations(
  token: string,
  workspaceId: string,
  options: { target_app_id?: string; limit?: number; offset?: number } = {}
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  })
  if (options.target_app_id) {
    params.set("target_app_id", options.target_app_id)
  }
  return request<{
    items: Automation[]
    total: number
    limit: number
    offset: number
  }>(`/api/v1/workspaces/${workspaceId}/automations?${params.toString()}`, {
    token,
  })
}

export function createAutomation(
  token: string,
  workspaceId: string,
  input: AutomationCreateInput
) {
  return request<AutomationCreateResponse>(
    `/api/v1/workspaces/${workspaceId}/automations`,
    {
      method: "POST",
      token,
      body: JSON.stringify(input),
    }
  )
}

export function getAutomation(
  token: string,
  workspaceId: string,
  automationId: string
) {
  return request<Automation>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}`,
    { token }
  )
}

export function updateAutomation(
  token: string,
  workspaceId: string,
  automationId: string,
  input: AutomationUpdateInput
) {
  return request<Automation>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(input),
    }
  )
}

export function pauseAutomation(
  token: string,
  workspaceId: string,
  automationId: string
) {
  return request<Automation>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/pause`,
    { method: "POST", token }
  )
}

export function resumeAutomation(
  token: string,
  workspaceId: string,
  automationId: string
) {
  return request<Automation>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/resume`,
    { method: "POST", token }
  )
}

export function rotateAutomationWebhookSecret(
  token: string,
  workspaceId: string,
  automationId: string
) {
  return request<AutomationWebhookSecretRotateResponse>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/webhook-secret/rotate`,
    { method: "POST", token }
  )
}

export function executeAutomationNow(
  token: string,
  workspaceId: string,
  automationId: string,
  requestId?: string
) {
  return request<AutomationExecutionDetail>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/execute`,
    {
      method: "POST",
      token,
      body: JSON.stringify(requestId ? { request_id: requestId } : {}),
    }
  )
}

export function listAutomationExecutions(
  token: string,
  workspaceId: string,
  automationId: string,
  options: { limit?: number; offset?: number } = {}
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  })
  return request<{
    items: AutomationExecutionSummary[]
    total: number
    limit: number
    offset: number
  }>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/executions?${params.toString()}`,
    { token }
  )
}

export function getAutomationExecution(
  token: string,
  workspaceId: string,
  automationId: string,
  executionId: string
) {
  return request<AutomationExecutionDetail>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/executions/${executionId}`,
    { token }
  )
}

export function cancelAutomationExecution(
  token: string,
  workspaceId: string,
  automationId: string,
  executionId: string
) {
  return request<AutomationExecutionDetail>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/executions/${executionId}/cancel`,
    { method: "POST", token }
  )
}

export function approveAutomationToolCall(
  token: string,
  workspaceId: string,
  automationId: string,
  executionId: string,
  callId: string,
  approve: boolean
) {
  return request<AutomationExecutionDetail>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/executions/${executionId}/tool-calls/${encodeURIComponent(callId)}/approval`,
    {
      method: "POST",
      token,
      body: JSON.stringify({ approve }),
    }
  )
}

export function submitAutomationWorkflowForm(
  token: string,
  workspaceId: string,
  automationId: string,
  executionId: string,
  input: WorkflowFormSubmitInput
) {
  return request<AutomationExecutionDetail>(
    `/api/v1/workspaces/${workspaceId}/automations/${automationId}/executions/${executionId}/form`,
    {
      method: "POST",
      token,
      body: JSON.stringify({
        runtime_node_id: input.runtime_node_id,
        form_data: input.data,
      }),
    }
  )
}

export function listAgentPublicationVersions(
  token: string,
  workspaceId: string,
  agentId: string
) {
  return request<{ items: AgentPublicationVersionItem[] }>(
    `/api/v1/workspaces/${workspaceId}/agents/${agentId}/versions`,
    { token }
  )
}

export { requestPage }

export function automationWebhookUrl(path: string | null) {
  if (!path) return ""
  if (typeof window === "undefined" || !/^https?:$/.test(window.location.protocol)) return path
  return new URL(path, window.location.origin).href
}

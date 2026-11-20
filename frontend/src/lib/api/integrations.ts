import { request } from "@/lib/api-client"

export type IntegrationProvider = "dida" | "feishu" | "tencent_meeting"
export type Integration = {
  provider: IntegrationProvider
  status: "disconnected" | "connected" | "reauthorization_required"
  configured: boolean
  expires_at: string | null
  source_id: string | null
}
export type IntegrationApplication = {
  client_id: string
  has_client_secret: boolean
  scopes: string[]
  redirect_uri: string
}
export type IntegrationAuthorization = {
  authorization_url: string
  state: string
  mode: "redirect" | "device"
  poll_seconds: number
}

function path(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/integrations${suffix}`
}

export function listIntegrations(token: string, workspaceId: string) {
  return request<Integration[]>(path(workspaceId), { token })
}

export function getIntegrationApplication(
  token: string,
  workspaceId: string,
  provider: IntegrationProvider
) {
  return request<IntegrationApplication>(
    path(workspaceId, `/${provider}/application`),
    { token }
  )
}

export function configureIntegrationApplication(
  token: string,
  workspaceId: string,
  provider: IntegrationProvider,
  payload: { client_id: string; client_secret?: string; scopes: string[] }
) {
  return request<IntegrationApplication>(
    path(workspaceId, `/${provider}/application`),
    { token, method: "PUT", body: JSON.stringify(payload) }
  )
}

export function authorizeIntegration(
  token: string,
  workspaceId: string,
  provider: IntegrationProvider
) {
  return request<IntegrationAuthorization>(
    path(workspaceId, `/${provider}/authorize`),
    { token, method: "POST" }
  )
}

export function completeIntegrationAuthorization(
  token: string,
  workspaceId: string,
  provider: IntegrationProvider,
  payload: { state: string; code?: string }
) {
  return request<Integration>(path(workspaceId, `/${provider}/callback`), {
    token,
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function uninstallIntegration(
  token: string,
  workspaceId: string,
  provider: IntegrationProvider
) {
  return request<Integration>(path(workspaceId, `/${provider}`), {
    token,
    method: "DELETE",
  })
}

export function syncIntegrationTools(
  token: string,
  workspaceId: string,
  provider: IntegrationProvider
) {
  return request<Integration>(path(workspaceId, `/${provider}/sync`), {
    token,
    method: "POST",
  })
}

import { request } from "@/lib/api-client"

export type EnterpriseProvider = "feishu" | "dingtalk" | "wecom"

export type PublicEnterpriseConnection = {
  id: string
  provider: EnterpriseProvider
  name: string
  start_url: string
}

export type PublicEnterpriseConnections = {
  workspace_id: string | null
  workspace_name: string | null
  connections: PublicEnterpriseConnection[]
}

export type EnterpriseConnection = {
  id: string
  workspace_id: string
  provider: EnterpriseProvider
  name: string
  client_id: string
  tenant_id: string
  agent_id: string | null
  enabled: boolean
  has_client_secret: boolean
  client_secret_hint: string | null
  callback_url: string
  login_url: string
  updated_at: string
}

export type EnterpriseIdentity = {
  id: string
  connection_id: string
  provider: EnterpriseProvider
  user_id: string | null
  username: string | null
  user_name: string | null
  subject_id: string
  display_name: string
  email: string | null
  status: string
  last_login_at: string | null
  created_at: string
}

export function listPublicEnterpriseConnections(workspaceId?: string) {
  const query = workspaceId
    ? `?workspace_id=${encodeURIComponent(workspaceId)}`
    : ""
  return request<PublicEnterpriseConnections>(
    `/api/v1/auth/enterprise/connections${query}`
  )
}

export function listEnterpriseConnections(token: string, workspaceId: string) {
  return request<EnterpriseConnection[]>(
    `/api/v1/admin/enterprise-identity/workspaces/${workspaceId}/connections`,
    { token }
  )
}

export function saveEnterpriseConnection(
  token: string,
  workspaceId: string,
  provider: EnterpriseProvider,
  payload: {
    name: string
    client_id?: string
    client_secret?: string
    tenant_id: string
    agent_id?: string
    enabled: boolean
  }
) {
  return request<EnterpriseConnection>(
    `/api/v1/admin/enterprise-identity/workspaces/${workspaceId}/connections/${provider}`,
    { method: "PUT", token, body: JSON.stringify(payload) }
  )
}

export function listEnterpriseIdentities(token: string, workspaceId: string) {
  return request<EnterpriseIdentity[]>(
    `/api/v1/admin/enterprise-identity/workspaces/${workspaceId}/identities`,
    { token }
  )
}

export function bindEnterpriseIdentity(
  token: string,
  workspaceId: string,
  identityId: string,
  userId: string | null
) {
  return request<EnterpriseIdentity>(
    `/api/v1/admin/enterprise-identity/workspaces/${workspaceId}/identities/${identityId}/binding`,
    { method: "PUT", token, body: JSON.stringify({ user_id: userId }) }
  )
}

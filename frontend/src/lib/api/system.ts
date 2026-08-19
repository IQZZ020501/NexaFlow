import { request } from "@/lib/api-client"
import type {
  User,
  UserPasswordResetResponse,
} from "@/lib/api/auth"

export type { MeResponse, User, UserPasswordResetResponse } from "@/lib/api/auth"

export type Workspace = {
  id: string
  name: string
  description: string
  status: string
  is_default: boolean
}

export type Team = {
  id: string
  workspace_id: string
  name: string
  description: string
  status: string
  is_default: boolean
}

export type WorkspaceCreateResponse = {
  workspace: Workspace
  admin_user: User
}

export type WorkspaceMember = {
  user: User
  role: string
}

export type TeamMember = {
  user: User
  role: string
}

export type AuditLog = {
  id: string
  actor_user_id: string
  actor_username: string
  actor_name: string
  workspace_id: string | null
  action: string
  resource_type: string
  resource_id: string
  resource_name: string
  details: Record<string, unknown>
  created_at: string
}

export type SystemLog = {
  id: string
  level: string
  event: string
  message: string
  path: string | null
  method: string | null
  status_code: number | null
  user_id: string | null
  username: string | null
  ip_address: string | null
  details: Record<string, unknown>
  stack_trace: string | null
  created_at: string
}

export type AdminHealth = {
  status: string
  components: Record<string, { status: string; detail?: string | null }>
  pending_tasks: number
  failed_logs_24h: number
  checked_at: string
}

export type WorkspaceInventory = {
  workspace_id: string
  members_total: number
  members_active: number
  teams_total: number
  teams_active: number
  agents_total: number
  knowledge_bases_total: number
  models_total: number
  tools_total: number
  workflows_total: number
  active_runs: number
  failed_runs_24h: number
  failed_tasks_24h: number
  updated_at: string
}

export type WorkspaceGovernance = {
  workspace_id: string
  daily_run_limit: number | null
  monthly_token_limit: number | null
  alert_threshold_percent: number
  retention_days: number | null
  timezone: string
  updated_at: string
}

export type WorkspaceInvitation = {
  id: string
  workspace_id: string
  username: string
  email: string
  name: string
  role: string
  expires_at: string
  accepted_at: string | null
  created_at: string
  token?: string | null
  invite_url?: string | null
}

export type RefreshSession = {
  id: string
  created_at: string
  last_used_at: string
  expires_at: string
  user_agent: string | null
  ip_address: string | null
  is_current: boolean
}

export type AuditFilters = {
  limit?: number
  offset?: number
  workspace_id?: string
  actor?: string
  action?: string
  resource_type?: string
  resource_id?: string
  search?: string
  from?: string
  to?: string
}

function filtersQuery(filters: AuditFilters = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value))
  }
  const query = params.toString()
  return query ? `?${query}` : ""
}

export type UserPasswordForm = {
  user: User
  newPassword: string
  confirmPassword: string
}

export type WorkspaceForm = {
  name: string
  description: string
  adminUserId: string
}

export type TeamForm = {
  workspaceId: string
  name: string
  description: string
  adminUserId: string
}

export type ScopeEditForm = {
  id: string
  name: string
  description: string
}

export type UserCreateForm = {
  username: string
  email: string
  name: string
  workspaceId: string
  teamIds: string[]
  isGlobalAdmin: boolean
}

export type UserForm = {
  id: string
  username: string
  email: string
  name: string
  isGlobalAdmin: boolean
}

export type UserStatusFilter = "all" | "active" | "inactive"
export type UserRoleFilter =
  "all" | "global_admin" | "workspace_admin" | "team_admin" | "member"

export function listUsers(token: string) {
  return request<User[]>("/api/v1/admin/users", { token })
}

export function createUser(
  token: string,
  payload: {
    username: string
    email: string
    name: string
    is_global_admin?: boolean
    workspace_id?: string | null
    team_ids?: string[]
  }
) {
  return request<UserPasswordResetResponse>("/api/v1/admin/users", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updateUser(
  token: string,
  userId: string,
  payload: {
    username?: string
    email?: string
    name?: string
    is_global_admin?: boolean
    is_active?: boolean
  }
) {
  return request<User>(`/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function changeUserPassword(
  token: string,
  userId: string,
  newPassword: string
) {
  return request<User>(`/api/v1/admin/users/${userId}/change-password`, {
    method: "POST",
    token,
    body: JSON.stringify({
      new_password: newPassword,
    }),
  })
}

export function deleteUser(token: string, userId: string) {
  return request<void>(`/api/v1/admin/users/${userId}`, {
    method: "DELETE",
    token,
  })
}

export function listWorkspaces(token: string) {
  return request<Workspace[]>("/api/v1/workspaces", { token })
}

export function createWorkspace(
  token: string,
  payload: {
    name: string
    description: string
    admin_user_id: string
  }
) {
  return request<WorkspaceCreateResponse>("/api/v1/workspaces", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updateWorkspace(
  token: string,
  workspaceId: string,
  payload: {
    name?: string
    description?: string
    status?: string
  }
) {
  return request<Workspace>(`/api/v1/workspaces/${workspaceId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function deleteWorkspace(token: string, workspaceId: string) {
  return request<void>(`/api/v1/workspaces/${workspaceId}`, {
    method: "DELETE",
    token,
  })
}

export function listWorkspaceMembers(
  token: string,
  workspaceId: string,
  limit = 200,
  offset = 0
) {
  return request<WorkspaceMember[]>(
    `/api/v1/workspaces/${workspaceId}/members?limit=${limit}&offset=${offset}`,
    { token }
  )
}

const WORKSPACE_MEMBER_PAGE_SIZE = 200

export async function listAllWorkspaceMembers(
  token: string,
  workspaceId: string
) {
  const members: WorkspaceMember[] = []
  let offset = 0

  while (true) {
    const page = await listWorkspaceMembers(
      token,
      workspaceId,
      WORKSPACE_MEMBER_PAGE_SIZE,
      offset
    )
    members.push(...page)
    if (page.length < WORKSPACE_MEMBER_PAGE_SIZE) return members
    offset += page.length
  }
}

export function addWorkspaceMember(
  token: string,
  workspaceId: string,
  payload: {
    user_id: string
    role?: string
  }
) {
  return request<WorkspaceMember>(`/api/v1/workspaces/${workspaceId}/members`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function createWorkspaceUser(
  token: string,
  workspaceId: string,
  payload: {
    username: string
    email: string
    name: string
  }
) {
  return request<UserPasswordResetResponse>(
    `/api/v1/workspaces/${workspaceId}/members/users`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    }
  )
}

export function updateWorkspaceMember(
  token: string,
  workspaceId: string,
  userId: string,
  payload: {
    role: string
  }
) {
  return request<WorkspaceMember>(
    `/api/v1/workspaces/${workspaceId}/members/${userId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    }
  )
}

export function removeWorkspaceMember(
  token: string,
  workspaceId: string,
  userId: string
) {
  return request<void>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
    method: "DELETE",
    token,
  })
}

export function listTeams(token: string, workspaceId: string) {
  return request<Team[]>(`/api/v1/workspaces/${workspaceId}/teams`, { token })
}

export function createTeam(
  token: string,
  workspaceId: string,
  payload: {
    name: string
    description: string
    admin_user_id: string
  }
) {
  return request<Team>(`/api/v1/workspaces/${workspaceId}/teams`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updateTeam(
  token: string,
  workspaceId: string,
  teamId: string,
  payload: {
    name?: string
    description?: string
    status?: string
  }
) {
  return request<Team>(`/api/v1/workspaces/${workspaceId}/teams/${teamId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function deleteTeam(token: string, workspaceId: string, teamId: string) {
  return request<void>(`/api/v1/workspaces/${workspaceId}/teams/${teamId}`, {
    method: "DELETE",
    token,
  })
}

export function listTeamMembers(
  token: string,
  workspaceId: string,
  teamId: string,
  limit = 200,
  offset = 0
) {
  return request<TeamMember[]>(
    `/api/v1/workspaces/${workspaceId}/teams/${teamId}/members?limit=${limit}&offset=${offset}`,
    { token }
  )
}

export function addTeamMember(
  token: string,
  workspaceId: string,
  teamId: string,
  payload: { user_id: string; role?: string }
) {
  return request<TeamMember>(
    `/api/v1/workspaces/${workspaceId}/teams/${teamId}/members`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    }
  )
}

export function updateTeamMember(
  token: string,
  workspaceId: string,
  teamId: string,
  userId: string,
  payload: { role: string }
) {
  return request<TeamMember>(
    `/api/v1/workspaces/${workspaceId}/teams/${teamId}/members/${userId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    }
  )
}

export function removeTeamMember(
  token: string,
  workspaceId: string,
  teamId: string,
  userId: string
) {
  return request<void>(
    `/api/v1/workspaces/${workspaceId}/teams/${teamId}/members/${userId}`,
    {
      method: "DELETE",
      token,
    }
  )
}

export function listAuditLogs(token: string, filters: AuditFilters = {}) {
  return request<AuditLog[]>(`/api/v1/admin/audit-logs${filtersQuery(filters)}`, {
    token,
  })
}

export function listWorkspaceAuditLogs(
  token: string,
  workspaceId: string,
  filters: AuditFilters = {}
) {
  return request<AuditLog[]>(
    `/api/v1/workspaces/${workspaceId}/audit-logs${filtersQuery(filters)}`,
    { token }
  )
}

export function listSystemLogs(token: string, filters: AuditFilters & {
  level?: string
  event?: string
  status_code?: number
  user_id?: string
  include_stack?: boolean
} = {}) {
  return request<SystemLog[]>(`/api/v1/admin/system-logs${filtersQuery(filters)}`, {
    token,
  })
}

export function getAdminHealth(token: string) {
  return request<AdminHealth>("/api/v1/admin/governance/health", { token })
}

export function getWorkspaceInventory(token: string, workspaceId: string) {
  return request<WorkspaceInventory>(
    `/api/v1/workspaces/${workspaceId}/inventory`,
    { token }
  )
}

export function getWorkspaceGovernance(token: string, workspaceId: string) {
  return request<WorkspaceGovernance>(
    `/api/v1/workspaces/${workspaceId}/governance`,
    { token }
  )
}

export function updateWorkspaceGovernance(
  token: string,
  workspaceId: string,
  payload: {
    daily_run_limit: number | null
    monthly_token_limit: number | null
    alert_threshold_percent: number
    retention_days: number | null
    timezone: string
  }
) {
  return request<WorkspaceGovernance>(
    `/api/v1/workspaces/${workspaceId}/governance`,
    { method: "PATCH", token, body: JSON.stringify(payload) }
  )
}

export function listWorkspaceInvitations(token: string, workspaceId: string) {
  return request<WorkspaceInvitation[]>(
    `/api/v1/workspaces/${workspaceId}/invitations`,
    { token }
  )
}

export function createWorkspaceInvitation(
  token: string,
  workspaceId: string,
  payload: { username: string; email: string; name: string; role: string }
) {
  return request<WorkspaceInvitation>(
    `/api/v1/workspaces/${workspaceId}/invitations`,
    { method: "POST", token, body: JSON.stringify(payload) }
  )
}

export function revokeWorkspaceInvitation(
  token: string,
  workspaceId: string,
  invitationId: string
) {
  return request<void>(
    `/api/v1/workspaces/${workspaceId}/invitations/${invitationId}`,
    { method: "DELETE", token }
  )
}

export function listSessions(token: string) {
  return request<RefreshSession[]>("/api/v1/auth/sessions", { token })
}

export function revokeSession(token: string, sessionId: string) {
  return request<void>(`/api/v1/auth/sessions/${sessionId}`, {
    method: "DELETE",
    token,
  })
}

export function revokeOtherSessions(token: string) {
  return request<void>("/api/v1/auth/sessions/revoke-others", {
    method: "POST",
    token,
  })
}

export function listUserSessions(token: string, userId: string) {
  return request<RefreshSession[]>(`/api/v1/admin/users/${userId}/sessions`, {
    token,
  })
}

export function revokeUserSession(
  token: string,
  userId: string,
  sessionId: string
) {
  return request<void>(`/api/v1/admin/users/${userId}/sessions/${sessionId}`, {
    method: "DELETE",
    token,
  })
}

export function revokeAllUserSessions(token: string, userId: string) {
  return request<void>(`/api/v1/admin/users/${userId}/sessions`, {
    method: "DELETE",
    token,
  })
}

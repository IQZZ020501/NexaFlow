import { request, requestPage } from "@/lib/api-client"
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

export type SmtpSecurity = "none" | "starttls" | "ssl"

export type SmtpSettings = {
  host: string
  port: number
  username: string
  security: SmtpSecurity
  from_email: string
  from_name: string
  enabled: boolean
  timeout_seconds: number
  has_password: boolean
  password_hint: string | null
  configured: boolean
  site_url: string
  identity_configured: boolean
  updated_at: string
}

export type SmtpSettingsUpdate = {
  host?: string
  port?: number
  username?: string
  password?: string
  clear_password?: boolean
  security?: SmtpSecurity
  from_email?: string
  from_name?: string
  enabled?: boolean
  timeout_seconds?: number
  site_url?: string
}

export type AdminHealth = {
  status: "ok" | "degraded"
  components: Record<
    string,
    {
      status: "ok" | "error" | "not_configured"
      detail?: "timeout" | "unavailable" | null
    }
  >
  pending_tasks: number
  failed_logs_24h: number
  pending_graph_tasks: number
  failed_graph_tasks_24h: number
  pending_graph_profile_repairs: number
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
  timezone: "Asia/Shanghai"
  updated_at: string
}

export type WorkspaceInvitationKind = "personal" | "generic"

export type WorkspaceInvitation = {
  id: string
  workspace_id: string
  kind: WorkspaceInvitationKind
  username: string | null
  email: string | null
  name: string | null
  role: string
  expires_at: string
  accepted_at: string | null
  created_at: string
  token?: string | null
  invite_url?: string | null
  email_delivery_status?: "queued" | "not_configured" | "not_applicable" | null
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

/**
 * Builds a URL query string from defined, non-empty audit filters.
 *
 * @param filters - The audit filter values to include in the query string
 * @returns A query string beginning with `?`, or an empty string when no filters are provided
 */
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

/**
 * Lists users available to administrators.
 *
 * @returns The available users
 */
export function listUsers(token: string) {
  return request<User[]>("/api/v1/admin/users", { token })
}

/**
 * Creates an administrator-managed user account.
 *
 * @param payload - User details and optional administrative, workspace, and team assignments
 * @returns The user-creation response containing the created user and initial password
 */
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

/**
 * Updates selected attributes of an administrator-managed user.
 *
 * @param userId - The identifier of the user to update
 * @param payload - The user attributes to change
 * @returns The updated user
 */
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

/**
 * Changes the password for a specified user.
 *
 * @param userId - The identifier of the user whose password will be changed
 * @param newPassword - The user's new password
 * @returns The updated user
 */
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

/**
 * Deletes a user from the system.
 *
 * @param userId - The ID of the user to delete
 */
export function deleteUser(token: string, userId: string) {
  return request<void>(`/api/v1/admin/users/${userId}`, {
    method: "DELETE",
    token,
  })
}

/**
 * Lists the workspaces available to the authenticated user.
 *
 * @returns The available workspaces
 */
export function listWorkspaces(token: string) {
  return request<Workspace[]>("/api/v1/workspaces", { token })
}

/**
 * Creates a workspace with the specified administrator.
 *
 * @param payload - The workspace name, description, and administrator user ID.
 * @returns The created workspace details.
 */
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

/**
 * Updates the details of a workspace.
 *
 * @param workspaceId - The identifier of the workspace to update
 * @param payload - The workspace fields to change
 * @returns The updated workspace
 */
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

/**
 * Deletes a workspace.
 *
 * @param workspaceId - The identifier of the workspace to delete
 */
export function deleteWorkspace(token: string, workspaceId: string) {
  return request<void>(`/api/v1/workspaces/${workspaceId}`, {
    method: "DELETE",
    token,
  })
}

/**
 * Lists members of a workspace.
 *
 * @param workspaceId - The workspace whose members to retrieve
 * @param limit - The maximum number of members to retrieve
 * @param offset - The number of members to skip
 * @returns The workspace members matching the requested page
 */
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

/**
 * Retrieves all members of a workspace across paginated responses.
 *
 * @param workspaceId - The identifier of the workspace whose members to retrieve
 * @returns The complete list of workspace members
 */
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

/**
 * Adds a user to a workspace with an optional role.
 *
 * @param workspaceId - The workspace to which the user is added
 * @param payload - The user identifier and optional workspace role
 * @returns The created workspace membership
 */
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

/**
 * Creates a user and adds them to a workspace.
 *
 * @param workspaceId - The workspace receiving the new user
 * @param payload - The new user's username, email address, and display name
 * @returns The user-creation response containing the created user and initial password
 */
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

/**
 * Updates a user's role within a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - Identifier of the workspace
 * @param userId - Identifier of the workspace member
 * @param payload - Updated membership details
 * @returns The updated workspace member
 */
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

/**
 * Removes a user from a workspace.
 *
 * @param workspaceId - The workspace containing the membership
 * @param userId - The user to remove from the workspace
 */
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

/**
 * Lists the teams in a workspace.
 *
 * @param workspaceId - The workspace whose teams to retrieve
 * @returns The workspace's teams
 */
export function listTeams(token: string, workspaceId: string) {
  return request<Team[]>(`/api/v1/workspaces/${workspaceId}/teams`, { token })
}

/**
 * Creates a team within a workspace.
 *
 * @param workspaceId - The workspace that will contain the team
 * @param payload - The team's name, description, and administrator user ID
 * @returns The created team
 */
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

/**
 * Updates a team's details within a workspace.
 *
 * @param workspaceId - The workspace containing the team
 * @param teamId - The team to update
 * @param payload - The team fields to change
 * @returns The updated team
 */
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

/**
 * Deletes a team from a workspace.
 *
 * @param workspaceId - The workspace containing the team
 * @param teamId - The team to delete
 */
export function deleteTeam(token: string, workspaceId: string, teamId: string) {
  return request<void>(`/api/v1/workspaces/${workspaceId}/teams/${teamId}`, {
    method: "DELETE",
    token,
  })
}

/**
 * Lists members of a team within a workspace.
 *
 * @param limit - Maximum number of members to include
 * @param offset - Number of members to skip before listing results
 * @returns The team's members
 */
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

/**
 * Adds a user to a workspace team.
 *
 * @param workspaceId - The workspace containing the team
 * @param teamId - The team to which the user is added
 * @param payload - The user identifier and optional team role
 * @returns The created team membership
 */
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

/**
 * Updates a user's role within a workspace team.
 *
 * @param workspaceId - The workspace containing the team
 * @param teamId - The team containing the member
 * @param userId - The user whose team membership is updated
 * @param payload - The updated team membership role
 * @returns The updated team member
 */
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

/**
 * Removes a user from a team within a workspace.
 *
 * @param workspaceId - The workspace containing the team
 * @param teamId - The team from which to remove the user
 * @param userId - The user to remove
 */
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

/**
 * Retrieves administrator audit logs matching the specified filters.
 *
 * @param filters - Optional criteria used to narrow the audit logs
 * @returns The matching audit log entries
 */
export function listAuditLogs(token: string, filters: AuditFilters = {}) {
  return request<AuditLog[]>(`/api/v1/admin/audit-logs${filtersQuery(filters)}`, {
    token,
  })
}

export function listAuditLogsPage(token: string, filters: AuditFilters = {}) {
  return requestPage<AuditLog>(`/api/v1/admin/audit-logs${filtersQuery(filters)}`, { token })
}

/**
 * Retrieves every audit log matching the supplied filters by paging through
 * the admin audit log endpoint until the reported total is reached.
 *
 * @param token - The session access token
 * @param filters - The audit filters applied to every page
 * @returns All matching audit logs across pages
 */
export async function listAllAuditLogs(
  token: string,
  filters: AuditFilters = {}
) {
  const items: AuditLog[] = []
  let offset = 0
  while (true) {
    const page = await listAuditLogsPage(token, {
      ...filters,
      limit: 200,
      offset,
    })
    items.push(...page.items)
    if (!page.items.length || offset + page.items.length >= page.total) {
      return items
    }
    offset += page.items.length
  }
}

/**
 * Retrieves audit logs for a workspace, optionally filtered by audit criteria.
 *
 * @param workspaceId - The identifier of the workspace whose audit logs are retrieved
 * @param filters - Optional criteria used to filter the audit logs
 * @returns The workspace's matching audit log entries
 */
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

export function listWorkspaceAuditLogsPage(token: string, workspaceId: string, filters: AuditFilters = {}) {
  return requestPage<AuditLog>(`/api/v1/workspaces/${workspaceId}/audit-logs${filtersQuery(filters)}`, { token })
}

/**
 * Retrieves every audit log for a workspace by paging through the workspace
 * audit log endpoint until the reported total is reached.
 *
 * @param token - The session access token
 * @param workspaceId - The workspace whose audit logs are exported
 * @param filters - The audit filters applied to every page
 * @returns All matching audit logs across pages
 */
export async function listAllWorkspaceAuditLogs(
  token: string,
  workspaceId: string,
  filters: AuditFilters = {}
) {
  const items: AuditLog[] = []
  let offset = 0
  while (true) {
    const page = await listWorkspaceAuditLogsPage(
      token,
      workspaceId,
      { ...filters, limit: 200, offset }
    )
    items.push(...page.items)
    if (!page.items.length || offset + page.items.length >= page.total) {
      return items
    }
    offset += page.items.length
  }
}

/**
 * Retrieves system logs matching the supplied filters.
 *
 * @param filters - Optional filters for log level, event, status code, user, time range, and stack trace inclusion
 * @returns The matching system logs
 */
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

export function listSystemLogsPage(token: string, filters: AuditFilters & {
  level?: string
  event?: string
  status_code?: number
  user_id?: string
  include_stack?: boolean
} = {}) {
  return requestPage<SystemLog>(`/api/v1/admin/system-logs${filtersQuery(filters)}`, { token })
}

/**
 * Retrieves every system log matching the supplied filters by paging through
 * the system log endpoint until the reported total is reached.
 *
 * @param token - The session access token
 * @param filters - The log filters applied to every page
 * @returns All matching system logs across pages
 */
export async function listAllSystemLogs(
  token: string,
  filters: Parameters<typeof listSystemLogsPage>[1] = {}
) {
  const items: SystemLog[] = []
  let offset = 0
  while (true) {
    const page = await listSystemLogsPage(token, {
      ...filters,
      limit: 200,
      offset,
    })
    items.push(...page.items)
    if (!page.items.length || offset + page.items.length >= page.total) {
      return items
    }
    offset += page.items.length
  }
}

/**
 * Retrieves the administrator health status.
 *
 * @returns The current administrator health information.
 */
export function getAdminHealth(token: string) {
  return request<AdminHealth>("/api/v1/admin/governance/health", { token })
}

/** Retrieves the global SMTP delivery configuration. */
export function getSmtpSettings(token: string) {
  return request<SmtpSettings>("/api/v1/admin/smtp", { token })
}

/** Updates the global SMTP delivery configuration without returning secrets. */
export function updateSmtpSettings(
  token: string,
  payload: SmtpSettingsUpdate
) {
  return request<SmtpSettings>("/api/v1/admin/smtp", {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

/** Sends a one-off SMTP test message to an administrator-provided address. */
export function sendSmtpTest(token: string, toEmail: string) {
  return request<{ success: boolean }>("/api/v1/admin/smtp/test", {
    method: "POST",
    token,
    body: JSON.stringify({ to_email: toEmail }),
  })
}

/**
 * Retrieves inventory details for a workspace.
 *
 * @param workspaceId - The workspace identifier
 * @returns The workspace inventory
 */
export function getWorkspaceInventory(token: string, workspaceId: string) {
  return request<WorkspaceInventory>(
    `/api/v1/workspaces/${workspaceId}/inventory`,
    { token }
  )
}

/**
 * Retrieves governance settings for a workspace.
 *
 * @param workspaceId - The identifier of the workspace
 * @returns The workspace governance settings
 */
export function getWorkspaceGovernance(token: string, workspaceId: string) {
  return request<WorkspaceGovernance>(
    `/api/v1/workspaces/${workspaceId}/governance`,
    { token }
  )
}

/**
 * Updates governance settings for a workspace.
 *
 * @param workspaceId - The workspace whose governance settings are updated
 * @param payload - The governance limits, alert threshold, retention period, and timezone
 * @returns The updated workspace governance settings
 */
export function updateWorkspaceGovernance(
  token: string,
  workspaceId: string,
  payload: {
    daily_run_limit: number | null
    monthly_token_limit: number | null
    alert_threshold_percent: number
    retention_days: number | null
    timezone: "Asia/Shanghai"
  }
) {
  return request<WorkspaceGovernance>(
    `/api/v1/workspaces/${workspaceId}/governance`,
    { method: "PATCH", token, body: JSON.stringify(payload) }
  )
}

/**
 * Lists invitations for a workspace.
 *
 * @param workspaceId - The workspace whose invitations to retrieve
 * @returns The workspace invitations
 */
export function listWorkspaceInvitations(token: string, workspaceId: string) {
  return request<WorkspaceInvitation[]>(
    `/api/v1/workspaces/${workspaceId}/invitations`,
    { token }
  )
}

/**
 * Creates an invitation for a user to join a workspace.
 *
 * @param workspaceId - The workspace receiving the invitation
 * @param payload - The invitation kind, workspace role, and personal recipient when applicable
 * @returns The created workspace invitation
 */
export function createWorkspaceInvitation(
  token: string,
  workspaceId: string,
  payload:
    | { kind: "personal"; username: string; email: string; name: string; role: string }
    | { kind: "generic"; role: string }
) {
  return request<WorkspaceInvitation>(
    `/api/v1/workspaces/${workspaceId}/invitations`,
    { method: "POST", token, body: JSON.stringify(payload) }
  )
}

/**
 * Revokes an invitation to join a workspace.
 *
 * @param token - The authentication token
 * @param workspaceId - The workspace containing the invitation
 * @param invitationId - The invitation to revoke
 */
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

/**
 * Permanently deletes a workspace invitation.
 *
 * @param token - The authentication token
 * @param workspaceId - The workspace containing the invitation
 * @param invitationId - The invitation to delete
 */
export function deleteWorkspaceInvitation(
  token: string,
  workspaceId: string,
  invitationId: string
) {
  return request<void>(
    `/api/v1/workspaces/${workspaceId}/invitations/${invitationId}/permanent`,
    { method: "DELETE", token }
  )
}

/**
 * Lists the authenticated user's active sessions.
 *
 * @returns The user's active sessions
 */
export function listSessions(token: string) {
  return request<RefreshSession[]>("/api/v1/auth/sessions", { token })
}

/** Revokes a session for the authenticated user.

 * @param sessionId - The identifier of the session to revoke
 */
export function revokeSession(token: string, sessionId: string) {
  return request<void>(`/api/v1/auth/sessions/${sessionId}`, {
    method: "DELETE",
    token,
  })
}

/**
 * Revokes all sessions associated with the authenticated user except the current session.
 */
export function revokeOtherSessions(token: string) {
  return request<void>("/api/v1/auth/sessions/revoke-others", {
    method: "POST",
    token,
  })
}

/**
 * Lists the active sessions for a user.
 *
 * @param userId - The identifier of the user whose sessions to retrieve
 * @returns The user's active sessions
 */
export function listUserSessions(token: string, userId: string) {
  return request<RefreshSession[]>(`/api/v1/admin/users/${userId}/sessions`, {
    token,
  })
}

/**
 * Revokes a specific session for a user.
 *
 * @param userId - The identifier of the user whose session is revoked
 * @param sessionId - The identifier of the session to revoke
 */
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

/**
 * Revokes all active sessions for a specified user.
 *
 * @param token - Authentication token for the request
 * @param userId - Identifier of the user whose sessions are revoked
 */
export function revokeAllUserSessions(token: string, userId: string) {
  return request<void>(`/api/v1/admin/users/${userId}/sessions`, {
    method: "DELETE",
    token,
  })
}

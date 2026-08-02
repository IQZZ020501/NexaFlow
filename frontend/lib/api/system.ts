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
  admin_created: boolean
  admin_initial_password: string | null
}

export type WorkspaceMember = {
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

export type UserPasswordForm = {
  user: User
  newPassword: string
  confirmPassword: string
}

export type WorkspaceForm = {
  name: string
  description: string
  adminUsername: string
  adminEmail: string
  adminName: string
}

export type TeamForm = {
  workspaceId: string
  name: string
  description: string
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
  isGlobalAdmin: boolean
  workspaceId: string
  teamIds: string[]
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
    admin: {
      username: string
      email: string
      name: string
    }
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

export function listWorkspaceMembers(token: string, workspaceId: string) {
  return request<WorkspaceMember[]>(`/api/v1/workspaces/${workspaceId}/members`, {
    token,
  })
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

export function listAuditLogs(token: string) {
  return request<AuditLog[]>("/api/v1/admin/audit-logs", { token })
}

export function listWorkspaceAuditLogs(token: string, workspaceId: string) {
  return request<AuditLog[]>(`/api/v1/workspaces/${workspaceId}/audit-logs`, {
    token,
  })
}

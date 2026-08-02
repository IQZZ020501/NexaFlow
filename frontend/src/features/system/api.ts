import { request } from "@/lib/api-client"
import type {
  User,
  UserPasswordResetResponse,
} from "@/features/auth/types"
import type {
  AuditLog,
  Team,
  Workspace,
  WorkspaceCreateResponse,
  WorkspaceMember,
} from "@/features/system/types"

export function listUsers(token: string) {
  return request<User[]>("/users", { token })
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
  return request<UserPasswordResetResponse>("/users", {
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
  return request<User>(`/users/${userId}`, {
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
  return request<User>(`/users/${userId}/change-password`, {
    method: "POST",
    token,
    body: JSON.stringify({
      new_password: newPassword,
    }),
  })
}

export function deleteUser(token: string, userId: string) {
  return request<void>(`/users/${userId}`, {
    method: "DELETE",
    token,
  })
}

export function listWorkspaces(token: string) {
  return request<Workspace[]>("/workspaces", { token })
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
  return request<WorkspaceCreateResponse>("/workspaces", {
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
  return request<Workspace>(`/workspaces/${workspaceId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function deleteWorkspace(token: string, workspaceId: string) {
  return request<void>(`/workspaces/${workspaceId}`, {
    method: "DELETE",
    token,
  })
}

export function listWorkspaceMembers(token: string, workspaceId: string) {
  return request<WorkspaceMember[]>(`/workspaces/${workspaceId}/members`, {
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
  return request<WorkspaceMember>(`/workspaces/${workspaceId}/members`, {
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
    `/workspaces/${workspaceId}/members/users`,
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
    `/workspaces/${workspaceId}/members/${userId}`,
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
  return request<void>(`/workspaces/${workspaceId}/members/${userId}`, {
    method: "DELETE",
    token,
  })
}

export function listTeams(token: string, workspaceId: string) {
  return request<Team[]>(`/workspaces/${workspaceId}/teams`, { token })
}

export function createTeam(
  token: string,
  workspaceId: string,
  payload: {
    name: string
    description: string
  }
) {
  return request<Team>(`/workspaces/${workspaceId}/teams`, {
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
  return request<Team>(`/workspaces/${workspaceId}/teams/${teamId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function deleteTeam(token: string, workspaceId: string, teamId: string) {
  return request<void>(`/workspaces/${workspaceId}/teams/${teamId}`, {
    method: "DELETE",
    token,
  })
}

export function listAuditLogs(token: string) {
  return request<AuditLog[]>("/audit-logs", { token })
}

export function listWorkspaceAuditLogs(token: string, workspaceId: string) {
  return request<AuditLog[]>(`/workspaces/${workspaceId}/audit-logs`, {
    token,
  })
}

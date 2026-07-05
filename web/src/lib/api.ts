const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

export type User = {
  id: string
  username: string
  email: string
  name: string
  is_global_admin: boolean
  must_change_password: boolean
  is_active: boolean
  created_at: string
  workspaces: UserWorkspace[]
  teams: UserTeam[]
}

export type UserWorkspace = {
  id: string
  name: string
  slug: string
  is_default: boolean
  role: string
}

export type UserTeam = {
  id: string
  workspace_id: string
  name: string
  slug: string
  is_default: boolean
  role: string
}

export type Membership = {
  workspace_id: string
  role: string
}

export type MeResponse = {
  user: User
  memberships: Membership[]
}

export type LoginResponse = {
  access_token: string
  token_type: string
  must_change_password: boolean
}

export type Workspace = {
  id: string
  name: string
  slug: string
  status: string
  is_default: boolean
}

export type Team = {
  id: string
  workspace_id: string
  name: string
  slug: string
  status: string
  is_default: boolean
}

export type WorkspaceCreateResponse = {
  workspace: Workspace
  admin_user: User
  admin_created: boolean
  admin_initial_password: string | null
}

export type UserPasswordResetResponse = {
  user: User
  initial_password: string
}

export type AuditLog = {
  id: string
  actor_user_id: string
  actor_username: string
  actor_name: string
  action: string
  resource_type: string
  resource_id: string
  resource_name: string
  details: Record<string, unknown>
  created_at: string
}

type RequestOptions = RequestInit & {
  token?: string
  workspaceId?: string
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

function errorMessage(payload: unknown, fallback: string) {
  if (typeof payload === "string" && payload) {
    return payload
  }

  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === "string") {
      return detail
    }

    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg)
          }

          return String(item)
        })
        .join("; ")
    }
  }

  return fallback
}

async function request<T>(path: string, options: RequestOptions = {}) {
  const headers = new Headers(options.headers)

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`)
  }

  if (options.workspaceId) {
    headers.set("X-Workspace-ID", options.workspaceId)
  }

  const response = await fetch(apiUrl(path), {
    ...options,
    headers,
  })

  if (response.status === 204) {
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText)
    }

    return undefined as T
  }

  const text = await response.text()
  const payload = text ? JSON.parse(text) : null

  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(payload, response.statusText))
  }

  return payload as T
}

export function login(username: string, password: string) {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({
      username,
      password,
    }),
  })
}

export function changePassword(
  token: string,
  newPassword: string,
  currentPassword?: string
) {
  return request<void>("/auth/change-password", {
    method: "POST",
    token,
    body: JSON.stringify({
      new_password: newPassword,
      current_password: currentPassword,
    }),
  })
}

export function getMe(token: string) {
  return request<MeResponse>("/auth/me", { token })
}

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

export function resetUserPassword(token: string, userId: string) {
  return request<UserPasswordResetResponse>(`/users/${userId}/reset-password`, {
    method: "POST",
    token,
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
    slug: string
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
    slug?: string
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

export function listTeams(token: string, workspaceId: string) {
  return request<Team[]>("/teams", { token, workspaceId })
}

export function createTeam(
  token: string,
  workspaceId: string,
  payload: {
    name: string
    slug: string
  }
) {
  return request<Team>("/teams", {
    method: "POST",
    token,
    workspaceId,
    body: JSON.stringify(payload),
  })
}

export function updateTeam(
  token: string,
  workspaceId: string,
  teamId: string,
  payload: {
    name?: string
    slug?: string
    status?: string
  }
) {
  return request<Team>(`/teams/${teamId}`, {
    method: "PATCH",
    token,
    workspaceId,
    body: JSON.stringify(payload),
  })
}

export function deleteTeam(token: string, workspaceId: string, teamId: string) {
  return request<void>(`/teams/${teamId}`, {
    method: "DELETE",
    token,
    workspaceId,
  })
}

export function listAuditLogs(token: string) {
  return request<AuditLog[]>("/audit-logs", { token })
}

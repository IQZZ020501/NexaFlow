import { request } from "@/lib/api-client"

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
  is_default: boolean
  role: string
}

export type UserTeam = {
  id: string
  workspace_id: string
  name: string
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
  expires_in: number
  must_change_password: boolean
}

export type UserPasswordResetResponse = {
  user: User
  initial_password: string
}

export function acceptWorkspaceInvitation(token: string, password: string) {
  return request<User>("/api/v1/auth/invitations/accept", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  })
}

export function login(username: string, password: string) {
  return request<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({
      username,
      password,
    }),
  })
}

export function refreshAccessToken() {
  return request<LoginResponse>("/api/v1/auth/refresh", { method: "POST" })
}

export function logout() {
  return request<void>("/api/v1/auth/logout", { method: "POST" })
}

export function changePassword(
  token: string,
  newPassword: string,
  currentPassword?: string
) {
  return request<void>("/api/v1/auth/change-password", {
    method: "POST",
    token,
    body: JSON.stringify({
      new_password: newPassword,
      current_password: currentPassword,
    }),
  })
}

export function getMe(token: string) {
  return request<MeResponse>("/api/v1/auth/me", { token })
}

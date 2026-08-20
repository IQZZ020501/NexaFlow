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

/**
 * Accepts a workspace invitation with a token and password.
 *
 * @param token - The workspace invitation token
 * @param password - The password for the new user account
 * @param identity - Account details required when accepting a generic invitation
 * @returns The created user
 */
export function acceptWorkspaceInvitation(
  token: string,
  password: string,
  identity?: { username: string; email: string; name: string }
) {
  return request<User>("/api/v1/auth/invitations/accept", {
    method: "POST",
    body: JSON.stringify({ token, password, ...identity }),
  })
}

/**
 * Authenticates a user with their username and password.
 *
 * @param username - The user's username
 * @param password - The user's password
 * @returns The access token, token type, expiration, and password-change requirement
 */
export function login(username: string, password: string) {
  return request<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({
      username,
      password,
    }),
  })
}

/**
 * Refreshes the current authentication credentials.
 *
 * @returns The refreshed login credentials
 */
export function refreshAccessToken() {
  return request<LoginResponse>("/api/v1/auth/refresh", { method: "POST" })
}

/**
 * Ends the authenticated session.
 */
export function logout() {
  return request<void>("/api/v1/auth/logout", { method: "POST" })
}

/**
 * Changes the password associated with an authenticated account.
 *
 * @param token - Authentication token for the account
 * @param newPassword - Password to set for the account
 * @param currentPassword - Existing password when required
 */
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

/**
 * Retrieves the authenticated user's profile and memberships.
 *
 * @param token - The access token used to authenticate the request
 * @returns The authenticated user's details and memberships
 */
export function getMe(token: string) {
  return request<MeResponse>("/api/v1/auth/me", { token })
}

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
  must_change_password: boolean
}

export type UserPasswordResetResponse = {
  user: User
  initial_password: string
}

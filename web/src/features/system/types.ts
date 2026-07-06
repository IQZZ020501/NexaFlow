import type { User } from "@/features/auth/types"

export type { MeResponse, User, UserPasswordResetResponse } from "@/features/auth/types"

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

import type { User } from "@/lib/api"

export type UserPasswordForm = {
  user: User
  newPassword: string
  confirmPassword: string
}

export type WorkspaceForm = {
  name: string
  slug: string
  adminUsername: string
  adminEmail: string
  adminName: string
}

export type TeamForm = {
  workspaceId: string
  name: string
  slug: string
}

export type ScopeEditForm = {
  id: string
  name: string
  slug: string
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

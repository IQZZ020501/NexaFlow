import { type MeResponse } from "@/lib/api/auth"
import { type RegisteredModel } from "@/lib/api/llm"
import { type TFunction } from "@/i18n"

export function modelLabel(model: RegisteredModel) {
  return model.name
}

export function initials(name: string) {
  const value = name.trim() || "NexaFlow"
  return value.slice(0, 2).toUpperCase()
}

export function formatDateTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value))
}

type DefaultNamedScope = {
  name: string
  is_default: boolean
}

export function displayWorkspaceName(
  workspace: DefaultNamedScope,
  t: TFunction
) {
  if (workspace.is_default && workspace.name === "Default Workspace") {
    return t("默认工作空间")
  }

  return workspace.name
}

export function displayTeamName(team: DefaultNamedScope, t: TFunction) {
  if (team.is_default && team.name === "Default Team") {
    return t("默认团队")
  }

  return team.name
}

export function hasWorkspaceMembership(
  me: MeResponse | null,
  workspaceId: string
) {
  return Boolean(
    me &&
      (me.user.is_global_admin ||
        me.memberships.some(
          (membership) => membership.workspace_id === workspaceId
        ))
  )
}

export function getMembershipRole(
  me: MeResponse | null,
  workspaceId: string | null
) {
  if (!me || !workspaceId) {
    return null
  }

  if (me.user.is_global_admin) {
    return "admin"
  }

  return (
    me.memberships.find((membership) => membership.workspace_id === workspaceId)
      ?.role ?? null
  )
}

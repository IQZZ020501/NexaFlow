import { type User } from "@/lib/api"
import { type TFunction } from "@/lib/i18n"
import { AUDIT_DETAIL_LABEL_KEYS, STATUS_LABEL_KEYS } from "@/app/constants"
import { displayTeamName, displayWorkspaceName } from "@/app/display"
import type { UserRoleFilter } from "@/features/system/types"

export function formatUserWorkspaces(user: User, t: TFunction) {
  if (!user.workspaces.length) {
    return "-"
  }

  return user.workspaces
    .map((workspace) => displayWorkspaceName(workspace, t))
    .join(t("列表分隔符"))
}

export function formatUserTeams(user: User, t: TFunction) {
  if (!user.teams.length) {
    return "-"
  }

  return user.teams
    .map((team) => displayTeamName(team, t))
    .join(t("列表分隔符"))
}

export function getUserRoleLabel(user: User, t: TFunction) {
  if (user.is_global_admin) {
    return t("全局管理员")
  }

  if (user.workspaces.some((workspace) => workspace.role === "admin")) {
    return t("工作空间管理员")
  }

  if (user.teams.some((team) => team.role === "admin")) {
    return t("团队管理员")
  }

  return t("普通用户")
}

export function getUserRoleKey(user: User): UserRoleFilter {
  if (user.is_global_admin) {
    return "global_admin"
  }

  if (user.workspaces.some((workspace) => workspace.role === "admin")) {
    return "workspace_admin"
  }

  if (user.teams.some((team) => team.role === "admin")) {
    return "team_admin"
  }

  return "member"
}

export function getUserRoleClass(user: User) {
  const role = getUserRoleKey(user)

  if (role === "global_admin" || role === "workspace_admin") {
    return "border-amber-300/60 bg-amber-100 text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300"
  }

  if (role === "team_admin") {
    return "border-red-300/60 bg-red-100 text-red-600 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"
  }

  return "border-border bg-muted text-muted-foreground"
}

export function displaySlug(slug: string, isDefault: boolean, t: TFunction) {
  if (isDefault && slug === "default") {
    return t("默认")
  }

  return slug
}

export function formatAuditDetails(
  details: Record<string, unknown>,
  t: TFunction
) {
  const entries = Object.entries(details).filter(
    ([, value]) => value !== null && value !== undefined && value !== ""
  )
  if (!entries.length) {
    return "-"
  }

  return entries
    .map(([key, value]) => {
      const labelKey = AUDIT_DETAIL_LABEL_KEYS[key]
      const label = labelKey ? t(labelKey) : key
      return `${label}: ${formatAuditDetailValue(key, value, t)}`
    })
    .join(t("详情分隔符"))
}

function formatAuditDetailValue(
  key: string,
  value: unknown,
  t: TFunction
): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => formatAuditDetailValue(key, item, t))
      .join(t("列表分隔符"))
  }

  if (typeof value === "boolean") {
    return value ? t("是") : t("否")
  }

  if (key === "status" && typeof value === "string") {
    const labelKey = STATUS_LABEL_KEYS[value]
    return labelKey ? t(labelKey) : value
  }

  return String(value)
}

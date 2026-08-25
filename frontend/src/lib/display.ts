import { type MeResponse } from "@/lib/api/auth"
import { type RegisteredModel } from "@/lib/api/llm"
import { type TFunction } from "@/i18n"

/**
 * Gets the registered model's name.
 *
 * @param model - The registered model
 * @returns The model's name
 */
export function modelLabel(model: RegisteredModel) {
  return model.name
}

/**
 * Generates uppercase initials from a name.
 *
 * @param name - The name from which to derive initials
 * @returns The first two characters of the trimmed name in uppercase, or `"NE"` when the name is empty
 */
export function initials(name: string) {
  const value = name.trim() || "NexaFlow"
  return value.slice(0, 2).toUpperCase()
}

/**
 * Formats a date-time value according to the specified locale.
 *
 * @param value - The date-time string to format
 * @param locale - The locale used for formatting
 * @returns The localized date and 24-hour time representation
 */
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

export function formatUserIdentity(
  name: string | null | undefined,
  username: string | null | undefined,
  fallback: string
) {
  if (name && username && name !== username) return `${name} · ${username}`
  return name || username || fallback
}

type DefaultNamedScope = {
  name: string
  is_default: boolean
}

/**
 * Resolves the display name for a workspace, translating the default workspace name when applicable.
 *
 * @param workspace - The workspace whose name should be displayed
 * @param t - The translation function
 * @returns The translated default workspace name or the workspace's original name
 */
export function displayWorkspaceName(
  workspace: DefaultNamedScope,
  t: TFunction
) {
  if (workspace.is_default && workspace.name === "Default Workspace") {
    return t("默认工作空间")
  }

  return workspace.name
}

/**
 * Resolves the display name for a team, translating the default team name when applicable.
 *
 * @param team - The team whose display name is resolved
 * @param t - The translation function
 * @returns The translated default team name or the team's original name
 */
export function displayTeamName(team: DefaultNamedScope, t: TFunction) {
  if (team.is_default && team.name === "Default Team") {
    return t("默认团队")
  }

  return team.name
}

/**
 * Determines whether a user has access to a workspace.
 *
 * @param me - The current user's profile and workspace memberships
 * @param workspaceId - The workspace to check
 * @returns `true` if the user is a global administrator or has membership in the workspace, `false` otherwise.
 */
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

/**
 * Resolves a user's role for a workspace.
 *
 * @param me - The current user's profile and workspace memberships
 * @param workspaceId - The workspace identifier
 * @returns `"admin"` for global administrators, the matching membership role, or `null` when no role applies
 */
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

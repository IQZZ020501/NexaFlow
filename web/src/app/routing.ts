import { type PageKey } from "@/lib/pages"

export type SystemTabKey = "workspaces" | "teams" | "users" | "audit"

export type AppRoute = {
  page: PageKey
  systemTab: SystemTabKey
}

export const PAGE_PATHS: Record<PageKey, string> = {
  apps: "/apps",
  knowledge: "/knowledge",
  models: "/models",
  tools: "/tools",
  system: "/system/workspaces",
}

export const SYSTEM_TAB_PATHS: Record<SystemTabKey, string> = {
  workspaces: "/system/workspaces",
  teams: "/system/teams",
  users: "/system/users",
  audit: "/system/audit",
}

export function routeFromPath(pathname = window.location.pathname): AppRoute {
  const path = pathname.replace(/\/+$/, "") || "/"

  switch (path) {
    case "/":
    case "/apps":
      return { page: "apps", systemTab: "workspaces" }
    case "/knowledge":
      return { page: "knowledge", systemTab: "workspaces" }
    case "/models":
      return { page: "models", systemTab: "workspaces" }
    case "/tools":
      return { page: "tools", systemTab: "workspaces" }
    case "/system":
    case "/system/workspaces":
      return { page: "system", systemTab: "workspaces" }
    case "/system/teams":
      return { page: "system", systemTab: "teams" }
    case "/system/users":
      return { page: "system", systemTab: "users" }
    case "/system/audit":
      return { page: "system", systemTab: "audit" }
    case "/system/account":
      return { page: "system", systemTab: "workspaces" }
    default:
      return { page: "apps", systemTab: "workspaces" }
  }
}

export function pathForRoute(route: AppRoute) {
  if (route.page === "system") {
    return SYSTEM_TAB_PATHS[route.systemTab]
  }

  return PAGE_PATHS[route.page]
}

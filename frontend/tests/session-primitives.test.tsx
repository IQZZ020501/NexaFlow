/* @jsxImportSource react */
/**
 * DOM-level coverage for the real SessionProvider, the LanguageProvider,
 * and the shared UI primitives (top-progress, filter-dropdown,
 * dropdown-menu, dialog, badge, field).
 *
 * The SessionProvider is exercised with the real provider (no module mock):
 * refresh / me / workspaces / teams all go through the stubbed fetch.
 */
import { beforeEach, describe, expect, mock, test } from "bun:test"
import type { WheelEventHandler as ReactWheelEventHandler } from "react"

import { TopLoadingBar, TopProgress } from "@/components/app/top-progress"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge, badgeVariants } from "@/components/ui/badge"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import {
  addCreatedTeamMembership,
  addCreatedWorkspaceMembership,
  getInitialWorkspaceId,
  replaceSessionUser,
  SessionProvider,
  useCurrentWorkspaceName,
  useSession,
} from "@/contexts/session-context"
import { LanguageProvider, useLanguage } from "@/contexts/language-provider"
import type { LoginResponse, MeResponse, User } from "@/lib/api/auth"
import type { Team, Workspace } from "@/lib/api/system"
import { LEGACY_TOKEN_KEY, WORKSPACE_KEY } from "@/lib/storage"
import {
  fireEvent,
  jsonResponse,
  render,
  renderPage,
  screen,
  waitFor,
  within,
  type FetchHandler,
} from "./helpers/dom"

// Mutable pathname so TopProgress can observe navigation changes.
let navPathname = "/app/dashboard"
mock.module("next/navigation", () => ({
  useParams: () => ({}),
  useRouter: () => ({
    push: () => undefined,
    replace: () => undefined,
    back: () => undefined,
    forward: () => undefined,
    prefetch: () => undefined,
    refresh: () => undefined,
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => navPathname,
}))

let handler: FetchHandler = () => jsonResponse(null, 404)

beforeEach(() => {
  localStorage.clear()
  document.documentElement.lang = ""
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    return Promise.resolve(handler(url, init))
  }) as typeof fetch
})

// ---------------------------------------------------------------------------
// Session fixtures
// ---------------------------------------------------------------------------

const user: User = {
  id: "u-1",
  username: "admin",
  email: "admin@app.local",
  name: "NexaFlow Admin",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [],
  teams: [],
}

const memberMe: MeResponse = {
  user,
  memberships: [
    { workspace_id: "ws-1", role: "admin" },
    { workspace_id: "ws-2", role: "member" },
  ],
}

const ws1: Workspace = {
  id: "ws-1",
  name: "Workspace One",
  description: "",
  status: "active",
  is_default: true,
}
const ws2: Workspace = {
  id: "ws-2",
  name: "Workspace Two",
  description: "",
  status: "active",
  is_default: false,
}
const ws3: Workspace = {
  id: "ws-3",
  name: "Archived",
  description: "",
  status: "archived",
  is_default: false,
}
const ws4: Workspace = {
  id: "ws-4",
  name: "No Membership",
  description: "",
  status: "active",
  is_default: false,
}
const wsNew: Workspace = {
  id: "ws-new",
  name: "Brand New",
  description: "",
  status: "active",
  is_default: false,
}

const team1: Team = {
  id: "team-1",
  workspace_id: "ws-1",
  name: "Team One",
  description: "",
  status: "active",
  is_default: true,
}
const team2: Team = {
  id: "team-2",
  workspace_id: "ws-1",
  name: "Team Two",
  description: "",
  status: "active",
  is_default: false,
}

const refreshPayload: LoginResponse = {
  access_token: "fresh-token",
  token_type: "bearer",
  expires_in: 3600,
  must_change_password: false,
}

/**
 * Standard restore handler. Records the kind of every request it serves.
 */
function restoreHandler(options: {
  refreshPayload?: LoginResponse
  me?: MeResponse | null
  meError?: Response
  workspaces?: Workspace[]
  teams?: (url: string) => Team[]
  logoutStatus?: Response
} = {}) {
  const calls: string[] = []
  const refresh = options.refreshPayload ?? refreshPayload
  const me = options.me === undefined ? memberMe : options.me
  const workspaces = options.workspaces ?? [ws1, ws2, ws3, ws4]
  const teams = options.teams ?? (() => [team1])
  handler = (url, init) => {
    if (url.endsWith("/api/v1/auth/refresh")) {
      calls.push("refresh")
      return jsonResponse(refresh)
    }
    if (url.endsWith("/api/v1/auth/me")) {
      calls.push("me")
      return options.meError ?? (me ? jsonResponse(me) : jsonResponse(null, 401))
    }
    if (url.endsWith("/api/v1/workspaces") && init?.method === undefined) {
      calls.push("workspaces")
      return jsonResponse(workspaces)
    }
    if (url.includes("/teams")) {
      calls.push("teams")
      return jsonResponse(teams(url))
    }
    if (url.endsWith("/api/v1/auth/logout")) {
      calls.push("logout")
      return options.logoutStatus ?? jsonResponse(null, 204)
    }
    calls.push("other")
    return jsonResponse(null, 404)
  }
  return calls
}

// ---------------------------------------------------------------------------
// Probe component exposing the whole session surface
// ---------------------------------------------------------------------------

function SessionProbe() {
  const session = useSession()
  const { setLanguage } = useLanguage()
  const wsName = useCurrentWorkspaceName()
  return (
    <div>
      <span data-testid="token">{session.token ?? "null"}</span>
      <span data-testid="me">{session.me?.user.username ?? "null"}</span>
      <span data-testid="user-name">{session.me?.user.name ?? ""}</span>
      <span data-testid="memberships">
        {session.me?.memberships.map((m) => m.workspace_id).join(",") ?? ""}
      </span>
      <span data-testid="user-teams">{session.me?.user.teams.length ?? 0}</span>
      <span data-testid="restored">{String(session.isSessionRestored)}</span>
      <span data-testid="loading">{String(session.isSessionLoading)}</span>
      <span data-testid="ws">{session.selectedWorkspaceId ?? "null"}</span>
      <span data-testid="wsname">{wsName}</span>
      <span data-testid="ws-count">{session.workspaces.length}</span>
      <span data-testid="ws-options">
        {session.workspaceOptions.map((w) => w.id).join(",")}
      </span>
      <span data-testid="ws2name">
        {session.workspaces.find((w) => w.id === "ws-2")?.name ?? "-"}
      </span>
      <span data-testid="teams">{session.teams.length}</span>
      <span data-testid="teamnames">
        {session.teams.map((t) => t.name).join(",")}
      </span>
      <span data-testid="teams-loading">{String(session.isTeamsLoading)}</span>
      <span data-testid="mcp">{String(session.mustChangePassword)}</span>
      <span data-testid="err">{session.sessionError ?? ""}</span>
      <span data-testid="notif">
        {session.notification
          ? `${session.notification.kind}:${session.notification.message}`
          : "none"}
      </span>
      <span data-testid="pw">{String(session.passwordDialogOpen)}</span>

      <button type="button" onClick={() => session.login("login-token", false, 3600)}>
        login
      </button>
      <button type="button" onClick={() => session.login("short-token", false, 61)}>
        login-short
      </button>
      <button type="button" onClick={() => session.logout()}>
        logout
      </button>
      <button type="button" onClick={() => session.selectWorkspace("ws-2")}>
        select-ws2
      </button>
      <button type="button" onClick={() => session.selectWorkspace("ws-1")}>
        select-ws1
      </button>
      <button type="button" onClick={() => session.selectWorkspace("ws-99")}>
        select-ws99
      </button>
      <button type="button" onClick={() => session.selectWorkspace("ws-3")}>
        select-ws3
      </button>
      <button type="button" onClick={() => session.selectWorkspace("ws-4")}>
        select-ws4
      </button>
      <button type="button" onClick={() => session.clearSelectedWorkspace()}>
        clear-ws
      </button>
      <button
        type="button"
        onClick={() =>
          session.workspaceCreated({ workspace: wsNew, admin_user: memberMe.user })
        }
      >
        ws-created
      </button>
      <button
        type="button"
        onClick={() => session.workspaceUpdated({ ...ws1, status: "archived" })}
      >
        ws-archived
      </button>
      <button
        type="button"
        onClick={() => session.workspaceUpdated({ ...ws2, name: "Workspace Two Renamed" })}
      >
        ws-renamed
      </button>
      <button type="button" onClick={() => session.workspaceDeleted("ws-1")}>
        ws-deleted
      </button>
      <button type="button" onClick={() => session.workspaceDeleted("ws-2")}>
        ws-deleted2
      </button>
      <button
        type="button"
        onClick={() => session.teamCreated(team2, memberMe.user.id)}
      >
        team-created
      </button>
      <button
        type="button"
        onClick={() => session.teamCreated(team2, "someone-else")}
      >
        team-created-other
      </button>
      <button
        type="button"
        onClick={() => session.teamUpdated({ ...team1, name: "Team One Renamed" })}
      >
        team-updated
      </button>
      <button type="button" onClick={() => session.teamDeleted("team-1")}>
        team-deleted
      </button>
      <button
        type="button"
        onClick={() => session.userUpdated({ ...memberMe.user, name: "Renamed User" })}
      >
        user-updated
      </button>
      <button
        type="button"
        onClick={() => session.userUpdated({ ...memberMe.user, id: "other" })}
      >
        user-updated-other
      </button>
      <button type="button" onClick={() => session.notify("success", "hello")}>
        notify
      </button>
      <button type="button" onClick={() => setLanguage("en")}>
        language-en
      </button>
      <button type="button" onClick={() => session.dismissNotification()}>
        dismiss
      </button>
      <button type="button" onClick={() => session.openPasswordDialog()}>
        open-pw
      </button>
      <button type="button" onClick={() => session.closePasswordDialog()}>
        close-pw
      </button>
      <button type="button" onClick={() => void session.passwordChanged()}>
        password-changed
      </button>
    </div>
  )
}

function renderSession() {
  return render(
    <LanguageProvider defaultLanguage="zh-Hans">
      <SessionProvider>
        <SessionProbe />
      </SessionProvider>
    </LanguageProvider>
  )
}

// ---------------------------------------------------------------------------
// SessionProvider
// ---------------------------------------------------------------------------

describe("SessionProvider", () => {
  test("restores the session and loads workspaces and teams", async () => {
    const calls = restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("teams").textContent).toBe("1"))
    expect(screen.getByTestId("token").textContent).toBe("fresh-token")
    expect(screen.getByTestId("me").textContent).toBe("admin")
    expect(screen.getByTestId("restored").textContent).toBe("true")
    expect(screen.getByTestId("loading").textContent).toBe("false")
    expect(screen.getByTestId("ws").textContent).toBe("ws-1")
    expect(screen.getByTestId("wsname").textContent).toBe("Workspace One")
    expect(screen.getByTestId("ws-count").textContent).toBe("4")
    expect(screen.getByTestId("ws-options").textContent).toBe("ws-1,ws-2")
    expect(screen.getByTestId("teams-loading").textContent).toBe("false")
    expect(screen.getByTestId("notif").textContent).toBe("none")
    expect(localStorage.getItem(WORKSPACE_KEY)).toBe("ws-1")
    expect(calls).toContain("refresh")
    expect(calls).toContain("me")
    expect(calls).toContain("workspaces")
    expect(calls).toContain("teams")
  })

  test("does not reload session data when the language changes", async () => {
    const calls = restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("teams").textContent).toBe("1"))
    const requestsBeforeLanguageChange = [...calls]

    fireEvent.click(screen.getByText("language-en"))
    await waitFor(() => expect(document.documentElement.lang).toBe("en"))
    await new Promise((resolve) => setTimeout(resolve, 50))

    expect(calls).toEqual(requestsBeforeLanguageChange)
  })

  test("prefers the stored workspace when restoring", async () => {
    localStorage.setItem(WORKSPACE_KEY, "ws-2")
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-2"))
    expect(screen.getByTestId("wsname").textContent).toBe("Workspace Two")
    expect(localStorage.getItem(WORKSPACE_KEY)).toBe("ws-2")
  })

  test("falls back from an invalid stored workspace", async () => {
    localStorage.setItem(WORKSPACE_KEY, "ws-99")
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
  })

  test("removes the stored workspace when none can be selected", async () => {
    localStorage.setItem(WORKSPACE_KEY, "ws-1")
    restoreHandler({ workspaces: [ws3] })
    renderSession()
    await waitFor(() => expect(screen.getByTestId("restored").textContent).toBe("true"))
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("null"))
    expect(screen.getByTestId("wsname").textContent).toBe("未选择工作空间")
    expect(localStorage.getItem(WORKSPACE_KEY)).toBeNull()
  })

  test("reports non-auth restore errors", async () => {
    handler = () => {
      throw new Error("offline")
    }
    renderSession()
    await waitFor(() => expect(screen.getByTestId("restored").textContent).toBe("true"))
    expect(screen.getByTestId("err").textContent).toBe("offline")
    expect(screen.getByTestId("notif").textContent).toBe("error:offline")
    expect(screen.getByTestId("loading").textContent).toBe("false")
    expect(screen.getByTestId("token").textContent).toBe("null")
  })

  test("ignores 401 during the initial restore", async () => {
    handler = () => jsonResponse({ detail: "no session" }, 401)
    renderSession()
    await waitFor(() => expect(screen.getByTestId("restored").textContent).toBe("true"))
    expect(screen.getByTestId("err").textContent).toBe("")
    expect(screen.getByTestId("notif").textContent).toBe("none")
    expect(screen.getByTestId("token").textContent).toBe("null")
  })

  test("renews the access token when me returns 401", async () => {
    let meCalls = 0
    let refreshCalls = 0
    handler = (url) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        refreshCalls++
        return jsonResponse({
          ...refreshPayload,
          access_token: refreshCalls === 1 ? "fresh-token" : "renewed-token",
        })
      }
      if (url.endsWith("/api/v1/auth/me")) {
        meCalls++
        return meCalls === 1 ? jsonResponse({ detail: "expired" }, 401) : jsonResponse(memberMe)
      }
      if (url.endsWith("/api/v1/workspaces")) return jsonResponse([ws1, ws2])
      if (url.includes("/teams")) return jsonResponse([team1])
      return jsonResponse(null, 404)
    }
    renderSession()
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("renewed-token"))
    await waitFor(() => expect(screen.getByTestId("me").textContent).toBe("admin"))
    expect(refreshCalls).toBe(2)
  })

  test("clears the session when renewal fails", async () => {
    let refreshCalls = 0
    handler = (url) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        refreshCalls++
        return refreshCalls === 1
          ? jsonResponse(refreshPayload)
          : jsonResponse({ detail: "expired" }, 401)
      }
      if (url.endsWith("/api/v1/auth/me")) return jsonResponse({ detail: "expired" }, 401)
      return jsonResponse(null, 404)
    }
    renderSession()
    await waitFor(() => expect(screen.getByTestId("restored").textContent).toBe("true"))
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("null"))
    expect(screen.getByTestId("me").textContent).toBe("null")
    expect(screen.getByTestId("ws").textContent).toBe("null")
    expect(screen.getByTestId("err").textContent).toBe("")
  })

  test("reports non-auth errors while loading the user", async () => {
    restoreHandler({ meError: jsonResponse({ detail: "profile broken" }, 500) })
    renderSession()
    await waitFor(() => expect(screen.getByTestId("err").textContent).toBe("profile broken"))
    expect(screen.getByTestId("notif").textContent).toBe("error:profile broken")
    expect(screen.getByTestId("loading").textContent).toBe("false")
  })

  test("defers workspace loading while the password must change", async () => {
    let meCalls = 0
    handler = (url) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        return jsonResponse({ ...refreshPayload, must_change_password: true })
      }
      if (url.endsWith("/api/v1/auth/me")) {
        meCalls++
        const mustChange = meCalls === 1
        return jsonResponse({
          ...memberMe,
          user: { ...memberMe.user, must_change_password: mustChange },
        })
      }
      if (url.endsWith("/api/v1/workspaces")) return jsonResponse([ws1, ws2])
      if (url.includes("/teams")) return jsonResponse([team1])
      return jsonResponse(null, 404)
    }
    renderSession()
    await waitFor(() => expect(screen.getByTestId("mcp").textContent).toBe("true"))
    expect(screen.getByTestId("ws").textContent).toBe("null")
    expect(screen.getByTestId("ws-count").textContent).toBe("0")
    expect(screen.getByTestId("teams-loading").textContent).toBe("false")

    fireEvent.click(screen.getByText("password-changed"))
    await waitFor(() => expect(screen.getByTestId("mcp").textContent).toBe("false"))
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    expect(screen.getByTestId("notif").textContent).toBe("success:密码已修改")
  })

  test("selectWorkspace switches, validates, and reloads teams", async () => {
    const calls = restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    expect(calls.filter((c) => c === "teams").length).toBe(1)

    fireEvent.click(screen.getByText("select-ws2"))
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-2"))
    expect(localStorage.getItem(WORKSPACE_KEY)).toBe("ws-2")
    await waitFor(() => expect(calls.filter((c) => c === "teams").length).toBe(2))

    // invalid, archived, and non-member workspaces are rejected
    fireEvent.click(screen.getByText("select-ws99"))
    expect(screen.getByTestId("ws").textContent).toBe("ws-2")
    fireEvent.click(screen.getByText("select-ws3"))
    expect(screen.getByTestId("ws").textContent).toBe("ws-2")
    fireEvent.click(screen.getByText("select-ws4"))
    expect(screen.getByTestId("ws").textContent).toBe("ws-2")
    // selecting the same workspace is a no-op
    fireEvent.click(screen.getByText("select-ws2"))
    expect(screen.getByTestId("ws").textContent).toBe("ws-2")
    expect(calls.filter((c) => c === "teams").length).toBe(2)
  })

  test("clearSelectedWorkspace resets the selection", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    fireEvent.click(screen.getByText("clear-ws"))
    expect(screen.getByTestId("ws").textContent).toBe("null")
    expect(screen.getByTestId("teams").textContent).toBe("0")
    expect(screen.getByTestId("wsname").textContent).toBe("未选择工作空间")
    expect(localStorage.getItem(WORKSPACE_KEY)).toBeNull()
  })

  test("logout clears state and calls the endpoint", async () => {
    const calls = restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    localStorage.setItem(LEGACY_TOKEN_KEY, "stale")
    fireEvent.click(screen.getByText("logout"))
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("null"))
    expect(calls).toContain("logout")
    expect(screen.getByTestId("me").textContent).toBe("null")
    expect(screen.getByTestId("ws").textContent).toBe("null")
    expect(localStorage.getItem(WORKSPACE_KEY)).toBeNull()
    expect(localStorage.getItem(LEGACY_TOKEN_KEY)).toBeNull()
  })

  test("workspaceCreated appends the workspace and membership", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws-count").textContent).toBe("4"))
    fireEvent.click(screen.getByText("ws-created"))
    expect(screen.getByTestId("ws-count").textContent).toBe("5")
    expect(screen.getByTestId("memberships").textContent).toBe("ws-1,ws-2,ws-new")
  })

  test("workspaceUpdated archives the selected workspace and switches", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    fireEvent.click(screen.getByText("ws-archived"))
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-2"))
    expect(localStorage.getItem(WORKSPACE_KEY)).toBe("ws-2")
  })

  test("workspaceUpdated renames a non-selected workspace", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    fireEvent.click(screen.getByText("ws-renamed"))
    expect(screen.getByTestId("ws").textContent).toBe("ws-1")
    expect(screen.getByTestId("ws2name").textContent).toBe("Workspace Two Renamed")
  })

  test("workspaceDeleted falls back to another workspace", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    fireEvent.click(screen.getByText("ws-deleted"))
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-2"))
    expect(screen.getByTestId("ws-count").textContent).toBe("3")
  })

  test("workspaceDeleted clears the selection without a fallback", async () => {
    restoreHandler({ workspaces: [ws1] })
    renderSession()
    await waitFor(() => expect(screen.getByTestId("ws").textContent).toBe("ws-1"))
    fireEvent.click(screen.getByText("ws-deleted"))
    expect(screen.getByTestId("ws").textContent).toBe("null")
    expect(screen.getByTestId("wsname").textContent).toBe("未选择工作空间")
  })

  test("team lifecycle updates teams and memberships", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("teams").textContent).toBe("1"))
    fireEvent.click(screen.getByText("team-created"))
    expect(screen.getByTestId("teams").textContent).toBe("2")
    expect(screen.getByTestId("user-teams").textContent).toBe("1")
    expect(screen.getByTestId("teamnames").textContent).toBe("Team One,Team Two")
    // a different admin does not add a membership
    fireEvent.click(screen.getByText("team-created-other"))
    expect(screen.getByTestId("teams").textContent).toBe("3")
    expect(screen.getByTestId("user-teams").textContent).toBe("1")
    fireEvent.click(screen.getByText("team-updated"))
    expect(screen.getByTestId("teamnames").textContent).toContain("Team One Renamed")
    fireEvent.click(screen.getByText("team-deleted"))
    expect(screen.getByTestId("teams").textContent).toBe("2")
  })

  test("userUpdated replaces only the current session user", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("user-name").textContent).toBe("NexaFlow Admin"))
    fireEvent.click(screen.getByText("user-updated"))
    expect(screen.getByTestId("user-name").textContent).toBe("Renamed User")
    fireEvent.click(screen.getByText("user-updated-other"))
    expect(screen.getByTestId("user-name").textContent).toBe("Renamed User")
  })

  test("notify, dismiss, and the password dialog", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("restored").textContent).toBe("true"))
    expect(screen.getByTestId("pw").textContent).toBe("false")
    fireEvent.click(screen.getByText("open-pw"))
    expect(screen.getByTestId("pw").textContent).toBe("true")
    fireEvent.click(screen.getByText("close-pw"))
    expect(screen.getByTestId("pw").textContent).toBe("false")
    fireEvent.click(screen.getByText("notify"))
    expect(screen.getByTestId("notif").textContent).toBe("success:hello")
    fireEvent.click(screen.getByText("dismiss"))
    expect(screen.getByTestId("notif").textContent).toBe("none")
  })

  test("notifications auto-dismiss after a delay", async () => {
    restoreHandler()
    renderSession()
    await waitFor(() => expect(screen.getByTestId("restored").textContent).toBe("true"))
    fireEvent.click(screen.getByText("notify"))
    await waitFor(
      () => expect(screen.getByTestId("notif").textContent).toBe("none"),
      { timeout: 5000 }
    )
  })

  test("reports team loading errors", async () => {
    restoreHandler({
      teams: () => {
        throw new Error("teams exploded")
      },
    })
    renderSession()
    await waitFor(() => expect(screen.getByTestId("restored").textContent).toBe("true"))
    await waitFor(() =>
      expect(screen.getByTestId("notif").textContent).toBe("error:teams exploded")
    )
    expect(screen.getByTestId("teams").textContent).toBe("0")
    expect(screen.getByTestId("teams-loading").textContent).toBe("false")
  })

  test("renews the token when the refresh timer fires early", async () => {
    let refreshCalls = 0
    handler = (url) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        refreshCalls++
        return jsonResponse({
          ...refreshPayload,
          access_token: refreshCalls === 1 ? "fresh-token" : "timer-token-2",
        })
      }
      if (url.endsWith("/api/v1/auth/me")) return jsonResponse(memberMe)
      if (url.endsWith("/api/v1/workspaces")) return jsonResponse([ws1, ws2])
      if (url.includes("/teams")) return jsonResponse([team1])
      return jsonResponse(null, 404)
    }
    renderSession()
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("fresh-token"))
    fireEvent.click(screen.getByText("login-short"))
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("short-token"))
    // expiresIn=61 schedules the refresh one second out
    await waitFor(
      () => expect(screen.getByTestId("token").textContent).toBe("timer-token-2"),
      { timeout: 5000 }
    )
    expect(refreshCalls).toBe(2)
  })

  test("retries the refresh timer after a non-auth failure", async () => {
    let refreshCalls = 0
    handler = (url) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        refreshCalls++
        return refreshCalls === 1
          ? jsonResponse(refreshPayload)
          : jsonResponse({ detail: "refresh failed" }, 500)
      }
      if (url.endsWith("/api/v1/auth/me")) return jsonResponse(memberMe)
      if (url.endsWith("/api/v1/workspaces")) return jsonResponse([ws1, ws2])
      if (url.includes("/teams")) return jsonResponse([team1])
      return jsonResponse(null, 404)
    }
    renderSession()
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("fresh-token"))
    fireEvent.click(screen.getByText("login-short"))
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("short-token"))
    await waitFor(
      () => expect(screen.getByTestId("notif").textContent).toBe("error:refresh failed"),
      { timeout: 5000 }
    )
    expect(screen.getByTestId("token").textContent).toBe("short-token")
  })

  test("clears the session when the refresh timer hits 401", async () => {
    let refreshCalls = 0
    handler = (url) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        refreshCalls++
        return refreshCalls === 1
          ? jsonResponse(refreshPayload)
          : jsonResponse({ detail: "expired" }, 401)
      }
      if (url.endsWith("/api/v1/auth/me")) return jsonResponse(memberMe)
      if (url.endsWith("/api/v1/workspaces")) return jsonResponse([ws1, ws2])
      if (url.includes("/teams")) return jsonResponse([team1])
      return jsonResponse(null, 404)
    }
    renderSession()
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("fresh-token"))
    fireEvent.click(screen.getByText("login-short"))
    await waitFor(() => expect(screen.getByTestId("token").textContent).toBe("short-token"))
    await waitFor(
      () => expect(screen.getByTestId("token").textContent).toBe("null"),
      { timeout: 5000 }
    )
    expect(screen.getByTestId("me").textContent).toBe("null")
    expect(screen.getByTestId("ws").textContent).toBe("null")
  })

  test("useSession throws outside the provider", () => {
    expect(() => renderPage(<SessionProbe />)).toThrow(
      "useSession must be used within a SessionProvider"
    )
  })
})

describe("session helpers", () => {
  test("replaceSessionUser replaces only the current user", () => {
    const me: MeResponse = { user: memberMe.user, memberships: [] }
    const updated = { ...memberMe.user, name: "New" }
    expect(replaceSessionUser(me, updated)).toEqual({ user: updated, memberships: [] })
    expect(replaceSessionUser(me, { ...updated, id: "other" })).toBe(me)
    expect(replaceSessionUser(null, updated)).toBeNull()
  })

  test("addCreatedWorkspaceMembership adds the admin membership once", () => {
    const me: MeResponse = {
      user: memberMe.user,
      memberships: [{ workspace_id: "ws-1", role: "admin" }],
    }
    const payload = { workspace: wsNew, admin_user: memberMe.user }
    expect(addCreatedWorkspaceMembership(me, payload)?.memberships).toContainEqual({
      workspace_id: "ws-new",
      role: "admin",
    })
    expect(addCreatedWorkspaceMembership(null, payload)).toBeNull()
    // already a member of the workspace
    expect(addCreatedWorkspaceMembership(me, { workspace: ws1, admin_user: memberMe.user })).toBe(me)
    // a different admin does not change anything
    expect(
      addCreatedWorkspaceMembership(me, {
        workspace: wsNew,
        admin_user: { ...memberMe.user, id: "other" },
      })
    ).toBe(me)
  })

  test("addCreatedTeamMembership adds the team for the creating admin", () => {
    const me: MeResponse = { user: memberMe.user, memberships: [] }
    const next = addCreatedTeamMembership(me, team2, memberMe.user.id)
    expect(next?.user.teams).toContainEqual({
      id: "team-2",
      workspace_id: "ws-1",
      name: "Team Two",
      is_default: false,
      role: "admin",
    })
    expect(addCreatedTeamMembership(null, team2, memberMe.user.id)).toBeNull()
    expect(addCreatedTeamMembership(me, team2, "someone-else")).toBe(me)
    const withTeam = addCreatedTeamMembership(me, team2, memberMe.user.id)!
    expect(addCreatedTeamMembership(withTeam, team2, memberMe.user.id)).toBe(withTeam)
  })

  test("getInitialWorkspaceId picks the stored then first active membership", () => {
    const workspaces = [ws1, ws2, ws3, ws4]
    expect(getInitialWorkspaceId(memberMe, workspaces, "ws-2")).toBe("ws-2")
    expect(getInitialWorkspaceId(memberMe, workspaces, "ws-99")).toBe("ws-1")
    expect(getInitialWorkspaceId(memberMe, workspaces, null)).toBe("ws-1")
    expect(getInitialWorkspaceId(memberMe, [ws3], null)).toBeNull()
    const globalAdmin: MeResponse = {
      user: { ...memberMe.user, is_global_admin: true },
      memberships: [],
    }
    expect(getInitialWorkspaceId(globalAdmin, [ws1, ws4], "ws-4")).toBe("ws-4")
  })
})

// ---------------------------------------------------------------------------
// LanguageProvider
// ---------------------------------------------------------------------------

function LanguageProbe() {
  const { t, language, setLanguage } = useLanguage()
  return (
    <div>
      <span data-testid="lang">{language}</span>
      <span data-testid="text">{t("保存")}</span>
      <button type="button" onClick={() => setLanguage("en")}>
        to-en
      </button>
      <button type="button" onClick={() => setLanguage("zh-Hant")}>
        to-hant
      </button>
    </div>
  )
}

describe("LanguageProvider", () => {
  test("renders with the default language", () => {
    renderPage(<LanguageProbe />)
    expect(screen.getByTestId("lang").textContent).toBe("zh-Hans")
    expect(screen.getByTestId("text").textContent).toBe("保存")
  })

  test("applies the stored language on mount", async () => {
    localStorage.setItem("nexaflow.language", "en")
    renderPage(<LanguageProbe />)
    await waitFor(() => expect(screen.getByTestId("lang").textContent).toBe("en"))
    expect(screen.getByTestId("text").textContent).toBe("Save")
  })

  test("setLanguage persists and updates the document language", () => {
    renderPage(<LanguageProbe />)
    fireEvent.click(screen.getByText("to-en"))
    expect(screen.getByTestId("lang").textContent).toBe("en")
    expect(screen.getByTestId("text").textContent).toBe("Save")
    expect(localStorage.getItem("nexaflow.language")).toBe("en")
    expect(document.documentElement.lang).toBe("en")
  })

  test("storage events sync the language across tabs", async () => {
    renderPage(<LanguageProbe />)
    fireEvent.click(screen.getByText("to-hant"))
    expect(screen.getByTestId("text").textContent).toBe("儲存")
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "nexaflow.language",
        newValue: "en",
        storageArea: localStorage,
      })
    )
    await waitFor(() => expect(screen.getByTestId("text").textContent).toBe("Save"))
  })

  test("ignores storage events for other keys", () => {
    renderPage(<LanguageProbe />)
    window.dispatchEvent(
      new StorageEvent("storage", { key: "other", newValue: "en", storageArea: localStorage })
    )
    expect(screen.getByTestId("lang").textContent).toBe("zh-Hans")
  })

  test("falls back to the default language for an invalid stored value", async () => {
    renderPage(<LanguageProbe />)
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "nexaflow.language",
        newValue: "klingon",
        storageArea: localStorage,
      })
    )
    await waitFor(() => expect(screen.getByTestId("lang").textContent).toBe("zh-Hans"))
  })

  test("supports a custom storage key", () => {
    render(
      <LanguageProvider defaultLanguage="zh-Hans" storageKey="custom.lang">
        <LanguageProbe />
      </LanguageProvider>
    )
    fireEvent.click(screen.getByText("to-en"))
    expect(localStorage.getItem("custom.lang")).toBe("en")
    expect(localStorage.getItem("nexaflow.language")).toBeNull()
  })

  test("useLanguage throws outside the provider", () => {
    expect(() => render(<LanguageProbe />)).toThrow(
      "useLanguage must be used within a LanguageProvider"
    )
  })
})

// ---------------------------------------------------------------------------
// Top progress
// ---------------------------------------------------------------------------

describe("TopLoadingBar / TopProgress", () => {
  test("TopLoadingBar renders the progress width", () => {
    const { container, rerender } = render(<TopLoadingBar progress={35} />)
    const bar = container.querySelector("div[style]") as HTMLElement | null
    expect(bar?.style.width).toBe("35%")
    expect(container.querySelector(".top-loading-bar-indicator")).toBeTruthy()
    rerender(<TopLoadingBar progress={100} />)
    expect((container.querySelector("div[style]") as HTMLElement).style.width).toBe("100%")
  })

  test("TopProgress animates on navigation and completes", async () => {
    navPathname = "/app/dashboard"
    const { container, rerender } = render(<TopProgress />)
    expect(container.firstChild).toBeNull()

    navPathname = "/app/agents"
    rerender(<TopProgress />)
    await waitFor(() => {
      const bar = container.querySelector("div[style]") as HTMLElement | null
      expect(bar).toBeTruthy()
    })
    await waitFor(() => expect(container.firstChild).toBeNull(), { timeout: 4000 })
  })
})

// ---------------------------------------------------------------------------
// FilterDropdown + DropdownMenu
// ---------------------------------------------------------------------------

describe("FilterDropdown", () => {
  const options = [
    { value: "a", label: "Option A" },
    { value: "b", label: "Option B" },
  ]

  test("shows the selected label and reports changes", async () => {
    let changed: string | null = null
    render(
      <FilterDropdown
        ariaLabel="filter"
        value="a"
        options={options}
        onChange={(value) => {
          changed = value
        }}
      />
    )
    const trigger = screen.getByRole("button", { name: "filter" })
    expect(trigger.textContent).toContain("Option A")
    fireEvent.pointerDown(trigger)
    const menu = await screen.findByRole("menu")
    const itemA = within(menu).getByText("Option A")
    expect(itemA.closest("[data-slot='dropdown-menu-item']")?.querySelector("svg")).toBeTruthy()
    fireEvent.click(within(menu).getByText("Option B"))
    await waitFor(() => expect(changed).toBe("b"))
  })

  test("falls back to the raw value when not in the options", () => {
    render(
      <FilterDropdown ariaLabel="filter2" value="zzz" options={options} onChange={() => {}} />
    )
    expect(screen.getByRole("button", { name: "filter2" }).textContent).toContain("zzz")
  })
})

describe("DropdownMenu primitives", () => {
  test("renders items, labels, separators, and variants", async () => {
    render(
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button">open</button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuGroup>
            <DropdownMenuItem>Plain</DropdownMenuItem>
            <DropdownMenuItem inset variant="destructive">
              Danger
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuLabel inset>Group</DropdownMenuLabel>
          <DropdownMenuSeparator />
        </DropdownMenuContent>
      </DropdownMenu>
    )
    fireEvent.pointerDown(screen.getByText("open"))
    const menu = await screen.findByRole("menu")
    const danger = within(menu).getByText("Danger").closest("[data-slot='dropdown-menu-item']")!
    expect(danger.getAttribute("data-variant")).toBe("destructive")
    expect(danger.getAttribute("data-inset")).toBe("true")
    expect(within(menu).getByText("Plain").closest("[data-slot='dropdown-menu-item']")?.getAttribute("data-variant")).toBe("default")
    const label = within(menu).getByText("Group").closest("[data-slot='dropdown-menu-label']")!
    expect(label.getAttribute("data-inset")).toBe("true")
    expect(menu.querySelector("[data-slot='dropdown-menu-separator']")).toBeTruthy()
  })

  test("wheel capture scrolls the content and respects overflow", async () => {
    const onWheel = mock<ReactWheelEventHandler>()
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger asChild>
          <button type="button">t</button>
        </DropdownMenuTrigger>
        <DropdownMenuContent onWheelCapture={onWheel}>
          <div style={{ height: 300 }}>content</div>
        </DropdownMenuContent>
      </DropdownMenu>
    )
    const content = (await screen.findByRole("menu")) as HTMLElement
    Object.defineProperty(content, "scrollHeight", { value: 300, configurable: true })
    Object.defineProperty(content, "clientHeight", { value: 100, configurable: true })
    content.scrollTop = 0
    const ev1 = new WheelEvent("wheel", { deltaY: 30, bubbles: true, cancelable: true })
    content.dispatchEvent(ev1)
    expect(ev1.defaultPrevented).toBe(true)
    expect(content.scrollTop).toBe(30)
    expect(onWheel).toHaveBeenCalled()

    // already at the bottom: nothing scrolls, nothing is prevented
    content.scrollTop = 200
    const ev2 = new WheelEvent("wheel", { deltaY: 30, bubbles: true, cancelable: true })
    content.dispatchEvent(ev2)
    expect(ev2.defaultPrevented).toBe(false)

    // not scrollable at all
    Object.defineProperty(content, "scrollHeight", { value: 100, configurable: true })
    content.scrollTop = 0
    const ev3 = new WheelEvent("wheel", { deltaY: 30, bubbles: true, cancelable: true })
    content.dispatchEvent(ev3)
    expect(ev3.defaultPrevented).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------

describe("Dialog primitives", () => {
  test("renders content, header, footer, title and description", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm</DialogTitle>
            <DialogDescription>Are you sure?</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button type="button">OK</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
    expect(screen.getByRole("dialog")).toBeTruthy()
    expect(screen.getByText("Confirm")).toBeTruthy()
    expect(screen.getByText("Are you sure?")).toBeTruthy()
    expect(screen.getByText("OK")).toBeTruthy()
  })

  test("renders the right-side variant", () => {
    render(
      <Dialog open>
        <DialogContent side="right">panel</DialogContent>
      </Dialog>
    )
    const content = document.querySelector("[data-slot='dialog-content']")!
    expect(content.className).toContain("right-0")
    expect(content.className).toContain("sm:max-w-lg")
  })

  test("does not render content while closed", () => {
    render(
      <Dialog open={false}>
        <DialogContent>hidden</DialogContent>
      </Dialog>
    )
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("escape closes the dialog through onOpenChange", async () => {
    const onOpenChange = mock<(open: boolean) => void>()
    render(
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent>panel</DialogContent>
      </Dialog>
    )
    expect(screen.getByRole("dialog")).toBeTruthy()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })
})

// ---------------------------------------------------------------------------
// Badge and Field
// ---------------------------------------------------------------------------

describe("Badge", () => {
  test("renders every variant and merges class names", () => {
    render(
      <>
        <Badge>D</Badge>
        <Badge variant="secondary">S</Badge>
        <Badge variant="outline">O</Badge>
        <Badge variant="destructive">X</Badge>
        <Badge className="custom-cls">C</Badge>
      </>
    )
    const badges = document.querySelectorAll("[data-slot='badge']")
    expect(badges).toHaveLength(5)
    expect(badges[0].textContent).toBe("D")
    expect(badges[0].className).toContain("bg-primary")
    expect(badges[1].className).toContain("bg-secondary")
    expect(badges[2].className).toContain("text-foreground")
    expect(badges[3].className).toContain("text-destructive")
    expect(badges[4].className).toContain("custom-cls")
    expect(badgeVariants()).toContain("inline-flex")
    expect(badgeVariants({ variant: "outline" })).toContain("text-foreground")
  })
})

describe("Field primitives", () => {
  test("renders group, field, label and description", () => {
    render(
      <FieldGroup className="g-cls">
        <Field className="f-cls">
          <FieldLabel htmlFor="x">Name</FieldLabel>
          <FieldDescription>hint</FieldDescription>
        </Field>
      </FieldGroup>
    )
    expect(document.querySelector("[data-slot='field-group']")!.className).toContain("g-cls")
    const field = document.querySelector("[data-slot='field']")!
    expect(field.className).toContain("f-cls")
    expect(field.className).toContain("gap-2")
    expect(document.querySelector("[data-slot='field-label']")!.getAttribute("for")).toBe("x")
    expect(document.querySelector("[data-slot='field-description']")!.textContent).toBe("hint")
  })
})

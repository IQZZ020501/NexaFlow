/* @jsxImportSource react */
/**
 * DOM-level coverage for MCP forms, system API clients,
 * and the system display helpers.
 *
 * Session is mocked (mutating the shared mock session object per test);
 * all backend traffic goes through globalThis.fetch stubbed by withFetch.
 */
import { beforeEach, describe, expect, test } from "bun:test"
import { act } from "react"

import { buildMcpServerCreatePayload, type McpForm } from "@/components/tools/mcp-form"
import { SystemShell } from "@/components/system/system-shell"
import { LanguageProvider } from "@/contexts/language-provider"
import {
  canManageTeamMembers,
  formatAuditDetails,
  formatUserTeams,
  formatUserWorkspaces,
  getUserRoleClass,
  getUserRoleKey,
  getUserRoleLabel,
} from "@/components/system/system-utils"
import type { MeResponse, User } from "@/lib/api/auth"
import {
  addWorkspaceMember,
  addTeamMember,
  changeUserPassword,
  createTeam,
  createUser,
  createWorkspace,
  createWorkspaceUser,
  deleteTeam,
  deleteUser,
  deleteWorkspace,
  listAuditLogsPage,
  listAllWorkspaceMembers,
  listTeams,
  listTeamMembers,
  listUsers,
  listWorkspaceAuditLogsPage,
  listWorkspaceMembers,
  listWorkspaces,
  removeTeamMember,
  removeWorkspaceMember,
  updateTeam,
  updateTeamMember,
  updateUser,
  updateWorkspace,
  updateWorkspaceMember,
  type AuditLog,
  type Team,
  type Workspace,
} from "@/lib/api/system"
import { translate, type TFunction } from "@/i18n"
import {
  fireEvent,
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  type FetchHandler,
} from "./helpers/dom"

// ---------------------------------------------------------------------------
// Shared session mock (mutated per test) and fetch dispatcher.
// ---------------------------------------------------------------------------

const session = makeSession()
mockUseSession(session)
mockNextNavigation()

// makeSession types these fields as non-null/no-arg; the mock's useSession
// returns the same object, so mutations through this wider view are observed.
const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  selectedWorkspaceId: string | null
  workspaces: Workspace[]
  notify: (kind: "success" | "error", message: string) => void
}

let handler: FetchHandler = () => jsonResponse([], 200)

// withFetch's afterEach restores the original fetch after each test, so the
// stub must be re-installed before every test instead.
beforeEach(() => {
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

const adminUser: User = {
  id: "u-1",
  username: "admin",
  email: "admin@app.local",
  name: "NexaFlow Admin",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [],
  teams: [],
}

const adminMe: MeResponse = { user: adminUser, memberships: [] }

function setSession(overrides: {
  me?: MeResponse | null
  token?: string | null
  selectedWorkspaceId?: string | null
} = {}) {
  sessionState.me = overrides.me === undefined ? adminMe : overrides.me
  sessionState.token = overrides.token === undefined ? "test-token" : overrides.token
  sessionState.selectedWorkspaceId =
    overrides.selectedWorkspaceId === undefined ? "ws-1" : overrides.selectedWorkspaceId
}

beforeEach(() => {
  handler = () => jsonResponse([], 200)
})

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const user: User = {
  id: "u-1",
  username: "alice",
  email: "alice@app.local",
  name: "Alice",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [],
  teams: [],
}

const workspace: Workspace = {
  id: "w-1",
  name: "Workspace One",
  description: "desc",
  status: "active",
  is_default: true,
}

const team: Team = {
  id: "t-1",
  workspace_id: "w-1",
  name: "Team One",
  description: "",
  status: "active",
  is_default: false,
}

const auditLog: AuditLog = {
  id: "a-1",
  actor_user_id: "u-1",
  actor_username: "alice",
  actor_name: "Alice",
  workspace_id: "w-1",
  action: "workspace.create",
  resource_type: "workspace",
  resource_id: "w-2",
  resource_name: "W2",
  details: { email: "x@app.local" },
  created_at: "2026-08-02T00:00:00Z",
}

// ---------------------------------------------------------------------------
// MCP create payload builders
// ---------------------------------------------------------------------------

describe("MCP create payloads", () => {
  function form(overrides: Partial<McpForm> = {}): McpForm {
    return {
      name: "Tools",
      transport: "streamable_http",
      url: "https://mcp.example.com/mcp",
      bearerToken: "tok",
      stdioConfig: "",
      ...overrides,
    }
  }

  test("remote transports carry the URL and optional bearer token", () => {
    expect(buildMcpServerCreatePayload(form())).toEqual({
      name: "Tools",
      transport: "streamable_http",
      url: "https://mcp.example.com/mcp",
      bearer_token: "tok",
    })
    expect(
      buildMcpServerCreatePayload(form({ transport: "sse", bearerToken: "   " }))
    ).toEqual({
      name: "Tools",
      transport: "sse",
      url: "https://mcp.example.com/mcp",
    })
  })

  test("stdio payload requires a valid JSON config", () => {
    expect(
      buildMcpServerCreatePayload(
        form({
          transport: "stdio",
          stdioConfig: JSON.stringify({
            command: "node",
            args: ["a"],
            cwd: "/srv",
            env: { K: "v" },
            transport: "stdio",
          }),
        })
      )
    ).toEqual({
      name: "Tools",
      transport: "stdio",
      stdio_config: { command: "node", args: ["a"], cwd: "/srv", env: { K: "v" } },
    })
    // blank cwd is dropped
    expect(
      buildMcpServerCreatePayload(
        form({ transport: "stdio", stdioConfig: JSON.stringify({ command: "node", args: [], env: {} }) })
      )
    ).toEqual({ name: "Tools", transport: "stdio", stdio_config: { command: "node", args: [], env: {} } })
  })

  test("invalid payloads are rejected", () => {
    const stdio = (config: string) => form({ transport: "stdio", stdioConfig: config })
    expect(buildMcpServerCreatePayload(form({ name: "   " }))).toBeNull()
    expect(buildMcpServerCreatePayload(form({ url: "   " }))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(""))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio("not json"))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify([])))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify("str")))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", unknown_key: 1 })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", transport: "sse" })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "", args: [] })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: 42, args: [] })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: "nope" })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: [1] })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: ["ok"], cwd: 42 })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: [], env: [1] })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: [], env: { "1bad": "v" } })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: [], env: { K: 1 } })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: [], env: { K: "v".repeat(8001) } })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x".repeat(1001), args: [] })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: ["a".repeat(2001)] })))).toBeNull()
    const manyArgs = Array.from({ length: 65 }, (_, i) => `a${i}`)
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: manyArgs })))).toBeNull()
    const manyEnv: Record<string, string> = {}
    for (let i = 0; i < 33; i++) manyEnv[`K${i}`] = "v"
    expect(buildMcpServerCreatePayload(stdio(JSON.stringify({ command: "x", args: [], env: manyEnv })))).toBeNull()
    expect(buildMcpServerCreatePayload(stdio("x".repeat(65_537)))).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// system API client
// ---------------------------------------------------------------------------

describe("system API client", () => {
  function recordRequests(respond: (url: string, init?: RequestInit) => Response) {
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      return respond(url, init)
    }
    return calls
  }

  test("user admin endpoints", async () => {
    const calls = recordRequests((url, init) => {
      if (init?.method === "DELETE") return jsonResponse(null, 204)
      if (url.endsWith("/change-password")) return jsonResponse(user)
      if (init?.method === "POST") return jsonResponse({ user, initial_password: "NexaFlow@123.." })
      if (init?.method === "PATCH") return jsonResponse(user)
      return jsonResponse([user])
    })

    await expect(listUsers("tok")).resolves.toEqual([user])
    await expect(
      createUser("tok", { username: "bob", email: "b@app.local", name: "Bob", workspace_id: "w-1", team_ids: ["t-1"] })
    ).resolves.toEqual({ user, initial_password: "NexaFlow@123.." })
    await updateUser("tok", "u-1", { name: "Alice 2", is_active: false })
    await changeUserPassword("tok", "u-1", "new-pass")
    await deleteUser("tok", "u-1")

    expect(calls.map((c) => [c.url, c.init?.method])).toEqual([
      ["/api/v1/admin/users", undefined],
      ["/api/v1/admin/users", "POST"],
      ["/api/v1/admin/users/u-1", "PATCH"],
      ["/api/v1/admin/users/u-1/change-password", "POST"],
      ["/api/v1/admin/users/u-1", "DELETE"],
    ])
    expect(JSON.parse(calls[1].init!.body as string)).toEqual({
      username: "bob",
      email: "b@app.local",
      name: "Bob",
      workspace_id: "w-1",
      team_ids: ["t-1"],
    })
    expect(JSON.parse(calls[2].init!.body as string)).toEqual({ name: "Alice 2", is_active: false })
    expect(JSON.parse(calls[3].init!.body as string)).toEqual({ new_password: "new-pass" })
    expect(new Headers(calls[0].init?.headers).get("Authorization")).toBe("Bearer tok")
  })

  test("workspace and team endpoints", async () => {
    const calls = recordRequests((url, init) => {
      const method = init?.method
      if (method === "DELETE") return jsonResponse(null, 204)
      if (url.endsWith("/members/users")) return jsonResponse({ user, initial_password: "pw" })
      if (url.includes("/members") && method === "POST") return jsonResponse({ user, role: "member" })
      if (url.includes("/members") && method === "PATCH") return jsonResponse({ user, role: "admin" })
      if (url.includes("/members")) return jsonResponse([{ user, role: "member" }])
      if (url.includes("/teams") && method === "POST") return jsonResponse(team)
      if (url.includes("/teams") && method === "PATCH") return jsonResponse(team)
      if (url.includes("/teams")) return jsonResponse([team])
      if (url.includes("/workspaces") && method === "POST") return jsonResponse({ workspace, admin_user: user })
      if (url.includes("/workspaces") && method === "PATCH") return jsonResponse(workspace)
      return jsonResponse([workspace])
    })

    await listWorkspaces("tok")
    await createWorkspace("tok", { name: "W", description: "d", admin_user_id: "u-1" })
    await updateWorkspace("tok", "w-1", { name: "W2" })
    await deleteWorkspace("tok", "w-1")
    await listWorkspaceMembers("tok", "w-1")
    await addWorkspaceMember("tok", "w-1", { user_id: "u-2", role: "member" })
    await createWorkspaceUser("tok", "w-1", { username: "c", email: "c@a.co", name: "C" })
    await updateWorkspaceMember("tok", "w-1", "u-2", { role: "admin" })
    await removeWorkspaceMember("tok", "w-1", "u-2")
    await listTeams("tok", "w-1")
    await createTeam("tok", "w-1", { name: "T", description: "", admin_user_id: "u-1" })
    await updateTeam("tok", "w-1", "t-1", { name: "T2" })
    await deleteTeam("tok", "w-1", "t-1")
    await listTeamMembers("tok", "w-1", "t-1")
    await addTeamMember("tok", "w-1", "t-1", { user_id: "u-2" })
    await updateTeamMember("tok", "w-1", "t-1", "u-2", { role: "admin" })
    await removeTeamMember("tok", "w-1", "t-1", "u-2")

    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/workspaces",
      "/api/v1/workspaces",
      "/api/v1/workspaces/w-1",
      "/api/v1/workspaces/w-1",
      "/api/v1/workspaces/w-1/members?limit=200&offset=0",
      "/api/v1/workspaces/w-1/members",
      "/api/v1/workspaces/w-1/members/users",
      "/api/v1/workspaces/w-1/members/u-2",
      "/api/v1/workspaces/w-1/members/u-2",
      "/api/v1/workspaces/w-1/teams",
      "/api/v1/workspaces/w-1/teams",
      "/api/v1/workspaces/w-1/teams/t-1",
      "/api/v1/workspaces/w-1/teams/t-1",
      "/api/v1/workspaces/w-1/teams/t-1/members?limit=200&offset=0",
      "/api/v1/workspaces/w-1/teams/t-1/members",
      "/api/v1/workspaces/w-1/teams/t-1/members/u-2",
      "/api/v1/workspaces/w-1/teams/t-1/members/u-2",
    ])
    expect(calls.map((c) => c.init?.method)).toEqual([
      undefined, "POST", "PATCH", "DELETE", undefined, "POST", "POST", "PATCH", "DELETE",
      undefined, "POST", "PATCH", "DELETE", undefined, "POST", "PATCH", "DELETE",
    ])
    expect(JSON.parse(calls[1].init!.body as string)).toEqual({ name: "W", description: "d", admin_user_id: "u-1" })
    expect(JSON.parse(calls[2].init!.body as string)).toEqual({ name: "W2" })
    expect(JSON.parse(calls[5].init!.body as string)).toEqual({ user_id: "u-2", role: "member" })
    expect(JSON.parse(calls[6].init!.body as string)).toEqual({ username: "c", email: "c@a.co", name: "C" })
    expect(JSON.parse(calls[7].init!.body as string)).toEqual({ role: "admin" })
    expect(JSON.parse(calls[10].init!.body as string)).toEqual({ name: "T", description: "", admin_user_id: "u-1" })
    expect(JSON.parse(calls[11].init!.body as string)).toEqual({ name: "T2" })
    expect(JSON.parse(calls[14].init!.body as string)).toEqual({ user_id: "u-2" })
    expect(JSON.parse(calls[15].init!.body as string)).toEqual({ role: "admin" })
  })

  test("member list pagination parameters", async () => {
    const calls = recordRequests(() => jsonResponse([]))
    await listWorkspaceMembers("tok", "w-1", 10, 5)
    await listTeamMembers("tok", "w-1", "t-1", 20, 0)
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/workspaces/w-1/members?limit=10&offset=5",
      "/api/v1/workspaces/w-1/teams/t-1/members?limit=20&offset=0",
    ])
  })

  test("loads every workspace member page", async () => {
    const calls = recordRequests((url) => {
      const offset = new URL(url, "http://localhost").searchParams.get("offset")
      return jsonResponse(
        offset === "0"
          ? Array.from({ length: 200 }, (_, index) => ({
              user: { ...user, id: `u-${index}` },
              role: "member",
            }))
          : [{ user, role: "admin" }]
      )
    })

    await expect(listAllWorkspaceMembers("tok", "w-1")).resolves.toHaveLength(
      201
    )
    expect(calls.map((call) => call.url)).toEqual([
      "/api/v1/workspaces/w-1/members?limit=200&offset=0",
      "/api/v1/workspaces/w-1/members?limit=200&offset=200",
    ])
  })

  test("audit log endpoints", async () => {
    const calls = recordRequests(() => jsonResponse([auditLog]))
    await expect(listAuditLogsPage("tok")).resolves.toMatchObject({ items: [auditLog] })
    await expect(listWorkspaceAuditLogsPage("tok", "w-1")).resolves.toMatchObject({ items: [auditLog] })
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/admin/audit-logs",
      "/api/v1/workspaces/w-1/audit-logs",
    ])
  })

  test("request surfaces API error details", async () => {
    handler = (url) => {
      if (url === "/api/v1/admin/audit-logs") return jsonResponse({ detail: "forbidden" }, 403)
      if (url === "/api/v1/workspaces") return jsonResponse({ detail: [{ msg: "name required" }, "raw item"] }, 422)
      return new Response("boom text", { status: 500 })
    }
    await expect(listAuditLogsPage("tok")).rejects.toThrow("forbidden")
    await expect(listWorkspaces("tok")).rejects.toThrow("name required; raw item")
    // A non-JSON error body fails while parsing the payload.
    await expect(listTeams("tok", "w-1")).rejects.toThrow(/boom/)
  })
})

describe("SystemShell audit loading", () => {
  test("debounces search and ignores an older response", async () => {
    setSession()
    const searches: string[] = []
    let resolveOldSearch: (response: Response) => void = () => undefined
    handler = (url) => {
      const parsed = new URL(url, "http://localhost")
      if (parsed.pathname !== "/api/v1/admin/audit-logs") {
        return jsonResponse([])
      }
      const search = parsed.searchParams.get("search") ?? ""
      searches.push(search)
      if (search === "old") {
        return new Promise<Response>((resolve) => {
          resolveOldSearch = resolve
        })
      }
      if (search === "new") {
        return jsonResponse([
          { ...auditLog, id: "audit-new", resource_name: "Newest result" },
        ])
      }
      return jsonResponse([])
    }

    renderPage(<SystemShell activeTab="audit" />)
    const searchInput = await screen.findByLabelText("搜索审计")
    fireEvent.change(searchInput, { target: { value: "o" } })
    fireEvent.change(searchInput, { target: { value: "ol" } })
    fireEvent.change(searchInput, { target: { value: "old" } })
    await waitFor(() => expect(searches).toContain("old"))
    expect(searches).not.toContain("o")
    expect(searches).not.toContain("ol")

    fireEvent.change(searchInput, { target: { value: "new" } })
    await waitFor(() => expect(screen.getByText("Newest result")).toBeTruthy())
    await act(async () => {
      resolveOldSearch(
        jsonResponse([
          { ...auditLog, id: "audit-old", resource_name: "Stale result" },
        ])
      )
    })

    expect(screen.queryByText("Stale result")).toBeNull()
    expect(screen.getByText("Newest result")).toBeTruthy()
  })

  test("resets pagination on refresh and workspace changes", async () => {
    const workspaceOne = { ...workspace, id: "ws-1", name: "Workspace One" }
    const workspaceTwo = { ...workspace, id: "ws-2", name: "Workspace Two" }
    const workspaceAdmin: MeResponse = {
      user: {
        ...adminUser,
        is_global_admin: false,
        workspaces: [
          { id: "ws-1", name: "Workspace One", is_default: true, role: "admin" },
          { id: "ws-2", name: "Workspace Two", is_default: false, role: "admin" },
        ],
      },
      memberships: [
        { workspace_id: "ws-1", role: "admin" },
        { workspace_id: "ws-2", role: "admin" },
      ],
    }
    setSession({ me: workspaceAdmin, selectedWorkspaceId: "ws-1" })
    sessionState.workspaces = [workspaceOne, workspaceTwo]
    const requests: string[] = []
    handler = (url) => {
      const parsed = new URL(url, "http://localhost")
      const offset = parsed.searchParams.get("offset") ?? "0"
      requests.push(`${parsed.pathname}?offset=${offset}`)
      if (parsed.pathname.endsWith("/ws-2/audit-logs")) {
        return new Response(
          JSON.stringify([
            { ...auditLog, id: "ws-2-page-1", resource_name: "Workspace two page one" },
          ]),
          {
            headers: { "Content-Type": "application/json", "X-Total-Count": "1" },
          }
        )
      }
      if (offset === "20") {
        return new Response(
          JSON.stringify([
            { ...auditLog, id: "ws-1-page-2", resource_name: "Workspace one page two" },
          ]),
          {
            headers: { "Content-Type": "application/json", "X-Total-Count": "21" },
          }
        )
      }
      return new Response(
        JSON.stringify(
          Array.from({ length: 20 }, (_, index) => ({
            ...auditLog,
            id: `ws-1-page-1-${index}`,
            resource_name: `Workspace one page one ${index}`,
          }))
        ),
        {
          headers: { "Content-Type": "application/json", "X-Total-Count": "21" },
        }
      )
    }

    const view = renderPage(<SystemShell activeTab="audit" />)
    await screen.findByText("Workspace one page one 0")
    fireEvent.click(screen.getByRole("button", { name: "下一页" }))
    await screen.findByText("Workspace one page two")

    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    await waitFor(() => expect(screen.queryByText("Workspace one page two")).toBeNull())
    expect(
      requests.filter((request) => request === "/api/v1/workspaces/ws-1/audit-logs?offset=0")
    ).toHaveLength(2)

    fireEvent.click(screen.getByRole("button", { name: "下一页" }))
    await screen.findByText("Workspace one page two")
    sessionState.selectedWorkspaceId = "ws-2"
    view.rerender(
      <LanguageProvider defaultLanguage="zh-Hans">
        <SystemShell activeTab="audit" />
      </LanguageProvider>
    )

    await screen.findByText("Workspace two page one")
    expect(screen.queryByText("Workspace one page two")).toBeNull()
    expect(requests).toContain("/api/v1/workspaces/ws-2/audit-logs?offset=0")
    expect(requests).not.toContain("/api/v1/workspaces/ws-2/audit-logs?offset=100")
  })
})

// ---------------------------------------------------------------------------
// system-utils display helpers
// ---------------------------------------------------------------------------

describe("system-utils", () => {
  const t: TFunction = (key, values) => translate("zh-Hans", key, values)

  const baseUser: User = {
    id: "u-1",
    username: "u",
    email: "u@a.co",
    name: "U",
    is_global_admin: false,
    must_change_password: false,
    is_active: true,
    created_at: "2026-08-01T00:00:00Z",
    workspaces: [],
    teams: [],
  }

  const team1: Team = {
    id: "t-1",
    workspace_id: "w-1",
    name: "T1",
    description: "",
    status: "active",
    is_default: false,
  }

  test("canManageTeamMembers follows the hierarchy", () => {
    const globalAdmin: MeResponse = { user: { ...baseUser, is_global_admin: true }, memberships: [] }
    const wsAdmin: MeResponse = {
      user: { ...baseUser, workspaces: [{ id: "w-1", name: "W1", is_default: false, role: "admin" }] },
      memberships: [],
    }
    const teamAdmin: MeResponse = {
      user: { ...baseUser, teams: [{ id: "t-1", workspace_id: "w-1", name: "T1", is_default: false, role: "admin" }] },
      memberships: [],
    }
    const none: MeResponse = { user: baseUser, memberships: [] }
    expect(canManageTeamMembers(globalAdmin, team1)).toBe(true)
    expect(canManageTeamMembers(wsAdmin, team1)).toBe(true)
    expect(canManageTeamMembers(teamAdmin, team1)).toBe(true)
    expect(canManageTeamMembers(none, team1)).toBe(false)
  })

  test("formatUserWorkspaces joins display names", () => {
    expect(formatUserWorkspaces({ ...baseUser, workspaces: [] }, t)).toBe("-")
    expect(
      formatUserWorkspaces(
        {
          ...baseUser,
          workspaces: [
            { id: "w-1", name: "Default Workspace", is_default: true, role: "admin" },
            { id: "w-2", name: "Custom", is_default: false, role: "member" },
          ],
        },
        t
      )
    ).toBe("默认工作空间、Custom")
  })

  test("formatUserTeams joins display names", () => {
    expect(formatUserTeams({ ...baseUser, teams: [] }, t)).toBe("-")
    expect(
      formatUserTeams(
        {
          ...baseUser,
          teams: [
            { id: "t-1", workspace_id: "w-1", name: "Default Team", is_default: true, role: "admin" },
            { id: "t-2", workspace_id: "w-1", name: "Team B", is_default: false, role: "member" },
          ],
        },
        t
      )
    ).toBe("默认团队、Team B")
  })

  test("getUserRoleLabel and getUserRoleKey rank roles", () => {
    const globalAdmin = { ...baseUser, is_global_admin: true }
    const wsAdmin = { ...baseUser, workspaces: [{ id: "w-1", name: "W1", is_default: false, role: "admin" }] }
    const teamAdmin = {
      ...baseUser,
      teams: [{ id: "t-1", workspace_id: "w-1", name: "T1", is_default: false, role: "admin" }],
    }
    expect(getUserRoleLabel(globalAdmin, t)).toBe("全局管理员")
    expect(getUserRoleLabel(wsAdmin, t)).toBe("工作空间管理员")
    expect(getUserRoleLabel(teamAdmin, t)).toBe("团队管理员")
    expect(getUserRoleLabel(baseUser, t)).toBe("普通用户")
    expect(getUserRoleKey(globalAdmin)).toBe("global_admin")
    expect(getUserRoleKey(wsAdmin)).toBe("workspace_admin")
    expect(getUserRoleKey(teamAdmin)).toBe("team_admin")
    expect(getUserRoleKey(baseUser)).toBe("member")
  })

  test("getUserRoleClass styles by role", () => {
    expect(getUserRoleClass({ ...baseUser, is_global_admin: true })).toContain("text-amber-700")
    expect(
      getUserRoleClass({
        ...baseUser,
        workspaces: [{ id: "w-1", name: "W1", is_default: false, role: "admin" }],
      })
    ).toContain("text-amber-700")
    expect(
      getUserRoleClass({
        ...baseUser,
        teams: [{ id: "t-1", workspace_id: "w-1", name: "T1", is_default: false, role: "admin" }],
      })
    ).toContain("text-red-600")
    expect(getUserRoleClass(baseUser)).toContain("text-muted-foreground")
  })

  test("formatAuditDetails renders labeled, filtered values", () => {
    expect(formatAuditDetails({}, t)).toBe("-")
    expect(formatAuditDetails({ email: "", is_active: null, name: undefined }, t)).toBe("-")
    expect(formatAuditDetails({ email: "a@b.co" }, t)).toBe("邮箱: a@b.co")
    expect(formatAuditDetails({ status: "active" }, t)).toBe("状态: 已启用")
    expect(formatAuditDetails({ status: "weird" }, t)).toBe("状态: weird")
    expect(formatAuditDetails({ is_active: true, is_global_admin: false }, t)).toBe(
      "启用状态: 是；全局管理员: 否"
    )
    expect(formatAuditDetails({ roles: ["a", "b"], flags: [true, false] }, t)).toBe(
      "其他字段: a、b；其他字段: 是、否"
    )
    expect(formatAuditDetails({ slug_x: "v" }, t)).toBe("其他字段: v")
  })
})

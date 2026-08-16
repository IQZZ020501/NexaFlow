/* @jsxImportSource react */
/**
 * DOM-level coverage for the MCP tools page, the MCP/system API clients,
 * and the system display helpers.
 *
 * Session is mocked (mutating the shared mock session object per test);
 * all backend traffic goes through globalThis.fetch stubbed by withFetch.
 */
import { beforeEach, describe, expect, test } from "bun:test"

import { McpToolsPage, buildMcpServerCreatePayload, type McpForm } from "@/components/tools/mcp-tools-page"
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
import type { McpServer } from "@/lib/api/mcp"
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
  listAuditLogs,
  listTeams,
  listTeamMembers,
  listUsers,
  listWorkspaceAuditLogs,
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
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  within,
  type FetchHandler,
} from "./helpers/dom"

// ---------------------------------------------------------------------------
// Shared session mock (mutated per test) and fetch dispatcher.
// ---------------------------------------------------------------------------

const session = makeSession()
mockUseSession(session)

// makeSession types these fields as non-null/no-arg; the mock's useSession
// returns the same object, so mutations through this wider view are observed.
const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  selectedWorkspaceId: string | null
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

const memberMe: MeResponse = {
  user: { ...adminUser, id: "u-2", username: "member", name: "Member", is_global_admin: false },
  memberships: [{ workspace_id: "ws-1", role: "member" }],
}

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

function withNotifySpy() {
  const calls: Array<[string, string]> = []
  sessionState.notify = (kind, message) => {
    calls.push([kind, message])
  }
  return calls
}

async function chooseDropdownOption(trigger: HTMLElement, label: string) {
  fireEvent.pointerDown(trigger)
  fireEvent.click(within(await screen.findByRole("menu")).getByText(label))
}

async function respondToConfirm(label: string) {
  const dialog = await screen.findByRole("dialog", { name: "确认操作" })
  fireEvent.click(within(dialog).getByRole("button", { name: label }))
}

beforeEach(() => {
  handler = () => jsonResponse([], 200)
})

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function mcpServer(overrides: Partial<McpServer> = {}): McpServer {
  return {
    id: "mcp-1",
    workspace_id: "ws-1",
    name: "Release tools",
    transport: "streamable_http",
    url: "https://mcp.example.com/mcp",
    stdio_command: null,
    tools: [
      {
        name: "web_search",
        description: "Search the web",
        input_schema: {},
        annotations: null,
        definition_hash: "h1",
        policy_mode: "approval_required",
      },
      {
        name: "no_desc",
        description: "",
        input_schema: {},
        annotations: null,
        definition_hash: "h2",
        policy_mode: "disabled",
      },
    ],
    status: "active",
    has_bearer_token: true,
    bearer_token_hint: "tav…",
    last_error: null,
    created_by_user_id: "u-1",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }
}

const stdioServer = mcpServer({
  id: "mcp-stdio",
  name: "Local tools",
  transport: "stdio",
  url: null,
  stdio_command: "/usr/local/bin/node server.js",
  has_bearer_token: false,
  bearer_token_hint: null,
  last_error: "connection reset by peer",
  tools: [
    {
      name: "local_tool",
      description: "Runs locally",
      input_schema: {},
      annotations: null,
      definition_hash: "h3",
      policy_mode: "read_only",
    },
  ],
})

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

// Controllable IntersectionObserver so the infinite-scroll hook can be
// triggered deterministically from the test.
let ioTrigger: ((entries: IntersectionObserverEntry[]) => void) | null = null
class FakeIntersectionObserver {
  root: Element | null = null
  rootMargin = ""
  thresholds: ReadonlyArray<number> = []
  constructor(callback: (entries: IntersectionObserverEntry[]) => void) {
    ioTrigger = callback
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}
;(globalThis as { IntersectionObserver: unknown }).IntersectionObserver =
  FakeIntersectionObserver

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
// McpToolsPage rendering and interactions
// ---------------------------------------------------------------------------

describe("McpToolsPage", () => {
  test("returns nothing without a session token or user", () => {
    setSession({ token: null })
    const { container } = renderPage(<McpToolsPage />)
    expect(container.firstChild).toBeNull()

    setSession({ token: null, me: null })
    const { container: container2 } = renderPage(<McpToolsPage />)
    expect(container2.firstChild).toBeNull()
  })

  test("shows a loading state while fetching servers", async () => {
    setSession()
    let resolveList!: (response: Response) => void
    handler = () =>
      new Promise<Response>((resolve) => {
        resolveList = resolve
      })
    renderPage(<McpToolsPage />)
    expect(screen.getByText("正在加载")).toBeTruthy()
    resolveList(jsonResponse([mcpServer()]))
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
  })

  test("lists servers with tools, badges and details", async () => {
    setSession()
    handler = () => jsonResponse([mcpServer(), stdioServer])
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    expect(screen.getAllByText("2 个工具").length).toBe(1)
    expect(screen.getByText("1 个工具")).toBeTruthy()
    expect(screen.getByText("Streamable HTTP")).toBeTruthy()
    expect(screen.getByText("tav…")).toBeTruthy()
    expect(screen.getByText("stdio 命令：/usr/local/bin/node server.js")).toBeTruthy()
    expect(screen.getByText("connection reset by peer")).toBeTruthy()
    // two servers, no more pages
    expect(screen.getByText("已加载全部")).toBeTruthy()
    // open tool list details
    fireEvent.click(screen.getAllByText("查看工具列表")[0])
    expect(screen.getByText("web_search")).toBeTruthy()
    expect(screen.getByText("Search the web")).toBeTruthy()
    const selects = screen.getAllByLabelText("工具执行策略")
    expect(selects).toHaveLength(3)
    expect(selects[0].textContent).toContain("每次调用前审批")
    expect(selects[1].textContent).toContain("禁用")
    expect(selects[2].textContent).toContain("只读自动执行")
  })

  test("renders an empty state and hides actions for non-admins", async () => {
    setSession({ me: memberMe })
    handler = () => jsonResponse([])
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    expect(screen.getByText("只有空间管理员可以添加、刷新或删除 MCP Server。")).toBeTruthy()
    expect(screen.queryAllByRole("button", { name: "添加 MCP Server" })).toHaveLength(0)
  })

  test("non-admins see a read-only policy badge and no manage buttons", async () => {
    setSession({ me: memberMe })
    handler = () => jsonResponse([mcpServer()])
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    expect(screen.queryByLabelText("刷新工具")).toBeNull()
    expect(screen.queryByLabelText("删除 MCP Server")).toBeNull()
    expect(screen.getByText("每次调用前审批")).toBeTruthy()
    expect(screen.getByText("禁用")).toBeTruthy()
    expect(screen.queryByLabelText("工具执行策略")).toBeNull()
  })

  test("reports list errors through notifications", async () => {
    setSession()
    const notifications = withNotifySpy()
    handler = () => jsonResponse({ detail: "unreachable" }, 502)
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    expect(notifications).toEqual([["error", "unreachable"]])
  })

  test("loads more servers when the end sentinel intersects", async () => {
    setSession()
    const batch1 = Array.from({ length: 50 }, (_, i) =>
      mcpServer({ id: `mcp-${i}`, name: `Server ${i}` })
    )
    const batch2 = Array.from({ length: 5 }, (_, i) =>
      mcpServer({ id: `more-${i}`, name: `More ${i}` })
    )
    let resolveMore!: (response: Response) => void
    handler = (url) => {
      if (url.includes("offset=50")) {
        return new Promise<Response>((resolve) => {
          resolveMore = resolve
        })
      }
      if (url.includes("/mcp-servers")) return jsonResponse(batch1)
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Server 0")).toBeTruthy())
    expect(screen.queryByText("More 0")).toBeNull()
    ioTrigger?.([{ isIntersecting: true } as IntersectionObserverEntry])
    await waitFor(() => expect(screen.getByText("正在加载")).toBeTruthy())
    // A second intersection while the batch is in flight is ignored.
    ioTrigger?.([{ isIntersecting: true } as IntersectionObserverEntry])
    resolveMore(jsonResponse(batch2))
    await waitFor(() => expect(screen.getByText("More 0")).toBeTruthy())
    await waitFor(() => expect(screen.getByText("已加载全部")).toBeTruthy())
  })

  test("does not load more servers without a selected workspace", async () => {
    setSession({ selectedWorkspaceId: null })
    const notifications = withNotifySpy()
    const calls: string[] = []
    handler = (url) => {
      calls.push(url)
      if (url.includes("/mcp-servers")) return jsonResponse([])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    ioTrigger?.([{ isIntersecting: true } as IntersectionObserverEntry])
    await waitFor(() =>
      expect(calls.some((call) => call.includes("offset=50"))).toBe(false)
    )
    expect(notifications).toEqual([])
  })

  test("reports errors when loading more servers fails", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: string[] = []
    const batch1 = Array.from({ length: 50 }, (_, i) =>
      mcpServer({ id: `mcp-${i}`, name: `Server ${i}` })
    )
    handler = (url) => {
      calls.push(url)
      if (url.includes("offset=50")) {
        return jsonResponse({ detail: "more failed" }, 500)
      }
      if (url.includes("/mcp-servers")) return jsonResponse(batch1)
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(
      () => expect(screen.getByText("Server 0")).toBeTruthy(),
      { timeout: 5000 }
    )
    ioTrigger?.([{ isIntersecting: true } as IntersectionObserverEntry])
    // The failed page request must actually have been issued...
    await waitFor(
      () => expect(calls.some((call) => call.includes("offset=50"))).toBe(true),
      { timeout: 5000 }
    )
    // ...before the error notification lands.
    await waitFor(
      () => expect(notifications).toEqual([["error", "more failed"]]),
      { timeout: 5000 }
    )
    // The first batch stays and the list is not marked complete.
    expect(screen.getByText("Server 0")).toBeTruthy()
    expect(screen.queryByText("已加载全部")).toBeNull()
  })

  test("disables policy changes while another update is pending and keeps other servers intact", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    let resolvePolicy!: (response: Response) => void
    handler = (url, init) => {
      calls.push({ url, init })
      if (url.includes("/tools/web_search/policy")) {
        return new Promise<Response>((resolve) => {
          resolvePolicy = resolve
        })
      }
      if (url.includes("/mcp-servers")) {
        return jsonResponse([mcpServer(), stdioServer])
      }
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    fireEvent.click(screen.getAllByText("查看工具列表")[0])
    fireEvent.click(screen.getAllByText("查看工具列表")[1])
    const serverSelect = screen.getAllByLabelText("工具执行策略")[0]
    const otherSelect = screen.getAllByLabelText("工具执行策略")[2]

    // Start a policy update on the first server (kept pending).
    await chooseDropdownOption(serverSelect, "只读自动执行")
    await respondToConfirm("确认")
    await waitFor(() => expect(notifications).toHaveLength(0))

    expect((serverSelect as HTMLButtonElement).disabled).toBe(true)
    expect((otherSelect as HTMLButtonElement).disabled).toBe(true)
    expect(otherSelect.textContent).toContain("只读自动执行")
    const policyCalls = calls.filter((call) => call.url.includes("/policy"))
    expect(policyCalls).toHaveLength(1)

    resolvePolicy(
      jsonResponse({
        workspace_id: "ws-1",
        mcp_server_id: "mcp-1",
        tool_name: "web_search",
        definition_hash: "h1-new",
        mode: "read_only",
        reviewed_by_user_id: null,
        reviewed_at: null,
      })
    )
    await waitFor(() =>
      expect(notifications).toEqual([["success", "MCP 工具策略已更新"]])
    )
    await waitFor(() => expect(serverSelect.textContent).toContain("只读自动执行"))
    expect(otherSelect.textContent).toContain("只读自动执行")
  })

  test("creates a streamable_http server through the dialog", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (init?.method === "POST") {
        return jsonResponse(mcpServer({ id: "mcp-new", name: "My server", url: "https://example.com/mcp" }))
      }
      if (url.includes("/mcp-servers")) return jsonResponse([])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "添加 MCP Server" })[0])
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
    expect(screen.getByText("保存时会连接 Server 并发现可用工具。")).toBeTruthy()

    // preset fills the form
    fireEvent.click(screen.getByText("Tavily"))
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe("Tavily")
    expect((screen.getByLabelText("MCP 地址") as HTMLInputElement).value).toBe("https://mcp.tavily.com/mcp")
    expect(screen.getByText("需要 Token")).toBeTruthy()

    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "My server" } })
    fireEvent.change(screen.getByLabelText("MCP 地址"), { target: { value: "https://example.com/mcp" } })
    fireEvent.change(screen.getByLabelText("Bearer Token（可选）"), { target: { value: "secret" } })

    const dialog = screen.getByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "添加 MCP Server" }))
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true))
    const post = calls.find((c) => c.init?.method === "POST")!
    expect(post.url).toBe("/api/v1/workspaces/ws-1/mcp-servers")
    expect(JSON.parse(post.init!.body as string)).toEqual({
      name: "My server",
      transport: "streamable_http",
      url: "https://example.com/mcp",
      bearer_token: "secret",
    })
    expect(notifications).toEqual([["success", "MCP Server 已添加"]])
    await waitFor(() => expect(screen.getByText("My server")).toBeTruthy())
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("submit stays disabled until the form is valid", async () => {
    setSession()
    handler = (url) => (url.includes("/mcp-servers") ? jsonResponse([]) : jsonResponse(null, 404))
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "添加 MCP Server" })[0])
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
    const dialog = screen.getByRole("dialog")
    const submit = within(dialog).getByRole("button", { name: "添加 MCP Server" }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Only name" } })
    expect(submit.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText("MCP 地址"), { target: { value: "https://example.com/mcp" } })
    expect(submit.disabled).toBe(false)
    // cancel resets the form and closes the dialog
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("reports create errors and keeps the dialog open", async () => {
    setSession()
    const notifications = withNotifySpy()
    handler = (url, init) => {
      if (init?.method === "POST") return jsonResponse({ detail: "connection refused" }, 500)
      if (url.includes("/mcp-servers")) return jsonResponse([])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "添加 MCP Server" })[0])
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Broken" } })
    fireEvent.change(screen.getByLabelText("MCP 地址"), { target: { value: "https://example.com/mcp" } })
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "添加 MCP Server" }))
    await waitFor(() => expect(notifications).toEqual([["error", "connection refused"]]))
    expect(screen.getByRole("dialog")).toBeTruthy()
  })

  test("registers a stdio server with a JSON config", async () => {
    setSession()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (init?.method === "POST") return jsonResponse(mcpServer({ id: "mcp-local", name: "Local" }))
      if (url.includes("/mcp-servers")) return jsonResponse([])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "添加 MCP Server" })[0])
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("radio")[2]) // stdio
    expect(screen.queryByLabelText("MCP 地址")).toBeNull()
    expect(screen.queryByLabelText("Bearer Token（可选）")).toBeNull()
    const textarea = screen.getByLabelText("stdio 配置（JSON）") as HTMLTextAreaElement
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Local" } })

    fireEvent.change(textarea, { target: { value: "{not json" } })
    await waitFor(() => expect(screen.getByText("请输入有效的 stdio JSON 配置。")).toBeTruthy())
    expect(
      (within(screen.getByRole("dialog")).getByRole("button", { name: "添加 MCP Server" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)

    fireEvent.change(textarea, {
      target: {
        value: JSON.stringify({
          command: "/usr/bin/node",
          args: ["server.js"],
          cwd: "/srv",
          env: { KEY: "v" },
          transport: "stdio",
        }),
      },
    })
    await waitFor(() => expect(screen.getByText("stdio 配置会加密保存，之后不会返回明文。")).toBeTruthy())
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "添加 MCP Server" }))
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true))
    const post = calls.find((c) => c.init?.method === "POST")!
    expect(JSON.parse(post.init!.body as string)).toEqual({
      name: "Local",
      transport: "stdio",
      stdio_config: { command: "/usr/bin/node", args: ["server.js"], cwd: "/srv", env: { KEY: "v" } },
    })
  })

  test("registers an SSE server and switches transport placeholders", async () => {
    setSession()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (init?.method === "POST") return jsonResponse(mcpServer({ id: "mcp-sse", name: "SSE Server" }))
      if (url.includes("/mcp-servers")) return jsonResponse([])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "添加 MCP Server" })[0])
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
    expect((screen.getByLabelText("MCP 地址") as HTMLInputElement).placeholder).toBe("https://mcp.example.com/mcp")
    fireEvent.click(screen.getAllByRole("radio")[1]) // SSE
    expect((screen.getByLabelText("MCP 地址") as HTMLInputElement).placeholder).toBe("https://mcp.example.com/sse")
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "SSE Server" } })
    fireEvent.change(screen.getByLabelText("MCP 地址"), { target: { value: "https://mcp.example.com/sse" } })
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "添加 MCP Server" }))
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true))
    const body = JSON.parse(calls.find((c) => c.init?.method === "POST")!.init!.body as string)
    expect(body).toEqual({
      name: "SSE Server",
      transport: "sse",
      url: "https://mcp.example.com/sse",
    })
  })

  test("refreshes a server's tools", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (url.endsWith("/mcp-servers/mcp-1/refresh")) {
        return jsonResponse(mcpServer({ tools: [mcpServer().tools[0]] }))
      }
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("2 个工具")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("刷新工具"))
    await waitFor(() => expect(screen.getByText("1 个工具")).toBeTruthy())
    expect(notifications).toEqual([["success", "MCP 工具列表已刷新"]])
    expect(calls.some((c) => c.url.endsWith("/mcp-servers/mcp-1/refresh") && c.init?.method === "POST")).toBe(true)
  })

  test("reports refresh errors", async () => {
    setSession()
    const notifications = withNotifySpy()
    handler = (url) => {
      if (url.endsWith("/mcp-servers/mcp-1/refresh")) return jsonResponse({ detail: "refresh failed" }, 500)
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("刷新工具"))
    await waitFor(() => expect(notifications).toEqual([["error", "refresh failed"]]))
    expect(screen.getByText("2 个工具")).toBeTruthy()
  })

  test("deletes a server after confirmation", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (init?.method === "DELETE") return jsonResponse(null, 204)
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("删除 MCP Server"))
    const dialog = await screen.findByRole("dialog", { name: "确认操作" })
    expect(dialog.textContent).toContain("确定删除 MCP Server“Release tools”吗？")
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }))
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    expect(calls.some((c) => c.url.endsWith("/mcp-servers/mcp-1") && c.init?.method === "DELETE")).toBe(true)
    expect(notifications).toEqual([["success", "MCP Server 已删除"]])
  })

  test("keeps the server when deletion is cancelled or fails", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("删除 MCP Server"))
    await respondToConfirm("取消")
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false)
    expect(screen.getByText("Release tools")).toBeTruthy()

    // delete failure reports the error and keeps the server
    handler = (url, init) => {
      calls.push({ url, init })
      if (init?.method === "DELETE") return jsonResponse({ detail: "gone" }, 500)
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    fireEvent.click(screen.getByLabelText("删除 MCP Server"))
    await respondToConfirm("删除")
    await waitFor(() => expect(notifications).toEqual([["error", "gone"]]))
    expect(screen.getByText("Release tools")).toBeTruthy()
  })

  test("updates a tool policy to read_only after confirmation", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (url.includes("/tools/web_search/policy")) {
        return jsonResponse({
          workspace_id: "ws-1",
          mcp_server_id: "mcp-1",
          tool_name: "web_search",
          definition_hash: "h1-new",
          mode: "read_only",
          reviewed_by_user_id: null,
          reviewed_at: null,
        })
      }
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    const select = screen.getAllByLabelText("工具执行策略")[0]
    await chooseDropdownOption(select, "只读自动执行")
    const dialog = await screen.findByRole("dialog", { name: "确认操作" })
    expect(dialog.textContent).toContain("确认将工具“web_search”标记为只读并允许自动执行吗？")
    expect((select as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(within(dialog).getByRole("button", { name: "确认" }))
    await waitFor(() => expect(notifications).toEqual([["success", "MCP 工具策略已更新"]]))
    const put = calls.find((c) => c.url.includes("/tools/web_search/policy"))
    expect(put?.init?.method).toBe("PUT")
    expect(JSON.parse(put!.init!.body as string)).toEqual({ mode: "read_only" })
    await waitFor(() => expect(select.textContent).toContain("只读自动执行"))
  })

  test("restores the policy when the confirmation is declined", async () => {
    setSession()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    const select = screen.getAllByLabelText("工具执行策略")[0]
    await chooseDropdownOption(select, "只读自动执行")
    await respondToConfirm("取消")
    expect(select.textContent).toContain("每次调用前审批")
    expect(calls.some((c) => c.url.includes("/policy"))).toBe(false)
  })

  test("disables a tool without confirmation", async () => {
    setSession()
    const notifications = withNotifySpy()
    const calls: Array<{ url: string; init?: RequestInit }> = []
    handler = (url, init) => {
      calls.push({ url, init })
      if (url.includes("/tools/no_desc/policy")) {
        return jsonResponse({
          workspace_id: "ws-1",
          mcp_server_id: "mcp-1",
          tool_name: "no_desc",
          definition_hash: "h2-new",
          mode: "disabled",
          reviewed_by_user_id: null,
          reviewed_at: null,
        })
      }
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    const select = screen.getAllByLabelText("工具执行策略")[1]
    expect(select.textContent).toContain("禁用")
    await chooseDropdownOption(select, "每次调用前审批")
    await waitFor(() => expect(notifications).toEqual([["success", "MCP 工具策略已更新"]]))
    expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    const put = calls.find((c) => c.url.includes("/tools/no_desc/policy"))
    expect(JSON.parse(put!.init!.body as string)).toEqual({ mode: "approval_required" })
  })

  test("restores the policy when the policy update fails", async () => {
    setSession()
    const notifications = withNotifySpy()
    handler = (url) => {
      if (url.includes("/tools/web_search/policy")) return jsonResponse({ detail: "policy failed" }, 500)
      if (url.includes("/mcp-servers")) return jsonResponse([mcpServer()])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("Release tools")).toBeTruthy())
    const select = screen.getAllByLabelText("工具执行策略")[0]
    await chooseDropdownOption(select, "禁用")
    await waitFor(() => expect(notifications).toEqual([["error", "policy failed"]]))
    expect(select.textContent).toContain("每次调用前审批")
  })

  test("shows the saving state while connecting", async () => {
    setSession()
    let resolveCreate!: (response: Response) => void
    handler = (url, init) => {
      if (init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolveCreate = resolve
        })
      }
      if (url.includes("/mcp-servers")) return jsonResponse([])
      return jsonResponse(null, 404)
    }
    renderPage(<McpToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有 MCP Server")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "添加 MCP Server" })[0])
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Slow" } })
    fireEvent.change(screen.getByLabelText("MCP 地址"), { target: { value: "https://example.com/mcp" } })
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "添加 MCP Server" }))
    await waitFor(() => expect(screen.getByText("连接并发现中")).toBeTruthy())
    resolveCreate(jsonResponse(mcpServer({ id: "mcp-slow", name: "Slow" })))
    await waitFor(() => expect(screen.getByText("Slow")).toBeTruthy())
    expect(screen.queryByRole("dialog")).toBeNull()
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

  test("audit log endpoints", async () => {
    const calls = recordRequests(() => jsonResponse([auditLog]))
    await expect(listAuditLogs("tok")).resolves.toEqual([auditLog])
    await expect(listWorkspaceAuditLogs("tok", "w-1")).resolves.toEqual([auditLog])
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
    await expect(listAuditLogs("tok")).rejects.toThrow("forbidden")
    await expect(listWorkspaces("tok")).rejects.toThrow("name required; raw item")
    // A non-JSON error body fails while parsing the payload.
    await expect(listTeams("tok", "w-1")).rejects.toThrow(/boom/)
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
      "roles: a、b；flags: 是、否"
    )
    expect(formatAuditDetails({ slug_x: "v" }, t)).toBe("slug_x: v")
  })
})

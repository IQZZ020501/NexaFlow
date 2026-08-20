/* @jsxImportSource react */
/**
 * DOM-level coverage for the SystemShell audit tab: error paths, action
 * filtering, search debounce, refresh, load-more and workspace-scoped logs.
 *
 * Session is mocked (mutated per test); all backend traffic goes through
 * globalThis.fetch stubbed by a per-test route handler.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"

import { SystemShell } from "@/components/system/system-shell"
import type { MeResponse } from "@/lib/api/auth"
import type { AuditLog, Team, Workspace } from "@/lib/api/system"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  within,
  type FetchHandler,
} from "./helpers/dom"

const session = makeSession()
mockUseSession(session)
mockNextNavigation()

const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  selectedWorkspaceId: string | null
  workspaces: Workspace[]
  teams: Team[]
  notify: (kind: "success" | "error", message: string) => void
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ws1: Workspace = {
  id: "ws-1",
  name: "Test Workspace",
  description: "",
  status: "active",
  is_default: true,
}
const ws2: Workspace = {
  id: "ws-2",
  name: "Second Space",
  description: "second",
  status: "active",
  is_default: false,
}

const adminUser = {
  id: "u-1",
  username: "admin",
  email: "admin@app.local",
  name: "NexaFlow Admin",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [{ id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" }],
  teams: [],
}
const alice = {
  id: "u-2",
  username: "alice",
  email: "alice@app.local",
  name: "Alice",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [{ id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" }],
  teams: [],
}

const adminMe: MeResponse = {
  user: adminUser,
  memberships: [{ workspace_id: "ws-1", role: "admin" }],
}
const wsAdminMe: MeResponse = {
  user: {
    ...alice,
    is_global_admin: false,
    workspaces: [
      { id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" },
    ],
  },
  memberships: [{ workspace_id: "ws-1", role: "admin" }],
}

const auditLog: AuditLog = {
  id: "a-1",
  actor_user_id: "u-1",
  actor_username: "admin",
  actor_name: "NexaFlow Admin",
  workspace_id: "ws-1",
  action: "workspace.create",
  resource_type: "workspace",
  resource_id: "ws-new",
  resource_name: "New Space",
  details: { email: "x@app.local" },
  created_at: "2026-08-02T00:00:00Z",
}

type Route = {
  method?: string
  path: string
  handle: (url: string, init?: RequestInit) => Response
}

function routeHandler(routes: Route[]): FetchHandler {
  return (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET"
    const pathname = url.split("?")[0]
    for (const route of routes) {
      if ((route.method ?? "GET") === method && pathname === route.path) {
        return route.handle(url, init)
      }
    }
    throw new Error(`Unexpected request: ${method} ${url}`)
  }
}

let handler: FetchHandler = () => jsonResponse([], 200)

function setSession(
  overrides: {
    me?: MeResponse | null
    token?: string | null
    selectedWorkspaceId?: string | null
    workspaces?: Workspace[]
  } = {}
) {
  sessionState.me = overrides.me === undefined ? adminMe : overrides.me
  sessionState.token = overrides.token === undefined ? "test-token" : overrides.token
  sessionState.selectedWorkspaceId =
    overrides.selectedWorkspaceId === undefined ? "ws-1" : overrides.selectedWorkspaceId
  sessionState.workspaces = overrides.workspaces ?? [ws1, ws2]
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
  setSession()
  sessionState.notify = () => undefined
})

afterEach(() => {
  cleanup()
  resetFetch()
})

// ---------------------------------------------------------------------------
// Audit tab
// ---------------------------------------------------------------------------

describe("audit tab", () => {
  test("shows the empty state and reports loading failures", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/admin/audit-logs",
        handle: () => jsonResponse({ detail: "audit failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="audit" />)
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "audit failed"])
    )
    expect(await screen.findByText("暂无审计日志")).toBeTruthy()
  })

  test("renders audit rows and filters by action with the debounced search", async () => {
    const notifications = withNotifySpy()
    const requests: string[] = []
    handler = routeHandler([
      {
        path: "/api/v1/admin/audit-logs",
        handle: (url) => {
          requests.push(url)
          const parsed = new URL(url, "http://localhost")
          const action = parsed.searchParams.get("action")
          const search = parsed.searchParams.get("search")
          if (action === "workspace.create") {
            return jsonResponse([auditLog])
          }
          if (search) {
            return jsonResponse([{ ...auditLog, id: "a-searched" }])
          }
          return jsonResponse([{ ...auditLog, id: "a-other", action: "user.create", resource_name: "Other Resource" }])
        },
      },
    ])
    renderPage(<SystemShell activeTab="audit" />)
    expect(await screen.findByText("Other Resource")).toBeTruthy()
    expect(screen.getByText("NexaFlow Admin")).toBeTruthy()

    // Action filter: options come from the loaded logs.
    await chooseDropdownOption(screen.getByLabelText("筛选动作"), "新建用户")
    await waitFor(() =>
      expect(
        requests.some((request) => request.includes("action=user.create"))
      ).toBe(true)
    )

    // Search input debounces 300ms before refetching.
    const searchInput = screen.getByLabelText("搜索审计")
    fireEvent.change(searchInput, { target: { value: "sp" } })
    fireEvent.change(searchInput, { target: { value: "space" } })
    await waitFor(() =>
      expect(
        requests.some((request) => {
          const parsed = new URL(request, "http://localhost")
          return parsed.searchParams.get("search") === "space"
        })
      ).toBe(true)
    )
    expect(
      requests.some((request) => {
        const parsed = new URL(request, "http://localhost")
        return parsed.searchParams.get("search") === "sp"
      })
    ).toBe(false)
    expect(await screen.findByText("New Space")).toBeTruthy()
    expect(notifications).toEqual([])
  })

  test("refreshes and loads more pages of audit logs", async () => {
    const requests: string[] = []
    handler = routeHandler([
      {
        path: "/api/v1/admin/audit-logs",
        handle: (url) => {
          requests.push(url)
          const parsed = new URL(url, "http://localhost")
          const offset = parsed.searchParams.get("offset") ?? "0"
          if (offset === "100") {
            return jsonResponse([
              { ...auditLog, id: "a-page-2", resource_name: "Page Two" },
            ])
          }
          return jsonResponse(
            Array.from({ length: 100 }, (_, index) => ({
              ...auditLog,
              id: `a-page-1-${index}`,
              resource_name: `Page One ${index}`,
            }))
          )
        },
      },
    ])
    renderPage(<SystemShell activeTab="audit" />)
    expect(await screen.findByText("Page One 0")).toBeTruthy()

    // Load more appends the next page and hides the button once exhausted.
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }))
    expect(await screen.findByText("Page Two")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "加载更多" })).toBeNull()
    expect(requests.some((request) => request.includes("offset=100"))).toBe(true)

    // Refresh resets to the first page.
    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    await waitFor(() => expect(screen.queryByText("Page Two")).toBeNull())
    expect(await screen.findByText("Page One 0")).toBeTruthy()
    expect(
      requests.filter(
        (request) =>
          request.includes("offset=0") && !request.includes("offset=100")
      ).length
    ).toBeGreaterThanOrEqual(2)
  })

  test("workspace admin sees workspace-scoped audit logs", async () => {
    const requests: string[] = []
    setSession({ me: wsAdminMe, selectedWorkspaceId: "ws-1" })
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/audit-logs",
        handle: (url) => {
          requests.push(url)
          return jsonResponse([auditLog])
        },
      },
    ])
    renderPage(<SystemShell activeTab="audit" />)
    expect(await screen.findByText("New Space")).toBeTruthy()
    expect(screen.getByText(/工作空间范围: Test Workspace/)).toBeTruthy()
    expect(requests[0]).toContain("/api/v1/workspaces/ws-1/audit-logs")
  })

  test("reports failures from the workspace-scoped audit endpoint", async () => {
    const notifications = withNotifySpy()
    setSession({ me: wsAdminMe, selectedWorkspaceId: "ws-1" })
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/audit-logs",
        handle: () => jsonResponse({ detail: "ws audit failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="audit" />)
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "ws audit failed"])
    )
    expect(await screen.findByText("暂无审计日志")).toBeTruthy()
  })
})

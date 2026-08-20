/* @jsxImportSource react */
/**
 * DOM-level coverage for SystemShell access control plus the workspace and
 * team management tabs and their member dialogs.
 *
 * Session is mocked (mutated per test); all backend traffic goes through
 * globalThis.fetch stubbed by a per-test route handler.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { act } from "@testing-library/react"

import { SystemShell, type SystemTab } from "@/components/system/system-shell"
import { LanguageProvider } from "@/contexts/language-provider"
import type { MeResponse, User } from "@/lib/api/auth"
import type { Team, Workspace, WorkspaceMember } from "@/lib/api/system"
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
const pushes: string[] = []
const replacements: string[] = []
mockUseSession(session)
mockNextNavigation({
  push: (href: string) => pushes.push(href),
  replace: (href: string) => replacements.push(href),
})

const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  selectedWorkspaceId: string | null
  workspaces: Workspace[]
  teams: Team[]
  notify: (kind: "success" | "error", message: string) => void
  selectWorkspace: (workspaceId: string) => void
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
const team1: Team = {
  id: "t-1",
  workspace_id: "ws-1",
  name: "Team One",
  description: "",
  status: "active",
  is_default: false,
}
const teamArchived: Team = {
  id: "t-2",
  workspace_id: "ws-1",
  name: "Old Team",
  description: "",
  status: "archived",
  is_default: false,
}

const adminUser: User = {
  id: "u-1",
  username: "admin",
  email: "admin@app.local",
  name: "NexaFlow Admin",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" },
  ],
  teams: [],
}
const alice: User = {
  id: "u-2",
  username: "alice",
  email: "alice@app.local",
  name: "Alice",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" },
  ],
  teams: [],
}
const bob: User = {
  id: "u-3",
  username: "bob",
  email: "bob@app.local",
  name: "Bob",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [],
  teams: [
    {
      id: "t-1",
      workspace_id: "ws-1",
      name: "Team One",
      is_default: false,
      role: "admin",
    },
  ],
}
const carol: User = {
  id: "u-4",
  username: "carol",
  email: "carol@app.local",
  name: "Carol",
  is_global_admin: false,
  must_change_password: false,
  is_active: false,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [],
  teams: [],
}
const dave: User = {
  id: "u-5",
  username: "dave",
  email: "dave@app.local",
  name: "Dave",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [],
  teams: [],
}

const allUsers = [adminUser, alice, bob, carol, dave]
const adminMe: MeResponse = {
  user: adminUser,
  memberships: [{ workspace_id: "ws-1", role: "admin" }],
}
const wsMembers: WorkspaceMember[] = [
  { user: alice, role: "admin" },
  { user: carol, role: "member" },
]
const teamMembers = [
  { user: carol, role: "member" },
  { user: adminUser, role: "admin" },
]

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
    teams?: Team[]
  } = {}
) {
  sessionState.me = overrides.me === undefined ? adminMe : overrides.me
  sessionState.token =
    overrides.token === undefined ? "test-token" : overrides.token
  sessionState.selectedWorkspaceId =
    overrides.selectedWorkspaceId === undefined
      ? "ws-1"
      : overrides.selectedWorkspaceId
  sessionState.workspaces = overrides.workspaces ?? [ws1, ws2]
  sessionState.teams = overrides.teams ?? [team1, teamArchived]
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
  await act(async () => {
    fireEvent.click(within(dialog).getByRole("button", { name: label }))
    await Promise.resolve()
  })
}

function formOf(dialog: HTMLElement) {
  return dialog.querySelector("form") as HTMLFormElement
}

function rerenderShell(view: ReturnType<typeof renderPage>, tab: SystemTab) {
  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      <SystemShell activeTab={tab} />
    </LanguageProvider>
  )
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
  pushes.length = 0
  replacements.length = 0
  setSession()
  sessionState.notify = () => undefined
  sessionState.selectWorkspace = () => undefined
})

afterEach(() => {
  cleanup()
  resetFetch()
})

// ---------------------------------------------------------------------------
// Access control
// ---------------------------------------------------------------------------

describe("SystemShell access control", () => {
  test("renders nothing without a session or token", () => {
    setSession({ me: null, token: null })
    const { container } = renderPage(<SystemShell activeTab="workspaces" />)
    expect(container.firstChild).toBeNull()

    setSession({ me: adminMe, token: null })
    const view = renderPage(<SystemShell activeTab="workspaces" />)
    expect(view.container.firstChild).toBeNull()

    setSession({ me: null, token: "test-token" })
    const view2 = renderPage(<SystemShell activeTab="workspaces" />)
    expect(view2.container.firstChild).toBeNull()
  })

  test("redirects a user without system access to the app", () => {
    const plainMe: MeResponse = {
      user: {
        ...alice,
        id: "u-9",
        username: "plain",
        name: "Plain User",
        workspaces: [],
        teams: [],
      },
      memberships: [],
    }
    setSession({ me: plainMe })
    const { container } = renderPage(<SystemShell activeTab="workspaces" />)
    expect(container.firstChild).toBeNull()
    expect(replacements).toEqual(["/app/apps"])
  })

  test("redirects the users tab when the user cannot manage users", () => {
    const teamAdminMe: MeResponse = {
      user: {
        ...alice,
        id: "u-9",
        username: "tadmin",
        name: "Team Admin",
        workspaces: [],
        teams: [
          {
            id: "t-1",
            workspace_id: "ws-1",
            name: "Team One",
            is_default: false,
            role: "admin",
          },
        ],
      },
      memberships: [{ workspace_id: "ws-1", role: "member" }],
    }
    setSession({ me: teamAdminMe })
    renderPage(<SystemShell activeTab="users" />)
    expect(replacements).toEqual(["/system/teams"])
  })

  test("redirects the audit tab when the user is not an admin of the selected workspace", () => {
    const otherAdminMe: MeResponse = {
      user: {
        ...alice,
        id: "u-9",
        username: "wadmin",
        name: "Workspace Admin",
        is_global_admin: false,
        workspaces: [
          {
            id: "ws-2",
            name: "Second Space",
            is_default: false,
            role: "admin",
          },
        ],
        teams: [],
      },
      memberships: [
        { workspace_id: "ws-2", role: "admin" },
        { workspace_id: "ws-1", role: "member" },
      ],
    }
    setSession({ me: otherAdminMe })
    renderPage(<SystemShell activeTab="audit" />)
    expect(replacements).toEqual(["/system/teams"])
  })

  test("allows the audit tab for an admin of the selected workspace", async () => {
    const wsAdminMe: MeResponse = {
      user: {
        ...alice,
        is_global_admin: false,
        workspaces: [
          {
            id: "ws-1",
            name: "Test Workspace",
            is_default: true,
            role: "admin",
          },
        ],
      },
      memberships: [{ workspace_id: "ws-1", role: "admin" }],
    }
    setSession({ me: wsAdminMe })
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/audit-logs",
        handle: () => jsonResponse([]),
      },
    ])
    renderPage(<SystemShell activeTab="audit" />)
    expect(await screen.findByText("暂无审计日志")).toBeTruthy()
    expect(replacements).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// Workspaces tab
// ---------------------------------------------------------------------------

describe("workspaces tab", () => {
  test("renders workspaces, links and switches tabs via router push", async () => {
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    expect(await screen.findByText("Test Workspace")).toBeTruthy()
    expect(screen.getByText("Second Space")).toBeTruthy()
    expect(screen.queryByText("暂无工作空间")).toBeNull()

    for (const label of ["工作空间", "团队", "用户管理", "审计日志"]) {
      expect(screen.getByRole("tab", { name: label })).toBeTruthy()
    }
    for (const label of ["系统运行", "SMTP 邮件", "工作空间治理", "会话安全"]) {
      expect(screen.getByText(label)).toBeTruthy()
    }

    fireEvent.click(screen.getByRole("tab", { name: "团队" }))
    fireEvent.click(screen.getByRole("tab", { name: "用户管理" }))
    fireEvent.click(screen.getByRole("tab", { name: "审计日志" }))
    expect(pushes).toEqual(["/system/teams", "/system/users", "/system/audit"])
  })

  test("creates a workspace with a selected admin", async () => {
    const notifications = withNotifySpy()
    const created: { body?: unknown; url?: string } = {}
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "POST",
        path: "/api/v1/workspaces",
        handle: (url, init) => {
          created.body = JSON.parse(String(init?.body))
          created.url = url
          return jsonResponse({
            workspace: {
              id: "ws-new",
              name: "New Space",
              description: "fresh",
              status: "active",
              is_default: false,
            },
            admin_user: alice,
          })
        },
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(await screen.findByRole("button", { name: "新建工作空间" }))
    const dialog = await screen.findByRole("dialog", { name: "新建工作空间" })
    await waitFor(() =>
      expect(
        (document.getElementById("workspaceAdmin") as HTMLButtonElement)
          .disabled
      ).toBe(false)
    )
    fireEvent.change(within(dialog).getByLabelText("名称"), {
      target: { value: "New Space" },
    })
    fireEvent.change(within(dialog).getByLabelText("描述"), {
      target: { value: "fresh" },
    })
    await chooseDropdownOption(
      document.getElementById("workspaceAdmin") as HTMLElement,
      "Alice"
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "新建" }))
    await waitFor(() => expect(created.url).not.toBeUndefined())
    expect(created.url).toBe("/api/v1/workspaces")
    expect(created.body).toEqual({
      name: "New Space",
      description: "fresh",
      admin_user_id: "u-2",
    })
    expect(notifications).toContainEqual(["success", "工作空间已新建"])
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("requires an admin selection when creating a workspace", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(await screen.findByRole("button", { name: "新建工作空间" }))
    const dialog = await screen.findByRole("dialog", { name: "新建工作空间" })
    await waitFor(() =>
      expect(
        (document.getElementById("workspaceAdmin") as HTMLButtonElement)
          .disabled
      ).toBe(false)
    )
    fireEvent.submit(formOf(dialog))
    expect(notifications).toContainEqual(["error", "请选择负责人"])
  })

  test("reports an error when creating a workspace fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "POST",
        path: "/api/v1/workspaces",
        handle: () => jsonResponse({ detail: "name taken" }, 409),
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(await screen.findByRole("button", { name: "新建工作空间" }))
    const dialog = await screen.findByRole("dialog", { name: "新建工作空间" })
    await waitFor(() =>
      expect(
        (document.getElementById("workspaceAdmin") as HTMLButtonElement)
          .disabled
      ).toBe(false)
    )
    await chooseDropdownOption(
      document.getElementById("workspaceAdmin") as HTMLElement,
      "Alice"
    )
    fireEvent.submit(formOf(dialog))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "name taken"])
    )
    expect(screen.getByRole("dialog")).toBeTruthy()
  })

  test("edits a workspace", async () => {
    const notifications = withNotifySpy()
    let patchBody: unknown = null
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1",
        handle: (_url, init) => {
          patchBody = JSON.parse(String(init?.body))
          return jsonResponse({ ...ws1, name: "Renamed Space" })
        },
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "编辑工作空间" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "编辑工作空间" })
    fireEvent.change(within(dialog).getByLabelText("名称"), {
      target: { value: "Renamed Space" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(patchBody).toEqual({ name: "Renamed Space", description: "" })
    )
    expect(notifications).toContainEqual(["success", "工作空间已更新"])
  })

  test("archives and restores a workspace through the confirm dialog", async () => {
    const notifications = withNotifySpy()
    const patches: Array<Record<string, unknown>> = []
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1",
        handle: (_url, init) => {
          patches.push(
            JSON.parse(String(init?.body)) as Record<string, unknown>
          )
          return jsonResponse(ws1)
        },
      },
    ])
    const view = renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "归档工作空间" }))[0]
    )
    await respondToConfirm("归档")
    await waitFor(() => expect(patches).toEqual([{ status: "archived" }]))
    expect(notifications).toContainEqual(["success", "工作空间已归档"])

    sessionState.workspaces = [{ ...ws1, status: "archived" }, ws2]
    rerenderShell(view, "workspaces")
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "恢复工作空间" }))[0]
    )
    await respondToConfirm("恢复")
    await waitFor(() => expect(patches).toContainEqual({ status: "active" }))
    expect(notifications).toContainEqual(["success", "工作空间已恢复"])
  })

  test("cancelling the workspace archive confirm does nothing", async () => {
    const notifications = withNotifySpy()
    const patches: string[] = []
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1",
        handle: (_url, init) => {
          patches.push(String(init?.body))
          return jsonResponse(ws1)
        },
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "归档工作空间" }))[0]
    )
    await respondToConfirm("取消")
    expect(patches).toEqual([])
    expect(notifications).toEqual([])
  })

  test("deletes a workspace after confirmation", async () => {
    const notifications = withNotifySpy()
    const deletes: string[] = []
    handler = routeHandler([
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1",
        handle: (url) => {
          deletes.push(url)
          return jsonResponse(null, 204)
        },
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "永久删除工作空间" }))[0]
    )
    await respondToConfirm("删除")
    await waitFor(() => expect(deletes).toEqual(["/api/v1/workspaces/ws-1"]))
    expect(notifications).toContainEqual(["success", "工作空间已删除"])
  })

  test("cancelling workspace deletion keeps the workspace", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "永久删除工作空间" }))[0]
    )
    await respondToConfirm("取消")
    expect(notifications).toEqual([])
    expect(screen.getAllByText("Test Workspace").length).toBeGreaterThan(0)
  })

  test("reports errors from workspace mutation requests", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1",
        handle: () => jsonResponse({ detail: "update failed" }, 500),
      },
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1",
        handle: () => jsonResponse({ detail: "delete failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "归档工作空间" }))[0]
    )
    await respondToConfirm("归档")
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "update failed"])
    )
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "永久删除工作空间" }))[0]
    )
    await respondToConfirm("删除")
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "delete failed"])
    )
  })

  test("manages workspace members: add, update role and remove", async () => {
    const notifications = withNotifySpy()
    const requests: string[] = []
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "POST",
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => {
          requests.push("POST")
          return jsonResponse({ user: dave, role: "member" })
        },
      },
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/members/u-4",
        handle: () => {
          requests.push("PATCH")
          return jsonResponse({ user: carol, role: "admin" })
        },
      },
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1/members/u-4",
        handle: () => {
          requests.push("DELETE")
          return jsonResponse(null, 204)
        },
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理工作空间成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    await waitFor(() => expect(within(dialog).getByText("Alice")).toBeTruthy())
    expect(within(dialog).getByText("Carol")).toBeTruthy()

    // Add Dave as a new member with the admin role.
    await chooseDropdownOption(
      document.getElementById("workspaceMemberUser") as HTMLElement,
      "Dave · dave"
    )
    await chooseDropdownOption(
      document.getElementById("workspaceMemberRole") as HTMLElement,
      "管理员"
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "添加成员" }))
    await waitFor(() => expect(requests).toContain("POST"))
    expect(notifications).toContainEqual(["success", "工作空间成员已添加"])
    await waitFor(() => expect(within(dialog).getByText("Dave")).toBeTruthy())

    // Promote Carol (currently a member) to admin.
    const carolRow = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    await chooseDropdownOption(
      within(carolRow).getByRole("button", { name: "成员" }),
      "管理员"
    )
    await waitFor(() => expect(requests).toContain("PATCH"))
    expect(notifications).toContainEqual(["success", "工作空间成员已更新"])

    // Remove Carol (now admin; two admins remain so removal is allowed).
    const carolRow2 = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    fireEvent.click(within(carolRow2).getByRole("button", { name: "移除成员" }))
    await respondToConfirm("移除")
    await waitFor(() => expect(requests).toContain("DELETE"))
    expect(notifications).toContainEqual(["success", "工作空间成员已移除"])
    await waitFor(() =>
      expect([
        within(dialog).queryByText("Carol"),
        (document.getElementById("workspaceMemberUser") as HTMLButtonElement)
          .disabled,
      ]).toEqual([null, false])
    )
  })

  test("cancels removing a workspace member", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理工作空间成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    await waitFor(() => expect(within(dialog).getByText("Carol")).toBeTruthy())
    const row = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    fireEvent.click(within(row).getByRole("button", { name: "移除成员" }))
    await respondToConfirm("取消")
    expect(notifications).toEqual([])
    expect(within(dialog).getByText("Carol")).toBeTruthy()
  })

  test("reports workspace member load and mutation failures", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse({ detail: "members unavailable" }, 500),
      },
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理工作空间成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "members unavailable"])
    )
    expect(within(dialog).getByText("暂无工作空间成员")).toBeTruthy()
  })

  test("reports an error when adding a workspace member fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "POST",
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse({ detail: "add failed" }, 400),
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理工作空间成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    await waitFor(() => expect(within(dialog).getByText("Alice")).toBeTruthy())
    await chooseDropdownOption(
      document.getElementById("workspaceMemberUser") as HTMLElement,
      "Dave · dave"
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "添加成员" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "add failed"])
    )
  })

  test("reports workspace member role update and removal failures", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/members/u-4",
        handle: () => jsonResponse({ detail: "role failed" }, 500),
      },
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1/members/u-4",
        handle: () => jsonResponse({ detail: "remove failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理工作空间成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    await waitFor(() => expect(within(dialog).getByText("Carol")).toBeTruthy())

    const carolRow = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    await chooseDropdownOption(
      within(carolRow).getByRole("button", { name: "成员" }),
      "管理员"
    )
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "role failed"])
    )

    fireEvent.click(within(carolRow).getByRole("button", { name: "移除成员" }))
    await respondToConfirm("移除")
    await waitFor(() => {
      expect(notifications).toContainEqual(["error", "remove failed"])
      expect(
        (document.getElementById("workspaceMemberUser") as HTMLButtonElement)
          .disabled
      ).toBe(false)
    })
    expect(within(dialog).getByText("Carol")).toBeTruthy()
  })

  test("reports an error when editing a workspace fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1",
        handle: () => jsonResponse({ detail: "edit failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="workspaces" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "编辑工作空间" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "编辑工作空间" })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "edit failed"])
    )
  })
})

// ---------------------------------------------------------------------------
// Teams tab
// ---------------------------------------------------------------------------

describe("teams tab", () => {
  test("lists teams for the selected workspace", async () => {
    handler = routeHandler([])
    renderPage(<SystemShell activeTab="teams" />)
    expect(await screen.findByText("Team One")).toBeTruthy()
    expect(screen.getByText("Old Team")).toBeTruthy()
    expect(screen.getByText("Test Workspace")).toBeTruthy()
  })

  test("creates a team with an admin from the selected workspace", async () => {
    const notifications = withNotifySpy()
    const selectedWorkspaces: string[] = []
    sessionState.selectWorkspace = (id: string) => selectedWorkspaces.push(id)
    const created: { body?: unknown; url?: string } = {}
    const ws2Members: WorkspaceMember[] = [{ user: dave, role: "admin" }]
    const candidatesCalls: string[] = []
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
      {
        path: "/api/v1/workspaces/ws-2/members",
        handle: (url) => {
          candidatesCalls.push(url.split("?")[0])
          return jsonResponse(ws2Members)
        },
      },
      {
        method: "POST",
        path: "/api/v1/workspaces/ws-2/teams",
        handle: (url, init) => {
          created.body = JSON.parse(String(init?.body))
          created.url = url
          return jsonResponse({
            id: "t-new",
            workspace_id: "ws-2",
            name: "Squad",
            description: "d",
            status: "active",
            is_default: false,
          })
        },
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(await screen.findByRole("button", { name: "新建团队" }))
    const dialog = await screen.findByRole("dialog", { name: "新建团队" })
    // The selected workspace is prefilled, so its candidates load first.
    await waitFor(() =>
      expect(
        (document.getElementById("teamAdmin") as HTMLButtonElement).disabled
      ).toBe(false)
    )
    await chooseDropdownOption(
      document.getElementById("teamWorkspace") as HTMLElement,
      "Second Space"
    )
    await waitFor(() =>
      expect(candidatesCalls).toContain("/api/v1/workspaces/ws-2/members")
    )
    fireEvent.change(within(dialog).getByLabelText("名称"), {
      target: { value: "Squad" },
    })
    fireEvent.change(within(dialog).getByLabelText("描述"), {
      target: { value: "d" },
    })
    await chooseDropdownOption(
      document.getElementById("teamAdmin") as HTMLElement,
      "Dave"
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "新建" }))
    await waitFor(() => expect(created.url).not.toBeUndefined())
    expect(created.url).toBe("/api/v1/workspaces/ws-2/teams")
    expect(created.body).toEqual({
      name: "Squad",
      description: "d",
      admin_user_id: "u-5",
    })
    expect(notifications).toContainEqual(["success", "团队已新建"])
    expect(selectedWorkspaces).toEqual(["ws-2"])
  })

  test("requires an admin when creating a team", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(await screen.findByRole("button", { name: "新建团队" }))
    const dialog = await screen.findByRole("dialog", { name: "新建团队" })
    await waitFor(() =>
      expect(
        (document.getElementById("teamAdmin") as HTMLButtonElement).disabled
      ).toBe(false)
    )
    fireEvent.submit(formOf(dialog))
    expect(notifications).toContainEqual(["error", "请选择团队管理员"])
  })

  test("reports an error when creating a team fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
      {
        method: "POST",
        path: "/api/v1/workspaces/ws-1/teams",
        handle: () => jsonResponse({ detail: "team failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(await screen.findByRole("button", { name: "新建团队" }))
    const dialog = await screen.findByRole("dialog", { name: "新建团队" })
    await waitFor(() =>
      expect(
        (document.getElementById("teamAdmin") as HTMLButtonElement).disabled
      ).toBe(false)
    )
    await chooseDropdownOption(
      document.getElementById("teamAdmin") as HTMLElement,
      "Alice"
    )
    fireEvent.submit(formOf(dialog))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "team failed"])
    )
  })

  test("edits a team", async () => {
    const notifications = withNotifySpy()
    let patchBody: unknown = null
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/teams/t-1",
        handle: (_url, init) => {
          patchBody = JSON.parse(String(init?.body))
          return jsonResponse({ ...team1, name: "Renamed Team" })
        },
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "编辑团队" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "编辑团队" })
    fireEvent.change(within(dialog).getByLabelText("名称"), {
      target: { value: "Renamed Team" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(patchBody).toEqual({ name: "Renamed Team", description: "" })
    )
    expect(notifications).toContainEqual(["success", "团队已更新"])
  })

  test("archives and restores a team through the confirm dialog", async () => {
    const notifications = withNotifySpy()
    const patches: Array<Record<string, unknown>> = []
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/teams/t-1",
        handle: (_url, init) => {
          patches.push(
            JSON.parse(String(init?.body)) as Record<string, unknown>
          )
          return jsonResponse(team1)
        },
      },
    ])
    const view = renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "归档团队" }))[0]
    )
    await respondToConfirm("归档")
    await waitFor(() => expect(patches).toEqual([{ status: "archived" }]))
    expect(notifications).toContainEqual(["success", "团队已归档"])

    sessionState.teams = [{ ...team1, status: "archived" }, teamArchived]
    rerenderShell(view, "teams")
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "恢复团队" }))[0]
    )
    await respondToConfirm("恢复")
    await waitFor(() => expect(patches).toContainEqual({ status: "active" }))
    expect(notifications).toContainEqual(["success", "团队已恢复"])
  })

  test("cancelling the team archive confirm does nothing", async () => {
    const notifications = withNotifySpy()
    const patches: string[] = []
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/teams/t-1",
        handle: (_url, init) => {
          patches.push(String(init?.body))
          return jsonResponse(team1)
        },
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "归档团队" }))[0]
    )
    await respondToConfirm("取消")
    expect(patches).toEqual([])
    expect(notifications).toEqual([])
  })

  test("deletes a team after confirmation", async () => {
    const notifications = withNotifySpy()
    const deletes: string[] = []
    handler = routeHandler([
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1/teams/t-1",
        handle: (url) => {
          deletes.push(url)
          return jsonResponse(null, 204)
        },
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "永久删除团队" }))[0]
    )
    await respondToConfirm("删除")
    await waitFor(() =>
      expect(deletes).toEqual(["/api/v1/workspaces/ws-1/teams/t-1"])
    )
    expect(notifications).toContainEqual(["success", "团队已删除"])
  })

  test("reports team mutation failures", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/teams/t-1",
        handle: () => jsonResponse({ detail: "team update failed" }, 500),
      },
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1/teams/t-1",
        handle: () => jsonResponse({ detail: "team delete failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "归档团队" }))[0]
    )
    await respondToConfirm("归档")
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "team update failed"])
    )
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "永久删除团队" }))[0]
    )
    await respondToConfirm("删除")
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "team delete failed"])
    )
  })

  test("manages team members: add, update role and remove", async () => {
    const notifications = withNotifySpy()
    const requests: string[] = []
    const teamWsMembers: WorkspaceMember[] = [
      { user: alice, role: "admin" },
      { user: dave, role: "member" },
    ]
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/teams/t-1/members",
        handle: () => jsonResponse(teamMembers),
      },
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(teamWsMembers),
      },
      {
        method: "POST",
        path: "/api/v1/workspaces/ws-1/teams/t-1/members",
        handle: () => {
          requests.push("POST")
          return jsonResponse({ user: dave, role: "member" })
        },
      },
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/teams/t-1/members/u-4",
        handle: () => {
          requests.push("PATCH")
          return jsonResponse({ user: carol, role: "admin" })
        },
      },
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1/teams/t-1/members/u-4",
        handle: () => {
          requests.push("DELETE")
          return jsonResponse(null, 204)
        },
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理团队成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "管理团队成员" })
    await waitFor(() =>
      expect(within(dialog).getByText("NexaFlow Admin")).toBeTruthy()
    )
    expect(within(dialog).getByText("Carol")).toBeTruthy()

    // Add Dave from the workspace member candidates.
    await chooseDropdownOption(
      document.getElementById("teamMemberUser") as HTMLElement,
      "Dave · dave"
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "添加成员" }))
    await waitFor(() => expect(requests).toContain("POST"))
    expect(notifications).toContainEqual(["success", "团队成员已添加"])

    // Promote Carol (member) to admin.
    const carolRow = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    await chooseDropdownOption(
      within(carolRow).getByRole("button", { name: "成员" }),
      "管理员"
    )
    await waitFor(() => expect(requests).toContain("PATCH"))
    expect(notifications).toContainEqual(["success", "团队成员已更新"])

    // Remove Carol.
    const carolRow2 = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    fireEvent.click(within(carolRow2).getByRole("button", { name: "移除成员" }))
    await respondToConfirm("移除")
    await waitFor(() => {
      expect(requests).toContain("DELETE")
      expect(notifications).toContainEqual(["success", "团队成员已移除"])
      expect(
        (document.getElementById("teamMemberUser") as HTMLButtonElement)
          .disabled
      ).toBe(false)
    })
  })

  test("reports team member load and mutation failures", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/teams/t-1/members",
        handle: () => jsonResponse({ detail: "team members failed" }, 500),
      },
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理团队成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "管理团队成员" })
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "team members failed"])
    )
    expect(within(dialog).getByText("暂无团队成员")).toBeTruthy()
  })

  test("reports team member add, role update and removal failures", async () => {
    const notifications = withNotifySpy()
    const teamWsMembers: WorkspaceMember[] = [
      { user: alice, role: "admin" },
      { user: dave, role: "member" },
    ]
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/teams/t-1/members",
        handle: () => jsonResponse(teamMembers),
      },
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(teamWsMembers),
      },
      {
        method: "POST",
        path: "/api/v1/workspaces/ws-1/teams/t-1/members",
        handle: () => jsonResponse({ detail: "add member failed" }, 500),
      },
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/teams/t-1/members/u-4",
        handle: () => jsonResponse({ detail: "role update failed" }, 500),
      },
      {
        method: "DELETE",
        path: "/api/v1/workspaces/ws-1/teams/t-1/members/u-4",
        handle: () => jsonResponse({ detail: "remove member failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理团队成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "管理团队成员" })
    await waitFor(() => expect(within(dialog).getByText("Carol")).toBeTruthy())

    await chooseDropdownOption(
      document.getElementById("teamMemberUser") as HTMLElement,
      "Dave · dave"
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "添加成员" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "add member failed"])
    )

    const carolRow = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    await chooseDropdownOption(
      within(carolRow).getByRole("button", { name: "成员" }),
      "管理员"
    )
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "role update failed"])
    )

    fireEvent.click(within(carolRow).getByRole("button", { name: "移除成员" }))
    await respondToConfirm("移除")
    await waitFor(() => {
      expect(notifications).toContainEqual(["error", "remove member failed"])
      expect(
        (document.getElementById("teamMemberUser") as HTMLButtonElement)
          .disabled
      ).toBe(false)
    })
    expect(within(dialog).getByText("Carol")).toBeTruthy()
  })

  test("cancels removing a team member", async () => {
    const notifications = withNotifySpy()
    const teamWsMembers: WorkspaceMember[] = [
      { user: alice, role: "admin" },
      { user: dave, role: "member" },
    ]
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/teams/t-1/members",
        handle: () => jsonResponse(teamMembers),
      },
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(teamWsMembers),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "管理团队成员" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "管理团队成员" })
    await waitFor(() => expect(within(dialog).getByText("Carol")).toBeTruthy())
    const row = within(dialog)
      .getByText("Carol")
      .closest("div.rounded-lg") as HTMLElement
    fireEvent.click(within(row).getByRole("button", { name: "移除成员" }))
    await respondToConfirm("取消")
    expect(notifications).toEqual([])
    expect(within(dialog).getByText("Carol")).toBeTruthy()
  })

  test("reports an error when editing a team fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        method: "PATCH",
        path: "/api/v1/workspaces/ws-1/teams/t-1",
        handle: () => jsonResponse({ detail: "team edit failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "编辑团队" }))[0]
    )
    const dialog = await screen.findByRole("dialog", { name: "编辑团队" })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "team edit failed"])
    )
  })

  test("cancels deleting a team", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "永久删除团队" }))[0]
    )
    await respondToConfirm("取消")
    expect(notifications).toEqual([])
    expect(screen.getByText("Team One")).toBeTruthy()
  })

  test("reports an error loading team admin candidates", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse({ detail: "candidates failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="teams" />)
    fireEvent.click(await screen.findByRole("button", { name: "新建团队" }))
    const dialog = await screen.findByRole("dialog", { name: "新建团队" })
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "candidates failed"])
    )
    fireEvent.submit(formOf(dialog))
    expect(notifications).toContainEqual(["error", "请选择团队管理员"])
  })
})

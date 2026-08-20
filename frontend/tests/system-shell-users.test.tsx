/* @jsxImportSource react */
/**
 * DOM-level coverage for the SystemShell users tab: global admin user
 * management and the workspace-admin workspace user panel.
 *
 * Session is mocked (mutated per test); all backend traffic goes through
 * globalThis.fetch stubbed by a per-test route handler.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { act } from "@testing-library/react"

import { SystemShell } from "@/components/system/system-shell"
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

const team1: Team = {
  id: "t-1",
  workspace_id: "ws-1",
  name: "Team One",
  description: "",
  status: "active",
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

type Route = {
  method?: string
  path: string
  handle: (url: string, init?: RequestInit) => Response | Promise<Response>
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
  sessionState.teams = overrides.teams ?? [team1]
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

function userRow(name: string) {
  return screen.getByText(name).closest("[role=row]") as HTMLElement
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
// Global admin users tab
// ---------------------------------------------------------------------------

describe("global admin users tab", () => {
  test("loads the user list and filters by search, status, role and workspace", async () => {
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
    ])
    renderPage(<SystemShell activeTab="users" />)
    expect(await screen.findByText("Alice")).toBeTruthy()
    expect(screen.getByText("NexaFlow Admin")).toBeTruthy()
    expect(screen.getByText("Bob")).toBeTruthy()
    expect(screen.getByText("Carol")).toBeTruthy()
    expect(screen.getByText("Dave")).toBeTruthy()

    // Search by name/username/email.
    const search = screen.getByPlaceholderText("搜索姓名、账号、邮箱")
    fireEvent.change(search, { target: { value: "ali" } })
    expect(screen.getByText("Alice")).toBeTruthy()
    expect(screen.queryByText("Bob")).toBeNull()
    fireEvent.change(search, { target: { value: "dave@app.local" } })
    expect(screen.getByText("Dave")).toBeTruthy()
    expect(screen.queryByText("Alice")).toBeNull()
    fireEvent.change(search, { target: { value: "zzz" } })
    expect(screen.getByText("没有匹配的用户")).toBeTruthy()
    fireEvent.change(search, { target: { value: "" } })
    expect(screen.queryByText("没有匹配的用户")).toBeNull()

    // Status filter.
    await chooseDropdownOption(screen.getByLabelText("筛选用户状态"), "已停用")
    expect(screen.getByText("Carol")).toBeTruthy()
    expect(screen.queryByText("Alice")).toBeNull()
    await chooseDropdownOption(screen.getByLabelText("筛选用户状态"), "已启用")
    expect(screen.getByText("Alice")).toBeTruthy()

    // Role filter.
    await chooseDropdownOption(
      screen.getByLabelText("筛选用户角色"),
      "工作空间管理员"
    )
    expect(screen.getByText("Alice")).toBeTruthy()
    expect(screen.queryByText("Bob")).toBeNull()
    await chooseDropdownOption(
      screen.getByLabelText("筛选用户角色"),
      "团队管理员"
    )
    expect(screen.getByText("Bob")).toBeTruthy()
    expect(screen.queryByText("Alice")).toBeNull()
    await chooseDropdownOption(
      screen.getByLabelText("筛选用户角色"),
      "普通用户"
    )
    expect(screen.getByText("Dave")).toBeTruthy()
    expect(screen.queryByText("Alice")).toBeNull()

    // Reset the role filter before applying the workspace filter.
    await chooseDropdownOption(
      screen.getByLabelText("筛选用户角色"),
      "全部角色"
    )
    await chooseDropdownOption(
      screen.getByLabelText("筛选工作空间"),
      "Test Workspace"
    )
    expect(screen.getByText("Alice")).toBeTruthy()
    expect(screen.queryByText("Dave")).toBeNull()
    await chooseDropdownOption(
      screen.getByLabelText("筛选工作空间"),
      "全部工作空间"
    )
    expect(screen.getByText("Dave")).toBeTruthy()
  })

  test("reports a failure loading users and shows the empty state", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      {
        path: "/api/v1/admin/users",
        handle: () => jsonResponse({ detail: "users unavailable" }, 503),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "users unavailable"])
    )
    expect(await screen.findByText("暂无用户")).toBeTruthy()
  })

  test("creates a user with workspace, team and global-admin assignment", async () => {
    const notifications = withNotifySpy()
    const created: { body?: unknown; url?: string } = {}
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        path: "/api/v1/workspaces/ws-1/teams",
        handle: () => jsonResponse([team1]),
      },
      { path: "/api/v1/workspaces/ws-2/teams", handle: () => jsonResponse([]) },
      {
        method: "POST",
        path: "/api/v1/admin/users",
        handle: (url, init) => {
          created.body = JSON.parse(String(init?.body))
          created.url = url
          return jsonResponse({
            user: {
              ...carol,
              id: "u-9",
              username: "newbie",
              email: "newbie@app.local",
              name: "Newbie",
              workspaces: [
                {
                  id: "ws-1",
                  name: "Test Workspace",
                  is_default: true,
                  role: "member",
                },
              ],
              teams: [],
            },
            initial_password: "Init1pass",
          })
        },
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getByRole("button", { name: "新建用户" }))
    const dialog = await screen.findByRole("dialog", { name: "新建用户" })
    // Selected workspace (ws-1) preloads its teams.
    await waitFor(() =>
      expect(within(dialog).getByText("Team One")).toBeTruthy()
    )

    fireEvent.change(within(dialog).getByLabelText("姓名"), {
      target: { value: "Newbie" },
    })
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "newbie" },
    })
    fireEvent.change(within(dialog).getByLabelText("邮箱"), {
      target: { value: "newbie@app.local" },
    })

    // Switch workspace: teams refetch (empty note).
    await chooseDropdownOption(
      document.getElementById("newUserWorkspace") as HTMLElement,
      "Second Space"
    )
    await waitFor(() =>
      expect(within(dialog).getByText("该工作空间下暂无团队")).toBeTruthy()
    )
    // Back to ws-1: team checkbox appears.
    await chooseDropdownOption(
      document.getElementById("newUserWorkspace") as HTMLElement,
      "Test Workspace"
    )
    await waitFor(() =>
      expect(within(dialog).getByText("Team One")).toBeTruthy()
    )
    fireEvent.click(within(dialog).getByText("Team One"))
    fireEvent.click(within(dialog).getByText("全局管理员权限"))
    fireEvent.click(within(dialog).getByRole("button", { name: "新建" }))

    await waitFor(() => expect(created.url).not.toBeUndefined())
    expect(created.url).toBe("/api/v1/admin/users")
    expect(created.body).toEqual({
      username: "newbie",
      email: "newbie@app.local",
      name: "Newbie",
      is_global_admin: true,
      workspace_id: "ws-1",
      team_ids: ["t-1"],
    })
    expect(notifications).toContainEqual([
      "success",
      "用户已新建，初始密码：Init1pass",
    ])
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(screen.getByText("Newbie")).toBeTruthy())
  })

  test("create-user dialog handles an unspecified workspace", async () => {
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        path: "/api/v1/workspaces/ws-1/teams",
        handle: () => jsonResponse([team1]),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getByRole("button", { name: "新建用户" }))
    const dialog = await screen.findByRole("dialog", { name: "新建用户" })
    await waitFor(() =>
      expect(within(dialog).getByText("Team One")).toBeTruthy()
    )
    await chooseDropdownOption(
      document.getElementById("newUserWorkspace") as HTMLElement,
      "不指定工作空间"
    )
    expect(
      within(dialog).getByText("选择工作空间后可分配该空间下的团队")
    ).toBeTruthy()
    expect(within(dialog).queryByText("Team One")).toBeNull()
  })

  test("reports failures creating a user and loading its teams", async () => {
    const notifications = withNotifySpy()
    let teamsFetched = 0
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        path: "/api/v1/workspaces/ws-1/teams",
        handle: () => {
          teamsFetched += 1
          return jsonResponse({ detail: "teams failed" }, 500)
        },
      },
      {
        method: "POST",
        path: "/api/v1/admin/users",
        handle: () => jsonResponse({ detail: "duplicate user" }, 409),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getByRole("button", { name: "新建用户" }))
    const dialog = await screen.findByRole("dialog", { name: "新建用户" })
    // The initial team load fails → error notification.
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "teams failed"])
    )
    expect(teamsFetched).toBe(1)

    fireEvent.change(within(dialog).getByLabelText("姓名"), {
      target: { value: "Newbie" },
    })
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "newbie" },
    })
    fireEvent.change(within(dialog).getByLabelText("邮箱"), {
      target: { value: "newbie@app.local" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "新建" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "duplicate user"])
    )
    expect(screen.getByRole("dialog")).toBeTruthy()
  })

  test("edits a user and grants global admin after confirmation", async () => {
    const notifications = withNotifySpy()
    const patches: string[] = []
    let resolveUpdate: (response: Response) => void = () => undefined
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "PATCH",
        path: "/api/v1/admin/users/u-2",
        handle: (_url, init) => {
          patches.push(String(init?.body))
          return new Promise<Response>((resolve) => {
            resolveUpdate = resolve
          })
        },
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getAllByRole("button", { name: "编辑用户" })[1])
    const dialog = await screen.findByRole("dialog", { name: "编辑用户" })
    fireEvent.change(within(dialog).getByLabelText("姓名"), {
      target: { value: "Alice Renamed" },
    })
    fireEvent.click(within(dialog).getByRole("checkbox"))
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await respondToConfirm("确认")

    await waitFor(() => expect(patches).toHaveLength(1))
    await act(async () => {
      resolveUpdate(
        jsonResponse({
          ...alice,
          name: "Alice Renamed",
          is_global_admin: true,
        })
      )
    })
    expect(JSON.parse(patches[0])).toEqual({
      username: "alice",
      email: "alice@app.local",
      name: "Alice Renamed",
      is_global_admin: true,
    })
    expect(notifications).toContainEqual(["success", "用户已更新"])
    await waitFor(() => expect(screen.getByText("Alice Renamed")).toBeTruthy())
  })

  test("cancelling the global-admin confirmation skips the update", async () => {
    const notifications = withNotifySpy()
    const patches: string[] = []
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "PATCH",
        path: "/api/v1/admin/users/u-2",
        handle: (_url, init) => {
          patches.push(String(init?.body))
          return jsonResponse(alice)
        },
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getAllByRole("button", { name: "编辑用户" })[1])
    const dialog = await screen.findByRole("dialog", { name: "编辑用户" })
    fireEvent.click(within(dialog).getByRole("checkbox"))
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await respondToConfirm("取消")
    expect(patches).toEqual([])
    expect(notifications).toEqual([])
  })

  test("reports an error when updating a user fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "PATCH",
        path: "/api/v1/admin/users/u-2",
        handle: () => jsonResponse({ detail: "user update failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getAllByRole("button", { name: "编辑用户" })[1])
    const dialog = await screen.findByRole("dialog", { name: "编辑用户" })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "user update failed"])
    )
  })

  test("changes a user password with validation", async () => {
    const notifications = withNotifySpy()
    const posts: string[] = []
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "POST",
        path: "/api/v1/admin/users/u-2/change-password",
        handle: (_url, init) => {
          posts.push(String(init?.body))
          return jsonResponse({ ...alice, must_change_password: false })
        },
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getAllByRole("button", { name: "修改密码" })[1])
    const dialog = await screen.findByRole("dialog", { name: "修改密码" })

    // Mismatched passwords are rejected without a request.
    fireEvent.change(within(dialog).getByLabelText("新密码"), {
      target: { value: "Passw0rd" },
    })
    fireEvent.change(within(dialog).getByLabelText("确认密码"), {
      target: { value: "Different1" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "两次输入的新密码不一致"])
    )
    expect(posts).toEqual([])

    // Too-short passwords are rejected as well (native minLength validation
    // would block a button-triggered submit, so dispatch submit directly).
    fireEvent.change(within(dialog).getByLabelText("新密码"), {
      target: { value: "short" },
    })
    fireEvent.change(within(dialog).getByLabelText("确认密码"), {
      target: { value: "short" },
    })
    fireEvent.submit(dialog.querySelector("form") as HTMLFormElement)
    await waitFor(() =>
      expect(notifications).toContainEqual([
        "error",
        "密码至少 6 位，并且包含一个大写字母",
      ])
    )
    expect(posts).toEqual([])

    // Valid password submits the change request.
    fireEvent.change(within(dialog).getByLabelText("新密码"), {
      target: { value: "Passw0rd" },
    })
    fireEvent.change(within(dialog).getByLabelText("确认密码"), {
      target: { value: "Passw0rd" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(JSON.parse(posts[0])).toEqual({ new_password: "Passw0rd" })
    expect(notifications).toContainEqual(["success", "Alice 的密码已修改"])
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("reports an error when changing a password fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "POST",
        path: "/api/v1/admin/users/u-2/change-password",
        handle: () => jsonResponse({ detail: "password change failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.click(screen.getAllByRole("button", { name: "修改密码" })[1])
    const dialog = await screen.findByRole("dialog", { name: "修改密码" })
    fireEvent.change(within(dialog).getByLabelText("新密码"), {
      target: { value: "Passw0rd" },
    })
    fireEvent.change(within(dialog).getByLabelText("确认密码"), {
      target: { value: "Passw0rd" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "password change failed"])
    )
  })

  test("toggles a user active and inactive", async () => {
    const notifications = withNotifySpy()
    const patches: string[] = []
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "PATCH",
        path: "/api/v1/admin/users/u-2",
        handle: (_url, init) => {
          const body = JSON.parse(String(init?.body)) as { is_active: boolean }
          patches.push(String(init?.body))
          return jsonResponse({ ...alice, is_active: body.is_active })
        },
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")

    fireEvent.pointerDown(
      within(userRow("Alice")).getByRole("button", { name: "操作 Alice" })
    )
    fireEvent.click(within(await screen.findByRole("menu")).getByText("停用"))
    await waitFor(() =>
      expect(patches).toEqual([JSON.stringify({ is_active: false })])
    )
    expect(notifications).toContainEqual(["success", "用户已停用"])
    await waitFor(() =>
      expect(within(userRow("Alice")).getByText("已停用")).toBeTruthy()
    )

    fireEvent.pointerDown(
      within(userRow("Alice")).getByRole("button", { name: "操作 Alice" })
    )
    fireEvent.click(within(await screen.findByRole("menu")).getByText("启用"))
    await waitFor(() =>
      expect(patches).toContainEqual(JSON.stringify({ is_active: true }))
    )
    expect(notifications).toContainEqual(["success", "用户已启用"])
  })

  test("reports an error toggling a user", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "PATCH",
        path: "/api/v1/admin/users/u-2",
        handle: () => jsonResponse({ detail: "toggle failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Alice")
    fireEvent.pointerDown(
      within(userRow("Alice")).getByRole("button", { name: "操作 Alice" })
    )
    fireEvent.click(within(await screen.findByRole("menu")).getByText("停用"))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "toggle failed"])
    )
  })

  test("deletes a user after confirmation", async () => {
    const notifications = withNotifySpy()
    const deletes: string[] = []
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "DELETE",
        path: "/api/v1/admin/users/u-4",
        handle: (url) => {
          deletes.push(url)
          return jsonResponse(null, 204)
        },
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Carol")
    fireEvent.pointerDown(
      within(userRow("Carol")).getByRole("button", { name: "操作 Carol" })
    )
    fireEvent.click(within(await screen.findByRole("menu")).getByText("删除"))
    await respondToConfirm("删除")
    await waitFor(() => expect(deletes).toEqual(["/api/v1/admin/users/u-4"]))
    expect(notifications).toContainEqual(["success", "用户已删除"])
    await waitFor(() => expect(screen.queryByText("Carol")).toBeNull())
  })

  test("cancels deleting a user", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Carol")
    fireEvent.pointerDown(
      within(userRow("Carol")).getByRole("button", { name: "操作 Carol" })
    )
    fireEvent.click(within(await screen.findByRole("menu")).getByText("删除"))
    await respondToConfirm("取消")
    expect(notifications).toEqual([])
    expect(screen.getByText("Carol")).toBeTruthy()
  })

  test("reports an error when deleting a user fails", async () => {
    const notifications = withNotifySpy()
    handler = routeHandler([
      { path: "/api/v1/admin/users", handle: () => jsonResponse(allUsers) },
      {
        method: "DELETE",
        path: "/api/v1/admin/users/u-4",
        handle: () => jsonResponse({ detail: "delete failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await screen.findByText("Carol")
    fireEvent.pointerDown(
      within(userRow("Carol")).getByRole("button", { name: "操作 Carol" })
    )
    fireEvent.click(within(await screen.findByRole("menu")).getByText("删除"))
    await respondToConfirm("删除")
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "delete failed"])
    )
    expect(screen.getByText("Carol")).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// Workspace admin users tab
// ---------------------------------------------------------------------------

describe("workspace admin users tab", () => {
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

  test("lists workspace members and creates a workspace user", async () => {
    const notifications = withNotifySpy()
    const created: { body?: unknown; url?: string } = {}
    setSession({ me: wsAdminMe, selectedWorkspaceId: "ws-1" })
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse(wsMembers),
      },
      {
        method: "POST",
        path: "/api/v1/workspaces/ws-1/members/users",
        handle: (url, init) => {
          created.body = JSON.parse(String(init?.body))
          created.url = url
          return jsonResponse({
            user: {
              ...carol,
              id: "u-9",
              username: "newbie",
              email: "newbie@app.local",
              name: "Newbie",
              workspaces: [
                {
                  id: "ws-1",
                  name: "Test Workspace",
                  is_default: true,
                  role: "member",
                },
              ],
              teams: [],
            },
            initial_password: "Init1pass",
          })
        },
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    expect(await screen.findByText("Alice")).toBeTruthy()
    expect(screen.getByText("Carol")).toBeTruthy()
    expect(screen.getByRole("table", { name: "工作空间用户列表" })).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "新建用户" }))
    const dialog = await screen.findByRole("dialog", { name: "新建用户" })
    fireEvent.change(within(dialog).getByLabelText("姓名"), {
      target: { value: "Newbie" },
    })
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "newbie" },
    })
    fireEvent.change(within(dialog).getByLabelText("邮箱"), {
      target: { value: "newbie@app.local" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "新建" }))
    await waitFor(() => expect(created.url).not.toBeUndefined())
    expect(created.url).toBe("/api/v1/workspaces/ws-1/members/users")
    expect(created.body).toEqual({
      username: "newbie",
      email: "newbie@app.local",
      name: "Newbie",
    })
    expect(notifications).toContainEqual([
      "success",
      "用户已新建，初始密码：Init1pass",
    ])
    await waitFor(() => expect(screen.getByText("Newbie")).toBeTruthy())

    // The members dialog for a workspace admin has no add section.
    fireEvent.click(screen.getByRole("button", { name: "管理成员" }))
    const membersDialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    expect(within(membersDialog).getByText("Carol")).toBeTruthy()
    expect(within(membersDialog).queryByText("添加成员")).toBeNull()
  })

  test("reports a failure loading workspace users", async () => {
    const notifications = withNotifySpy()
    setSession({ me: wsAdminMe, selectedWorkspaceId: "ws-1" })
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/members",
        handle: () => jsonResponse({ detail: "members failed" }, 500),
      },
    ])
    renderPage(<SystemShell activeTab="users" />)
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "members failed"])
    )
    expect(await screen.findByText("暂无用户")).toBeTruthy()
  })

  test("workspace admin can still open the audit tab", async () => {
    setSession({ me: wsAdminMe, selectedWorkspaceId: "ws-1" })
    handler = routeHandler([
      {
        path: "/api/v1/workspaces/ws-1/audit-logs",
        handle: () => jsonResponse([]),
      },
    ])
    renderPage(<SystemShell activeTab="audit" />)
    expect(await screen.findByText("暂无审计日志")).toBeTruthy()
  })
})

/* @jsxImportSource react */
/**
 * DOM-level coverage for the global users panel and the workspace users
 * panel. Both panels are presentational (props are data + callbacks), so
 * they are rendered directly through renderPage with mocked session.
 */
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test"
import { useState } from "react"

import { GlobalUsersPanel } from "@/components/system/panels/global-users-panel"
import { WorkspaceUsersPanel } from "@/components/system/panels/workspace-users-panel"
import type { MeResponse, User } from "@/lib/api/auth"
import type {
  UserRoleFilter,
  UserStatusFilter,
  Workspace,
  WorkspaceMember,
} from "@/lib/api/system"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  within,
  type FetchHandler,
} from "./helpers/dom"

mockUseSession()
mockNextNavigation()

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u-9",
    username: "member",
    email: "member@app.local",
    name: "Member",
    is_global_admin: false,
    must_change_password: false,
    is_active: true,
    created_at: "2026-08-01T00:00:00Z",
    workspaces: [],
    teams: [],
    ...overrides,
  }
}

const ws1: Workspace = {
  id: "ws-1",
  name: "Test Workspace",
  description: "",
  status: "active",
  is_default: true,
}
const ws2: Workspace = {
  id: "ws-2",
  name: "Alpha",
  description: "",
  status: "active",
  is_default: false,
}
const wsDefault: Workspace = {
  id: "ws-3",
  name: "Default Workspace",
  description: "",
  status: "active",
  is_default: true,
}

// Me is the global admin; the row with id u-1 therefore has disabled actions.
const adminUser: User = user({
  id: "u-1",
  username: "root",
  email: "root@app.local",
  name: "Root",
  is_global_admin: true,
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" },
  ],
  teams: [
    { id: "team-1", workspace_id: "ws-1", name: "Platform", is_default: true, role: "admin" },
  ],
})
const adminMe: MeResponse = {
  user: adminUser,
  memberships: [{ workspace_id: "ws-1", role: "admin" }],
}

const globalUser: User = user({
  id: "u-1",
  username: "root",
  email: "root@app.local",
  name: "Root",
  is_global_admin: true,
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" },
  ],
  teams: [
    { id: "team-1", workspace_id: "ws-1", name: "Platform", is_default: true, role: "admin" },
  ],
})
const wsAdminUser: User = user({
  id: "u-2",
  username: "wsadmin",
  email: "ws@app.local",
  name: "Ws Admin",
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" },
  ],
})
const teamAdminUser: User = user({
  id: "u-3",
  username: "teamadmin",
  email: "team@app.local",
  name: "Team Admin",
  teams: [
    { id: "team-1", workspace_id: "ws-1", name: "Platform", is_default: true, role: "admin" },
  ],
})
const plainUser: User = user({
  id: "u-4",
  username: "plain",
  email: "plain@app.local",
  name: "Plain",
})
const offUser: User = user({
  id: "u-5",
  username: "off",
  email: "off@app.local",
  name: "Off",
  is_active: false,
})

const allUsers = [globalUser, wsAdminUser, teamAdminUser, plainUser, offUser]

const handler: FetchHandler = () => jsonResponse([], 200)

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

afterEach(() => {
  cleanup()
  resetFetch()
})

// ---------------------------------------------------------------------------
// GlobalUsersPanel harness (owns the filter state like the shell does)
// ---------------------------------------------------------------------------

type GlobalHarnessProps = {
  users?: User[]
  filteredUsers?: User[]
  workspaces?: Workspace[]
  isUsersLoading?: boolean
  me?: MeResponse
  onOpenCreateUser?: () => void
  onToggleUser?: (user: User) => void
  onOpenEditUser?: (user: User) => void
  onOpenUserPasswordDialog?: (user: User) => void
  onDeleteUser?: (user: User) => void
}

function GlobalHarness({
  users = allUsers,
  filteredUsers = allUsers,
  workspaces = [ws1, ws2, wsDefault],
  isUsersLoading = false,
  me = adminMe,
  onOpenCreateUser = () => undefined,
  onToggleUser = () => undefined,
  onOpenEditUser = () => undefined,
  onOpenUserPasswordDialog = () => undefined,
  onDeleteUser = () => undefined,
}: GlobalHarnessProps) {
  const [userSearch, setUserSearch] = useState("")
  const [userStatusFilter, setUserStatusFilter] =
    useState<UserStatusFilter>("all")
  const [userRoleFilter, setUserRoleFilter] = useState<UserRoleFilter>("all")
  const [userWorkspaceFilter, setUserWorkspaceFilter] = useState("all")

  return (
    <GlobalUsersPanel
      me={me}
      users={users}
      filteredUsers={filteredUsers}
      workspaces={workspaces}
      isUsersLoading={isUsersLoading}
      userSearch={userSearch}
      setUserSearch={setUserSearch}
      userStatusFilter={userStatusFilter}
      setUserStatusFilter={setUserStatusFilter}
      userRoleFilter={userRoleFilter}
      setUserRoleFilter={setUserRoleFilter}
      userWorkspaceFilter={userWorkspaceFilter}
      setUserWorkspaceFilter={setUserWorkspaceFilter}
      locale="zh-CN"
      handleOpenCreateUser={onOpenCreateUser}
      handleToggleUser={onToggleUser}
      handleOpenEditUser={onOpenEditUser}
      handleOpenUserPasswordDialog={onOpenUserPasswordDialog}
      handleDeleteUser={onDeleteUser}
    />
  )
}

async function openUserMenu(name: string) {
  const trigger = screen.getByRole("button", { name: `操作 ${name}` })
  fireEvent.pointerDown(trigger)
  return await screen.findByRole("menu")
}

// ---------------------------------------------------------------------------
// GlobalUsersPanel
// ---------------------------------------------------------------------------

describe("GlobalUsersPanel", () => {
  test("shows a loading spinner while users are loading", () => {
    renderPage(<GlobalHarness isUsersLoading users={[]} />)
    expect(document.querySelector(".animate-spin")).toBeTruthy()
    expect(screen.queryByRole("table")).toBeNull()
    // Header actions stay visible while loading.
    expect(screen.getByRole("button", { name: "新建用户" })).toBeTruthy()
    expect(screen.getByText("用户管理")).toBeTruthy()
    expect(screen.getByText("全局账号")).toBeTruthy()
  })

  test("renders an empty state when there are no users", () => {
    renderPage(<GlobalHarness users={[]} filteredUsers={[]} />)
    expect(screen.getByText("暂无用户")).toBeTruthy()
    expect(screen.queryByRole("table")).toBeNull()
  })

  test("renders every user variant with role, status, and joined names", () => {
    renderPage(<GlobalHarness />)
    expect(screen.getByRole("table", { name: "用户列表" })).toBeTruthy()
    expect(screen.getAllByRole("row").length).toBe(6) // header + 5 users

    // Basic identity columns.
    for (const u of allUsers) {
      expect(screen.getByText(u.name)).toBeTruthy()
      expect(screen.getByText(u.username)).toBeTruthy()
      expect(screen.getByText(u.email)).toBeTruthy()
    }

    // Workspace / team cells, including the "-" fallbacks.
    expect(screen.getAllByText("Test Workspace").length).toBe(2)
    expect(screen.getAllByText("Platform").length).toBe(2)
    expect(screen.getAllByText("-").length).toBe(6)

    // Role labels for every variant.
    expect(screen.getAllByText("全局管理员").length).toBe(1)
    expect(screen.getAllByText("工作空间管理员").length).toBe(1)
    expect(screen.getAllByText("团队管理员").length).toBe(1)
    expect(screen.getAllByText("普通用户").length).toBe(2)

    // Status variants.
    expect(screen.getAllByText("已启用").length).toBe(4)
    expect(screen.getByText("已停用")).toBeTruthy()

    // Formatted creation dates.
    expect(screen.getAllByText(/2026/).length).toBe(5)

    // Per-row actions.
    expect(screen.getAllByRole("button", { name: "编辑用户" }).length).toBe(5)
    expect(screen.getAllByRole("button", { name: "修改密码" }).length).toBe(5)
  })

  test("updates the search input through onChange", () => {
    renderPage(<GlobalHarness />)
    const input = screen.getByPlaceholderText(
      "搜索姓名、账号、邮箱"
    ) as HTMLInputElement
    fireEvent.change(input, { target: { value: "alice" } })
    expect(input.value).toBe("alice")
    fireEvent.change(input, { target: { value: "" } })
    expect(input.value).toBe("")
  })

  test("status filter selects 全部状态 / 已启用 / 已停用", async () => {
    renderPage(<GlobalHarness />)
    const statusTrigger = screen.getByRole("button", {
      name: "筛选用户状态",
    })
    expect(statusTrigger.textContent).toContain("全部状态")

    fireEvent.pointerDown(statusTrigger)
    let menu = await screen.findByRole("menu")
    fireEvent.click(within(menu).getByText("已停用"))
    await waitFor(() =>
      expect(statusTrigger.textContent).toContain("已停用")
    )

    fireEvent.pointerDown(statusTrigger)
    menu = await screen.findByRole("menu")
    fireEvent.click(within(menu).getByText("已启用"))
    await waitFor(() =>
      expect(statusTrigger.textContent).toContain("已启用")
    )

    fireEvent.pointerDown(statusTrigger)
    menu = await screen.findByRole("menu")
    fireEvent.click(within(menu).getByText("全部状态"))
    await waitFor(() =>
      expect(statusTrigger.textContent).toContain("全部状态")
    )
  })

  test("role filter selects 全局管理员 / 工作空间管理员 / 团队管理员 / 普通用户", async () => {
    renderPage(<GlobalHarness />)
    const roleTrigger = screen.getByRole("button", { name: "筛选用户角色" })
    expect(roleTrigger.textContent).toContain("全部角色")

    for (const label of ["全局管理员", "工作空间管理员", "团队管理员", "普通用户"]) {
      fireEvent.pointerDown(roleTrigger)
      const menu = await screen.findByRole("menu")
      fireEvent.click(within(menu).getByText(label))
      await waitFor(() => expect(roleTrigger.textContent).toContain(label))
    }
  })

  test("workspace filter lists workspaces and reports selections", async () => {
    renderPage(<GlobalHarness />)
    const wsTrigger = screen.getByRole("button", { name: "筛选工作空间" })
    expect(wsTrigger.textContent).toContain("全部工作空间")

    fireEvent.pointerDown(wsTrigger)
    let menu = await screen.findByRole("menu")
    // Default workspace name is translated.
    expect(within(menu).getByText("默认工作空间")).toBeTruthy()
    fireEvent.click(within(menu).getByText("Alpha"))
    await waitFor(() => expect(wsTrigger.textContent).toContain("Alpha"))

    fireEvent.pointerDown(wsTrigger)
    menu = await screen.findByRole("menu")
    fireEvent.click(within(menu).getByText("全部工作空间"))
    await waitFor(() =>
      expect(wsTrigger.textContent).toContain("全部工作空间")
    )
  })

  test("新建用户 button invokes the create-user callback", () => {
    const onOpenCreateUser = mock<() => void>()
    renderPage(<GlobalHarness onOpenCreateUser={onOpenCreateUser} />)
    fireEvent.click(screen.getByRole("button", { name: "新建用户" }))
    expect(onOpenCreateUser).toHaveBeenCalled()
  })

  test("edit and password action buttons pass the row user", () => {
    const onOpenEditUser = mock<(user: User) => void>()
    const onOpenUserPasswordDialog = mock<(user: User) => void>()
    renderPage(
      <GlobalHarness
        onOpenEditUser={onOpenEditUser}
        onOpenUserPasswordDialog={onOpenUserPasswordDialog}
      />
    )
    const rows = screen.getAllByRole("row")
    fireEvent.click(within(rows[2]).getByRole("button", { name: "编辑用户" }))
    expect(onOpenEditUser).toHaveBeenCalledWith(wsAdminUser)

    fireEvent.click(within(rows[3]).getByRole("button", { name: "修改密码" }))
    expect(onOpenUserPasswordDialog).toHaveBeenCalledWith(teamAdminUser)
  })

  test("toggle menu disables a user through 停用 and reactivates through 启用", async () => {
    const onToggleUser = mock<(user: User) => void>()
    renderPage(<GlobalHarness onToggleUser={onToggleUser} />)

    const menu = await openUserMenu("Plain")
    fireEvent.click(within(menu).getByText("停用"))
    await waitFor(() => expect(onToggleUser).toHaveBeenCalledWith(plainUser))

    const menu2 = await openUserMenu("Off")
    fireEvent.click(within(menu2).getByText("启用"))
    await waitFor(() => expect(onToggleUser).toHaveBeenCalledWith(offUser))
  })

  test("delete menu item invokes the delete callback", async () => {
    const onDeleteUser = mock<(user: User) => void>()
    renderPage(<GlobalHarness onDeleteUser={onDeleteUser} />)

    const menu = await openUserMenu("Team Admin")
    fireEvent.click(within(menu).getByText("删除"))
    await waitFor(() =>
      expect(onDeleteUser).toHaveBeenCalledWith(teamAdminUser)
    )
  })

  test("disables toggle/delete for the current user row", async () => {
    const onToggleUser = mock<(user: User) => void>()
    const onDeleteUser = mock<(user: User) => void>()
    renderPage(
      <GlobalHarness onToggleUser={onToggleUser} onDeleteUser={onDeleteUser} />
    )

    const menu = await openUserMenu("Root")
    const toggleItem = within(menu)
      .getByText("停用")
      .closest("[data-slot='dropdown-menu-item']")!
    const deleteItem = within(menu)
      .getByText("删除")
      .closest("[data-slot='dropdown-menu-item']")!
    expect(toggleItem.getAttribute("data-disabled")).not.toBeNull()
    expect(deleteItem.getAttribute("data-disabled")).not.toBeNull()

    // Disabled items never fire their handlers.
    fireEvent.click(toggleItem)
    fireEvent.click(deleteItem)
    expect(onToggleUser).not.toHaveBeenCalled()
    expect(onDeleteUser).not.toHaveBeenCalled()
  })

  test("shows the no-match message when filters exclude every user", () => {
    renderPage(<GlobalHarness filteredUsers={[]} />)
    expect(screen.getByText("没有匹配的用户")).toBeTruthy()
    expect(screen.getByRole("table")).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// WorkspaceUsersPanel
// ---------------------------------------------------------------------------

function renderWorkspacePanel(overrides: Partial<{
  selectedWorkspace: Workspace | null
  selectedWorkspaceId: string | null
  workspaceMembers: WorkspaceMember[]
  isWorkspaceMembersLoading: boolean
  handleOpenCreateUser: () => void
  handleOpenWorkspaceMembers: () => void
}> = {}) {
  const props = {
    selectedWorkspace: ws1,
    selectedWorkspaceId: "ws-1",
    workspaceMembers: [] as WorkspaceMember[],
    isWorkspaceMembersLoading: false,
    locale: "zh-CN",
    handleOpenCreateUser: () => undefined,
    handleOpenWorkspaceMembers: () => undefined,
    ...overrides,
  }
  return renderPage(<WorkspaceUsersPanel {...props} />)
}

describe("WorkspaceUsersPanel", () => {
  test("shows the workspace name and enables member actions", () => {
    const onOpenCreateUser = mock<() => void>()
    const onOpenWorkspaceMembers = mock<() => void>()
    renderWorkspacePanel({
      handleOpenCreateUser: onOpenCreateUser,
      handleOpenWorkspaceMembers: onOpenWorkspaceMembers,
    })

    expect(screen.getByText("用户管理")).toBeTruthy()
    expect(screen.getByText("Test Workspace")).toBeTruthy()

    const membersButton = screen.getByRole("button", {
      name: "管理成员",
    }) as HTMLButtonElement
    const createButton = screen.getByRole("button", {
      name: "新建用户",
    }) as HTMLButtonElement
    expect(membersButton.disabled).toBe(false)
    expect(createButton.disabled).toBe(false)

    fireEvent.click(membersButton)
    expect(onOpenWorkspaceMembers).toHaveBeenCalled()
    fireEvent.click(createButton)
    expect(onOpenCreateUser).toHaveBeenCalled()
  })

  test("without a selected workspace shows 未选择工作空间 and disables actions", () => {
    renderWorkspacePanel({
      selectedWorkspace: null,
      selectedWorkspaceId: null,
    })
    expect(screen.getByText("未选择工作空间")).toBeTruthy()
    expect(
      (screen.getByRole("button", { name: "管理成员" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(
      (screen.getByRole("button", { name: "新建用户" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
  })

  test("keeps actions disabled when only the workspace id is missing", () => {
    renderWorkspacePanel({ selectedWorkspaceId: null })
    expect(screen.getByText("Test Workspace")).toBeTruthy()
    expect(
      (screen.getByRole("button", { name: "管理成员" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(
      (screen.getByRole("button", { name: "新建用户" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
  })

  test("shows a loading spinner while members load", () => {
    renderWorkspacePanel({ isWorkspaceMembersLoading: true })
    expect(document.querySelector(".animate-spin")).toBeTruthy()
    expect(screen.queryByRole("table")).toBeNull()
  })

  test("renders member rows with roles, statuses, and dates", () => {
    const activeAdmin: WorkspaceMember = {
      user: user({
        id: "m-1",
        username: "alice",
        email: "alice@app.local",
        name: "Alice",
      }),
      role: "admin",
    }
    const inactiveMember: WorkspaceMember = {
      user: user({
        id: "m-2",
        username: "bob",
        email: "bob@app.local",
        name: "Bob",
        is_active: false,
      }),
      role: "member",
    }
    renderWorkspacePanel({
      workspaceMembers: [activeAdmin, inactiveMember],
    })

    expect(screen.getByRole("table", { name: "工作空间用户列表" })).toBeTruthy()
    expect(screen.getAllByRole("row").length).toBe(3) // header + 2 members
    expect(screen.getByText("Alice")).toBeTruthy()
    expect(screen.getByText("alice")).toBeTruthy()
    expect(screen.getByText("alice@app.local")).toBeTruthy()
    expect(screen.getByText("Bob")).toBeTruthy()
    expect(screen.getByText("管理员")).toBeTruthy()
    expect(screen.getByText("成员")).toBeTruthy()
    expect(screen.getByText("已启用")).toBeTruthy()
    expect(screen.getByText("已停用")).toBeTruthy()
    expect(screen.getAllByText(/2026/).length).toBe(2)
  })

  test("shows an empty state when the workspace has no members", () => {
    renderWorkspacePanel()
    expect(screen.getByText("暂无用户")).toBeTruthy()
    expect(screen.queryByRole("table")).toBeNull()
  })
})

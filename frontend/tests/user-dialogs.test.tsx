/* @jsxImportSource react */
/**
 * DOM-level coverage for the user management dialogs (create / edit /
 * password). The dialogs are controlled components, so each is driven
 * through a small stateful harness that mirrors how system-shell wires them.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { useState, type FormEvent } from "react"
import { act } from "@testing-library/react"

import {
  CreateUserDialog,
  EditUserDialog,
  UserPasswordDialog,
} from "@/components/system/dialogs/user-dialogs"
import type { MeResponse, User } from "@/lib/api/auth"
import {
  listTeams,
  type Team,
  type UserCreateForm,
  type UserForm,
  type UserPasswordForm,
  type Workspace,
} from "@/lib/api/system"
import { getNewPasswordError } from "@/lib/password"
import { translate, type TFunction } from "@/i18n"
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

const adminUser: User = {
  id: "u-1",
  username: "root",
  email: "root@app.local",
  name: "Root",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [],
  teams: [],
}
const adminMe: MeResponse = { user: adminUser, memberships: [] }

const memberUser: User = {
  ...adminUser,
  id: "u-2",
  username: "operator",
  name: "Operator",
  is_global_admin: false,
}
const memberMe: MeResponse = {
  user: memberUser,
  memberships: [{ workspace_id: "ws-1", role: "admin" }],
}

const ws1: Workspace = {
  id: "ws-1",
  name: "Alpha",
  description: "",
  status: "active",
  is_default: true,
}
const ws2: Workspace = {
  id: "ws-2",
  name: "Beta",
  description: "",
  status: "active",
  is_default: false,
}

const teamA: Team = {
  id: "t-1",
  workspace_id: "ws-1",
  name: "Platform",
  description: "",
  status: "active",
  is_default: true,
}
const teamB: Team = {
  id: "t-2",
  workspace_id: "ws-1",
  name: "Growth",
  description: "",
  status: "active",
  is_default: false,
}

const editForm: UserForm = {
  id: "u-4",
  username: "alice",
  email: "alice@app.local",
  name: "Alice",
  isGlobalAdmin: false,
}

const passwordForm: UserPasswordForm = {
  user: memberUser,
  newPassword: "",
  confirmPassword: "",
}

let handler: FetchHandler = () => jsonResponse([], 200)

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
// CreateUserDialog harness — mirrors system-shell wiring, including the
// fetch-driven team loading for the selected workspace.
// ---------------------------------------------------------------------------

type CreateHarnessProps = {
  me?: MeResponse
  activeWorkspaces?: Workspace[]
  selectedWorkspaceId?: string | null
  isCreatingUser?: boolean
  initialOpen?: boolean
  onSubmit?: (form: UserCreateForm) => void
}

function CreateHarness({
  me = adminMe,
  activeWorkspaces = [ws1, ws2],
  selectedWorkspaceId = null,
  isCreatingUser = false,
  initialOpen = true,
  onSubmit = () => undefined,
}: CreateHarnessProps) {
  const [open, setOpen] = useState(initialOpen)
  const [form, setForm] = useState<UserCreateForm>({
    username: "",
    email: "",
    name: "",
    workspaceId: "",
    teamIds: [],
    isGlobalAdmin: false,
  })
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [teams, setTeams] = useState<Team[]>([])
  const [teamsLoading, setTeamsLoading] = useState(false)

  function handleWorkspaceChange(workspaceId: string) {
    setForm((current) => ({ ...current, workspaceId, teamIds: [] }))
    setWorkspace(
      activeWorkspaces.find((active) => active.id === workspaceId) ?? null
    )
    if (workspaceId) {
      setTeamsLoading(true)
      setTeams([])
      void listTeams("test-token", workspaceId)
        .then((loaded) => {
          setTeams(loaded)
          setTeamsLoading(false)
        })
        .catch(() => setTeamsLoading(false))
    } else {
      setTeams([])
      setTeamsLoading(false)
    }
  }

  function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit(form)
  }

  return (
    <CreateUserDialog
      isUserCreateDialogOpen={open}
      setIsUserCreateDialogOpen={setOpen}
      userCreateForm={form}
      setUserCreateForm={setForm}
      userCreateWorkspace={workspace}
      userCreateTeams={teams}
      isUserCreateTeamsLoading={teamsLoading}
      activeWorkspaces={activeWorkspaces}
      me={me}
      selectedWorkspaceId={selectedWorkspaceId}
      isCreatingUser={isCreatingUser}
      handleCreateUser={handleCreateUser}
      handleUserCreateWorkspaceChange={handleWorkspaceChange}
    />
  )
}

async function openWorkspaceDropdown() {
  const trigger = screen.getByRole("button", { name: /工作空间/ })
  fireEvent.pointerDown(trigger)
  return { trigger, menu: await screen.findByRole("menu") }
}

// ---------------------------------------------------------------------------
// CreateUserDialog
// ---------------------------------------------------------------------------

describe("CreateUserDialog", () => {
  test("renders the create form for a global administrator", () => {
    renderPage(<CreateHarness />)
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("新建用户")).toBeTruthy()
    expect(
      within(dialog).getByText("创建账号并分配工作空间与团队")
    ).toBeTruthy()
    expect(within(dialog).getByText("基本信息")).toBeTruthy()

    expect(within(dialog).getByLabelText("姓名")).toBeTruthy()
    expect(within(dialog).getByLabelText("用户名")).toBeTruthy()
    expect(within(dialog).getByLabelText("邮箱")).toBeTruthy()

    const workspaceTrigger = within(dialog).getByRole("button", {
      name: /不指定工作空间/,
    })
    expect(workspaceTrigger.textContent).toContain("不指定工作空间")

    const adminCheckbox = within(dialog).getByLabelText(/全局管理员权限/)
    expect((adminCheckbox as HTMLInputElement).checked).toBe(false)

    expect(
      within(dialog).getByText("选择工作空间后可分配该空间下的团队")
    ).toBeTruthy()

    const submit = within(dialog).getByRole("button", {
      name: "新建",
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(false)
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeTruthy()
  })

  test("updates the basic-info fields through onChange", () => {
    renderPage(<CreateHarness />)
    const dialog = screen.getByRole("dialog")

    const name = within(dialog).getByLabelText("姓名") as HTMLInputElement
    const username = within(dialog).getByLabelText("用户名") as HTMLInputElement
    const email = within(dialog).getByLabelText("邮箱") as HTMLInputElement

    fireEvent.change(name, { target: { value: "Alice" } })
    fireEvent.change(username, { target: { value: "alice" } })
    fireEvent.change(email, { target: { value: "alice@app.local" } })

    expect(name.value).toBe("Alice")
    expect(username.value).toBe("alice")
    expect(email.value).toBe("alice@app.local")
  })

  test("toggles the global-admin checkbox", () => {
    renderPage(<CreateHarness />)
    const checkbox = screen.getByLabelText(/全局管理员权限/) as HTMLInputElement
    fireEvent.click(checkbox)
    expect(checkbox.checked).toBe(true)
    fireEvent.click(checkbox)
    expect(checkbox.checked).toBe(false)
  })

  test("selects a workspace, loads teams via fetch, and checks team checkboxes", async () => {
    handler = (url) => {
      if (url.includes("/teams")) {
        return jsonResponse([teamA, teamB])
      }
      return jsonResponse([], 200)
    }
    renderPage(<CreateHarness />)
    const dialog = screen.getByRole("dialog")

    const { trigger, menu } = await openWorkspaceDropdown()
    // Default workspace gets a badge; both options are listed.
    expect(within(menu).getByText("默认")).toBeTruthy()
    expect(within(menu).getByText("Alpha")).toBeTruthy()
    expect(within(menu).getByText("Beta")).toBeTruthy()

    fireEvent.click(within(menu).getByText("Alpha"))
    await waitFor(() => expect(trigger.textContent).toContain("Alpha"))

    // Teams arrive through the stubbed fetch and render as checkboxes.
    const platform = await waitFor(() =>
      within(dialog).getByLabelText("Platform")
    )
    const growth = within(dialog).getByLabelText("Growth") as HTMLInputElement
    expect((platform as HTMLInputElement).checked).toBe(false)
    fireEvent.click(platform)
    expect((platform as HTMLInputElement).checked).toBe(true)
    fireEvent.click(growth)
    expect((growth as HTMLInputElement).checked).toBe(true)
    // Unchecking removes the team id again.
    fireEvent.click(growth)
    expect((growth as HTMLInputElement).checked).toBe(false)
    fireEvent.click(growth)
    expect((growth as HTMLInputElement).checked).toBe(true)

    // The dialog must have stayed open through the dropdown interaction.
    expect(screen.getByRole("dialog")).toBeTruthy()
  })

  test("stays open for interactions inside dropdown-menu content", async () => {
    renderPage(<CreateHarness />)
    expect(screen.getByRole("dialog")).toBeTruthy()
    // Let Radix's deferred document-level listeners (setTimeout 0) register.
    const { promise, resolve } = Promise.withResolvers<void>()
    setTimeout(resolve, 0)
    await promise

    // A pointer interaction originating from dropdown-menu content (a portal
    // outside the dialog's React tree) must not dismiss the dialog: the
    // onInteractOutside guard recognizes the dropdown-menu content.
    const fake = document.createElement("div")
    fake.setAttribute("data-slot", "dropdown-menu-content")
    document.body.appendChild(fake)
    try {
      fireEvent.pointerDown(fake)
      fireEvent.click(fake)
      expect(screen.getByRole("dialog")).toBeTruthy()
    } finally {
      fake.remove()
    }
  })

  test("shows a loading state while teams are being fetched", async () => {
    let resolveTeams: ((response: Response) => void) | null = null
    handler = (url) => {
      if (url.includes("/teams")) {
        const { promise, resolve } = Promise.withResolvers<Response>()
        resolveTeams = resolve
        return promise
      }
      return jsonResponse([], 200)
    }
    renderPage(<CreateHarness />)

    const { menu } = await openWorkspaceDropdown()
    fireEvent.click(within(menu).getByText("Alpha"))
    await waitFor(() =>
      expect(document.querySelector("svg.lucide-loader-circle")).toBeTruthy()
    )

    await act(async () => {
      resolveTeams?.(jsonResponse([teamA]))
      await Promise.resolve()
    })
    await waitFor(() =>
      expect(screen.getByLabelText("Platform")).toBeTruthy()
    )
  })

  test("shows the empty-teams hint for a workspace without teams", async () => {
    handler = (url) => {
      if (url.includes("/teams")) {
        return jsonResponse([])
      }
      return jsonResponse([], 200)
    }
    renderPage(<CreateHarness />)

    const { menu } = await openWorkspaceDropdown()
    fireEvent.click(within(menu).getByText("Beta"))
    await waitFor(() =>
      expect(screen.getByText("该工作空间下暂无团队")).toBeTruthy()
    )
  })

  test("unspecifying the workspace resets the teams section", async () => {
    handler = (url) => {
      if (url.includes("/teams")) {
        return jsonResponse([teamA])
      }
      return jsonResponse([], 200)
    }
    renderPage(<CreateHarness />)

    const { trigger, menu } = await openWorkspaceDropdown()
    fireEvent.click(within(menu).getByText("Alpha"))
    await waitFor(() => expect(screen.getByLabelText("Platform")).toBeTruthy())

    const second = await openWorkspaceDropdown()
    fireEvent.click(within(second.menu).getByText("不指定工作空间"))
    await waitFor(() =>
      expect(
        screen.getByText("选择工作空间后可分配该空间下的团队")
      ).toBeTruthy()
    )
    expect(trigger.textContent).toContain("不指定工作空间")
    expect(screen.queryByLabelText("Platform")).toBeNull()
  })

  test("submits the form with the collected payload", async () => {
    handler = (url) => {
      if (url.includes("/teams")) {
        return jsonResponse([teamA, teamB])
      }
      return jsonResponse([], 200)
    }
    const submitted: UserCreateForm[] = []
    renderPage(
      <CreateHarness
        onSubmit={(form) => {
          submitted.push(form)
        }}
      />
    )
    const dialog = screen.getByRole("dialog")

    fireEvent.change(within(dialog).getByLabelText("姓名"), {
      target: { value: "Alice" },
    })
    fireEvent.change(within(dialog).getByLabelText("用户名"), {
      target: { value: "alice" },
    })
    fireEvent.change(within(dialog).getByLabelText("邮箱"), {
      target: { value: "alice@app.local" },
    })
    fireEvent.click(within(dialog).getByLabelText(/全局管理员权限/))

    const { menu } = await openWorkspaceDropdown()
    fireEvent.click(within(menu).getByText("Alpha"))
    const platform = await waitFor(() =>
      within(dialog).getByLabelText("Platform")
    )
    fireEvent.click(platform)

    fireEvent.click(within(dialog).getByRole("button", { name: "新建" }))
    expect(submitted[0]).toEqual({
      username: "alice",
      email: "alice@app.local",
      name: "Alice",
      workspaceId: "ws-1",
      teamIds: ["t-1"],
      isGlobalAdmin: true,
    })
  })

  test("disables the submit button and shows a spinner while creating", () => {
    renderPage(<CreateHarness isCreatingUser />)
    const submit = screen.getByRole("button", {
      name: "新建",
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    expect(document.querySelector("svg.lucide-loader-circle")).toBeTruthy()
  })

  test("cancels the dialog through the 取消 button", async () => {
    renderPage(<CreateHarness />)
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("does not render while closed", () => {
    renderPage(<CreateHarness initialOpen={false} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("hides admin-only sections for a non-global administrator", () => {
    renderPage(<CreateHarness me={memberMe} />)
    const dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getByText("创建普通账号并加入当前工作空间")
    ).toBeTruthy()
    expect(within(dialog).queryByRole("button", { name: /不指定工作空间/ })).toBeNull()
    expect(within(dialog).queryByLabelText(/全局管理员权限/)).toBeNull()
    expect(within(dialog).queryByText("团队")).toBeNull()

    // Without a selected workspace the submit action stays disabled.
    const submit = within(dialog).getByRole("button", {
      name: "新建",
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
  })

  test("enables the submit button for a workspace admin with a selected workspace", () => {
    renderPage(<CreateHarness me={memberMe} selectedWorkspaceId="ws-1" />)
    const submit = screen.getByRole("button", {
      name: "新建",
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// EditUserDialog harness
// ---------------------------------------------------------------------------

type EditHarnessProps = {
  canManageGlobalAdmin?: boolean
  isSavingUser?: boolean
  initialForm?: UserForm | null
  onSubmit?: (form: UserForm) => void
}

function EditHarness({
  canManageGlobalAdmin = true,
  isSavingUser = false,
  initialForm = editForm,
  onSubmit = () => undefined,
}: EditHarnessProps) {
  const [form, setForm] = useState<UserForm | null>(initialForm)

  function handleUpdateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (form) {
      onSubmit(form)
    }
  }

  return (
    <EditUserDialog
      userForm={form}
      setUserForm={setForm}
      canManageGlobalAdmin={canManageGlobalAdmin}
      isSavingUser={isSavingUser}
      handleUpdateUser={handleUpdateUser}
    />
  )
}

describe("EditUserDialog", () => {
  test("renders prefilled fields and toggles the admin checkbox", () => {
    renderPage(<EditHarness />)
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("编辑用户")).toBeTruthy()
    expect(within(dialog).getByText("更新账号基础信息")).toBeTruthy()

    const name = within(dialog).getByLabelText("姓名") as HTMLInputElement
    const username = within(dialog).getByLabelText("账号") as HTMLInputElement
    const email = within(dialog).getByLabelText("邮箱") as HTMLInputElement
    expect(name.value).toBe("Alice")
    expect(username.value).toBe("alice")
    expect(email.value).toBe("alice@app.local")

    const checkbox = within(dialog).getByLabelText(/全局管理员权限/) as HTMLInputElement
    expect(checkbox.checked).toBe(false)
    fireEvent.click(checkbox)
    expect(checkbox.checked).toBe(true)
    fireEvent.click(checkbox)
    expect(checkbox.checked).toBe(false)

    fireEvent.change(name, { target: { value: "Alicia" } })
    expect(name.value).toBe("Alicia")

    fireEvent.change(username, { target: { value: "alicia" } })
    fireEvent.change(email, { target: { value: "alicia@app.local" } })
    expect(username.value).toBe("alicia")
    expect(email.value).toBe("alicia@app.local")
  })

  test("hides the admin checkbox without global-admin management rights", () => {
    renderPage(<EditHarness canManageGlobalAdmin={false} />)
    expect(screen.queryByLabelText(/全局管理员权限/)).toBeNull()
  })

  test("submits the updated user", () => {
    const submitted: UserForm[] = []
    renderPage(
      <EditHarness
        onSubmit={(form) => {
          submitted.push(form)
        }}
      />
    )
    const dialog = screen.getByRole("dialog")

    fireEvent.change(within(dialog).getByLabelText("姓名"), {
      target: { value: "Alicia" },
    })
    fireEvent.click(within(dialog).getByLabelText(/全局管理员权限/))
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    expect(submitted[0]).toEqual({
      id: "u-4",
      username: "alice",
      email: "alice@app.local",
      name: "Alicia",
      isGlobalAdmin: true,
    })
  })

  test("cancels the dialog through the 取消 button", async () => {
    renderPage(<EditHarness />)
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("closes the dialog on escape", async () => {
    renderPage(<EditHarness />)
    expect(screen.getByRole("dialog")).toBeTruthy()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("disables the save button and shows a spinner while saving", () => {
    renderPage(<EditHarness isSavingUser />)
    const save = screen.getByRole("button", {
      name: "保存",
    }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    expect(document.querySelector("svg.lucide-loader-circle")).toBeTruthy()
  })

  test("does not render while closed", () => {
    renderPage(<EditHarness initialForm={null} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// UserPasswordDialog harness
// ---------------------------------------------------------------------------

type PasswordHarnessProps = {
  isChangingUserPassword?: boolean
  initialForm?: UserPasswordForm | null
  onSubmit?: (form: UserPasswordForm) => void
}

function PasswordHarness({
  isChangingUserPassword = false,
  initialForm = passwordForm,
  onSubmit = () => undefined,
}: PasswordHarnessProps) {
  const [form, setForm] = useState<UserPasswordForm | null>(initialForm)

  function handleChangeUserPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (form) {
      onSubmit(form)
    }
  }

  return (
    <UserPasswordDialog
      userPasswordForm={form}
      setUserPasswordForm={setForm}
      isChangingUserPassword={isChangingUserPassword}
      handleChangeUserPassword={handleChangeUserPassword}
    />
  )
}

describe("UserPasswordDialog", () => {
  test("renders the password form for the named user", () => {
    renderPage(<PasswordHarness />)
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("修改密码")).toBeTruthy()
    expect(within(dialog).getByText("为 Operator 设置新密码")).toBeTruthy()
    expect(
      within(dialog).getByText("至少 6 位，并且包含一个大写字母")
    ).toBeTruthy()

    const newPassword = within(dialog).getByLabelText(
      "新密码"
    ) as HTMLInputElement
    const confirm = within(dialog).getByLabelText(
      "确认密码"
    ) as HTMLInputElement
    expect(newPassword.type).toBe("password")
    expect(confirm.type).toBe("password")
    expect(newPassword.minLength).toBe(6)
  })

  test("updates the password fields through onChange", () => {
    renderPage(<PasswordHarness />)
    const dialog = screen.getByRole("dialog")
    const newPassword = within(dialog).getByLabelText(
      "新密码"
    ) as HTMLInputElement
    const confirm = within(dialog).getByLabelText(
      "确认密码"
    ) as HTMLInputElement

    fireEvent.change(newPassword, { target: { value: "Abcdef1" } })
    fireEvent.change(confirm, { target: { value: "Abcdef1" } })
    expect(newPassword.value).toBe("Abcdef1")
    expect(confirm.value).toBe("Abcdef1")
  })

  test("submits the new password", () => {
    const submitted: UserPasswordForm[] = []
    renderPage(
      <PasswordHarness
        onSubmit={(form) => {
          submitted.push(form)
        }}
      />
    )
    const dialog = screen.getByRole("dialog")
    fireEvent.change(within(dialog).getByLabelText("新密码"), {
      target: { value: "Abcdef1" },
    })
    fireEvent.change(within(dialog).getByLabelText("确认密码"), {
      target: { value: "Abcdef1" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    expect(submitted[0]?.newPassword).toBe("Abcdef1")
    expect(submitted[0]?.confirmPassword).toBe("Abcdef1")
    expect(submitted[0]?.user).toBe(memberUser)
  })

  test("cancels the dialog through the 取消 button", async () => {
    renderPage(<PasswordHarness />)
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("closes the dialog on escape", async () => {
    renderPage(<PasswordHarness />)
    expect(screen.getByRole("dialog")).toBeTruthy()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("disables the save button and shows a spinner while changing", () => {
    renderPage(<PasswordHarness isChangingUserPassword />)
    const save = screen.getByRole("button", {
      name: "保存",
    }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    expect(document.querySelector("svg.lucide-loader-circle")).toBeTruthy()
  })

  test("does not render while closed", () => {
    renderPage(<PasswordHarness initialForm={null} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Password validation helper
// ---------------------------------------------------------------------------

describe("getNewPasswordError", () => {
  const t: TFunction = (key, values) => translate("zh-Hans", key, values)

  test("rejects mismatched passwords", () => {
    expect(getNewPasswordError("Abcdef1", "Abcdef2", t)).toBe(
      "两次输入的新密码不一致"
    )
  })

  test("rejects passwords that are too short or lack an uppercase letter", () => {
    expect(getNewPasswordError("abc", "abc", t)).toBe(
      "密码至少 6 位，并且包含一个大写字母"
    )
    expect(getNewPasswordError("abcdef1", "abcdef1", t)).toBe(
      "密码至少 6 位，并且包含一个大写字母"
    )
  })

  test("accepts a matching password meeting the requirements", () => {
    expect(getNewPasswordError("Abcdef1", "Abcdef1", t)).toBeNull()
  })
})

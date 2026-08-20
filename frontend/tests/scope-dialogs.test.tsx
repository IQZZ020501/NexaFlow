/* @jsxImportSource react */
/**
 * DOM-level coverage for the scope creation/editing dialogs in
 * scope-dialogs.tsx: CreateWorkspaceDialog, EditWorkspaceDialog,
 * CreateTeamDialog, EditTeamDialog.
 *
 * All four are presentational: they render when their form/open state is
 * non-null/true and surface every change through the setter callbacks.
 */
import { afterEach, describe, expect, test } from "bun:test"
import { useState } from "react"
import type { RenderResult } from "@testing-library/react"

import {
  CreateTeamDialog,
  CreateWorkspaceDialog,
  EditTeamDialog,
  EditWorkspaceDialog,
} from "@/components/system/dialogs/scope-dialogs"
import { LanguageProvider } from "@/contexts/language-provider"
import type {
  ScopeEditForm,
  TeamForm,
  User,
  Workspace,
  WorkspaceForm,
  WorkspaceMember,
} from "@/lib/api/system"
import {
  cleanup,
  fireEvent,
  renderPage,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

afterEach(() => {
  cleanup()
})

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function user(overrides: Partial<User> = {}): User {
  return {
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
    ...overrides,
  }
}

const alice = user()
const bob = user({ id: "u-2", username: "bob", name: "Bob", email: "bob@app.local" })
const carol = user({
  id: "u-3",
  username: "carol",
  name: "Carol",
  email: "carol@app.local",
  is_active: false,
})

const ws1: Workspace = {
  id: "ws-1",
  name: "Alpha Workspace",
  description: "alpha desc",
  status: "active",
  is_default: false,
}

const ws2: Workspace = {
  id: "ws-2",
  name: "Beta Workspace",
  description: "beta desc",
  status: "active",
  is_default: false,
}

function workspaceMember(usr: User, role = "member"): WorkspaceMember {
  return { user: usr, role }
}

/** Opens the trigger's dropdown menu and clicks the item with the label. */
async function choose(trigger: HTMLElement, label: string) {
  fireEvent.pointerDown(trigger)
  fireEvent.click(within(await screen.findByRole("menu")).getByText(label))
}

function submitButton(name: string): HTMLButtonElement {
  return screen.getByRole("button", { name }) as HTMLButtonElement
}

/** Rerenders the page root with the LanguageProvider restored. */
function rerenderPage(view: RenderResult, ui: React.JSX.Element) {
  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">{ui}</LanguageProvider>
  )
}

// ---------------------------------------------------------------------------
// EditWorkspaceDialog
// ---------------------------------------------------------------------------

describe("EditWorkspaceDialog", () => {
  function Harness({
    initialForm = { id: "ws-1", name: "Alpha Workspace", description: "alpha desc" },
    isSavingWorkspace = false,
    onSubmit,
  }: {
    initialForm?: ScopeEditForm | null
    isSavingWorkspace?: boolean
    onSubmit?: () => void
  }) {
    const [form, setForm] = useState<ScopeEditForm | null>(initialForm)
    return (
      <EditWorkspaceDialog
        workspaceEditForm={form}
        setWorkspaceEditForm={setForm}
        isSavingWorkspace={isSavingWorkspace}
        handleUpdateWorkspace={(event) => {
          event.preventDefault()
          onSubmit?.()
        }}
      />
    )
  }

  test("renders nothing when the form is null", () => {
    renderPage(<Harness initialForm={null} />)
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(screen.queryByText("编辑工作空间")).toBeNull()
  })

  test("opens with the current name and description", async () => {
    renderPage(<Harness />)
    const dialog = await screen.findByRole("dialog", { name: "编辑工作空间" })
    expect(dialog.textContent).toContain("更新名称和描述")
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "Alpha Workspace"
    )
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "alpha desc"
    )
  })

  test("updates the form on name and description changes", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "编辑工作空间" })
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Renamed" },
    })
    fireEvent.change(screen.getByLabelText("描述"), {
      target: { value: "new desc" },
    })
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "Renamed"
    )
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "new desc"
    )
  })

  test("submits the workspace update", async () => {
    const submitted: string[] = []
    renderPage(<Harness onSubmit={() => submitted.push("save")} />)
    await screen.findByRole("dialog", { name: "编辑工作空间" })
    fireEvent.click(submitButton("保存"))
    expect(submitted).toEqual(["save"])
  })

  test("does not submit an empty required name", async () => {
    const submitted: string[] = []
    renderPage(
      <Harness
        initialForm={{ id: "ws-1", name: "", description: "" }}
        onSubmit={() => submitted.push("save")}
      />
    )
    await screen.findByRole("dialog", { name: "编辑工作空间" })
    fireEvent.click(submitButton("保存"))
    expect(submitted).toEqual([])
    expect((screen.getByLabelText("名称") as HTMLInputElement).required).toBe(
      true
    )
  })

  test("disables the save button and shows the spinner while saving", async () => {
    renderPage(<Harness isSavingWorkspace />)
    await screen.findByRole("dialog", { name: "编辑工作空间" })
    const save = submitButton("保存")
    expect(save.disabled).toBe(true)
    expect(save.querySelector("svg.lucide-loader-circle")).toBeTruthy()
  })

  test("closes via the cancel button", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "编辑工作空间" })
    fireEvent.click(submitButton("取消"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("closes via Escape", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "编辑工作空间" })
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })
})

// ---------------------------------------------------------------------------
// EditTeamDialog
// ---------------------------------------------------------------------------

describe("EditTeamDialog", () => {
  function Harness({
    initialForm = { id: "t-1", name: "Beta Team", description: "beta desc" },
    selectedWorkspace = ws1,
    selectedWorkspaceId = "ws-1",
    isSavingTeam = false,
    onSubmit,
  }: {
    initialForm?: ScopeEditForm | null
    selectedWorkspace?: Workspace | null
    selectedWorkspaceId?: string | null
    isSavingTeam?: boolean
    onSubmit?: () => void
  }) {
    const [form, setForm] = useState<ScopeEditForm | null>(initialForm)
    return (
      <EditTeamDialog
        teamEditForm={form}
        setTeamEditForm={setForm}
        selectedWorkspace={selectedWorkspace}
        selectedWorkspaceId={selectedWorkspaceId}
        isSavingTeam={isSavingTeam}
        handleUpdateTeam={(event) => {
          event.preventDefault()
          onSubmit?.()
        }}
      />
    )
  }

  test("renders nothing when the form is null", () => {
    renderPage(<Harness initialForm={null} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("opens with the workspace context and current values", async () => {
    renderPage(<Harness />)
    const dialog = await screen.findByRole("dialog", { name: "编辑团队" })
    expect(dialog.textContent).toContain("Alpha Workspace")
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "Beta Team"
    )
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "beta desc"
    )
  })

  test("shows the placeholder description without a workspace", async () => {
    renderPage(<Harness selectedWorkspace={null} selectedWorkspaceId={null} />)
    const dialog = await screen.findByRole("dialog", { name: "编辑团队" })
    expect(dialog.textContent).toContain("先选择工作空间")
  })

  test("updates the form on name and description changes", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "编辑团队" })
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Team Renamed" },
    })
    fireEvent.change(screen.getByLabelText("描述"), {
      target: { value: "team desc" },
    })
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "Team Renamed"
    )
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "team desc"
    )
  })

  test("submits the team update when a workspace is selected", async () => {
    const submitted: string[] = []
    renderPage(<Harness onSubmit={() => submitted.push("save")} />)
    await screen.findByRole("dialog", { name: "编辑团队" })
    fireEvent.click(submitButton("保存"))
    expect(submitted).toEqual(["save"])
  })

  test("disables save without a selected workspace and blocks empty names", async () => {
    const submitted: string[] = []
    const view = renderPage(
      <Harness
        selectedWorkspaceId={null}
        selectedWorkspace={null}
        onSubmit={() => submitted.push("save")}
      />
    )
    await screen.findByRole("dialog", { name: "编辑团队" })
    expect(submitButton("保存").disabled).toBe(true)
    expect(submitted).toEqual([])

    // A workspace id enables the button, but an empty required name still
    // blocks submission.
    rerenderPage(
      view,
      <Harness
        key="with-workspace"
        selectedWorkspaceId="ws-1"
        selectedWorkspace={ws1}
        initialForm={{ id: "t-1", name: "", description: "" }}
        onSubmit={() => submitted.push("save")}
      />
    )
    await screen.findByRole("dialog", { name: "编辑团队" })
    await waitFor(() => expect(submitButton("保存").disabled).toBe(false))
    fireEvent.click(submitButton("保存"))
    expect(submitted).toEqual([])
  })

  test("disables the save button and shows the spinner while saving", async () => {
    renderPage(<Harness isSavingTeam />)
    await screen.findByRole("dialog", { name: "编辑团队" })
    const save = submitButton("保存")
    expect(save.disabled).toBe(true)
    expect(save.querySelector("svg.lucide-loader-circle")).toBeTruthy()
  })

  test("closes via the cancel button", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "编辑团队" })
    fireEvent.click(submitButton("取消"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("closes via Escape", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "编辑团队" })
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })
})

// ---------------------------------------------------------------------------
// CreateWorkspaceDialog
// ---------------------------------------------------------------------------

describe("CreateWorkspaceDialog", () => {
  function Harness({
    initialOpen = true,
    initialForm = { name: "", description: "", adminUserId: "" },
    users = [alice, bob, carol],
    isUsersLoading = false,
    isCreatingWorkspace = false,
    onSubmit,
  }: {
    initialOpen?: boolean
    initialForm?: WorkspaceForm
    users?: User[]
    isUsersLoading?: boolean
    isCreatingWorkspace?: boolean
    onSubmit?: () => void
  }) {
    const [open, setOpen] = useState(initialOpen)
    const [form, setForm] = useState<WorkspaceForm>(initialForm)
    return (
      <CreateWorkspaceDialog
        isWorkspaceDialogOpen={open}
        setIsWorkspaceDialogOpen={setOpen}
        workspaceForm={form}
        setWorkspaceForm={setForm}
        users={users}
        isUsersLoading={isUsersLoading}
        isCreatingWorkspace={isCreatingWorkspace}
        handleCreateWorkspace={(event) => {
          event.preventDefault()
          onSubmit?.()
        }}
      />
    )
  }

  test("renders nothing while closed", () => {
    renderPage(<Harness initialOpen={false} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("opens with the form fields and placeholder admin selection", async () => {
    renderPage(<Harness />)
    const dialog = await screen.findByRole("dialog", { name: "新建工作空间" })
    expect(dialog.textContent).toContain("创建工作空间并指定已有用户为负责人")
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe("")
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe("")
    expect(
      screen.getByRole("button", { name: /负责人/ }).textContent
    ).toContain("选择负责人")
  })

  test("updates the form on name and description changes", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建工作空间" })
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "New Workspace" },
    })
    fireEvent.change(screen.getByLabelText("描述"), {
      target: { value: "fresh" },
    })
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "New Workspace"
    )
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "fresh"
    )
  })

  test("selects an active admin candidate and marks it in the menu", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建工作空间" })
    const trigger = screen.getByRole("button", { name: /负责人/ })

    fireEvent.pointerDown(trigger)
    const menu = await screen.findByRole("menu")
    expect(within(menu).getByText("Alice")).toBeTruthy()
    expect(within(menu).getByText("alice · alice@app.local")).toBeTruthy()
    expect(within(menu).getByText("Bob")).toBeTruthy()
    expect(within(menu).queryByText("Carol")).toBeNull()
    fireEvent.click(within(menu).getByText("Alice"))

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /负责人/ }).textContent).toContain(
        "Alice · alice"
      )
    )

    // The selected candidate carries the check icon inside the menu.
    fireEvent.pointerDown(screen.getByRole("button", { name: /负责人/ }))
    const reopened = await screen.findByRole("menu")
    const aliceItem = within(reopened)
      .getByText("Alice")
      .closest('[data-slot="dropdown-menu-item"]')!
    const bobItem = within(reopened)
      .getByText("Bob")
      .closest('[data-slot="dropdown-menu-item"]')!
    expect(aliceItem.querySelector("svg")).toBeTruthy()
    expect(bobItem.querySelector("svg")).toBeNull()
  })

  test("shows the loading placeholder and disables the admin select while users load", async () => {
    renderPage(<Harness isUsersLoading />)
    await screen.findByRole("dialog", { name: "新建工作空间" })
    const trigger = screen.getByRole("button", {
      name: /负责人/,
    }) as HTMLButtonElement
    expect(trigger.disabled).toBe(true)
    expect(trigger.textContent).toContain("正在加载")
  })

  test("shows the empty-candidates item when no active users exist", async () => {
    renderPage(<Harness users={[carol]} />)
    await screen.findByRole("dialog", { name: "新建工作空间" })
    fireEvent.pointerDown(screen.getByRole("button", { name: /负责人/ }))
    const menu = await screen.findByRole("menu")
    const empty = within(menu).getByText("暂无可选用户")
    expect(
      empty.closest('[data-slot="dropdown-menu-item"]')!.getAttribute("aria-disabled")
    ).toBe("true")
  })

  test("blocks submission without an admin and submits once selected", async () => {
    const submitted: string[] = []
    renderPage(<Harness onSubmit={() => submitted.push("create")} />)
    await screen.findByRole("dialog", { name: "新建工作空间" })
    expect(submitButton("新建").disabled).toBe(true)
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Named" },
    })

    await choose(screen.getByRole("button", { name: /负责人/ }), "Alice")
    await waitFor(() => expect(submitButton("新建").disabled).toBe(false))
    fireEvent.click(submitButton("新建"))
    expect(submitted).toEqual(["create"])
  })

  test("blocks submission while the name is empty", async () => {
    const submitted: string[] = []
    renderPage(
      <Harness
        initialForm={{ name: "", description: "", adminUserId: "u-1" }}
        onSubmit={() => submitted.push("create")}
      />
    )
    await screen.findByRole("dialog", { name: "新建工作空间" })
    await waitFor(() => expect(submitButton("新建").disabled).toBe(false))
    fireEvent.click(submitButton("新建"))
    expect(submitted).toEqual([])
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Named" },
    })
    fireEvent.click(submitButton("新建"))
    expect(submitted).toEqual(["create"])
  })

  test("disables the submit button and shows the spinner while creating", async () => {
    renderPage(
      <Harness
        initialForm={{ name: "W", description: "", adminUserId: "u-1" }}
        isCreatingWorkspace
      />
    )
    await screen.findByRole("dialog", { name: "新建工作空间" })
    const create = submitButton("新建")
    expect(create.disabled).toBe(true)
    expect(create.querySelector("svg.lucide-loader-circle")).toBeTruthy()
  })

  test("closes via the cancel button", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建工作空间" })
    fireEvent.click(submitButton("取消"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("closes via Escape", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建工作空间" })
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })
})

// ---------------------------------------------------------------------------
// CreateTeamDialog
// ---------------------------------------------------------------------------

describe("CreateTeamDialog", () => {
  function Harness({
    initialOpen = true,
    initialForm = { workspaceId: "", name: "", description: "", adminUserId: "" },
    teamWorkspace = null,
    manageableWorkspaces = [ws1, ws2],
    isCreatingTeam = false,
    teamAdminCandidates = [workspaceMember(alice), workspaceMember(bob), workspaceMember(carol)],
    isTeamAdminCandidatesLoading = false,
    onWorkspaceChange,
    onSubmit,
  }: {
    initialOpen?: boolean
    initialForm?: TeamForm
    teamWorkspace?: Workspace | null
    manageableWorkspaces?: Workspace[]
    isCreatingTeam?: boolean
    teamAdminCandidates?: WorkspaceMember[]
    isTeamAdminCandidatesLoading?: boolean
    onWorkspaceChange?: (workspaceId: string) => void
    onSubmit?: () => void
  }) {
    const [open, setOpen] = useState(initialOpen)
    const [form, setForm] = useState<TeamForm>(initialForm)
    return (
      <CreateTeamDialog
        isTeamDialogOpen={open}
        setIsTeamDialogOpen={setOpen}
        teamWorkspace={teamWorkspace}
        manageableWorkspaces={manageableWorkspaces}
        teamForm={form}
        setTeamForm={setForm}
        isCreatingTeam={isCreatingTeam}
        handleCreateTeam={(event) => {
          event.preventDefault()
          onSubmit?.()
        }}
        teamAdminCandidates={teamAdminCandidates}
        isTeamAdminCandidatesLoading={isTeamAdminCandidatesLoading}
        handleTeamWorkspaceChange={onWorkspaceChange ?? (() => undefined)}
      />
    )
  }

  test("renders nothing while closed", () => {
    renderPage(<Harness initialOpen={false} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("opens with the placeholder workspace and description", async () => {
    renderPage(<Harness />)
    const dialog = await screen.findByRole("dialog", { name: "新建团队" })
    expect(dialog.textContent).toContain("先选择工作空间")
    expect(
      screen.getByRole("button", { name: /工作空间/ }).textContent
    ).toContain("选择工作空间")
  })

  test("shows the selected workspace name in the description", async () => {
    renderPage(<Harness teamWorkspace={ws1} />)
    const dialog = await screen.findByRole("dialog", { name: "新建团队" })
    expect(dialog.textContent).toContain("Alpha Workspace")
  })

  test("lists manageable workspaces and reports the selection", async () => {
    const changes: string[] = []
    renderPage(<Harness onWorkspaceChange={(id) => changes.push(id)} />)
    await screen.findByRole("dialog", { name: "新建团队" })
    const trigger = screen.getByRole("button", { name: /工作空间/ })

    fireEvent.pointerDown(trigger)
    const menu = await screen.findByRole("menu")
    expect(within(menu).getByText("Alpha Workspace")).toBeTruthy()
    expect(within(menu).getByText("Beta Workspace")).toBeTruthy()
    fireEvent.click(within(menu).getByText("Beta Workspace"))
    expect(changes).toEqual(["ws-2"])
  })

  test("marks the currently selected workspace in the menu", async () => {
    renderPage(
      <Harness
        initialForm={{ workspaceId: "ws-1", name: "", description: "", adminUserId: "" }}
      />
    )
    await screen.findByRole("dialog", { name: "新建团队" })
    fireEvent.pointerDown(screen.getByRole("button", { name: /工作空间/ }))
    const menu = await screen.findByRole("menu")
    const ws1Item = within(menu)
      .getByText("Alpha Workspace")
      .closest('[data-slot="dropdown-menu-item"]')!
    const ws2Item = within(menu)
      .getByText("Beta Workspace")
      .closest('[data-slot="dropdown-menu-item"]')!
    expect(ws1Item.querySelector("svg")).toBeTruthy()
    expect(ws2Item.querySelector("svg")).toBeNull()
  })

  test("disables the workspace select when no workspaces are manageable", async () => {
    renderPage(<Harness manageableWorkspaces={[]} />)
    await screen.findByRole("dialog", { name: "新建团队" })
    expect(
      (
        screen.getByRole("button", { name: /工作空间/ }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
  })

  test("updates the form on name and description changes", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建团队" })
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "New Team" },
    })
    fireEvent.change(screen.getByLabelText("描述"), {
      target: { value: "team" },
    })
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "New Team"
    )
    expect((screen.getByLabelText("描述") as HTMLInputElement).value).toBe(
      "team"
    )
  })

  test("selects an active team admin candidate and marks it", async () => {
    renderPage(<Harness teamWorkspace={ws1} />)
    await screen.findByRole("dialog", { name: "新建团队" })
    const trigger = screen.getByRole("button", { name: /团队管理员/ })

    fireEvent.pointerDown(trigger)
    const menu = await screen.findByRole("menu")
    expect(within(menu).getByText("Alice")).toBeTruthy()
    expect(within(menu).getByText("Bob")).toBeTruthy()
    expect(within(menu).queryByText("Carol")).toBeNull()
    fireEvent.click(within(menu).getByText("Bob"))

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /团队管理员/ }).textContent
      ).toContain("Bob · bob")
    )

    // The selected candidate carries the check icon inside the menu.
    fireEvent.pointerDown(screen.getByRole("button", { name: /团队管理员/ }))
    const reopened = await screen.findByRole("menu")
    const bobItem = within(reopened)
      .getByText("Bob")
      .closest('[data-slot="dropdown-menu-item"]')!
    const aliceItem = within(reopened)
      .getByText("Alice")
      .closest('[data-slot="dropdown-menu-item"]')!
    expect(bobItem.querySelector("svg")).toBeTruthy()
    expect(aliceItem.querySelector("svg")).toBeNull()
  })

  test("shows the loading placeholder and disables the admin select while candidates load", async () => {
    renderPage(<Harness teamWorkspace={ws1} isTeamAdminCandidatesLoading />)
    await screen.findByRole("dialog", { name: "新建团队" })
    const trigger = screen.getByRole("button", {
      name: /团队管理员/,
    }) as HTMLButtonElement
    expect(trigger.disabled).toBe(true)
    expect(trigger.textContent).toContain("正在加载")
  })

  test("disables the admin select without a selected workspace", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建团队" })
    expect(
      (
        screen.getByRole("button", { name: /团队管理员/ }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
  })

  test("shows the empty-candidates item when no admins are available", async () => {
    renderPage(<Harness teamWorkspace={ws1} teamAdminCandidates={[]} />)
    await screen.findByRole("dialog", { name: "新建团队" })
    fireEvent.pointerDown(screen.getByRole("button", { name: /团队管理员/ }))
    const menu = await screen.findByRole("menu")
    const empty = within(menu).getByText("暂无可选成员")
    expect(
      empty.closest('[data-slot="dropdown-menu-item"]')!.getAttribute("aria-disabled")
    ).toBe("true")
  })

  test("blocks submission until workspace and admin are chosen", async () => {
    const submitted: string[] = []
    renderPage(<Harness onSubmit={() => submitted.push("create")} />)
    await screen.findByRole("dialog", { name: "新建团队" })
    expect(submitButton("新建").disabled).toBe(true)
    fireEvent.click(submitButton("新建"))
    expect(submitted).toEqual([])
  })

  test("submits once workspace and admin are set", async () => {
    const submitted: string[] = []
    renderPage(
      <Harness
        initialForm={{
          workspaceId: "ws-1",
          name: "Team",
          description: "",
          adminUserId: "u-1",
        }}
        teamWorkspace={ws1}
        onSubmit={() => submitted.push("create")}
      />
    )
    await screen.findByRole("dialog", { name: "新建团队" })
    await waitFor(() => expect(submitButton("新建").disabled).toBe(false))
    fireEvent.click(submitButton("新建"))
    expect(submitted).toEqual(["create"])
  })

  test("blocks submission while the name is empty", async () => {
    const submitted: string[] = []
    renderPage(
      <Harness
        initialForm={{
          workspaceId: "ws-1",
          name: "",
          description: "",
          adminUserId: "u-1",
        }}
        teamWorkspace={ws1}
        onSubmit={() => submitted.push("create")}
      />
    )
    await screen.findByRole("dialog", { name: "新建团队" })
    await waitFor(() => expect(submitButton("新建").disabled).toBe(false))
    fireEvent.click(submitButton("新建"))
    expect(submitted).toEqual([])
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Named Team" },
    })
    fireEvent.click(submitButton("新建"))
    expect(submitted).toEqual(["create"])
  })

  test("disables the submit button and shows the spinner while creating", async () => {
    renderPage(
      <Harness
        initialForm={{
          workspaceId: "ws-1",
          name: "T",
          description: "",
          adminUserId: "u-1",
        }}
        teamWorkspace={ws1}
        isCreatingTeam
      />
    )
    await screen.findByRole("dialog", { name: "新建团队" })
    const create = submitButton("新建")
    expect(create.disabled).toBe(true)
    expect(create.querySelector("svg.lucide-loader-circle")).toBeTruthy()
  })

  test("closes via the cancel button", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建团队" })
    fireEvent.click(submitButton("取消"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("closes via Escape", async () => {
    renderPage(<Harness />)
    await screen.findByRole("dialog", { name: "新建团队" })
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })
})

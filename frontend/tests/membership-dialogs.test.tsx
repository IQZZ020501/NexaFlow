/* @jsxImportSource react */
/**
 * DOM-level coverage for the workspace/team member management dialogs
 * (WorkspaceMembersDialog, TeamMembersDialog).
 *
 * Both dialogs are purely presentational: they render when the object prop
 * is non-null and call the setter with null on close. All member mutations
 * are surfaced through the onAddMember / onUpdateMemberRole / onRemoveMember
 * callbacks.
 */
import { afterEach, describe, expect, test } from "bun:test"
import { useState, type ComponentProps } from "react"
import type { RenderResult } from "@testing-library/react"

import { TeamMembersDialog } from "@/components/system/dialogs/team-members-dialog"
import { WorkspaceMembersDialog } from "@/components/system/dialogs/workspace-members-dialog"
import { LanguageProvider } from "@/contexts/language-provider"
import type {
  Team,
  TeamMember,
  User,
  Workspace,
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
const bob = user({
  id: "u-2",
  username: "bob",
  name: "Bob",
  email: "bob@app.local",
})
const carol = user({
  id: "u-3",
  username: "carol",
  name: "Carol",
  email: "carol@app.local",
  is_active: false,
})
const dave = user({
  id: "u-4",
  username: "dave",
  name: "Dave",
  email: "dave@app.local",
})

const workspace: Workspace = {
  id: "ws-1",
  name: "Alpha Workspace",
  description: "desc",
  status: "active",
  is_default: false,
}

const defaultWorkspace: Workspace = {
  id: "ws-2",
  name: "Default Workspace",
  description: "",
  status: "active",
  is_default: true,
}

const team: Team = {
  id: "t-1",
  workspace_id: "ws-1",
  name: "Beta Team",
  description: "",
  status: "active",
  is_default: false,
}

const defaultTeam: Team = {
  id: "t-2",
  workspace_id: "ws-1",
  name: "Default Team",
  description: "",
  status: "active",
  is_default: true,
}

function member(usr: User, role = "member"): WorkspaceMember {
  return { user: usr, role }
}

function teamMember(usr: User, role = "member"): TeamMember {
  return { user: usr, role }
}

// ---------------------------------------------------------------------------
// Interaction helpers
// ---------------------------------------------------------------------------

/** Opens the trigger's dropdown menu and clicks the item with the label. */
async function choose(trigger: HTMLElement, label: string) {
  fireEvent.pointerDown(trigger)
  fireEvent.click(within(await screen.findByRole("menu")).getByText(label))
}

/** Finds the member row card containing the given member name. */
function memberRow(userName: string): HTMLElement {
  const name = screen.getByText(userName)
  let el = name.parentElement
  while (
    el &&
    !(el.className.includes("rounded-lg") && el.className.includes("border"))
  ) {
    el = el.parentElement
  }
  return el!
}

/** Reads the current text of the add-member user trigger. */
function userTriggerText(): string {
  return screen.getByLabelText("成员").textContent ?? ""
}

type WorkspaceDialogProps = ComponentProps<typeof WorkspaceMembersDialog>
type TeamDialogProps = ComponentProps<typeof TeamMembersDialog>

/** Controlled wrapper so closing via Escape actually updates the open state. */
function WorkspaceHarness({
  initial,
  onClosed,
  ...rest
}: {
  initial: Workspace | null
  onClosed?: (next: Workspace | null) => void
} & Omit<WorkspaceDialogProps, "workspace" | "setWorkspace">) {
  const [current, setCurrent] = useState<Workspace | null>(initial)
  return (
    <>
      <button
        type="button"
        data-testid="reopen-workspace-members"
        onClick={() => setCurrent(initial)}
      >
        reopen
      </button>
      <WorkspaceMembersDialog
        {...rest}
        workspace={current}
        setWorkspace={(next) => {
          setCurrent(next)
          if (typeof next !== "function") onClosed?.(next)
        }}
      />
    </>
  )
}

function TeamHarness({
  initial,
  onClosed,
  ...rest
}: {
  initial: Team | null
  onClosed?: (next: Team | null) => void
} & Omit<TeamDialogProps, "team" | "setTeam">) {
  const [current, setCurrent] = useState<Team | null>(initial)
  return (
    <>
      <button
        type="button"
        data-testid="reopen-team-members"
        onClick={() => setCurrent(initial)}
      >
        reopen
      </button>
      <TeamMembersDialog
        {...rest}
        team={current}
        setTeam={(next) => {
          setCurrent(next)
          if (typeof next !== "function") onClosed?.(next)
        }}
      />
    </>
  )
}

/** Rerenders the page root with the LanguageProvider restored. */
function rerenderPage(view: RenderResult, ui: React.JSX.Element) {
  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">{ui}</LanguageProvider>
  )
}

// ---------------------------------------------------------------------------
// WorkspaceMembersDialog
// ---------------------------------------------------------------------------

describe("WorkspaceMembersDialog", () => {
  const baseProps = {
    workspace,
    setWorkspace: () => undefined,
    members: [member(alice, "admin"), member(bob)],
    users: [alice, bob, carol, dave],
    isLoading: false,
    isCandidatesLoading: false,
    isMutating: false,
    canAddMembers: true,
    canManageAdmins: true,
    onAddMember: async () => undefined,
    onUpdateMemberRole: async () => undefined,
    onRemoveMember: async () => undefined,
  }

  test("renders nothing when no workspace is selected", () => {
    renderPage(<WorkspaceMembersDialog {...baseProps} workspace={null} />)
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(screen.queryByText("管理工作空间成员")).toBeNull()
  })

  test("opens with the workspace name, member list and count badge", async () => {
    renderPage(<WorkspaceMembersDialog {...baseProps} />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    expect(dialog.textContent).toContain("Alpha Workspace")
    expect(dialog.textContent).toContain("Alice")
    expect(dialog.textContent).toContain("alice · alice@app.local")
    expect(dialog.textContent).toContain("Bob")
    expect(dialog.textContent).toContain("bob · bob@app.local")
    expect(screen.getByText("工作空间成员")).toBeTruthy()
    expect(screen.getByText("2")).toBeTruthy()
  })

  test("translates the default workspace display name", async () => {
    renderPage(
      <WorkspaceMembersDialog {...baseProps} workspace={defaultWorkspace} />
    )
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    expect(dialog.textContent).toContain("默认工作空间")
  })

  test("adds a member as admin and resets the selection", async () => {
    const calls: Array<[string, string]> = []
    renderPage(
      <WorkspaceMembersDialog
        {...baseProps}
        onAddMember={async (userId, role) => {
          calls.push([userId, role])
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })

    // Candidates exclude inactive users and existing members.
    const userTrigger = screen.getByLabelText("成员") as HTMLButtonElement
    expect(userTrigger.disabled).toBe(false)
    fireEvent.pointerDown(userTrigger)
    const menu = await screen.findByRole("menu")
    expect(within(menu).getByText("Dave · dave")).toBeTruthy()
    expect(within(menu).queryByText("Carol · carol")).toBeNull()
    expect(within(menu).queryByText("Alice · alice")).toBeNull()
    expect(within(menu).queryByText("Bob · bob")).toBeNull()
    fireEvent.click(within(menu).getByText("Dave · dave"))
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))

    const roleTrigger = screen.getByLabelText("空间角色") as HTMLButtonElement
    fireEvent.pointerDown(roleTrigger)
    fireEvent.click(within(await screen.findByRole("menu")).getByText("管理员"))
    await waitFor(() =>
      expect((roleTrigger.textContent ?? "").trim()).toContain("管理员")
    )

    fireEvent.click(screen.getByRole("button", { name: "添加成员" }))
    await waitFor(() => expect(calls).toEqual([["u-4", "admin"]]))
    await waitFor(() => expect(userTriggerText()).toContain("选择成员"))
    expect(
      (screen.getByLabelText("空间角色").textContent ?? "").trim()
    ).toContain("成员")
  })

  test("adds a member with the default member role", async () => {
    const calls: Array<[string, string]> = []
    renderPage(
      <WorkspaceMembersDialog
        {...baseProps}
        onAddMember={async (userId, role) => {
          calls.push([userId, role])
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    await choose(screen.getByLabelText("成员"), "Dave · dave")
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))
    fireEvent.click(screen.getByRole("button", { name: "添加成员" }))
    await waitFor(() => expect(calls).toEqual([["u-4", "member"]]))
  })

  test("shows the empty-candidates state and disables the add flow", async () => {
    renderPage(
      <WorkspaceMembersDialog {...baseProps} users={[alice, bob, carol]} />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    const userTrigger = screen.getByLabelText("成员") as HTMLButtonElement
    expect(userTrigger.disabled).toBe(true)
    expect(userTriggerText()).toContain("暂无可加入成员")
    expect(
      (screen.getByRole("button", { name: "添加成员" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
  })

  test("shows the loading text and disables the add flow while candidates load", async () => {
    renderPage(
      <WorkspaceMembersDialog
        {...baseProps}
        isCandidatesLoading
        users={[alice, bob]}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    const userTrigger = screen.getByLabelText("成员") as HTMLButtonElement
    expect(userTrigger.disabled).toBe(true)
    expect(userTriggerText()).toContain("正在加载")
  })

  test("shows the member list spinner while members load", async () => {
    renderPage(<WorkspaceMembersDialog {...baseProps} isLoading />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    expect(dialog.querySelector(".animate-spin")).toBeTruthy()
    expect(screen.queryByText("Alice")).toBeNull()
    const userTrigger = screen.getByLabelText("成员") as HTMLButtonElement
    expect(userTrigger.disabled).toBe(true)
    expect(userTriggerText()).toContain("正在加载")
  })

  test("renders the empty member list placeholder", async () => {
    renderPage(<WorkspaceMembersDialog {...baseProps} members={[]} />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    expect(dialog.textContent).toContain("暂无工作空间成员")
    expect(dialog.textContent).toContain("0")
  })

  test("disables every control and shows the spinner while mutating", async () => {
    renderPage(<WorkspaceMembersDialog {...baseProps} isMutating />)
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    const addButton = screen.getByRole("button", {
      name: "添加成员",
    }) as HTMLButtonElement
    expect(addButton.disabled).toBe(true)
    expect(addButton.querySelector("svg.lucide-loader-circle")).toBeTruthy()
    expect((screen.getByLabelText("成员") as HTMLButtonElement).disabled).toBe(
      true
    )
    expect(
      (screen.getByLabelText("空间角色") as HTMLButtonElement).disabled
    ).toBe(true)
    expect(
      (
        within(memberRow("Alice")).getByRole("button", {
          name: "管理员",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
    expect(
      (
        within(memberRow("Alice")).getByLabelText(
          "移除成员"
        ) as HTMLButtonElement
      ).disabled
    ).toBe(true)
  })

  test("updates an admin member to member and a member to admin", async () => {
    const calls: Array<[string, string]> = []
    renderPage(
      <WorkspaceMembersDialog
        {...baseProps}
        onUpdateMemberRole={async (userId, role) => {
          calls.push([userId, role])
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })

    // Alice (admin): demote to member. The admin item is disabled for her.
    const aliceRole = within(memberRow("Alice")).getByRole("button", {
      name: "管理员",
    })
    fireEvent.pointerDown(aliceRole)
    const aliceMenu = await screen.findByRole("menu")
    expect(
      within(aliceMenu)
        .getByRole("menuitem", { name: "管理员" })
        .getAttribute("aria-disabled")
    ).toBe("true")
    fireEvent.click(within(aliceMenu).getByText("成员"))
    await waitFor(() => expect(calls).toEqual([["u-1", "member"]]))

    // Bob (member): promote to admin.
    const bobRole = within(memberRow("Bob")).getByRole("button", {
      name: "成员",
    })
    fireEvent.pointerDown(bobRole)
    const bobMenu = await screen.findByRole("menu")
    expect(
      within(bobMenu)
        .getByRole("menuitem", { name: "成员" })
        .getAttribute("aria-disabled")
    ).toBe("true")
    fireEvent.click(within(bobMenu).getByText("管理员"))
    await waitFor(() =>
      expect(calls).toEqual([
        ["u-1", "member"],
        ["u-2", "admin"],
      ])
    )
  })

  test("removes a member through the remove button", async () => {
    const calls: string[] = []
    renderPage(
      <WorkspaceMembersDialog
        {...baseProps}
        onRemoveMember={async (userId) => {
          calls.push(userId)
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    fireEvent.click(within(memberRow("Bob")).getByLabelText("移除成员"))
    await waitFor(() => expect(calls).toEqual(["u-2"]))
  })

  test("protects the last admin from demotion and removal", async () => {
    renderPage(
      <WorkspaceMembersDialog
        {...baseProps}
        members={[member(alice, "admin")]}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    const roleTrigger = within(memberRow("Alice")).getByRole("button", {
      name: "管理员",
    }) as HTMLButtonElement
    expect(roleTrigger.disabled).toBe(true)
    expect(roleTrigger.getAttribute("title")).toBe("不能移除最后一个管理员")
    const remove = within(memberRow("Alice")).getByLabelText(
      "移除成员"
    ) as HTMLButtonElement
    expect(remove.disabled).toBe(true)
    expect(remove.getAttribute("title")).toBe("不能移除最后一个管理员")
  })

  test("hides admin role management and protects admins when admins cannot be managed", async () => {
    renderPage(
      <WorkspaceMembersDialog
        {...baseProps}
        members={[member(alice, "admin"), member(bob, "admin"), member(dave)]}
        canManageAdmins={false}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })

    // Member rows render static role badges instead of role dropdowns.
    const aliceRow = memberRow("Alice")
    expect(
      within(aliceRow).queryByRole("button", { name: "管理员" })
    ).toBeNull()
    expect(within(aliceRow).getByText("管理员")).toBeTruthy()
    expect(within(memberRow("Bob")).getByText("管理员")).toBeTruthy()
    expect(within(memberRow("Dave")).getByText("成员")).toBeTruthy()

    // Admins cannot be removed; members still can.
    const adminRemove = within(aliceRow).getByLabelText(
      "移除成员"
    ) as HTMLButtonElement
    expect(adminRemove.disabled).toBe(true)
    expect(adminRemove.getAttribute("title")).toBe(
      "只有系统管理员可以管理工作空间管理员"
    )
    expect(
      (
        within(memberRow("Dave")).getByLabelText(
          "移除成员"
        ) as HTMLButtonElement
      ).disabled
    ).toBe(false)

    expect(screen.queryByLabelText("空间角色")).toBeNull()
  })

  test("hides the whole add section when members cannot be added", async () => {
    renderPage(<WorkspaceMembersDialog {...baseProps} canAddMembers={false} />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理工作空间成员",
    })
    expect(dialog.textContent).not.toContain("添加成员")
    expect(dialog.textContent).not.toContain(
      "系统管理员可将已有用户加入工作空间"
    )
    expect(dialog.textContent).toContain("工作空间成员")
  })

  test("closes via Escape and resets the pending selection", async () => {
    const closed: Array<Workspace | null> = []
    renderPage(
      <WorkspaceHarness
        initial={workspace}
        onClosed={(next) => {
          closed.push(next)
        }}
        {...baseProps}
      />
    )
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    await choose(screen.getByLabelText("成员"), "Dave · dave")
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))

    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(closed).toEqual([null])

    fireEvent.click(screen.getByTestId("reopen-workspace-members"))
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    await waitFor(() => expect(userTriggerText()).toContain("选择成员"))
    expect(
      (screen.getByLabelText("空间角色").textContent ?? "").trim()
    ).toContain("成员")
  })

  test("resets the selection when the workspace changes", async () => {
    const view = renderPage(<WorkspaceMembersDialog {...baseProps} />)
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    await choose(screen.getByLabelText("成员"), "Dave · dave")
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))

    rerenderPage(
      view,
      <WorkspaceMembersDialog {...baseProps} workspace={defaultWorkspace} />
    )
    await waitFor(() => expect(userTriggerText()).toContain("选择成员"))
    expect(
      (screen.getByLabelText("空间角色").textContent ?? "").trim()
    ).toContain("成员")
  })

  test("keeps the dialog open when interacting with an open dropdown menu", async () => {
    renderPage(<WorkspaceMembersDialog {...baseProps} />)
    await screen.findByRole("dialog", { name: "管理工作空间成员" })
    fireEvent.pointerDown(screen.getByLabelText("成员"))
    const menu = await screen.findByRole("menu")
    // Pointer interaction inside the portaled dropdown content must not
    // dismiss the dialog.
    fireEvent.pointerDown(within(menu).getByText("Dave · dave"))
    expect(
      screen.getByRole("dialog", { name: "管理工作空间成员" })
    ).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// TeamMembersDialog
// ---------------------------------------------------------------------------

describe("TeamMembersDialog", () => {
  const baseProps = {
    team,
    setTeam: () => undefined,
    members: [teamMember(alice, "admin"), teamMember(bob)],
    workspaceMembers: [
      member(alice, "admin"),
      member(bob),
      member(carol, "member"),
      member(dave, "member"),
    ],
    isLoading: false,
    isMutating: false,
    canManageTeamAdmins: true,
    onAddMember: async () => undefined,
    onUpdateMemberRole: async () => undefined,
    onRemoveMember: async () => undefined,
  }

  test("renders nothing when no team is selected", () => {
    renderPage(<TeamMembersDialog {...baseProps} team={null} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("opens with the team name, member list and count badge", async () => {
    renderPage(<TeamMembersDialog {...baseProps} />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理团队成员",
    })
    expect(dialog.textContent).toContain("Beta Team")
    expect(dialog.textContent).toContain("Alice")
    expect(dialog.textContent).toContain("alice · alice@app.local")
    expect(dialog.textContent).toContain("Bob")
    expect(screen.getByText("团队成员")).toBeTruthy()
    expect(screen.getByText("2")).toBeTruthy()
  })

  test("translates the default team display name", async () => {
    renderPage(<TeamMembersDialog {...baseProps} team={defaultTeam} />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理团队成员",
    })
    expect(dialog.textContent).toContain("默认团队")
  })

  test("adds a workspace member as team admin and resets", async () => {
    const calls: Array<[string, string]> = []
    renderPage(
      <TeamMembersDialog
        {...baseProps}
        onAddMember={async (userId, role) => {
          calls.push([userId, role])
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })

    // Candidates come from active workspace members that are not in the team.
    const userTrigger = screen.getByLabelText("成员") as HTMLButtonElement
    fireEvent.pointerDown(userTrigger)
    const menu = await screen.findByRole("menu")
    expect(within(menu).getByText("Dave · dave")).toBeTruthy()
    expect(within(menu).queryByText("Carol · carol")).toBeNull()
    expect(within(menu).queryByText("Alice · alice")).toBeNull()
    fireEvent.click(within(menu).getByText("Dave · dave"))
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))

    const roleTrigger = screen.getByLabelText("角色") as HTMLButtonElement
    fireEvent.pointerDown(roleTrigger)
    fireEvent.click(within(await screen.findByRole("menu")).getByText("管理员"))
    await waitFor(() =>
      expect((roleTrigger.textContent ?? "").trim()).toContain("管理员")
    )

    fireEvent.click(screen.getByRole("button", { name: "添加成员" }))
    await waitFor(() => expect(calls).toEqual([["u-4", "admin"]]))
    await waitFor(() => expect(userTriggerText()).toContain("选择成员"))
    expect((screen.getByLabelText("角色").textContent ?? "").trim()).toContain(
      "成员"
    )
  })

  test("forces the member role when team admins cannot be managed", async () => {
    const calls: Array<[string, string]> = []
    renderPage(
      <TeamMembersDialog
        {...baseProps}
        canManageTeamAdmins={false}
        onAddMember={async (userId, role) => {
          calls.push([userId, role])
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })

    // The role field is not rendered at all.
    expect(screen.queryByLabelText("角色")).toBeNull()

    await choose(screen.getByLabelText("成员"), "Dave · dave")
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))
    fireEvent.click(screen.getByRole("button", { name: "添加成员" }))
    await waitFor(() => expect(calls).toEqual([["u-4", "member"]]))
  })

  test("shows the empty-candidates state when everyone is a member", async () => {
    renderPage(
      <TeamMembersDialog
        {...baseProps}
        workspaceMembers={[member(alice, "admin"), member(bob), member(carol)]}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })
    const userTrigger = screen.getByLabelText("成员") as HTMLButtonElement
    expect(userTrigger.disabled).toBe(true)
    expect(userTriggerText()).toContain("暂无可加入成员")
  })

  test("shows the loading text while members load", async () => {
    renderPage(<TeamMembersDialog {...baseProps} isLoading />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理团队成员",
    })
    expect(dialog.querySelector(".animate-spin")).toBeTruthy()
    expect(screen.queryByText("Alice")).toBeNull()
    const userTrigger = screen.getByLabelText("成员") as HTMLButtonElement
    expect(userTrigger.disabled).toBe(true)
    expect(userTriggerText()).toContain("正在加载")
  })

  test("renders the empty member list placeholder", async () => {
    renderPage(<TeamMembersDialog {...baseProps} members={[]} />)
    const dialog = await screen.findByRole("dialog", {
      name: "管理团队成员",
    })
    expect(dialog.textContent).toContain("暂无团队成员")
    expect(dialog.textContent).toContain("0")
  })

  test("disables controls and shows the spinner while mutating", async () => {
    renderPage(<TeamMembersDialog {...baseProps} isMutating />)
    await screen.findByRole("dialog", { name: "管理团队成员" })
    const addButton = screen.getByRole("button", {
      name: "添加成员",
    }) as HTMLButtonElement
    expect(addButton.disabled).toBe(true)
    expect(addButton.querySelector("svg.lucide-loader-circle")).toBeTruthy()
    expect((screen.getByLabelText("成员") as HTMLButtonElement).disabled).toBe(
      true
    )
    expect((screen.getByLabelText("角色") as HTMLButtonElement).disabled).toBe(
      true
    )
    expect(
      (
        within(memberRow("Alice")).getByRole("button", {
          name: "管理员",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
  })

  test("updates member roles through the row dropdowns", async () => {
    const calls: Array<[string, string]> = []
    renderPage(
      <TeamMembersDialog
        {...baseProps}
        onUpdateMemberRole={async (userId, role) => {
          calls.push([userId, role])
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })

    const aliceRole = within(memberRow("Alice")).getByRole("button", {
      name: "管理员",
    })
    fireEvent.pointerDown(aliceRole)
    fireEvent.click(within(await screen.findByRole("menu")).getByText("成员"))
    await waitFor(() => expect(calls).toEqual([["u-1", "member"]]))

    const bobRole = within(memberRow("Bob")).getByRole("button", {
      name: "成员",
    })
    fireEvent.pointerDown(bobRole)
    fireEvent.click(within(await screen.findByRole("menu")).getByText("管理员"))
    await waitFor(() =>
      expect(calls).toEqual([
        ["u-1", "member"],
        ["u-2", "admin"],
      ])
    )
  })

  test("removes a member through the remove button", async () => {
    const calls: string[] = []
    renderPage(
      <TeamMembersDialog
        {...baseProps}
        onRemoveMember={async (userId) => {
          calls.push(userId)
        }}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })
    fireEvent.click(within(memberRow("Bob")).getByLabelText("移除成员"))
    await waitFor(() => expect(calls).toEqual(["u-2"]))
  })

  test("protects the last admin from demotion and removal", async () => {
    renderPage(
      <TeamMembersDialog
        {...baseProps}
        members={[teamMember(alice, "admin")]}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })
    const roleTrigger = within(memberRow("Alice")).getByRole("button", {
      name: "管理员",
    }) as HTMLButtonElement
    expect(roleTrigger.disabled).toBe(true)
    expect(roleTrigger.getAttribute("title")).toBe("不能移除最后一个管理员")
    const remove = within(memberRow("Alice")).getByLabelText(
      "移除成员"
    ) as HTMLButtonElement
    expect(remove.disabled).toBe(true)
    expect(remove.getAttribute("title")).toBe("不能移除最后一个管理员")
  })

  test("hides role management and protects admin removal when admins cannot be managed", async () => {
    renderPage(
      <TeamMembersDialog
        {...baseProps}
        canManageTeamAdmins={false}
        workspaceMembers={[member(alice, "admin"), member(bob)]}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })
    const aliceRow = memberRow("Alice")
    expect(
      within(aliceRow).queryByRole("button", { name: "管理员" })
    ).toBeNull()
    expect(within(aliceRow).getByText("管理员")).toBeTruthy()
    expect(
      (within(aliceRow).getByLabelText("移除成员") as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(
      (within(memberRow("Bob")).getByLabelText("移除成员") as HTMLButtonElement)
        .disabled
    ).toBe(false)
  })

  test("closes via Escape and resets the pending selection", async () => {
    const closed: Array<Team | null> = []
    renderPage(
      <TeamHarness
        initial={team}
        onClosed={(next) => {
          closed.push(next)
        }}
        {...baseProps}
      />
    )
    await screen.findByRole("dialog", { name: "管理团队成员" })
    await choose(screen.getByLabelText("成员"), "Dave · dave")
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))

    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(closed).toEqual([null])

    fireEvent.click(screen.getByTestId("reopen-team-members"))
    await screen.findByRole("dialog", { name: "管理团队成员" })
    await waitFor(() => expect(userTriggerText()).toContain("选择成员"))
    expect((screen.getByLabelText("角色").textContent ?? "").trim()).toContain(
      "成员"
    )
  })

  test("resets the selection when the team changes", async () => {
    const view = renderPage(<TeamMembersDialog {...baseProps} />)
    await screen.findByRole("dialog", { name: "管理团队成员" })
    await choose(screen.getByLabelText("成员"), "Dave · dave")
    await waitFor(() => expect(userTriggerText()).toContain("Dave"))

    rerenderPage(view, <TeamMembersDialog {...baseProps} team={defaultTeam} />)
    await waitFor(() => expect(userTriggerText()).toContain("选择成员"))
  })

  test("keeps the dialog open when interacting with an open dropdown menu", async () => {
    renderPage(<TeamMembersDialog {...baseProps} />)
    await screen.findByRole("dialog", { name: "管理团队成员" })
    fireEvent.pointerDown(screen.getByLabelText("成员"))
    const menu = await screen.findByRole("menu")
    fireEvent.pointerDown(within(menu).getByText("Dave · dave"))
    expect(screen.getByRole("dialog", { name: "管理团队成员" })).toBeTruthy()
  })
})

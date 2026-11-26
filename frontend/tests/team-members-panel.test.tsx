/* @jsxImportSource react */
/**
 * DOM-level coverage for team-admin direct team-member management in
 * SystemShell (`/system/team-members` & `TeamMembersPanel`).
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"

import { SystemShell } from "@/components/system/system-shell"
import type { MeResponse } from "@/lib/api/auth"
import type { Team, TeamMember, Workspace, WorkspaceMember } from "@/lib/api/system"
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
const replacements: string[] = []
mockUseSession(session)
mockNextNavigation({
  replace: (href: string) => replacements.push(href),
})

const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  selectedWorkspaceId: string | null
  workspaces: Workspace[]
  teams: Team[]
  notify: (kind: "success" | "error", message: string) => void
}

const ws1: Workspace = {
  id: "ws-1",
  name: "Test Workspace",
  description: "",
  status: "active",
  is_default: true,
}

const teamAlpha: Team = {
  id: "team-1",
  workspace_id: "ws-1",
  name: "Team Alpha",
  description: "Alpha",
  status: "active",
  is_default: false,
}

const teamBeta: Team = {
  id: "team-2",
  workspace_id: "ws-1",
  name: "Team Beta",
  description: "Beta",
  status: "active",
  is_default: false,
}

const teamAdminUser = {
  id: "u-team-admin",
  username: "team_admin",
  email: "team_admin@app.local",
  name: "Team Admin",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "member" },
  ],
  teams: [
    {
      id: "team-1",
      workspace_id: "ws-1",
      name: "Team Alpha",
      is_default: false,
      role: "admin",
    },
  ],
}

const memberBob = {
  id: "u-bob",
  username: "bob",
  email: "bob@app.local",
  name: "Bob Member",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-02T00:00:00Z",
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "member" },
  ],
  teams: [],
}

const candidateCarol = {
  id: "u-carol",
  username: "carol",
  email: "carol@app.local",
  name: "Carol Candidate",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-03T00:00:00Z",
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "member" },
  ],
  teams: [],
}

const rootSystemAdmin = {
  id: "u-root",
  username: "root_admin",
  email: "root@app.local",
  name: "System Root Admin",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-04T00:00:00Z",
  workspaces: [
    { id: "ws-1", name: "Test Workspace", is_default: true, role: "admin" },
  ],
  teams: [],
}

const teamAdminMe: MeResponse = {
  user: teamAdminUser,
  memberships: [{ workspace_id: "ws-1", role: "member" }],
}

const ordinaryMe: MeResponse = {
  user: {
    ...memberBob,
    teams: [
      {
        id: "team-1",
        workspace_id: "ws-1",
        name: "Team Alpha",
        is_default: false,
        role: "member",
      },
    ],
  },
  memberships: [{ workspace_id: "ws-1", role: "member" }],
}

let handler: FetchHandler = () => jsonResponse([])

beforeEach(() => {
  replacements.length = 0
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    return Promise.resolve(handler(url, init))
  }) as typeof fetch
  sessionState.me = teamAdminMe
  sessionState.token = "test-token"
  sessionState.selectedWorkspaceId = "ws-1"
  sessionState.workspaces = [ws1]
  sessionState.teams = [teamAlpha, teamBeta]
  sessionState.notify = () => undefined
})

afterEach(() => {
  cleanup()
  resetFetch()
})

describe("team admin direct team-members navigation and management", () => {
  test("team admin sees the 团队成员 tab and can search, add, and remove members directly", async () => {
    const notifications: Array<[string, string]> = []
    sessionState.notify = (kind, message) => {
      notifications.push([kind, message])
    }

    let members: TeamMember[] = [
      { user: teamAdminUser, role: "admin" },
      { user: memberBob, role: "member" },
    ]
    const workspaceMembers: WorkspaceMember[] = [
      { user: teamAdminUser, role: "member" },
      { user: memberBob, role: "member" },
      { user: candidateCarol, role: "member" },
      { user: rootSystemAdmin, role: "admin" },
    ]
    const addRequests: Array<{ user_id: string; role: string }> = []
    const deletedUsers: string[] = []

    handler = (url, init) => {
      const method = init?.method ?? "GET"
      const pathname = url.split("?")[0]
      if (method === "GET" && pathname === "/api/v1/workspaces/ws-1/teams/team-1/members") {
        return jsonResponse(members)
      }
      if (method === "GET" && pathname === "/api/v1/workspaces/ws-1/members") {
        return jsonResponse(workspaceMembers)
      }
      if (method === "POST" && pathname === "/api/v1/workspaces/ws-1/teams/team-1/members") {
        const body = JSON.parse(String(init?.body ?? "{}")) as {
          user_id: string
          role: string
        }
        addRequests.push(body)
        const created: TeamMember = { user: candidateCarol, role: body.role }
        members = [...members, created]
        return jsonResponse(created, 201)
      }
      if (method === "DELETE" && pathname.startsWith("/api/v1/workspaces/ws-1/teams/team-1/members/")) {
        const targetId = pathname.split("/").pop() ?? ""
        deletedUsers.push(targetId)
        members = members.filter((item) => item.user.id !== targetId)
        return new Response(null, { status: 204 })
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    }

    renderPage(<SystemShell activeTab="teams" />)

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "工作空间",
      "团队",
      "团队成员",
      "记忆",
    ])

    fireEvent.click(screen.getByRole("tab", { name: "团队成员" }))

    expect(await screen.findByText("Bob Member")).toBeTruthy()
    expect(screen.getByText("Team Admin")).toBeTruthy()

    // Admin's remove button is disabled (last admin / protected), Bob's is enabled.
    const adminRow = screen.getByText("Team Admin").closest("tr")!
    const bobRow = screen.getByText("Bob Member").closest("tr")!
    expect(
      (within(adminRow).getByRole("button", { name: "移除成员" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(
      (within(bobRow).getByRole("button", { name: "移除成员" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)

    // Candidate search excludes global admins for team admins and supports fuzzy matching.
    const candidateInput = screen.getByRole("combobox", {
      name: "选择成员",
    }) as HTMLInputElement
    const searchInput = screen.getByLabelText("搜索团队成员") as HTMLInputElement
    expect(searchInput.placeholder).toBe("搜索已有成员（姓名、账号、邮箱）")
    expect(candidateInput.placeholder).toBe("搜索待添加成员")
    fireEvent.focus(candidateInput)
    const candidateListbox = await screen.findByRole("listbox")
    expect(within(candidateListbox).queryByText(/System Root Admin/)).toBeNull()
    expect(within(candidateListbox).getByText(/Carol Candidate/)).toBeTruthy()

    fireEvent.change(candidateInput, { target: { value: "crl" } })
    fireEvent.click(within(await screen.findByRole("listbox")).getByText(/Carol Candidate/))
    fireEvent.click(screen.getByRole("button", { name: "添加成员" }))

    await waitFor(() =>
      expect(addRequests).toEqual([{ user_id: "u-carol", role: "member" }])
    )
    expect(await screen.findByText("Carol Candidate")).toBeTruthy()

    // Filter with search box.
    fireEvent.change(searchInput, { target: { value: "Bob" } })
    expect(screen.queryByText("Carol Candidate")).toBeNull()
    expect(screen.getByText("Bob Member")).toBeTruthy()
    fireEvent.change(searchInput, { target: { value: "" } })

    // Remove Bob after confirmation.
    const refreshedBobRow = screen.getByText("Bob Member").closest("tr")!
    fireEvent.click(within(refreshedBobRow).getByRole("button", { name: "移除成员" }))
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "移除" }))

    await waitFor(() => expect(deletedUsers).toEqual(["u-bob"]))
    await waitFor(() => expect(screen.queryByText("Bob Member")).toBeNull())
    expect(notifications).toContainEqual(["success", "团队成员已添加"])
    expect(notifications).toContainEqual(["success", "团队成员已移除"])
  })

  test("ordinary members cannot open team-members tab directly", () => {
    sessionState.me = ordinaryMe
    const { container } = renderPage(<SystemShell activeTab="team-members" />)
    expect(container.firstChild).toBeNull()
    expect(replacements).toEqual(["/system/teams"])
  })
})

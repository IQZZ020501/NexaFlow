/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { TeamsPanel } from "@/components/system/panels/teams-panel"
import type { Team, Workspace } from "@/lib/api/system"
import { cleanup, fireEvent, renderPage, resetFetch, screen, waitFor } from "./helpers/dom"

afterEach(() => {
  cleanup()
  resetFetch()
})

const workspace: Workspace = {
  id: "ws-1",
  name: "Engineering",
  description: "",
  status: "active",
  is_default: false,
}

const defaultWorkspace: Workspace = {
  ...workspace,
  name: "Default Workspace",
  is_default: true,
}

const activeTeam: Team = {
  id: "t-1",
  workspace_id: "ws-1",
  name: "Platform",
  description: "Core platform",
  status: "active",
  is_default: false,
}

const archivedTeam: Team = {
  id: "t-2",
  workspace_id: "ws-1",
  name: "Legacy",
  description: "",
  status: "archived",
  is_default: false,
}

const defaultTeam: Team = {
  id: "t-3",
  workspace_id: "ws-1",
  name: "Default Team",
  description: "Everyone",
  status: "active",
  is_default: true,
}

describe("TeamsPanel", () => {
  test("shows a loading spinner while teams are loading", () => {
    const { container } = renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[]}
        isTeamsLoading
        canCreateTeam
        canManageWorkspace
        canManageTeamMembers={() => true}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(container.querySelector("svg.animate-spin")).toBeTruthy()
    expect(screen.queryByText("暂无团队")).toBeNull()
  })

  test("shows the empty message and workspace fallback when nothing is selected", () => {
    renderPage(
      <TeamsPanel
        selectedWorkspace={null}
        teams={[]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace={false}
        canManageTeamMembers={() => false}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(screen.getByRole("tabpanel")).toBeTruthy()
    expect(screen.getByText("团队")).toBeTruthy()
    expect(screen.getByText("未选择工作空间")).toBeTruthy()
    expect(screen.getByText("暂无团队")).toBeTruthy()
  })

  test("renders the selected workspace name", () => {
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace={false}
        canManageTeamMembers={() => false}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(screen.getByText("Engineering")).toBeTruthy()
  })

  test("translates the default workspace name", () => {
    renderPage(
      <TeamsPanel
        selectedWorkspace={defaultWorkspace}
        teams={[]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace={false}
        canManageTeamMembers={() => false}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(screen.getByText("默认工作空间")).toBeTruthy()
  })

  test("shows the create button only when permitted and reports clicks", () => {
    let createCalls = 0
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[]}
        isTeamsLoading={false}
        canCreateTeam
        canManageWorkspace
        canManageTeamMembers={() => true}
        handleOpenCreateTeam={() => {
          createCalls += 1
        }}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "新建团队" }))
    expect(createCalls).toBe(1)
  })

  test("hides the create button when creation is not permitted", () => {
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[activeTeam]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace
        canManageTeamMembers={() => true}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(screen.queryByRole("button", { name: "新建团队" })).toBeNull()
  })

  test("renders team rows with names, statuses, and default badge", () => {
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[activeTeam, archivedTeam, defaultTeam]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace={false}
        canManageTeamMembers={() => false}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(screen.getByText("Platform")).toBeTruthy()
    expect(screen.getByText("Core platform")).toBeTruthy()
    expect(screen.getAllByText("已启用").length).toBe(2)
    expect(screen.getByText("Legacy")).toBeTruthy()
    // Missing description falls back to a dash.
    expect(screen.getByText("-")).toBeTruthy()
    expect(screen.getByText("已归档")).toBeTruthy()
    // Default team name is translated and shows the default badge.
    expect(screen.getByText("默认团队")).toBeTruthy()
    expect(screen.getByText("默认")).toBeTruthy()
  })

  test("calls the member management handler for a team", () => {
    const opened: Team[] = []
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[activeTeam]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace={false}
        canManageTeamMembers={(team) => team.id === "t-1"}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={(team) => {
          opened.push(team)
        }}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "管理团队成员" }))
    expect(opened).toEqual([activeTeam])
  })

  test("hides the member button when membership management is unavailable", () => {
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[activeTeam]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace
        canManageTeamMembers={() => false}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(screen.queryByRole("button", { name: "管理团队成员" })).toBeNull()
    // Workspace-level actions remain available.
    expect(screen.getByRole("button", { name: "编辑团队" })).toBeTruthy()
  })

  test("calls edit, archive, and delete handlers for a team", () => {
    const edited: Team[] = []
    const archived: Team[] = []
    const deleted: Team[] = []
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[activeTeam]}
        isTeamsLoading={false}
        canCreateTeam
        canManageWorkspace
        canManageTeamMembers={() => true}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={(team) => {
          edited.push(team)
        }}
        handleArchiveTeam={(team) => {
          archived.push(team)
        }}
        handleDeleteTeam={(team) => {
          deleted.push(team)
        }}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "编辑团队" }))
    fireEvent.click(screen.getByRole("button", { name: "归档团队" }))
    fireEvent.click(screen.getByRole("button", { name: "永久删除团队" }))
    expect(edited).toEqual([activeTeam])
    expect(archived).toEqual([activeTeam])
    expect(deleted).toEqual([activeTeam])
  })

  test("flips the archive label for archived teams and restores them", () => {
    const archived: Team[] = []
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[archivedTeam]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace
        canManageTeamMembers={() => false}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={(team) => {
          archived.push(team)
        }}
        handleDeleteTeam={() => undefined}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "恢复团队" }))
    expect(archived).toEqual([archivedTeam])
  })

  test("hides workspace management actions when not permitted", () => {
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[activeTeam]}
        isTeamsLoading={false}
        canCreateTeam
        canManageWorkspace={false}
        canManageTeamMembers={() => true}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={() => undefined}
        handleDeleteTeam={() => undefined}
      />
    )

    expect(screen.queryByRole("button", { name: "编辑团队" })).toBeNull()
    expect(screen.queryByRole("button", { name: "归档团队" })).toBeNull()
    expect(screen.queryByRole("button", { name: "永久删除团队" })).toBeNull()
  })

  test("awaits asynchronous archive and delete handlers", async () => {
    const archived: string[] = []
    const deleted: string[] = []
    renderPage(
      <TeamsPanel
        selectedWorkspace={workspace}
        teams={[activeTeam]}
        isTeamsLoading={false}
        canCreateTeam={false}
        canManageWorkspace
        canManageTeamMembers={() => false}
        handleOpenCreateTeam={() => undefined}
        handleOpenTeamMembers={() => undefined}
        handleOpenEditTeam={() => undefined}
        handleArchiveTeam={async (team) => {
          archived.push(team.id)
        }}
        handleDeleteTeam={async (team) => {
          deleted.push(team.id)
        }}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "归档团队" }))
    fireEvent.click(screen.getByRole("button", { name: "永久删除团队" }))
    await waitFor(() => expect(archived).toEqual(["t-1"]))
    await waitFor(() => expect(deleted).toEqual(["t-1"]))
  })
})

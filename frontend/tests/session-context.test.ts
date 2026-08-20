import { describe, expect, test } from "bun:test"

import {
  addCreatedTeamMembership,
  addCreatedWorkspaceMembership,
  getInitialWorkspaceId,
  replaceSessionUser,
} from "../src/contexts/session-context"
import type { MeResponse, User } from "../src/lib/api/auth"
import type { Team, WorkspaceCreateResponse } from "../src/lib/api/system"

const currentUser: User = {
  id: "current-user",
  username: "admin",
  email: "admin@example.com",
  name: "NexaFlow Admin",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-06T00:00:00Z",
  workspaces: [],
  teams: [],
}

const me: MeResponse = {
  user: currentUser,
  memberships: [],
}

describe("session user updates", () => {
  test("replaces only the current session user", () => {
    const updatedUser = {
      ...currentUser,
      email: "updated@example.com",
      name: "Updated Admin",
    }

    expect(replaceSessionUser(me, updatedUser)).toEqual({
      ...me,
      user: updatedUser,
    })
    expect(
      replaceSessionUser(me, { ...updatedUser, id: "another-user" })
    ).toBe(me)
  })

  test("adds a created workspace when the current user is its admin", () => {
    const payload: WorkspaceCreateResponse = {
      workspace: {
        id: "workspace-1",
        name: "Workspace 1",
        description: "",
        status: "active",
        is_default: false,
      },
      admin_user: currentUser,
    }

    expect(addCreatedWorkspaceMembership(me, payload)).toEqual({
      ...me,
      memberships: [{ workspace_id: "workspace-1", role: "admin" }],
    })
    expect(
      addCreatedWorkspaceMembership(me, {
        ...payload,
        admin_user: { ...currentUser, id: "another-user" },
      })
    ).toBe(me)
  })

  test("adds a created team when the current user is its admin", () => {
    const team: Team = {
      id: "team-1",
      workspace_id: "workspace-1",
      name: "Team 1",
      description: "",
      status: "active",
      is_default: false,
    }

    expect(addCreatedTeamMembership(me, team, currentUser.id)).toEqual({
      ...me,
      user: {
        ...currentUser,
        teams: [
          {
            id: team.id,
            workspace_id: team.workspace_id,
            name: team.name,
            is_default: team.is_default,
            role: "admin",
          },
        ],
      },
    })
    expect(addCreatedTeamMembership(me, team, "another-user")).toBe(me)
  })

  test("selects any active workspace for a global admin", () => {
    const workspaces = [
      {
        id: "workspace-1",
        name: "Workspace 1",
        description: "",
        status: "active",
        is_default: false,
      },
      {
        id: "workspace-2",
        name: "Workspace 2",
        description: "",
        status: "active",
        is_default: false,
      },
    ]

    expect(getInitialWorkspaceId(me, workspaces, "workspace-2")).toBe(
      "workspace-2"
    )
  })
})

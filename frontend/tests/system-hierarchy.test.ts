import { describe, expect, test } from "bun:test"

import {
  canAccessWorkspaceAnalytics,
  canManageTeamMembers,
} from "../src/components/system/system-utils"
import type { MeResponse } from "../src/lib/api/auth"
import type { Team } from "../src/lib/api/system"
import { getMembershipRole, hasWorkspaceMembership } from "../src/lib/display"

const team: Team = {
  id: "team-1",
  workspace_id: "workspace-1",
  name: "Team 1",
  description: "",
  status: "active",
  is_default: false,
}

function me(overrides: Partial<MeResponse["user"]> = {}): MeResponse {
  return {
    user: {
      id: "user-1",
      username: "user-1",
      email: "user-1@example.com",
      name: "User 1",
      is_global_admin: false,
      must_change_password: false,
      is_active: true,
      created_at: "2026-08-06T00:00:00Z",
      workspaces: [],
      teams: [],
      ...overrides,
    },
    memberships: [],
  }
}

describe("system hierarchy permissions", () => {
  test("lets a global admin enter every workspace without explicit membership", () => {
    const globalAdmin = me({ is_global_admin: true })

    expect(hasWorkspaceMembership(globalAdmin, "workspace-1")).toBe(true)
    expect(getMembershipRole(globalAdmin, "workspace-1")).toBe("admin")
  })

  test("uses the selected workspace role for workspace-level management", () => {
    const workspaceAdmin = me()
    workspaceAdmin.memberships = [
      { workspace_id: "workspace-1", role: "admin" },
      { workspace_id: "workspace-2", role: "member" },
    ]

    expect(getMembershipRole(workspaceAdmin, "workspace-1")).toBe("admin")
    expect(getMembershipRole(workspaceAdmin, "workspace-2")).toBe("member")
  })

  test("limits team member management to the hierarchy's administrators", () => {
    const workspaceAdmin = me({
      workspaces: [
        {
          id: "workspace-1",
          name: "Workspace 1",
          is_default: false,
          role: "admin",
        },
      ],
    })
    const teamAdmin = me({
      teams: [
        {
          id: "team-1",
          workspace_id: "workspace-1",
          name: "Team 1",
          is_default: false,
          role: "admin",
        },
      ],
    })

    expect(canManageTeamMembers(workspaceAdmin, team)).toBe(true)
    expect(canManageTeamMembers(teamAdmin, team)).toBe(true)
    expect(canManageTeamMembers(me(), team)).toBe(false)
  })

  test("limits workspace analytics to global and workspace administrators", () => {
    const globalAdmin = me({ is_global_admin: true })
    const workspaceAdmin = me({
      workspaces: [
        {
          id: "workspace-1",
          name: "Workspace 1",
          is_default: false,
          role: "admin",
        },
      ],
    })
    const teamAdmin = me({
      teams: [
        {
          id: "team-1",
          workspace_id: "workspace-1",
          name: "Team 1",
          is_default: false,
          role: "admin",
        },
      ],
    })

    expect(canAccessWorkspaceAnalytics(globalAdmin)).toBe(true)
    expect(canAccessWorkspaceAnalytics(workspaceAdmin)).toBe(true)
    expect(canAccessWorkspaceAnalytics(teamAdmin)).toBe(false)
    expect(canAccessWorkspaceAnalytics(me())).toBe(false)
  })
})

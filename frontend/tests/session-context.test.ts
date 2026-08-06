import { describe, expect, test } from "bun:test"

import {
  addCreatedWorkspaceMembership,
  replaceSessionUser,
} from "../contexts/session-context"
import type { MeResponse, User } from "../lib/api/auth"
import type { WorkspaceCreateResponse } from "../lib/api/system"

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
})

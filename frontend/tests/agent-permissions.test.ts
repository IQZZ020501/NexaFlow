import { afterEach, describe, expect, test } from "bun:test"

import {
  grantAgentPermission,
  listAgentPermissions,
  revokeAgentPermission,
  type Agent,
  type AgentPermission,
} from "../src/lib/api/agents"
import { availableAgentPermissionTargets } from "../src/components/agents/agent-permissions-dialog"
import type { WorkspaceMember } from "../src/lib/api/system"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe("Agent permissions API", () => {
  test("lists, grants view, and revokes a user permission", async () => {
    const requests: Array<{ url: string; method: string; body: string }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      requests.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      })
      if (init?.method === "DELETE") {
        return new Response(null, { status: 204 })
      }
      return Response.json([])
    }) as unknown as typeof fetch

    await listAgentPermissions("token", "workspace-1", "agent-1")
    await grantAgentPermission("token", "workspace-1", "agent-1", "user-1")
    await revokeAgentPermission("token", "workspace-1", "agent-1", "user-1")

    expect(requests.map(({ method }) => method)).toEqual([
      "GET",
      "PUT",
      "DELETE",
    ])
    expect(requests.map(({ url }) => url)).toEqual([
      expect.stringContaining(
        "/api/v1/workspaces/workspace-1/agents/agent-1/permissions"
      ),
      expect.stringContaining(
        "/api/v1/workspaces/workspace-1/agents/agent-1/permissions/user-1"
      ),
      expect.stringContaining(
        "/api/v1/workspaces/workspace-1/agents/agent-1/permissions/user-1"
      ),
    ])
    expect(JSON.parse(requests[1].body)).toEqual({ permission: "view" })
  })

  test("offers only non-owner members without an existing grant", () => {
    const user = (id: string) =>
      ({ id, name: id, username: id }) as WorkspaceMember["user"]
    const agent = {
      created_by_user_id: "owner",
    } as Agent
    const members = ["owner", "granted", "available"].map((id) => ({
      user: user(id),
      role: "member",
    }))
    const permissions = [
      { user: user("granted"), permission: "view" },
    ] as AgentPermission[]

    expect(
      availableAgentPermissionTargets(members, agent, permissions).map(
        (member) => member.user.id
      )
    ).toEqual(["available"])
  })
})

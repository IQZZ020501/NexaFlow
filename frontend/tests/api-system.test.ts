import { afterEach, describe, expect, test } from "bun:test"

import { ApiError } from "@/lib/api-client"
import {
  addTeamMember,
  addWorkspaceMember,
  changeUserPassword,
  createTeam,
  createUser,
  createWorkspace,
  createWorkspaceInvitation,
  createWorkspaceUser,
  deleteWorkspaceInvitation,
  deleteTeam,
  deleteUser,
  deleteWorkspace,
  getAdminHealth,
  getSmtpSettings,
  getWorkspaceGovernance,
  getWorkspaceInventory,
  listAllWorkspaceMembers,
  listAuditLogs,
  listSessions,
  listSystemLogs,
  listTeamMembers,
  listTeams,
  listUserSessions,
  listUsers,
  listWorkspaceAuditLogs,
  listWorkspaceInvitations,
  listWorkspaceMembers,
  listWorkspaces,
  removeTeamMember,
  removeWorkspaceMember,
  revokeAllUserSessions,
  revokeOtherSessions,
  revokeSession,
  revokeUserSession,
  revokeWorkspaceInvitation,
  sendSmtpTest,
  updateSmtpSettings,
  updateTeam,
  updateTeamMember,
  updateUser,
  updateWorkspace,
  updateWorkspaceGovernance,
  updateWorkspaceMember,
} from "@/lib/api/system"
import type { WorkspaceMember } from "@/lib/api/system"
import { jsonResponse, resetFetch, withFetch } from "./helpers/dom"

const TOKEN = "tok-1"

type RecordedCall = {
  url: string
  method: string
  body: string | null
  auth: string | null
}

let calls: RecordedCall[] = []

function install(respond: (url: string, init: RequestInit) => Response) {
  calls = []
  withFetch((url, init) => {
    const options = init ?? {}
    const headers = new Headers(options.headers)
    calls.push({
      url,
      method: options.method ?? "GET",
      body: typeof options.body === "string" ? options.body : null,
      auth: headers.get("Authorization"),
    })
    return respond(url, options)
  })
}

function last(): RecordedCall {
  return calls[calls.length - 1]
}

function expectCall(url: string, method = "GET", body?: unknown) {
  const call = last()
  expect(call.url).toBe(url)
  expect(call.method).toBe(method)
  expect(call.auth).toBe(`Bearer ${TOKEN}`)
  if (body !== undefined) {
    expect(JSON.parse(call.body ?? "null")).toEqual(body)
  }
}

function noContent(): Response {
  return new Response(null, { status: 204 })
}

const user = {
  id: "u-1",
  username: "alice",
  email: "alice@app.local",
  name: "Alice",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  workspaces: [],
  teams: [],
}

function member(id: string): WorkspaceMember {
  return {
    user: {
      ...user,
      id,
      username: `user-${id}`,
      email: `${id}@app.local`,
      name: `User ${id}`,
    },
    role: "member",
  }
}

afterEach(() => {
  resetFetch()
})

describe("admin user management", () => {
  test("listUsers issues a GET and parses the response", async () => {
    install(() => jsonResponse([user]))
    const result = await listUsers(TOKEN)
    expectCall("/api/v1/admin/users")
    expect(result).toEqual([user])
  })

  test("createUser posts the payload", async () => {
    const payload = {
      username: "bob",
      email: "bob@app.local",
      name: "Bob",
      is_global_admin: true,
      workspace_id: "ws-1",
      team_ids: ["t-1"],
    }
    install(() => jsonResponse({ user, password: "secret" }))
    await createUser(TOKEN, payload)
    expectCall("/api/v1/admin/users", "POST", payload)
  })

  test("updateUser patches the user", async () => {
    const payload = { name: "Alicia", is_active: false }
    install(() => jsonResponse(user))
    await updateUser(TOKEN, "u-1", payload)
    expectCall("/api/v1/admin/users/u-1", "PATCH", payload)
  })

  test("changeUserPassword posts the new password", async () => {
    install(() => jsonResponse(user))
    await changeUserPassword(TOKEN, "u-1", "hunter2")
    expectCall("/api/v1/admin/users/u-1/change-password", "POST", {
      new_password: "hunter2",
    })
  })

  test("deleteUser issues a DELETE and resolves undefined on 204", async () => {
    install(() => noContent())
    await expect(deleteUser(TOKEN, "u-1")).resolves.toBeUndefined()
    expectCall("/api/v1/admin/users/u-1", "DELETE")
  })
})

describe("workspace management", () => {
  const workspace = {
    id: "ws-1",
    name: "Engineering",
    description: "",
    status: "active",
    is_default: false,
  }

  test("listWorkspaces returns the workspace list", async () => {
    install(() => jsonResponse([workspace]))
    const result = await listWorkspaces(TOKEN)
    expectCall("/api/v1/workspaces")
    expect(result).toEqual([workspace])
  })

  test("createWorkspace posts the workspace payload", async () => {
    const payload = {
      name: "Finance",
      description: "Money",
      admin_user_id: "u-1",
    }
    install(() => jsonResponse({ workspace, admin_user: user }))
    await createWorkspace(TOKEN, payload)
    expectCall("/api/v1/workspaces", "POST", payload)
  })

  test("updateWorkspace patches the workspace", async () => {
    const payload = { name: "Finance 2", status: "archived" }
    install(() => jsonResponse(workspace))
    await updateWorkspace(TOKEN, "ws-1", payload)
    expectCall("/api/v1/workspaces/ws-1", "PATCH", payload)
  })

  test("deleteWorkspace issues a DELETE", async () => {
    install(() => noContent())
    await deleteWorkspace(TOKEN, "ws-1")
    expectCall("/api/v1/workspaces/ws-1", "DELETE")
  })
})

describe("workspace members", () => {
  test("listWorkspaceMembers uses default pagination", async () => {
    install(() => jsonResponse([member("u-1")]))
    await listWorkspaceMembers(TOKEN, "ws-1")
    expectCall("/api/v1/workspaces/ws-1/members?limit=200&offset=0")
  })

  test("listWorkspaceMembers honors custom pagination", async () => {
    install(() => jsonResponse([member("u-1")]))
    await listWorkspaceMembers(TOKEN, "ws-1", 50, 25)
    expectCall("/api/v1/workspaces/ws-1/members?limit=50&offset=25")
  })

  test("listAllWorkspaceMembers pages through full pages", async () => {
    const pageFull = Array.from({ length: 200 }, (_, i) => member(`u-${i}`))
    const pageTail = Array.from({ length: 50 }, (_, i) =>
      member(`u-${200 + i}`)
    )
    install((url) =>
      jsonResponse(url.includes("offset=0") ? pageFull : pageTail)
    )
    const result = await listAllWorkspaceMembers(TOKEN, "ws-1")
    expect(calls).toHaveLength(2)
    expect(calls[0].url).toBe(
      "/api/v1/workspaces/ws-1/members?limit=200&offset=0"
    )
    expect(calls[1].url).toBe(
      "/api/v1/workspaces/ws-1/members?limit=200&offset=200"
    )
    expect(result).toHaveLength(250)
  })

  test("listAllWorkspaceMembers stops after a short page", async () => {
    install(() => jsonResponse([member("u-1")]))
    const result = await listAllWorkspaceMembers(TOKEN, "ws-1")
    expect(calls).toHaveLength(1)
    expect(result).toHaveLength(1)
  })

  test("addWorkspaceMember posts the membership", async () => {
    const payload = { user_id: "u-2", role: "admin" }
    install(() => jsonResponse(member("u-2")))
    await addWorkspaceMember(TOKEN, "ws-1", payload)
    expectCall("/api/v1/workspaces/ws-1/members", "POST", payload)
  })

  test("createWorkspaceUser posts the new user", async () => {
    const payload = { username: "carol", email: "c@app.local", name: "Carol" }
    install(() => jsonResponse({ user, password: "secret" }))
    await createWorkspaceUser(TOKEN, "ws-1", payload)
    expectCall("/api/v1/workspaces/ws-1/members/users", "POST", payload)
  })

  test("updateWorkspaceMember patches the role", async () => {
    const payload = { role: "admin" }
    install(() => jsonResponse(member("u-1")))
    await updateWorkspaceMember(TOKEN, "ws-1", "u-1", payload)
    expectCall("/api/v1/workspaces/ws-1/members/u-1", "PATCH", payload)
  })

  test("removeWorkspaceMember issues a DELETE", async () => {
    install(() => noContent())
    await removeWorkspaceMember(TOKEN, "ws-1", "u-1")
    expectCall("/api/v1/workspaces/ws-1/members/u-1", "DELETE")
  })
})

describe("teams", () => {
  const team = {
    id: "t-1",
    workspace_id: "ws-1",
    name: "Platform",
    description: "",
    status: "active",
    is_default: false,
  }

  test("listTeams returns the teams", async () => {
    install(() => jsonResponse([team]))
    const result = await listTeams(TOKEN, "ws-1")
    expectCall("/api/v1/workspaces/ws-1/teams")
    expect(result).toEqual([team])
  })

  test("createTeam posts the team", async () => {
    const payload = {
      name: "Platform",
      description: "Core",
      admin_user_id: "u-1",
    }
    install(() => jsonResponse(team))
    await createTeam(TOKEN, "ws-1", payload)
    expectCall("/api/v1/workspaces/ws-1/teams", "POST", payload)
  })

  test("updateTeam patches the team", async () => {
    const payload = { description: "Renamed", status: "archived" }
    install(() => jsonResponse(team))
    await updateTeam(TOKEN, "ws-1", "t-1", payload)
    expectCall("/api/v1/workspaces/ws-1/teams/t-1", "PATCH", payload)
  })

  test("deleteTeam issues a DELETE", async () => {
    install(() => noContent())
    await deleteTeam(TOKEN, "ws-1", "t-1")
    expectCall("/api/v1/workspaces/ws-1/teams/t-1", "DELETE")
  })
})

describe("team members", () => {
  test("listTeamMembers uses default pagination", async () => {
    install(() => jsonResponse([member("u-1")]))
    await listTeamMembers(TOKEN, "ws-1", "t-1")
    expectCall("/api/v1/workspaces/ws-1/teams/t-1/members?limit=200&offset=0")
  })

  test("listTeamMembers honors custom pagination", async () => {
    install(() => jsonResponse([member("u-1")]))
    await listTeamMembers(TOKEN, "ws-1", "t-1", 10, 40)
    expectCall("/api/v1/workspaces/ws-1/teams/t-1/members?limit=10&offset=40")
  })

  test("addTeamMember posts the membership", async () => {
    const payload = { user_id: "u-2", role: "admin" }
    install(() => jsonResponse(member("u-2")))
    await addTeamMember(TOKEN, "ws-1", "t-1", payload)
    expectCall("/api/v1/workspaces/ws-1/teams/t-1/members", "POST", payload)
  })

  test("updateTeamMember patches the role", async () => {
    const payload = { role: "member" }
    install(() => jsonResponse(member("u-1")))
    await updateTeamMember(TOKEN, "ws-1", "t-1", "u-1", payload)
    expectCall(
      "/api/v1/workspaces/ws-1/teams/t-1/members/u-1",
      "PATCH",
      payload
    )
  })

  test("removeTeamMember issues a DELETE", async () => {
    install(() => noContent())
    await removeTeamMember(TOKEN, "ws-1", "t-1", "u-1")
    expectCall("/api/v1/workspaces/ws-1/teams/t-1/members/u-1", "DELETE")
  })
})

describe("audit and system logs", () => {
  const log = {
    id: "audit-1",
    actor_user_id: "u-1",
    actor_username: "alice",
    actor_name: "Alice",
    workspace_id: "ws-1",
    action: "workspace.create",
    resource_type: "workspace",
    resource_id: "ws-2",
    resource_name: "Workspace 2",
    details: {},
    created_at: "2026-08-19T00:00:00Z",
  }

  test("listAuditLogs includes every defined filter", async () => {
    install(() => jsonResponse([log]))
    await listAuditLogs(TOKEN, {
      limit: 10,
      offset: 5,
      workspace_id: "ws-1",
      actor: "alice",
      action: "workspace.create",
      resource_type: "team",
      resource_id: "t-1",
      search: "rename",
      from: "2026-01-01",
      to: "2026-02-01",
    })
    expectCall(
      "/api/v1/admin/audit-logs?limit=10&offset=5&workspace_id=ws-1&actor=alice&action=workspace.create&resource_type=team&resource_id=t-1&search=rename&from=2026-01-01&to=2026-02-01"
    )
  })

  test("listAuditLogs drops empty filter values", async () => {
    install(() => jsonResponse([log]))
    await listAuditLogs(TOKEN, { action: "", search: undefined, from: "" })
    expectCall("/api/v1/admin/audit-logs")
  })

  test("listAuditLogs works without filters", async () => {
    install(() => jsonResponse([log]))
    await listAuditLogs(TOKEN)
    expectCall("/api/v1/admin/audit-logs")
  })

  test("listWorkspaceAuditLogs scopes the query to the workspace", async () => {
    install(() => jsonResponse([log]))
    await listWorkspaceAuditLogs(TOKEN, "ws-1", { action: "team.create" })
    expectCall(
      "/api/v1/workspaces/ws-1/audit-logs?action=team.create"
    )
  })

  test("listSystemLogs serializes log filters", async () => {
    install(() => jsonResponse([{ ...log, id: "sys-1" }]))
    await listSystemLogs(TOKEN, {
      level: "error",
      event: "auth.login_failed",
      status_code: 500,
      user_id: "u-1",
      include_stack: true,
      limit: 20,
    })
    expectCall(
      "/api/v1/admin/system-logs?level=error&event=auth.login_failed&status_code=500&user_id=u-1&include_stack=true&limit=20"
    )
  })

  test("getAdminHealth returns health status", async () => {
    const health = {
      status: "ok" as const,
      components: {},
      pending_tasks: 0,
      failed_logs_24h: 0,
      checked_at: "2026-08-19T00:00:00Z",
    }
    install(() => jsonResponse(health))
    const result = await getAdminHealth(TOKEN)
    expectCall("/api/v1/admin/governance/health")
    expect(result).toEqual(health)
  })
})

describe("smtp settings", () => {
  const smtp = {
    host: "smtp.app.local",
    port: 587,
    username: "noreply",
    security: "starttls" as const,
    from_email: "noreply@app.local",
    from_name: "NexaFlow",
    enabled: true,
    timeout_seconds: 10,
    has_password: true,
    password_hint: null,
    configured: true,
    site_url: "https://app.local",
    identity_configured: true,
    updated_at: "2026-08-19T00:00:00Z",
  }

  test("getSmtpSettings returns the configuration", async () => {
    install(() => jsonResponse(smtp))
    const result = await getSmtpSettings(TOKEN)
    expectCall("/api/v1/admin/smtp")
    expect(result).toEqual(smtp)
  })

  test("updateSmtpSettings patches the configuration", async () => {
    const payload = { host: "smtp2.app.local", enabled: false }
    install(() => jsonResponse(smtp))
    await updateSmtpSettings(TOKEN, payload)
    expectCall("/api/v1/admin/smtp", "PATCH", payload)
  })

  test("sendSmtpTest posts the recipient", async () => {
    install(() => jsonResponse({ success: true }))
    await sendSmtpTest(TOKEN, "ops@app.local")
    expectCall("/api/v1/admin/smtp/test", "POST", {
      to_email: "ops@app.local",
    })
  })
})

describe("workspace governance and invitations", () => {
  const governance = {
    workspace_id: "ws-1",
    daily_run_limit: 10,
    monthly_token_limit: null,
    alert_threshold_percent: 80,
    retention_days: 30,
    timezone: "Asia/Shanghai",
    updated_at: "2026-08-19T00:00:00Z",
  }
  const invitation = {
    id: "inv-1",
    workspace_id: "ws-1",
    kind: "generic" as const,
    username: null,
    email: null,
    name: null,
    role: "member",
    expires_at: "2026-09-19T00:00:00Z",
    accepted_at: null,
    created_at: "2026-08-19T00:00:00Z",
  }

  test("getWorkspaceInventory returns inventory", async () => {
    const inventory = {
      workspace_id: "ws-1",
      members_total: 2,
      members_active: 1,
      teams_total: 1,
      teams_active: 1,
      agents_total: 0,
      knowledge_bases_total: 0,
      models_total: 0,
      tools_total: 0,
      workflows_total: 0,
      active_runs: 0,
      failed_runs_24h: 0,
      failed_tasks_24h: 0,
      updated_at: "2026-08-19T00:00:00Z",
    }
    install(() => jsonResponse(inventory))
    const result = await getWorkspaceInventory(TOKEN, "ws-1")
    expectCall("/api/v1/workspaces/ws-1/inventory")
    expect(result).toEqual(inventory)
  })

  test("getWorkspaceGovernance returns governance settings", async () => {
    install(() => jsonResponse(governance))
    const result = await getWorkspaceGovernance(TOKEN, "ws-1")
    expectCall("/api/v1/workspaces/ws-1/governance")
    expect(result).toEqual(governance)
  })

  test("updateWorkspaceGovernance patches the settings", async () => {
    const payload = {
      daily_run_limit: null,
      monthly_token_limit: 5000,
      alert_threshold_percent: 90,
      retention_days: null,
      timezone: "UTC",
    }
    install(() => jsonResponse(governance))
    await updateWorkspaceGovernance(TOKEN, "ws-1", payload)
    expectCall("/api/v1/workspaces/ws-1/governance", "PATCH", payload)
  })

  test("listWorkspaceInvitations returns invitations", async () => {
    install(() => jsonResponse([invitation]))
    const result = await listWorkspaceInvitations(TOKEN, "ws-1")
    expectCall("/api/v1/workspaces/ws-1/invitations")
    expect(result).toEqual([invitation])
  })

  test("createWorkspaceInvitation posts a personal invitation", async () => {
    const payload: {
      kind: "personal"
      username: string
      email: string
      name: string
      role: string
    } = {
      kind: "personal",
      username: "dave",
      email: "d@app.local",
      name: "Dave",
      role: "admin",
    }
    install(() => jsonResponse(invitation))
    await createWorkspaceInvitation(TOKEN, "ws-1", payload)
    expectCall("/api/v1/workspaces/ws-1/invitations", "POST", payload)
  })

  test("createWorkspaceInvitation posts a generic invitation", async () => {
    const payload: { kind: "generic"; role: string } = {
      kind: "generic",
      role: "member",
    }
    install(() => jsonResponse(invitation))
    await createWorkspaceInvitation(TOKEN, "ws-1", payload)
    expectCall("/api/v1/workspaces/ws-1/invitations", "POST", payload)
  })

  test("revokeWorkspaceInvitation issues a DELETE", async () => {
    install(() => noContent())
    await revokeWorkspaceInvitation(TOKEN, "ws-1", "inv-1")
    expectCall("/api/v1/workspaces/ws-1/invitations/inv-1", "DELETE")
  })

  test("deleteWorkspaceInvitation issues a DELETE", async () => {
    install(() => noContent())
    await deleteWorkspaceInvitation(TOKEN, "ws-1", "inv-1")
    expectCall("/api/v1/workspaces/ws-1/invitations/inv-1/permanent", "DELETE")
  })
})

describe("sessions", () => {
  const session = {
    id: "sess-1",
    created_at: "2026-08-19T00:00:00Z",
    last_used_at: "2026-08-19T00:00:00Z",
    expires_at: "2026-09-19T00:00:00Z",
    user_agent: "bun-test",
    ip_address: "127.0.0.1",
    is_current: true,
  }

  test("listSessions returns the current sessions", async () => {
    install(() => jsonResponse([session]))
    const result = await listSessions(TOKEN)
    expectCall("/api/v1/auth/sessions")
    expect(result).toEqual([session])
  })

  test("revokeSession issues a DELETE", async () => {
    install(() => noContent())
    await revokeSession(TOKEN, "sess-1")
    expectCall("/api/v1/auth/sessions/sess-1", "DELETE")
  })

  test("revokeOtherSessions posts without a body", async () => {
    install(() => noContent())
    await revokeOtherSessions(TOKEN)
    expectCall("/api/v1/auth/sessions/revoke-others", "POST")
    expect(last().body).toBeNull()
  })

  test("listUserSessions returns a user's sessions", async () => {
    install(() => jsonResponse([session]))
    const result = await listUserSessions(TOKEN, "u-1")
    expectCall("/api/v1/admin/users/u-1/sessions")
    expect(result).toEqual([session])
  })

  test("revokeUserSession issues a DELETE", async () => {
    install(() => noContent())
    await revokeUserSession(TOKEN, "u-1", "sess-1")
    expectCall("/api/v1/admin/users/u-1/sessions/sess-1", "DELETE")
  })

  test("revokeAllUserSessions issues a DELETE", async () => {
    install(() => noContent())
    await revokeAllUserSessions(TOKEN, "u-1")
    expectCall("/api/v1/admin/users/u-1/sessions", "DELETE")
  })
})

describe("error handling", () => {
  test("throws ApiError with the detail message on non-2xx", async () => {
    install(() => jsonResponse({ detail: "Forbidden" }, 403))
    try {
      await listTeams(TOKEN, "ws-1")
      throw new Error("expected the request to fail")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(403)
      expect((error as ApiError).message).toBe("Forbidden")
    }
  })

  test("throws ApiError with a plain-text body as the message", async () => {
    install(() => new Response("upstream unavailable", { status: 502 }))
    try {
      await listUsers(TOKEN)
      throw new Error("expected the request to fail")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(502)
      expect((error as ApiError).message).toBe("upstream unavailable")
    }
  })
})

/* @jsxImportSource react */
import { act } from "react"
import { afterEach, expect, test } from "bun:test"

import { ResourcePermissionsPage } from "@/components/system/resource-permissions-page"
import { LanguageProvider } from "@/contexts/language-provider"
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
  withFetch,
} from "./helpers/dom"

const workspaceOne = {
  id: "ws-1",
  name: "Workspace One",
  description: "",
  status: "active",
  is_default: false,
}
const workspaceTwo = { ...workspaceOne, id: "ws-2", name: "Workspace Two" }
const session = makeSession({ workspaces: [workspaceOne, workspaceTwo] })

mockUseSession(session)
mockNextNavigation()

afterEach(() => {
  cleanup()
  resetFetch()
})

test("resource permissions ignore a stale workspace resource response", async () => {
  let resolveOldKnowledge: ((response: Response) => void) | null = null
  const permissionRequests: string[] = []
  const member = { user: session.me.user, role: "admin" }

  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return new Promise<Response>((resolve) => {
        resolveOldKnowledge = resolve
      })
    }
    if (parsed.pathname === "/api/v1/workspaces/ws-2/knowledge-bases") {
      return jsonResponse([
        {
          id: "kb-new",
          workspace_id: "ws-2",
          name: "New Knowledge",
          description: "",
          status: "active",
          embedding_model_id: null,
          reranker_model_id: null,
          created_by_user_id: "owner-2",
          created_at: "2026-08-27T00:00:00Z",
          updated_at: "2026-08-27T00:00:00Z",
          permission: "edit",
          document_count: 0,
          char_count: 0,
        },
      ])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (parsed.pathname.endsWith("/permissions")) {
      permissionRequests.push(parsed.pathname)
      return jsonResponse([])
    }
    throw new Error(`Unexpected request: ${url}`)
  })

  const view = renderPage(<ResourcePermissionsPage type="knowledge" />)
  await waitFor(() => expect(resolveOldKnowledge).not.toBeNull())

  session.selectedWorkspaceId = "ws-2"
  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      <ResourcePermissionsPage type="knowledge" />
    </LanguageProvider>
  )
  expect(await screen.findByText("New Knowledge")).toBeTruthy()
  await waitFor(() =>
    expect(permissionRequests).toContain(
      "/api/v1/workspaces/ws-2/knowledge-bases/kb-new/permissions"
    )
  )

  await act(async () => {
    resolveOldKnowledge!(
      jsonResponse([
        {
          id: "kb-old",
          workspace_id: "ws-1",
          name: "Old Knowledge",
          description: "",
          status: "active",
          embedding_model_id: null,
          reranker_model_id: null,
          created_by_user_id: "owner-1",
          created_at: "2026-08-26T00:00:00Z",
          updated_at: "2026-08-26T00:00:00Z",
          permission: "edit",
          document_count: 0,
          char_count: 0,
        },
      ])
    )
  })

  expect(screen.queryByText("Old Knowledge")).toBeNull()
  expect(permissionRequests).not.toContain(
    "/api/v1/workspaces/ws-2/knowledge-bases/kb-old/permissions"
  )
})

test("drops a deleted resource instead of failing the whole table", async () => {
  session.selectedWorkspaceId = "ws-1"
  const notifications: Array<{ kind: string; message: string }> = []
  session.notify = ((kind: string, message: string) => {
    notifications.push({ kind, message })
  }) as typeof session.notify
  const member = { user: session.me.user, role: "member" }

  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return jsonResponse([
        {
          id: "kb-live",
          workspace_id: "ws-1",
          name: "Live Knowledge",
          description: "",
          status: "active",
          embedding_model_id: null,
          reranker_model_id: null,
          created_by_user_id: "owner-1",
          created_at: "2026-08-27T00:00:00Z",
          updated_at: "2026-08-27T00:00:00Z",
          permission: "edit",
          document_count: 0,
          char_count: 0,
        },
        {
          id: "kb-gone",
          workspace_id: "ws-1",
          name: "Gone Knowledge",
          description: "",
          status: "active",
          embedding_model_id: null,
          reranker_model_id: null,
          created_by_user_id: "owner-1",
          created_at: "2026-08-26T00:00:00Z",
          updated_at: "2026-08-26T00:00:00Z",
          permission: "edit",
          document_count: 0,
          char_count: 0,
        },
      ])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (
      parsed.pathname ===
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-gone/permissions"
    ) {
      return new Response(
        JSON.stringify({ detail: "Knowledge base not found." }),
        {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }
      )
    }
    if (parsed.pathname.endsWith("/permissions")) return jsonResponse([])
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="knowledge" />)
  expect(await screen.findByText("Live Knowledge")).toBeTruthy()
  await waitFor(() => expect(screen.queryByText("Gone Knowledge")).toBeNull())

  expect(notifications).toEqual([
    {
      kind: "info",
      message: "部分资源已不存在，已从列表移除",
    },
  ])
  expect(screen.getByText("Live Knowledge")).toBeTruthy()
})

test("never requests permissions for the previous tab's resources during a type switch", async () => {
  session.selectedWorkspaceId = "ws-1"
  let resolveKnowledgeList: ((response: Response) => void) | null = null
  const permissionRequests: string[] = []
  const member = { user: session.me.user, role: "member" }

  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/agents") {
      return jsonResponse([
        {
          id: "agent-1",
          name: "Agent One",
          description: "",
          status: "active",
          created_by_user_id: "owner-1",
        },
      ])
    }
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return new Promise<Response>((resolve) => {
        resolveKnowledgeList = resolve
      })
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (parsed.pathname.includes("/permissions")) {
      permissionRequests.push(parsed.pathname)
      return jsonResponse([])
    }
    throw new Error(`Unexpected request: ${url}`)
  })

  const view = renderPage(<ResourcePermissionsPage type="apps" />)
  expect(await screen.findByText("Agent One")).toBeTruthy()
  await waitFor(() =>
    expect(permissionRequests).toContain(
      "/api/v1/workspaces/ws-1/agents/agent-1/permissions"
    )
  )

  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      <ResourcePermissionsPage type="knowledge" />
    </LanguageProvider>
  )
  await new Promise((resolve) => setTimeout(resolve, 50))
  expect(
    permissionRequests.filter((path) =>
      path.includes("/knowledge-bases/agent-1/permissions")
    )
  ).toHaveLength(0)

  await act(async () => {
    resolveKnowledgeList!(
      jsonResponse([
        {
          id: "kb-1",
          workspace_id: "ws-1",
          name: "Knowledge One",
          description: "",
          status: "active",
          embedding_model_id: null,
          reranker_model_id: null,
          created_by_user_id: "owner-1",
          created_at: "2026-08-27T00:00:00Z",
          updated_at: "2026-08-27T00:00:00Z",
          permission: "edit",
          document_count: 0,
          char_count: 0,
        },
      ])
    )
  })

  expect(await screen.findByText("Knowledge One")).toBeTruthy()
  await waitFor(() =>
    expect(permissionRequests).toContain(
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/permissions"
    )
  )
})

test("apps tab grants and revokes agent permissions", async () => {
  session.selectedWorkspaceId = "ws-1"
  const calls: string[] = []
  const member = { user: session.me.user, role: "member" }

  withFetch((url, init) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/agents") {
      return jsonResponse([
        {
          id: "agent-1",
          name: "Agent One",
          description: "An agent",
          status: "active",
          created_by_user_id: "owner-1",
        },
      ])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (parsed.pathname.endsWith(`/permissions/${member.user.id}`)) {
      calls.push(`${init?.method ?? "GET"} ${parsed.pathname}`)
      if (init?.method === "DELETE") {
        return new Response(null, { status: 204 })
      }
      return jsonResponse({ user: member.user, permission: "view" })
    }
    if (parsed.pathname.endsWith("/permissions")) {
      calls.push(`${init?.method ?? "GET"} ${parsed.pathname}`)
      return jsonResponse([])
    }
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="apps" />)
  const row = (await screen.findByText("Agent One")).closest("div.grid")! as HTMLElement
  const radios = within(row).getAllByRole("radio")
  expect(radios).toHaveLength(3)
  // Apps never expose a manage level.
  expect((radios[2] as HTMLInputElement).disabled).toBe(true)

  fireEvent.click(radios[1])
  await waitFor(() =>
    expect(calls).toContain(
      "PUT /api/v1/workspaces/ws-1/agents/agent-1/permissions/u-1"
    )
  )
  await waitFor(() =>
    expect((within(row).getAllByRole("radio")[1] as HTMLInputElement).checked).toBe(
      true
    )
  )

  fireEvent.click(within(row).getAllByRole("radio")[0])
  await waitFor(() =>
    expect(calls).toContain(
      "DELETE /api/v1/workspaces/ws-1/agents/agent-1/permissions/u-1"
    )
  )
})

test("tools tab maps tool rows and updates use-level permissions", async () => {
  session.selectedWorkspaceId = "ws-1"
  const calls: string[] = []
  const member = { user: session.me.user, role: "member" }

  withFetch((url, init) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/tools") {
      return jsonResponse([
        {
          id: "tool-1",
          display_name: "Tool One",
          description: "A tool",
          status: "active",
          created_by_user_id: "owner-1",
        },
      ])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (parsed.pathname.endsWith(`/permissions/${member.user.id}`)) {
      calls.push(`${init?.method ?? "GET"} ${parsed.pathname}`)
      if (init?.method === "DELETE") {
        return new Response(null, { status: 204 })
      }
      return jsonResponse({ user: member.user, permission: "view" })
    }
    if (parsed.pathname.endsWith("/permissions")) {
      calls.push(`${init?.method ?? "GET"} ${parsed.pathname}`)
      return jsonResponse([])
    }
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="tools" />)
  const row = (await screen.findByText("Tool One")).closest("div.grid")! as HTMLElement
  fireEvent.click(within(row).getAllByRole("radio")[2])
  await waitFor(() =>
    expect(calls).toContain(
      "PUT /api/v1/workspaces/ws-1/tools/tool-1/permissions/u-1"
    )
  )
})

test("knowledge tab sends edit for the manage level and drops 404 rows on update", async () => {
  session.selectedWorkspaceId = "ws-1"
  const requests: string[] = []
  const notifications: Array<{ kind: string; message: string }> = []
  session.notify = ((kind: string, message: string) => {
    notifications.push({ kind, message })
  }) as typeof session.notify
  const member = { user: session.me.user, role: "member" }
  const kb = {
    id: "kb-1",
    workspace_id: "ws-1",
    name: "Knowledge One",
    description: "",
    status: "active",
    embedding_model_id: null,
    reranker_model_id: null,
    created_by_user_id: "owner-1",
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
    permission: "edit",
    document_count: 0,
    char_count: 0,
  }

  withFetch((url, init) => {
    const parsed = new URL(url, "http://localhost")
    requests.push(`${init?.method ?? "GET"} ${parsed.pathname}`)
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return jsonResponse([kb])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (parsed.pathname.endsWith(`/permissions/${member.user.id}`)) {
      if (init?.method === "PUT") {
        return new Response(
          JSON.stringify({ detail: "Knowledge base not found." }),
          { status: 404, headers: { "Content-Type": "application/json" } }
        )
      }
      return jsonResponse({ user: member.user, permission: "edit" })
    }
    if (parsed.pathname.endsWith("/permissions")) return jsonResponse([])
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="knowledge" />)
  const row = (await screen.findByText("Knowledge One")).closest("div.grid")! as HTMLElement
  fireEvent.click(within(row).getAllByRole("radio")[2])
  await waitFor(() =>
    expect(requests).toContain(
      "PUT /api/v1/workspaces/ws-1/knowledge-bases/kb-1/permissions/u-1"
    )
  )
  await waitFor(() => expect(screen.queryByText("Knowledge One")).toBeNull())
  expect(notifications).toEqual([
    { kind: "info", message: "资源已不存在，已从列表移除" },
  ])
})

test("update failures and list failures surface error notifications", async () => {
  session.selectedWorkspaceId = "ws-1"
  const notifications: Array<{ kind: string; message: string }> = []
  session.notify = ((kind: string, message: string) => {
    notifications.push({ kind, message })
  }) as typeof session.notify
  const member = { user: session.me.user, role: "member" }

  withFetch((url, init) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return jsonResponse([
        {
          id: "kb-1",
          workspace_id: "ws-1",
          name: "Knowledge One",
          description: "",
          status: "active",
          embedding_model_id: null,
          reranker_model_id: null,
          created_by_user_id: "owner-1",
          created_at: "2026-08-27T00:00:00Z",
          updated_at: "2026-08-27T00:00:00Z",
          permission: "edit",
          document_count: 0,
          char_count: 0,
        },
      ])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (parsed.pathname.endsWith(`/permissions/${member.user.id}`)) {
      if (init?.method === "PUT") {
        return new Response(JSON.stringify({ detail: "boom" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        })
      }
      return jsonResponse({ user: member.user, permission: "edit" })
    }
    if (parsed.pathname.endsWith("/permissions")) return jsonResponse([])
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="knowledge" />)
  const row = (await screen.findByText("Knowledge One")).closest("div.grid")! as HTMLElement
  fireEvent.click(within(row).getAllByRole("radio")[2])
  await waitFor(() =>
    expect(notifications.some((item) => item.kind === "error")).toBe(true)
  )
})

test("owner rows are locked and empty member lists render a hint", async () => {
  session.selectedWorkspaceId = "ws-1"
  const owner = { user: session.me.user, role: "member" }

  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return jsonResponse([
        {
          id: "kb-1",
          workspace_id: "ws-1",
          name: "Owned Knowledge",
          description: "",
          status: "active",
          embedding_model_id: null,
          reranker_model_id: null,
          created_by_user_id: "u-1",
          created_at: "2026-08-27T00:00:00Z",
          updated_at: "2026-08-27T00:00:00Z",
          permission: "edit",
          document_count: 0,
          char_count: 0,
        },
      ])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([owner])
    if (parsed.pathname.endsWith("/permissions")) return jsonResponse([])
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="knowledge" />)
  const row = (await screen.findByText("Owned Knowledge")).closest("div.grid")! as HTMLElement
  const radios = within(row).getAllByRole("radio")
  for (const radio of radios) {
    expect((radio as HTMLInputElement).disabled).toBe(true)
  }
  // The locked row renders the manage check marker instead of radio actions.
  expect(row.querySelector("svg")).toBeTruthy()
})

test("empty member lists render a hint", async () => {
  session.selectedWorkspaceId = "ws-1"
  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return jsonResponse([])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([])
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="knowledge" />)
  expect(await screen.findByText("暂无成员")).toBeTruthy()
})

test("list failures render an error card", async () => {
  session.selectedWorkspaceId = "ws-1"
  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/knowledge-bases") {
      return new Response(JSON.stringify({ detail: "kaboom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      })
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([])
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<ResourcePermissionsPage type="knowledge" />)
  expect(await screen.findByText("kaboom")).toBeTruthy()
})

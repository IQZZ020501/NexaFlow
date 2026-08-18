/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { ToolPermissionsDialog } from "@/components/tools/tool-permissions-dialog"
import type { ToolSummary } from "@/lib/api/tools"
import {
  fireEvent,
  jsonResponse,
  renderPage,
  screen,
  waitFor,
} from "./helpers/dom"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

const alice = {
  id: "user-2",
  username: "alice",
  email: "alice@example.com",
  name: "Alice",
  is_global_admin: false,
  must_change_password: false,
  is_active: true,
  created_at: "2026-08-17T00:00:00Z",
  workspaces: [],
  teams: [],
}

const bob = {
  ...alice,
  id: "user-3",
  username: "bob",
  email: "bob@example.com",
  name: "Bob",
}

const tool: ToolSummary = {
  id: "tool-1",
  workspace_id: "ws-1",
  kind: "python",
  function_name: "formatter",
  display_name: "Formatter",
  description: "Formats text",
  current_version_id: "version-1",
  status: "active",
  availability: "available",
  source: { id: "source-1", name: "Python", kind: "python", transport: null },
  created_by_user_id: "owner-1",
  permission: "owner",
  can_view: true,
  can_use: true,
  can_manage: true,
}

describe("ToolPermissionsDialog", () => {
  test("changes view grants to use and can revoke them", async () => {
    const requests: Array<{ method: string; url: string; body?: unknown }> = []
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      requests.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (url.includes("/members")) {
        return jsonResponse([
          { user: alice, role: "member" },
          { user: bob, role: "member" },
          { user: { ...alice, id: "owner-1", name: "Owner" }, role: "admin" },
        ])
      }
      if (method === "GET") {
        return jsonResponse([{ user: alice, permission: "view" }])
      }
      if (method === "PUT") {
        return jsonResponse({ user: alice, permission: "use" })
      }
      return new Response(null, { status: 204 })
    }) as typeof fetch

    renderPage(
      <ToolPermissionsDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={tool}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByText("Alice")
    expect(
      screen.getByText(
        "查看权限只能查看脱敏详情；使用权限还可将工具绑定到自己的 Agent 或 Workflow。"
      )
    ).toBeTruthy()
    expect(screen.queryByText("Owner")).toBeNull()

    const search = screen.getByRole("searchbox")
    fireEvent.change(search, { target: { value: "bob@example.com" } })
    expect(screen.getByText("Bob")).toBeTruthy()
    expect(screen.queryByText("Alice")).toBeNull()
    fireEvent.change(search, { target: { value: "missing" } })
    expect(screen.getByText("没有匹配的成员")).toBeTruthy()
    fireEvent.change(search, { target: { value: "" } })

    const permission = screen.getByLabelText("Alice 的工具权限")
    fireEvent.pointerDown(permission)
    fireEvent.click(permission)
    fireEvent.click(await screen.findByRole("menuitem", { name: "使用" }))
    await waitFor(() => {
      expect(
        requests.some(
          (request) =>
            request.method === "PUT" &&
            request.url.endsWith("/tools/tool-1/permissions/user-2") &&
            JSON.stringify(request.body) ===
              JSON.stringify({ permission: "use" })
        )
      ).toBe(true)
    })

    fireEvent.pointerDown(permission)
    fireEvent.click(permission)
    fireEvent.click(await screen.findByRole("menuitem", { name: "无权限" }))
    await waitFor(() => {
      expect(
        requests.some(
          (request) =>
            request.method === "DELETE" &&
            request.url.endsWith("/tools/tool-1/permissions/user-2")
        )
      ).toBe(true)
    })
    expect(messages).toEqual(["工具授权已更新", "工具授权已更新"])
  })
})

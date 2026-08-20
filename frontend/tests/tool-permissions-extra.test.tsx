/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { useState } from "react"

import { ToolPermissionsDialog } from "@/components/tools/tool-permissions-dialog"
import type { ToolSummary } from "@/lib/api/tools"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  renderPage,
  screen,
  waitFor,
} from "./helpers/dom"

const originalFetch = globalThis.fetch

afterEach(() => {
  cleanup()
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

const inactive = {
  ...alice,
  id: "user-4",
  username: "left",
  email: "left@example.com",
  name: "Former Member",
  is_active: false,
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

function installFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>
) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    return handler(url, init)
  }) as typeof fetch
}

function dialog(
  open: boolean,
  onOpenChange: (open: boolean) => void,
  messages: string[] = []
) {
  return (
    <ToolPermissionsDialog
      open={open}
      onOpenChange={onOpenChange}
      token="token"
      workspaceId="ws-1"
      tool={tool}
      onMessage={(_kind, message) => messages.push(message)}
    />
  )
}

describe("ToolPermissionsDialog extra", () => {
  test("shows a retryable load error and recovers", async () => {
    let fails = true
    installFetch((url) => {
      if (fails) return jsonResponse({ detail: "permissions offline" }, 503)
      if (url.includes("/members")) {
        return jsonResponse([
          { user: alice, role: "member" },
          { user: bob, role: "member" },
        ])
      }
      return jsonResponse([])
    })

    renderPage(dialog(true, () => undefined))
    expect(await screen.findByText("工具加载失败")).toBeTruthy()
    expect(screen.getByText("permissions offline")).toBeTruthy()

    fails = false
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    expect(await screen.findByText("Alice")).toBeTruthy()
    expect(screen.queryByText("工具加载失败")).toBeNull()
  })

  test("reports an error when a permission update fails", async () => {
    const messages: string[] = []
    installFetch((url, init) => {
      if (url.includes("/members")) {
        return jsonResponse([{ user: alice, role: "member" }])
      }
      if (init?.method === "PUT") {
        return jsonResponse({ detail: "no permission" }, 403)
      }
      return jsonResponse([])
    })

    renderPage(dialog(true, () => undefined, messages))
    await screen.findByText("Alice")
    const permission = screen.getByLabelText("Alice 的工具权限")
    fireEvent.pointerDown(permission)
    fireEvent.click(permission)
    fireEvent.click(await screen.findByRole("menuitem", { name: "使用" }))

    await waitFor(() => expect(messages).toEqual(["资源不存在或无权访问"]))
  })

  test("closes through the done button and clears the search on close", async () => {
    const changes: boolean[] = []
    function Harness() {
      const [open, setOpen] = useState(true)
      return (
        <ToolPermissionsDialog
          open={open}
          onOpenChange={(next) => {
            changes.push(next)
            setOpen(next)
          }}
          token="token"
          workspaceId="ws-1"
          tool={tool}
          onMessage={() => undefined}
        />
      )
    }
    installFetch((url) => {
      if (url.includes("/members")) {
        return jsonResponse([{ user: alice, role: "member" }])
      }
      return jsonResponse([])
    })

    renderPage(<Harness />)
    await screen.findByText("Alice")
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "alice" },
    })
    fireEvent.click(screen.getByRole("button", { name: "完成" }))
    await waitFor(() => expect(changes).toEqual([false]))
    expect(screen.queryByRole("searchbox")).toBeNull()
  })

  test("clears the search when the dialog is dismissed with Escape", async () => {
    const changes: boolean[] = []
    function Harness() {
      const [open, setOpen] = useState(true)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open permissions
          </button>
          <ToolPermissionsDialog
            open={open}
            onOpenChange={(next) => {
              changes.push(next)
              setOpen(next)
            }}
            token="token"
            workspaceId="ws-1"
            tool={tool}
            onMessage={() => undefined}
          />
        </>
      )
    }
    installFetch((url) => {
      if (url.includes("/members")) {
        return jsonResponse([{ user: alice, role: "member" }])
      }
      return jsonResponse([])
    })

    renderPage(<Harness />)
    await screen.findByText("Alice")
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "alice" },
    })
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(changes).toEqual([false]))

    fireEvent.click(screen.getByRole("button", { name: "Open permissions" }))
    await screen.findByText("Alice")
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("")
  })

  test("shows no authorizable members when only the creator and inactive users exist", async () => {
    installFetch((url) => {
      if (url.includes("/members")) {
        return jsonResponse([
          { user: { ...alice, id: "owner-1", name: "Owner" }, role: "admin" },
          { user: inactive, role: "member" },
        ])
      }
      return jsonResponse([])
    })

    renderPage(dialog(true, () => undefined))
    expect(await screen.findByText("没有可授权的成员")).toBeTruthy()
    expect(screen.queryByRole("searchbox")).toBeNull()
  })

  test("labels admin members and ignores the tool creator", async () => {
    installFetch((url) => {
      if (url.includes("/members")) {
        return jsonResponse([
          { user: alice, role: "admin" },
          { user: { ...alice, id: "owner-1", name: "Owner" }, role: "admin" },
        ])
      }
      return jsonResponse([])
    })

    renderPage(dialog(true, () => undefined))
    await screen.findByText("Alice")
    expect(screen.getByText("管理员")).toBeTruthy()
    expect(screen.queryByText("Owner")).toBeNull()

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "nobody" },
    })
    expect(screen.getByText("没有匹配的成员")).toBeTruthy()
  })

  test("revokes a permission through the none option", async () => {
    const messages: string[] = []
    const requests: Array<{ method: string; url: string }> = []
    installFetch((url, init) => {
      const method = init?.method ?? "GET"
      requests.push({ method, url })
      if (url.includes("/members")) {
        return jsonResponse([{ user: alice, role: "member" }])
      }
      if (method === "GET") {
        return jsonResponse([{ user: alice, permission: "view" }])
      }
      return jsonResponse(null, 204)
    })

    renderPage(dialog(true, () => undefined, messages))
    await screen.findByText("Alice")
    const permission = screen.getByLabelText("Alice 的工具权限")
    fireEvent.pointerDown(permission)
    fireEvent.click(permission)
    fireEvent.click(await screen.findByRole("menuitem", { name: "无权限" }))

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.method === "DELETE" &&
            request.url.endsWith("/tools/tool-1/permissions/user-2")
        )
      ).toBe(true)
    )
    expect(messages).toEqual(["工具授权已更新"])
  })

  test("keeps the dialog open while a permission update is pending", async () => {
    const requests: Array<{ method: string; url: string }> = []
    const changes: boolean[] = []
    const pending = { release: null as (() => void) | null }
    installFetch((url, init) => {
      const method = init?.method ?? "GET"
      requests.push({ method, url })
      if (url.includes("/members")) {
        return jsonResponse([
          { user: alice, role: "member" },
          { user: bob, role: "member" },
        ])
      }
      if (method === "PUT" && url.endsWith("/user-2")) {
        return new Promise<Response>((resolve) => {
          pending.release = () =>
            resolve(jsonResponse({ user: alice, permission: "use" }))
        })
      }
      if (method === "PUT") {
        return jsonResponse({ user: bob, permission: "view" })
      }
      if (method === "GET") {
        return jsonResponse([{ user: alice, permission: "view" }])
      }
      return jsonResponse(null, 204)
    })

    function Harness() {
      const [open, setOpen] = useState(true)
      return (
        <ToolPermissionsDialog
          open={open}
          onOpenChange={(next) => {
            changes.push(next)
            setOpen(next)
          }}
          token="token"
          workspaceId="ws-1"
          tool={tool}
          onMessage={() => undefined}
        />
      )
    }
    renderPage(<Harness />)
    await screen.findByText("Alice")

    const aliceSelect = screen.getByLabelText("Alice 的工具权限")
    fireEvent.pointerDown(aliceSelect)
    fireEvent.click(aliceSelect)
    fireEvent.click(await screen.findByRole("menuitem", { name: "使用" }))

    const bobSelect = screen.getByLabelText("Bob 的工具权限")
    fireEvent.pointerDown(bobSelect)
    fireEvent.click(bobSelect)
    fireEvent.click(await screen.findByRole("menuitem", { name: "查看" }))

    await waitFor(() =>
      expect(
        requests.filter(
          (request) =>
            request.method === "PUT" && request.url.endsWith("/user-3")
        )
      ).toHaveLength(0)
    )
    expect(changes).toEqual([])

    // Escape is ignored while an update is pending.
    fireEvent.keyDown(document, { key: "Escape" })
    expect(changes).toEqual([])

    pending.release?.()
    await waitFor(() =>
      expect(
        requests.filter(
          (request) =>
            request.method === "PUT" && request.url.endsWith("/user-2")
        )
      ).toHaveLength(1)
    )
  })
})

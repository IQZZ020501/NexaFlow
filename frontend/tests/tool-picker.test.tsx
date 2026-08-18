/* @jsxImportSource react */
import { beforeEach, describe, expect, test } from "bun:test"
import { useState } from "react"

import { ToolPicker } from "@/components/tools/tool-picker"
import type { ToolRef, ToolSummary } from "@/lib/api/tools"
import {
  fireEvent,
  jsonResponse,
  renderPage,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

const tools: ToolSummary[] = [
  {
    id: "tool-use",
    workspace_id: "ws-1",
    kind: "python",
    function_name: "lookup",
    display_name: "Lookup account",
    description: "Find an account by email",
    current_version_id: "version-2",
    status: "active",
    availability: "available",
    source: {
      id: "source-1",
      name: "Finance",
      kind: "python",
      transport: null,
    },
    created_by_user_id: "u-1",
    permission: "use",
    can_view: true,
    can_use: true,
    can_manage: false,
  },
  {
    id: "tool-view",
    workspace_id: "ws-1",
    kind: "mcp",
    function_name: "private_report",
    display_name: "Private report",
    description: "View only",
    current_version_id: "version-1",
    status: "active",
    availability: "available",
    source: { id: "source-2", name: "Reports", kind: "mcp", transport: "sse" },
    created_by_user_id: "u-2",
    permission: "view",
    can_view: true,
    can_use: false,
    can_manage: false,
  },
]

let response: () => Promise<Response>

beforeEach(() => {
  response = async () => jsonResponse(tools)
  globalThis.fetch = (() => response()) as unknown as typeof fetch
})

function picker(
  value: ToolRef[] = [],
  onChange: (value: ToolRef[]) => void = () => undefined
) {
  return (
    <ToolPicker
      open
      onOpenChange={() => undefined}
      token="token"
      workspaceId="ws-1"
      value={value}
      onChange={onChange}
    />
  )
}

describe("ToolPicker", () => {
  test("loads searchable usable tools and excludes view-only tools", async () => {
    renderPage(picker())
    expect(screen.getByText("正在加载工具")).toBeTruthy()
    await screen.findByText("Lookup account")
    expect(screen.queryByText("Private report")).toBeNull()

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "finance" },
    })
    expect(screen.getByText("Lookup account")).toBeTruthy()
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "missing" },
    })
    expect(screen.getByText("没有匹配的工具")).toBeTruthy()
  })

  test("retains unavailable bindings, allows removal, and never upgrades implicitly", async () => {
    const changes: ToolRef[][] = []
    renderPage(
      picker(
        [
          { tool_id: "tool-use", version_id: "version-1" },
          { tool_id: "removed", version_id: "old-version" },
        ],
        (value) => changes.push(value)
      )
    )
    await screen.findByText("Lookup account")
    expect(screen.getByText("已固定旧版本")).toBeTruthy()
    expect(screen.getByText("工具已不可用或授权已撤销")).toBeTruthy()
    expect(changes).toEqual([])

    fireEvent.click(screen.getByRole("button", { name: "移除工具 removed" }))
    expect(changes.at(-1)).toEqual([
      { tool_id: "tool-use", version_id: "version-1" },
    ])
  })

  test("shows retry after an error and restores focusable content", async () => {
    response = async () => jsonResponse({ detail: "offline" }, 503)
    renderPage(picker())
    await screen.findByText("工具加载失败")
    response = async () => jsonResponse(tools)
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    await screen.findByText("Lookup account")
    expect((screen.getByRole("searchbox") as HTMLInputElement).disabled).toBe(
      false
    )
  })

  test("supports keyboard selection and a mobile-safe dialog width", async () => {
    const changes: ToolRef[][] = []
    renderPage(picker([], (value) => changes.push(value)))
    await screen.findByText("Lookup account")
    const dialog = screen.getByRole("dialog", { name: "选择工具" })
    expect(dialog.className).toContain("w-[calc(100%-2rem)]")
    const option = within(dialog).getByRole("checkbox", {
      name: "Lookup account",
    })
    const search = within(dialog).getByRole("searchbox")
    search.focus()
    fireEvent.keyDown(search, { key: "ArrowDown" })
    expect(document.activeElement).toBe(option)
    fireEvent.keyDown(option, { key: "Enter" })
    expect(changes.at(-1)).toEqual([
      { tool_id: "tool-use", version_id: "version-2" },
    ])
  })

  test("closes with Escape and restores focus to the trigger", async () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open tools
          </button>
          <ToolPicker
            open={open}
            onOpenChange={setOpen}
            token="token"
            workspaceId="ws-1"
            value={[]}
            onChange={() => undefined}
          />
        </>
      )
    }

    renderPage(<Harness />)
    const trigger = screen.getByRole("button", { name: "Open tools" })
    trigger.focus()
    fireEvent.click(trigger)
    await screen.findByText("Lookup account")
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("searchbox"))
    )
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(document.activeElement === trigger).toBe(true))
  })
})

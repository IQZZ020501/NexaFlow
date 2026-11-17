/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"

import { ToolPicker } from "@/components/tools/tool-picker"
import type { ToolRef, ToolSummary } from "@/lib/api/tools"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

const usable: ToolSummary = {
  id: "tool-a",
  workspace_id: "ws-1",
  kind: "mcp",
  function_name: "lookup",
  display_name: "Lookup account",
  description: "Find an account by email",
  current_version_id: "version-2",
  status: "active",
  availability: "available",
  source: { id: "source-1", name: "Finance", kind: "mcp", transport: null },
  created_by_user_id: "u-1",
  permission: "use",
  can_view: true,
  can_use: true,
  can_manage: false,
}

const secondUsable: ToolSummary = {
  ...usable,
  id: "tool-b",
  kind: "mcp",
  function_name: "report",
  display_name: "Weekly report",
  description: "Generate a report",
  current_version_id: "version-1",
  source: { id: "source-2", name: "Reports", kind: "mcp", transport: "sse" },
}

const viewOnly: ToolSummary = {
  ...usable,
  id: "tool-view",
  function_name: "private_report",
  display_name: "Private report",
  description: "View only",
  can_use: false,
  permission: "view",
}

let catalog: ToolSummary[] = [usable, secondUsable, viewOnly]

beforeEach(() => {
  catalog = [usable, secondUsable, viewOnly]
  globalThis.fetch = (async () =>
    jsonResponse(catalog)) as unknown as typeof fetch
})

afterEach(() => {
  cleanup()
  resetFetch()
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

describe("ToolPicker extra", () => {
  test("upgrades a pinned tool to its current version", async () => {
    const changes: ToolRef[][] = []
    renderPage(
      picker([{ tool_id: "tool-a", version_id: "version-1" }], (value) =>
        changes.push(value)
      )
    )
    await screen.findByText("Finance")
    expect(screen.getByText("已固定旧版本")).toBeTruthy()

    fireEvent.click(screen.getByText("升级到当前版本"))
    await waitFor(() =>
      expect(changes).toEqual([
        [{ tool_id: "tool-a", version_id: "version-2" }],
      ])
    )
  })

  test("navigates options with the keyboard and selects with Enter", async () => {
    const changes: ToolRef[][] = []
    renderPage(picker([], (value) => changes.push(value)))
    await screen.findByText("Finance")

    const dialog = screen.getByRole("dialog", { name: "选择工具" })
    const options = within(dialog).getAllByRole("checkbox")
    expect(options).toHaveLength(2)
    const [first, second] = options
    expect(first?.getAttribute("aria-label")).toBe("Finance")
    expect(second?.getAttribute("aria-label")).toBe("Reports")

    const search = within(dialog).getByRole("searchbox")
    search.focus()
    fireEvent.keyDown(search, { key: "ArrowDown" })
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(search, { key: "ArrowDown" })
    expect(document.activeElement).toBe(first)

    first.focus()
    fireEvent.keyDown(first, { key: "ArrowDown" })
    expect(document.activeElement).toBe(second)
    fireEvent.keyDown(second, { key: "ArrowUp" })
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(first, { key: "Home" })
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(first, { key: "End" })
    expect(document.activeElement).toBe(second)
    fireEvent.keyDown(second, { key: "ArrowDown" })
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(first, { key: "ArrowUp" })
    expect(document.activeElement).toBe(second)
    fireEvent.keyDown(second, { key: "x" })
    expect(document.activeElement).toBe(second)

    fireEvent.keyDown(second, { key: "Enter" })
    expect(changes.at(-1)).toEqual([
      { tool_id: "tool-b", version_id: "version-1" },
    ])
  })

  test("shows an empty message when the workspace has no usable tools", async () => {
    catalog = [viewOnly]
    renderPage(picker())
    expect(await screen.findByText("暂无可用工具")).toBeTruthy()
    expect(screen.queryByText("没有匹配的工具")).toBeNull()
  })

  test("shows a retryable load error and recovers", async () => {
    let fails = true
    globalThis.fetch = (async () => {
      if (fails) return jsonResponse({ detail: "tools offline" }, 503)
      return jsonResponse(catalog)
    }) as unknown as typeof fetch

    renderPage(picker())
    expect(await screen.findByText("工具加载失败")).toBeTruthy()
    expect(screen.getByText("tools offline")).toBeTruthy()
    expect((screen.getByRole("searchbox") as HTMLInputElement).disabled).toBe(
      true
    )

    fails = false
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    await screen.findByText("Finance")
    expect((screen.getByRole("searchbox") as HTMLInputElement).disabled).toBe(
      false
    )
  })

  test("upgrade keeps other pinned bindings untouched", async () => {
    const changes: ToolRef[][] = []
    renderPage(
      picker(
        [
          { tool_id: "tool-a", version_id: "version-1" },
          { tool_id: "tool-b", version_id: "version-1" },
        ],
        (value) => changes.push(value)
      )
    )
    await screen.findByText("Finance")
    fireEvent.click(screen.getByText("升级到当前版本"))
    await waitFor(() =>
      expect(changes).toEqual([
        [
          { tool_id: "tool-a", version_id: "version-2" },
          { tool_id: "tool-b", version_id: "version-1" },
        ],
      ])
    )
  })

  test("toggles a selected tool off with the checkbox", async () => {
    const changes: ToolRef[][] = []
    renderPage(
      picker([{ tool_id: "tool-a", version_id: "version-2" }], (value) =>
        changes.push(value)
      )
    )
    await screen.findByText("Finance")
    const checked = screen.getByRole("checkbox", { name: "Finance" })
    expect((checked as HTMLInputElement).checked).toBe(true)
    fireEvent.click(checked)
    expect(changes.at(-1)).toEqual([])
  })
  test("selects eligible tools as one service without exposing operation details", async () => {
    catalog = [
      usable,
      { ...secondUsable, source: usable.source },
      viewOnly,
      { ...usable, id: "offline", availability: "unavailable" },
      { ...usable, id: "disabled", status: "disabled" },
      { ...usable, id: "unpublished", current_version_id: null },
    ]
    const changes: ToolRef[][] = []
    renderPage(picker([], (value) => changes.push(value)))
    await screen.findByRole("checkbox", { name: "Finance" })
    expect(screen.getAllByRole("checkbox")).toHaveLength(1)
    expect(screen.queryByText("Lookup account")).toBeNull()
    expect(screen.queryByText("Weekly report")).toBeNull()
    expect(screen.queryByText("Find an account by email")).toBeNull()
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Finance" },
    })
    fireEvent.click(screen.getByRole("checkbox", { name: "Finance" }))
    expect(changes.at(-1)).toEqual([
      { tool_id: "tool-a", version_id: "version-2" },
      { tool_id: "tool-b", version_id: "version-1" },
    ])
  })

  test("preserves old versions in a partially selected service and removes the whole service", async () => {
    catalog = [usable, { ...secondUsable, source: usable.source }]
    const changes: ToolRef[][] = []
    renderPage(
      picker(
        [
          { tool_id: "tool-a", version_id: "old-version" },
          { tool_id: "unrelated", version_id: "unrelated-version" },
        ],
        (value) => changes.push(value)
      )
    )
    const service = (await screen.findByRole("checkbox", {
      name: "Finance",
    })) as HTMLInputElement
    expect(service.indeterminate).toBe(true)
    expect(changes).toEqual([])
    fireEvent.click(service)
    expect(changes.at(-1)).toEqual([
      { tool_id: "tool-a", version_id: "old-version" },
      { tool_id: "unrelated", version_id: "unrelated-version" },
      { tool_id: "tool-b", version_id: "version-1" },
    ])
    cleanup()
    renderPage(picker(changes.at(-1), (value) => changes.push(value)))
    fireEvent.click(await screen.findByRole("checkbox", { name: "Finance" }))
    expect(changes.at(-1)).toEqual([
      { tool_id: "unrelated", version_id: "unrelated-version" },
    ])
  })

  test("keeps services with the same name and different identities separate", async () => {
    catalog = [
      usable,
      { ...secondUsable, source: { ...secondUsable.source, name: "Finance" } },
    ]
    const changes: ToolRef[][] = []
    renderPage(picker([], (value) => changes.push(value)))
    const services = await screen.findAllByRole("checkbox", { name: "Finance" })
    expect(services).toHaveLength(2)
    fireEvent.click(services[1]!)
    expect(changes.at(-1)).toEqual([
      { tool_id: "tool-b", version_id: "version-1" },
    ])
  })
  test("keeps unavailable bindings in the same service entry and removes them with that service", async () => {
    catalog = [
      usable,
      { ...secondUsable, source: usable.source, can_use: false },
    ]
    const changes: ToolRef[][] = []
    renderPage(
      picker(
        [
          { tool_id: usable.id, version_id: "version-1" },
          { tool_id: secondUsable.id, version_id: "version-1" },
        ],
        (value) => changes.push(value)
      )
    )
    const service = await screen.findByRole("checkbox", { name: "Finance" })
    expect(screen.getAllByText("Finance")).toHaveLength(1)
    expect(screen.getByText("工具已不可用或授权已撤销")).toBeTruthy()
    expect(screen.queryByText("Weekly report")).toBeNull()
    expect(changes).toEqual([])
    fireEvent.click(service)
    expect(changes.at(-1)).toEqual([])
  })
})

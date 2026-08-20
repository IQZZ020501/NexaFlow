/* @jsxImportSource react */
import { beforeEach, describe, expect, test } from "bun:test"

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

const usable: ToolSummary = {
  id: "tool-a",
  workspace_id: "ws-1",
  kind: "python",
  function_name: "lookup",
  display_name: "Lookup account",
  description: "Find an account by email",
  current_version_id: "version-2",
  status: "active",
  availability: "available",
  source: { id: "source-1", name: "Finance", kind: "python", transport: null },
  created_by_user_id: "u-1",
  permission: "use",
  can_view: true,
  can_use: true,
  can_manage: false,
}

const secondUsable: ToolSummary = {
  ...usable,
  id: "tool-b",
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

function picker(
  value: ToolRef[] = [],
  onChange: (value: ToolRef[]) => void = () => undefined,
  maxItems = 12
) {
  return (
    <ToolPicker
      open
      onOpenChange={() => undefined}
      token="token"
      workspaceId="ws-1"
      value={value}
      onChange={onChange}
      maxItems={maxItems}
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
    await screen.findByText("Lookup account")
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
    await screen.findByText("Lookup account")

    const dialog = screen.getByRole("dialog", { name: "选择工具" })
    const options = within(dialog).getAllByRole("checkbox")
    expect(options).toHaveLength(2)
    const [first, second] = options

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

  test("enforces the maximum selection count", async () => {
    const changes: ToolRef[][] = []
    renderPage(
      picker(
        [{ tool_id: "tool-a", version_id: "version-2" }],
        (value) => changes.push(value),
        1
      )
    )
    await screen.findByText("Lookup account")

    const dialog = screen.getByRole("dialog", { name: "选择工具" })
    const second = within(dialog).getByRole("checkbox", {
      name: "Weekly report",
    })
    expect((second as HTMLInputElement).disabled).toBe(true)
    fireEvent.click(second)
    expect(changes).toEqual([])

    fireEvent.keyDown(second, { key: "Enter" })
    expect(changes).toEqual([])
    expect(
      screen.getByText("选择有使用权限且已发布的工具，最多 1 个。")
    ).toBeTruthy()
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
    await screen.findByText("Lookup account")
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
    await screen.findByText("Lookup account")
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
    await screen.findByText("Lookup account")
    const checked = screen.getByRole("checkbox", { name: "Lookup account" })
    expect((checked as HTMLInputElement).checked).toBe(true)
    fireEvent.click(checked)
    expect(changes.at(-1)).toEqual([])
  })
})

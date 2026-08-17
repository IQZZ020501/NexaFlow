/* @jsxImportSource react */
import { beforeEach, describe, expect, test } from "bun:test"

import { ToolsPage } from "@/components/tools/tools-page"
import type { MeResponse } from "@/lib/api/auth"
import type {
  ToolDetail,
  ToolSourceDetail,
  ToolSummary,
} from "@/lib/api/tools"
import {
  fireEvent,
  jsonResponse,
  makeSession,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

const session = makeSession()
mockUseSession(session)

const member: MeResponse = {
  user: {
    id: "u-1",
    username: "member",
    email: "member@example.com",
    name: "Member",
    is_global_admin: false,
    must_change_password: false,
    is_active: true,
    created_at: "2026-08-17T00:00:00Z",
    workspaces: [],
    teams: [],
  },
  memberships: [{ workspace_id: "ws-1", role: "member" }],
}

function tool(overrides: Partial<ToolSummary> = {}): ToolSummary {
  return {
    id: "tool-owner",
    workspace_id: "ws-1",
    kind: "python",
    function_name: "formatter",
    display_name: "Owned formatter",
    description: "Formats text",
    current_version_id: "version-1",
    status: "active",
    availability: "available",
    source: {
      id: "source-python",
      name: "Python",
      kind: "python",
      transport: null,
    },
    created_by_user_id: "u-1",
    permission: "owner",
    can_view: true,
    can_use: true,
    can_manage: true,
    ...overrides,
  }
}

function detail(summary: ToolSummary): ToolDetail {
  return {
    ...summary,
    version_id: summary.current_version_id,
    revision: 1,
    input_schema: { type: "object" },
    output_schema: { type: "object" },
    approval: "auto",
    effect: "pure",
    workflow_callable: true,
    parallel_safe: false,
    draft: null,
  }
}

function source(overrides: Partial<ToolSourceDetail> = {}): ToolSourceDetail {
  return {
    id: "source-mcp",
    workspace_id: "ws-1",
    name: "Remote tools",
    kind: "mcp",
    transport: "streamable_http",
    status: "active",
    url: "https://tools.example.com/mcp",
    stdio_command: null,
    has_bearer_token: false,
    bearer_token_hint: null,
    last_error: null,
    created_by_user_id: "u-1",
    created_at: "2026-08-17T00:00:00Z",
    updated_at: "2026-08-17T00:00:00Z",
    tool_count: 0,
    ...overrides,
  }
}

beforeEach(() => {
  Object.assign(session, {
    token: "token",
    me: member,
    selectedWorkspaceId: "ws-1",
  })
  globalThis.fetch = ((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes("/tools")) return Promise.resolve(jsonResponse([]))
    if (url.includes("/mcp-servers")) return Promise.resolve(jsonResponse([]))
    return Promise.resolve(jsonResponse([], 200))
  }) as typeof fetch
})

describe("ToolsPage", () => {
  test("renders the unified empty state and member-safe add menu", async () => {
    renderPage(<ToolsPage />)
    await screen.findByText("还没有工具")
    const trigger = screen.getByRole("button", { name: "添加工具" })
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    expect(await screen.findByText("Python 工具")).toBeTruthy()
    expect(screen.getByText("MCP Server")).toBeTruthy()
    expect(screen.getByText("Skill（后续开放）")).toBeTruthy()
  })

  test("shows an explicit retry state when the catalog fails", async () => {
    globalThis.fetch = (() =>
      Promise.resolve(
        jsonResponse({ detail: "offline" }, 503)
      )) as unknown as typeof fetch
    renderPage(<ToolsPage />)
    await screen.findByText("工具加载失败")
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy()
  })

  test("keeps a failed Tool detail open with an explicit retry", async () => {
    const remote = tool({
      id: "tool-mcp",
      kind: "mcp",
      function_name: "remote_lookup",
      display_name: "Remote lookup",
      source: {
        id: "source-mcp",
        name: "Remote",
        kind: "mcp",
        transport: "streamable_http",
      },
    })
    let detailFails = true
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tool-sources")) return jsonResponse([])
      if (url.endsWith("/tools/tool-mcp")) {
        return detailFails
          ? jsonResponse({ detail: "detail unavailable" }, 503)
          : jsonResponse(detail(remote))
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    fireEvent.click(screen.getByText("Remote lookup").closest("article")!)
    await screen.findByText("detail unavailable")

    detailFails = false
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    await screen.findByText("输入 Schema")
    expect(screen.queryByText("detail unavailable")).toBeNull()
  })

  test("keeps zero-tool MCP sources visible and manageable", async () => {
    const emptySource = source({ name: "Empty MCP" })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tool-sources?")) return jsonResponse([emptySource])
      if (url.includes("/tools?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Empty MCP")
    const emptySourceCard = screen.getByText("Empty MCP").closest("article")!
    expect(within(emptySourceCard).getByText("工具")).toBeTruthy()
    expect(within(emptySourceCard).getByText("0")).toBeTruthy()
    expect(
      screen.getByRole("button", { name: "管理来源 Empty MCP" })
    ).toBeTruthy()
  })

  test("lets an MCP owner choose safe policies without exposing disable", async () => {
    const remote = tool({
      id: "tool-mcp",
      kind: "mcp",
      function_name: "remote_lookup",
      display_name: "Remote lookup",
      source: {
        id: "source-mcp",
        name: "Remote tools",
        kind: "mcp",
        transport: "streamable_http",
      },
    })
    const remoteSource = source({ tool_count: 1 })
    const requests: Array<{ method: string; body: unknown }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.includes("/tool-sources?")) return jsonResponse([remoteSource])
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.endsWith("/tools/tool-mcp/policy")) {
        requests.push({
          method: init?.method ?? "GET",
          body: JSON.parse(String(init?.body)),
        })
        return jsonResponse({ ...detail(remote), approval: "each_call" })
      }
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    expect(
      await screen.findByRole("menuitem", { name: "只读自动执行" })
    ).toBeTruthy()
    expect(
      screen.getByRole("menuitem", { name: "每次调用前审批" })
    ).toBeTruthy()
    expect(screen.queryByRole("menuitem", { name: "禁用" })).toBeNull()

    fireEvent.click(
      screen.getByRole("menuitem", { name: "每次调用前审批" })
    )
    await waitFor(() =>
      expect(requests).toEqual([
        { method: "PUT", body: { mode: "approval_required" } },
      ])
    )
  })

  test("reserves disabling an MCP Tool for workspace admins", async () => {
    Object.assign(session, {
      me: {
        ...member,
        memberships: [{ workspace_id: "ws-1", role: "admin" }],
      },
    })
    const remote = tool({
      id: "tool-mcp",
      kind: "mcp",
      function_name: "remote_lookup",
      display_name: "Remote lookup",
      source: {
        id: "source-mcp",
        name: "Remote tools",
        kind: "mcp",
        transport: "streamable_http",
      },
    })
    const remoteSource = source({ tool_count: 1 })
    const requests: unknown[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.includes("/tool-sources?")) return jsonResponse([remoteSource])
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.endsWith("/tools/tool-mcp/policy")) {
        requests.push(JSON.parse(String(init?.body)))
        return jsonResponse({
          ...detail(remote),
          status: "disabled",
          availability: "unavailable",
          approval: "disabled",
        })
      }
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "禁用" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "禁用" }
      )
    )
    await waitFor(() =>
      expect(requests).toEqual([{ mode: "disabled" }])
    )
  })

  test("lets members add public MCP sources but disables stdio and private URLs", async () => {
    renderPage(<ToolsPage />)
    await screen.findByText("还没有工具")
    const addTrigger = screen.getByRole("button", { name: "添加工具" })
    fireEvent.pointerDown(addTrigger)
    fireEvent.click(addTrigger)
    fireEvent.click(await screen.findByText("MCP Server"))

    await screen.findByRole("heading", { name: "添加 MCP Server" })
    const stdio = screen.getByRole("radio", {
      name: /stdio/,
    }) as HTMLButtonElement
    expect(stdio.disabled).toBe(true)
    expect(
      screen.getByText("普通成员只能连接公网 HTTP 或 SSE 地址。")
    ).toBeTruthy()

    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Internal" },
    })
    fireEvent.change(screen.getByLabelText("MCP 地址"), {
      target: { value: "http://127.0.0.1:9000/mcp" },
    })
    expect(
      screen.getByText("仅空间管理员可使用 stdio 或私网地址。")
    ).toBeTruthy()
    expect(
      (
        screen.getByRole("button", {
          name: "添加 MCP Server",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)

    fireEvent.change(screen.getByLabelText("MCP 地址"), {
      target: { value: "https://tools.example.com/mcp" },
    })
    expect(
      (
        screen.getByRole("button", {
          name: "添加 MCP Server",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false)
  })

  test("shows governance actions only to managers and keeps view-only code hidden", async () => {
    const owned = tool()
    const shared = tool({
      id: "tool-view",
      function_name: "shared_formatter",
      display_name: "Shared viewer",
      created_by_user_id: "u-2",
      permission: "view",
      can_use: false,
      can_manage: false,
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tool-sources")) return jsonResponse([])
      if (url.includes("/tools?")) return jsonResponse([owned, shared])
      if (url.endsWith("/tools/tool-view")) {
        return jsonResponse(detail(shared))
      }
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    expect(
      screen.getByRole("button", { name: "管理工具 Owned formatter" })
    ).toBeTruthy()
    expect(
      screen.queryByRole("button", { name: "管理工具 Shared viewer" })
    ).toBeNull()

    const manage = screen.getByRole("button", {
      name: "管理工具 Owned formatter",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    expect(await screen.findByRole("menuitem", { name: "编辑" })).toBeTruthy()
    expect(screen.getByRole("menuitem", { name: "授权" })).toBeTruthy()
    expect(screen.getByRole("menuitem", { name: "禁用" })).toBeTruthy()
    expect(screen.getByRole("menuitem", { name: "归档" })).toBeTruthy()
    fireEvent.keyDown(document, { key: "Escape" })

    fireEvent.click(screen.getByText("Shared viewer").closest("article")!)
    await screen.findByRole("heading", { name: "Python 工具详情" })
    expect(
      screen.getByText("你拥有查看权限；草稿与代码不会显示。")
    ).toBeTruthy()
    expect(screen.queryByLabelText("Python 代码")).toBeNull()
  })

  test("keeps the 390px layout free of fixed desktop widths", async () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 390,
    })
    renderPage(<ToolsPage />)
    await waitFor(() => expect(screen.getByText("还没有工具")).toBeTruthy())
    expect(screen.getByRole("main").className).not.toContain("min-w-[")
  })
})

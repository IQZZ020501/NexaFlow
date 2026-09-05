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
    notify: () => undefined,
  })
  globalThis.fetch = ((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes("/tools")) return Promise.resolve(jsonResponse([]))
    if (url.includes("/mcp-servers")) return Promise.resolve(jsonResponse([]))
    return Promise.resolve(jsonResponse([], 200))
  }) as typeof fetch
})
describe("ToolsPage", () => {
  test("batch moves selected manageable tools into a folder", async () => {
    const requests: unknown[] = []
    const secondTool = tool({
      id: "tool-second",
      function_name: "second_formatter",
      display_name: "Second formatter",
    })
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.includes("/resource-folders/resources/move-batch")) {
        requests.push(JSON.parse(String(init?.body)))
        return new Response(null, { status: 204 })
      }
      if (url.includes("/resource-folders")) {
        return jsonResponse([
          {
            id: "folder-1",
            workspace_id: "ws-1",
            resource_type: "tool",
            parent_id: null,
            name: "生产工具",
            created_by_user_id: "u-1",
            created_at: "2026-09-05T00:00:00Z",
            updated_at: "2026-09-05T00:00:00Z",
          },
        ])
      }
      if (url.includes("/tool-sources?")) return jsonResponse([])
      if (url.includes("/tools?")) return jsonResponse([tool(), secondTool])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    expect(
      screen.queryByRole("checkbox", { name: "选择 Owned formatter" })
    ).toBeNull()
    const searchToolbar = screen.getByRole("search")
    fireEvent.click(
      within(searchToolbar).getByRole("button", { name: "批量管理" })
    )
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 Owned formatter" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 Second formatter" }))
    expect(screen.getByText("已选择 2 项")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "移动到文件夹" }))
    const dialog = await screen.findByRole("dialog", { name: "移动到文件夹" })
    fireEvent.click(within(dialog).getByRole("button", { name: "生产工具" }))

    await waitFor(() =>
      expect(requests).toEqual([
        {
          resource_type: "tool",
          resource_ids: ["tool-owner", "tool-second"],
          folder_id: "folder-1",
        },
      ])
    )
  })

  test("filters the current catalog with Skills, MCP, and Python tabs", async () => {
    const builtinTool = tool({
      id: "tool-skill",
      kind: "builtin",
      function_name: "pdf_skill",
      display_name: "PDF Skill",
      source: {
        id: "source-builtin",
        name: "Builtin",
        kind: "builtin",
        transport: null,
      },
      created_by_user_id: null,
    })
    const remoteTool = tool({
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
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tool-sources?"))
        return jsonResponse([source({ tool_count: 1 })])
      if (url.includes("/tools?"))
        return jsonResponse([builtinTool, remoteTool, tool()])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage initialKind="builtin" />)
    await screen.findByText("PDF")
    const searchToolbar = screen.getByRole("search")
    expect(within(searchToolbar).getByRole("searchbox")).toBeTruthy()
    expect(
      within(searchToolbar).getByRole("button", { name: "Skills" })
    ).toBeTruthy()
    expect(screen.queryByText("Remote lookup")).toBeNull()
    expect(screen.queryByText("Owned formatter")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "MCP" }))
    await screen.findByText("Remote lookup")
    expect(screen.getAllByText("Remote tools").length).toBeGreaterThan(0)
    expect(screen.queryByText("PDF")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "Python" }))
    await screen.findByText("Owned formatter")
    expect(screen.queryByText("Remote lookup")).toBeNull()
    expect(screen.queryByText("Remote tools")).toBeNull()
    expect(
      screen.getByRole("button", { name: "Python" }).getAttribute("aria-pressed")
    ).toBe("true")
  })

  test("renders the unified empty state and member-safe add menu", async () => {
    renderPage(<ToolsPage />)
    await screen.findByText("还没有工具")
    const trigger = screen.getByRole("button", { name: "添加工具" })
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    expect(await screen.findByText("Python 工具")).toBeTruthy()
    expect(screen.getByText("MCP Server")).toBeTruthy()
    expect(screen.getByRole("menuitem", { name: "Skills" }).getAttribute("href")).toBe(
      "/app/tools/skills"
    )
  })

  test("shows an explicit retry state when the catalog fails", async () => {
    let fail = true
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (fail) return jsonResponse({ detail: "offline" }, 503)
      if (url.includes("/tools?")) return jsonResponse([])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch
    renderPage(<ToolsPage />)
    await screen.findByText("工具加载失败")
    const retry = screen.getByRole("button", { name: "重试" })
    fail = false
    fireEvent.click(retry)
    await screen.findByText("还没有工具")
    expect(screen.queryByText("工具加载失败")).toBeNull()
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
    expect(screen.queryByText("还没有工具")).toBeNull()
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
      target: { value: "https://fdn.example.com/mcp" },
    })
    expect(
      (
        screen.getByRole("button", {
          name: "添加 MCP Server",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false)

    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(addTrigger))
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

  test("renders nothing without a session token", async () => {
    Object.assign(session, { token: null })
    renderPage(<ToolsPage />)
    await waitFor(() => expect(screen.queryByRole("main")).toBeNull())
  })

  test("shows builtin tools without a group heading", async () => {
    const builtinTool = tool({
      id: "tool-builtin",
      kind: "builtin",
      function_name: "current_time",
      display_name: "Current time",
      source: {
        id: "source-builtin",
        name: "Builtin",
        kind: "builtin",
        transport: null,
      },
      created_by_user_id: null,
    })
    const skillTool = tool({
      id: "tool-skill-pdf",
      kind: "builtin",
      function_name: "pdf_skill",
      display_name: "PDF Skill",
      description: "Create PDF files",
      source: builtinTool.source,
      created_by_user_id: null,
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?"))
        return jsonResponse([builtinTool, skillTool])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("当前时间")
    expect(screen.getByText("PDF")).toBeTruthy()
    expect(screen.queryByText("内置工具")).toBeNull()
    const card = screen.getByText("当前时间").closest("article")!
    expect(within(card).getAllByText("内置").length).toBeGreaterThan(0)
    expect(within(card).getByText("可用")).toBeTruthy()
  })

  test("renders SSE and stdio sources with connection details and errors", async () => {
    const sseSource = source({
      id: "source-sse",
      name: "SSE tools",
      transport: "sse",
      url: "https://tools.example.com/sse",
    })
    const stdioSource = source({
      id: "source-stdio",
      name: "Local stdio",
      transport: "stdio",
      url: null,
      stdio_command: "npx mcp-server",
      last_error: "连接超时",
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tool-sources?"))
        return jsonResponse([sseSource, stdioSource])
      if (url.includes("/tools?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("SSE tools")
    const sseCard = screen.getByText("SSE tools").closest("article")!
    const sourceSection = sseCard.closest("section")!
    expect(sourceSection.parentElement?.previousElementSibling?.tagName).toBe(
      "ASIDE"
    )
    expect(within(sseCard).getByText("SSE")).toBeTruthy()
    const stdioCard = screen.getByText("Local stdio").closest("article")!
    expect(
      within(stdioCard).getByText(/stdio 命令：npx mcp-server/)
    ).toBeTruthy()
    expect(within(stdioCard).getByText("连接超时")).toBeTruthy()
  })

  test("shows a no-match state when search filters everything out", async () => {
    const owned = tool()
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?")) return jsonResponse([owned])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "zzz-no-match" },
    })
    expect(screen.getByText("没有匹配的工具")).toBeTruthy()
    expect(screen.queryByText("Owned formatter")).toBeNull()
  })

  test("keeps MCP runtime identifiers out of cards and search", async () => {
    const remote = tool({
      id: "tool-mcp-tavily",
      kind: "mcp",
      function_name: "mcp_tavily_search_a1b2c3d4",
      display_name: "tavily_search",
      description: "Search the web with Tavily",
      source: {
        id: "source-mcp-tavily",
        name: "Tavily",
        kind: "mcp",
        transport: "streamable_http",
      },
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("tavily_search")
    expect(screen.queryByText("mcp_tavily_search_a1b2c3d4")).toBeNull()

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "mcp_tavily_search_a1b2c3d4" },
    })
    expect(screen.getByText("没有匹配的工具")).toBeTruthy()
    expect(screen.queryByText("tavily_search")).toBeNull()
  })

  test("opens a tool detail with the keyboard", async () => {
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
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-mcp")) return jsonResponse(detail(remote))
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    fireEvent.keyDown(screen.getByText("Remote lookup").closest("article")!, {
      key: "Enter",
    })
    await screen.findByText("输入 Schema")
  })

  test("marks tools from disabled MCP sources and guards their policy menu", async () => {
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
    const disabledSource = source({ status: "disabled", tool_count: 1 })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([disabledSource])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    const card = screen.getByText("Remote lookup").closest("article")!
    expect(within(card).getByText("来源已禁用")).toBeTruthy()

    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    expect(
      await screen.findByRole("menuitem", { name: "来源已禁用" })
    ).toBeTruthy()
    expect(
      screen.queryByRole("menuitem", { name: "每次调用前审批" })
    ).toBeNull()
  })

  test("locks the policy menu for disabled tools of non-admins", async () => {
    const remote = tool({
      id: "tool-mcp",
      kind: "mcp",
      function_name: "remote_lookup",
      display_name: "Remote lookup",
      status: "disabled",
      availability: "unavailable",
      current_version_id: null,
      source: {
        id: "source-mcp",
        name: "Remote tools",
        kind: "mcp",
        transport: "streamable_http",
      },
    })
    const remoteSource = source({ tool_count: 1 })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([remoteSource])
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
      await screen.findByRole("menuitem", { name: "工具调用已禁用" })
    ).toBeTruthy()
    expect(
      screen.queryByRole("menuitem", { name: "每次调用前审批" })
    ).toBeNull()
  })

  test("refreshes an MCP source from the tool menu", async () => {
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
    const remoteSource = source({ name: "Remote tools", tool_count: 1 })
    const requests: Array<{ method: string }> = []
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    let sourceState = remoteSource
    let refreshFails = false
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tool-sources/source-mcp/refresh")) {
        requests.push({ method: init?.method ?? "GET" })
        if (refreshFails) return jsonResponse({ detail: "refresh failed" }, 503)
        sourceState = { ...remoteSource, tool_count: 7 }
        return jsonResponse(sourceState)
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([sourceState])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "刷新工具" }))
    await waitFor(() => expect(requests).toEqual([{ method: "POST" }]))
    const sourceCard = screen.getAllByText("Remote tools")[0].closest(
      "article"
    )!
    await waitFor(() => expect(within(sourceCard).getByText("7")).toBeTruthy())

    // a failing refresh keeps the card and reports the error
    refreshFails = true
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "刷新工具" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "refresh failed"])
    )
    expect(within(sourceCard).getByText("7")).toBeTruthy()
  }, 20000)

  test("disables an MCP source with confirmation", async () => {
    const src = source({ name: "Remote tools", tool_count: 1 })
    const requests: Array<{ method: string }> = []
    let sourceState = src
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tool-sources/source-mcp/disable")) {
        requests.push({ method: init?.method ?? "GET" })
        sourceState = { ...src, status: "disabled" }
        return jsonResponse(sourceState)
      }
      if (url.includes("/tools?")) return jsonResponse([])
      if (url.includes("/tool-sources?")) return jsonResponse([sourceState])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findAllByText("Remote tools")
    const manage = screen.getByRole("button", {
      name: "管理来源 Remote tools",
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
    await waitFor(() => expect(requests).toEqual([{ method: "POST" }]))
    const sourceCard = screen.getByText("Remote tools").closest("article")!
    await waitFor(() =>
      expect(within(sourceCard).getByText("已停用")).toBeTruthy()
    )
  })

  test("enables a disabled MCP source without confirmation", async () => {
    const src = source({ name: "Remote tools", status: "disabled", tool_count: 1 })
    const requests: Array<{ method: string }> = []
    let sourceState = src
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tool-sources/source-mcp/enable")) {
        requests.push({ method: init?.method ?? "GET" })
        sourceState = { ...src, status: "active" }
        return jsonResponse(sourceState)
      }
      if (url.includes("/tools?")) return jsonResponse([])
      if (url.includes("/tool-sources?")) return jsonResponse([sourceState])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findAllByText("Remote tools")
    const manage = screen.getByRole("button", {
      name: "管理来源 Remote tools",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "启用" }))
    await waitFor(() => expect(requests).toEqual([{ method: "POST" }]))
    const sourceCard = screen.getByText("Remote tools").closest("article")!
    await waitFor(() =>
      expect(within(sourceCard).getByText("已启用")).toBeTruthy()
    )
  })

  test("keeps a source untouched when disabling or deleting is cancelled", async () => {
    const src = source({ name: "Remote tools", tool_count: 1 })
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
    const requests: Array<{ method: string }> = []
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([src])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findAllByText("Remote tools")
    const manage = screen.getByRole("button", {
      name: "管理来源 Remote tools",
    })

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "禁用" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "取消" }
      )
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除来源" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "取消" }
      )
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )

    expect(requests).toEqual([])
    expect(screen.getAllByText("Remote tools").length).toBeGreaterThan(0)
  }, 20000)

  test("keeps source cards when enable/disable or delete requests fail", async () => {
    const src = source({ name: "Remote tools", tool_count: 1 })
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
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/tool-sources/source-mcp/disable"))
        return jsonResponse({ detail: "cannot disable" }, 503)
      if (url.endsWith("/tool-sources/source-mcp"))
        return jsonResponse({ detail: "cannot delete" }, 503)
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([src])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findAllByText("Remote tools")
    const manage = screen.getByRole("button", {
      name: "管理来源 Remote tools",
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
      expect(notifications).toContainEqual(["error", "cannot disable"])
    )
    const sourceCard = screen.getAllByText("Remote tools")[0].closest(
      "article"
    )!
    expect(within(sourceCard).getByText("已启用")).toBeTruthy()

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除来源" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "删除" }
      )
    )
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "cannot delete"])
    )
    expect(screen.getAllByText("Remote tools").length).toBeGreaterThan(0)
  }, 20000)

  test("disables an owned python tool only after confirmation", async () => {
    const owned = tool()
    const requests: Array<{ method: string }> = []
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    let state = detail(owned)
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-owner/disable")) {
        requests.push({ method: init?.method ?? "GET" })
        state = { ...state, status: "disabled", availability: "unavailable" }
        return jsonResponse(state)
      }
      if (url.includes("/tools?")) return jsonResponse([owned])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    const manage = screen.getByRole("button", {
      name: "管理工具 Owned formatter",
    })

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "禁用" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "取消" }
      )
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )
    expect(requests).toEqual([])

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "禁用" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "禁用" }
      )
    )
    await waitFor(() => expect(requests).toEqual([{ method: "POST" }]))
    expect(notifications).toContainEqual(["success", "工具已禁用"])
    const card = screen.getByText("Owned formatter").closest("article")!
    await waitFor(() => expect(within(card).getByText("不可用")).toBeTruthy())
  }, 20000)

  test("enables a disabled python tool without confirmation", async () => {
    const owned = tool({
      status: "disabled",
      availability: "unavailable",
      current_version_id: null,
    })
    const requests: Array<{ method: string }> = []
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-owner/enable")) {
        requests.push({ method: init?.method ?? "GET" })
        return jsonResponse({
          ...detail(owned),
          status: "active",
          availability: "available",
          current_version_id: "version-1",
        })
      }
      if (url.includes("/tools?")) return jsonResponse([owned])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    const manage = screen.getByRole("button", {
      name: "管理工具 Owned formatter",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "启用" }))
    await waitFor(() => expect(requests).toEqual([{ method: "POST" }]))
    expect(notifications).toContainEqual(["success", "工具已启用"])
    const card = screen.getByText("Owned formatter").closest("article")!
    await waitFor(() => expect(within(card).getByText("可用")).toBeTruthy())
  })

  test("keeps the tool card when the disable request fails", async () => {
    const owned = tool()
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-owner/disable"))
        return jsonResponse({ detail: "nope" }, 503)
      if (url.includes("/tools?")) return jsonResponse([owned])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    const manage = screen.getByRole("button", {
      name: "管理工具 Owned formatter",
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
    await waitFor(() => expect(notifications).toContainEqual(["error", "nope"]))
    const card = screen.getByText("Owned formatter").closest("article")!
    expect(within(card).getByText("可用")).toBeTruthy()
  })

  test("marks an MCP tool read-only only after explicit confirmation", async () => {
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
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-mcp/policy")) {
        requests.push(JSON.parse(String(init?.body)))
        return jsonResponse({ ...detail(remote), approval: "read_only" })
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([remoteSource])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "只读自动执行" })
    )
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "取消" }
      )
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )
    expect(requests).toEqual([])

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "只读自动执行" })
    )
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "确认" }
      )
    )
    await waitFor(() => expect(requests).toEqual([{ mode: "read_only" }]))
    expect(notifications).toContainEqual(["success", "MCP 工具策略已更新"])
  }, 20000)

  test("keeps an MCP tool enabled when the admin cancels disabling", async () => {
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
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-mcp/policy")) {
        requests.push(JSON.parse(String(init?.body)))
        return jsonResponse({ detail: "policy rejected" }, 503)
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([remoteSource])
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
        { name: "取消" }
      )
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )
    expect(requests).toEqual([])

    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "每次调用前审批" })
    )
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "policy rejected"])
    )
    expect(requests).toEqual([{ mode: "approval_required" }])
  }, 20000)

  test("archives an owned python tool only after confirmation", async () => {
    const owned = tool()
    const requests: Array<{ method: string }> = []
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    let archiveFails = true
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-owner")) {
        requests.push({ method: init?.method ?? "GET" })
        if (archiveFails) return jsonResponse({ detail: "archive failed" }, 503)
        return jsonResponse(null)
      }
      if (url.includes("/tools?")) return jsonResponse([owned])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    const manage = screen.getByRole("button", {
      name: "管理工具 Owned formatter",
    })

    // cancelling leaves the tool in place
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "归档" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "取消" }
      )
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )
    expect(requests).toEqual([])

    // a failing archive keeps the card and reports the error
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "归档" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "归档" }
      )
    )
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "archive failed"])
    )
    expect(screen.getByText("Owned formatter")).toBeTruthy()

    // a successful archive removes the card
    archiveFails = false
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "归档" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "归档" }
      )
    )
    await waitFor(() => expect(screen.queryByText("Owned formatter")).toBeNull())
    expect(notifications).toContainEqual(["success", "工具已归档"])
    await screen.findByText("还没有工具")
  }, 20000)

  test("deletes an MCP source with confirmation and removes its tools", async () => {
    const src = source({ name: "Remote tools", tool_count: 1 })
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
    const requests: Array<{ method: string }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tool-sources/source-mcp")) {
        requests.push({ method: init?.method ?? "GET" })
        return jsonResponse(null)
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([src])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理来源 Remote tools",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除来源" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "删除" }
      )
    )
    await waitFor(() => expect(requests).toEqual([{ method: "DELETE" }]))
    await waitFor(() => expect(screen.queryByText("Remote lookup")).toBeNull())
    expect(screen.queryByText("Remote tools")).toBeNull()
    await screen.findByText("还没有工具")
  })

  test("deletes an MCP source from the tool menu", async () => {
    const src = source({ name: "Remote tools", tool_count: 1 })
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
    const requests: Array<{ method: string }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tool-sources/source-mcp")) {
        requests.push({ method: init?.method ?? "GET" })
        return jsonResponse(null)
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([src])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除来源" }))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "删除" }
      )
    )
    await waitFor(() => expect(requests).toEqual([{ method: "DELETE" }]))
    await waitFor(() => expect(screen.queryByText("Remote lookup")).toBeNull())
    await screen.findByText("还没有工具")
  })

  test("keeps unpublished details hidden for view-only MCP tools", async () => {
    const remote = tool({
      id: "tool-mcp",
      kind: "mcp",
      function_name: "remote_lookup",
      display_name: "Remote lookup",
      created_by_user_id: "u-2",
      permission: "view",
      can_use: false,
      can_manage: false,
      source: {
        id: "source-mcp",
        name: "Remote tools",
        kind: "mcp",
        transport: "streamable_http",
      },
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-mcp")) return jsonResponse(detail(remote))
      if (url.includes("/tools?")) return jsonResponse([remote])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Remote lookup")
    expect(
      screen.queryByRole("button", { name: "管理工具 Remote lookup" })
    ).toBeNull()
    fireEvent.click(screen.getByText("Remote lookup").closest("article")!)
    const note =
      "只显示已发布的脱敏详情；草稿和代码仅所有者或管理员可见。"
    await screen.findByText(note)
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(screen.queryByText(note)).toBeNull())
  })

  test("opens the python editor from the manage menu", async () => {
    const owned = tool()
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-owner")) return jsonResponse(detail(owned))
      if (url.includes("/tools?")) return jsonResponse([owned])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("Owned formatter")
    const manage = screen.getByRole("button", {
      name: "管理工具 Owned formatter",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "编辑" }))

    const pythonDialog = await screen.findByRole("dialog", {
      name: "Python 工具详情",
    })
    expect(within(pythonDialog).getByText("已发布")).toBeTruthy()
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Python 工具详情" })
      ).toBeNull()
    )
    expect(screen.getByText("Owned formatter")).toBeTruthy()
  })

  test("creates a python tool from the add menu", async () => {
    const created = detail(
      tool({
        id: "tool-created",
        function_name: "brand_new",
        display_name: "Brand new tool",
      })
    )
    const requests: Array<{ body: Record<string, unknown> }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.endsWith("/tools/python")) {
        requests.push({ body: JSON.parse(String(init?.body)) })
        return jsonResponse(created)
      }
      if (url.includes("/tools?")) return jsonResponse([])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("还没有工具")
    const addTrigger = screen.getByRole("button", { name: "添加工具" })
    fireEvent.pointerDown(addTrigger)
    fireEvent.click(addTrigger)
    fireEvent.click(await screen.findByText("Python 工具"))
    await screen.findByRole("heading", { name: "创建 Python 工具" })
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "Brand new tool" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建" }))
    await screen.findByText("Brand new tool")
    expect(requests).toEqual([
      {
        body: {
          display_name: "Brand new tool",
          description: "",
          input_schema: {
            type: "object",
            properties: {},
            additionalProperties: false,
          },
          output_schema: {
            type: "object",
            properties: {},
            additionalProperties: false,
          },
          code: "result = inputs",
        },
      },
    ])
  })

  test("creates a public MCP source from the add dialog", async () => {
    const createdSource = source({ id: "source-new", name: "New public MCP" })
    const notifications: Array<[string, string]> = []
    Object.assign(session, {
      notify: (kind: string, value: string) =>
        notifications.push([kind, value]),
    })
    let sources: ToolSourceDetail[] = []
    const requests: Array<{ method: string; body: unknown }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      if (url.includes("/tool-sources/mcp")) {
        requests.push({
          method: init?.method ?? "GET",
          body: JSON.parse(String(init?.body)),
        })
        sources = [createdSource]
        return jsonResponse(createdSource)
      }
      if (url.includes("/tools?")) return jsonResponse([])
      if (url.includes("/tool-sources?")) return jsonResponse(sources)
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("还没有工具")
    const addTrigger = screen.getByRole("button", { name: "添加工具" })
    fireEvent.pointerDown(addTrigger)
    fireEvent.click(addTrigger)
    fireEvent.click(await screen.findByText("MCP Server"))
    await screen.findByRole("heading", { name: "添加 MCP Server" })
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Internal" },
    })
    fireEvent.change(screen.getByLabelText("MCP 地址"), {
      target: { value: "https://tools.example.com/mcp" },
    })
    fireEvent.click(
      screen.getByRole("button", { name: "添加 MCP Server" })
    )
    await screen.findByText("New public MCP")
    expect(requests).toEqual([
      {
        method: "POST",
        body: {
          name: "Internal",
          transport: "streamable_http",
          url: "https://tools.example.com/mcp",
        },
      },
    ])
    expect(notifications).toContainEqual(["success", "MCP Server 已添加"])
  })
})

/* @jsxImportSource react */
import { beforeEach, describe, expect, test } from "bun:test"

import { ToolsPage } from "@/components/tools/tools-page"
import type { MeResponse } from "@/lib/api/auth"
import type { AgentSkill } from "@/lib/api/agent-skills"
import type { ToolDetail, ToolSourceDetail, ToolSummary } from "@/lib/api/tools"
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
    kind: "mcp",
    function_name: "formatter",
    display_name: "Owned formatter",
    description: "Formats text",
    current_version_id: "version-1",
    status: "active",
    availability: "available",
    source: {
      id: "source-owned",
      name: "Owned source",
      kind: "mcp",
      transport: null,
    },
    created_by_user_id: "u-1",
    created_at: "2026-08-17T00:00:00Z",
    updated_at: "2026-08-17T00:00:00Z",
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
function sourceGroup(name: string) {
  return screen
    .getAllByRole("article", { hidden: true })
    .find((item) => item.getAttribute("aria-label") === name)!
}

function manageSourceTools(name: string) {
  const manage = screen.getByRole("button", { name: `管理来源 ${name}` })
  fireEvent.pointerDown(manage)
  fireEvent.click(manage)
  fireEvent.click(screen.getByRole("menuitem", { name: "管理工具" }))
}

function openSkillMenu(name: string) {
  const trigger = screen.getByRole("button", { name: `管理技能 ${name}` })
  fireEvent.pointerDown(trigger)
  fireEvent.click(trigger)
}

describe("ToolsPage", () => {
  test("groups shared MCP operations without connection details or child cards even when searching", async () => {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      if (String(input).includes("/tools?"))
        return jsonResponse([
          tool({ can_manage: false }),
          tool({
            id: "tool-second",
            display_name: "Second operation",
            can_manage: false,
          }),
        ])
      return jsonResponse([])
    }) as typeof fetch
    renderPage(<ToolsPage initialKind="mcp" />)
    await screen.findByRole("article", { name: "Owned source" })
    expect(screen.getAllByRole("article")).toHaveLength(1)
    expect(screen.queryByText("Owned formatter")).toBeNull()
    expect(screen.queryByText("Second operation")).toBeNull()
    expect(screen.queryByText("Formats text")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "管理来源 Owned source" })
    ).toBeNull()
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Second operation" },
    })
    expect(screen.getByRole("article", { name: "Owned source" })).toBeTruthy()
    expect(screen.queryByText("Second operation")).toBeNull()
  })

  test("searches workspace Skills independently of built-in tools and edits the pinned files", async () => {
    const skill: AgentSkill = {
      id: "skill-1",
      workspace_id: "ws-1",
      name: "Research package",
      description: "Research tasks",
      definition: {
        instructions: "Use bundled resources.",
        intents: [],
        input_schema: {},
        output_schema: {},
        knowledge_base_ids: [],
        tools: [],
        files: { "assets/data.bin": "AP8=" },
        execution_timeout_seconds: 30,
        guardrails: {
          allow_external_reads: false,
          allow_external_writes: false,
          require_approval_for_external_writes: true,
        },
      },
      status: "active",
      current_published_version_id: "v1",
      current_version_number: 1,
      has_unpublished_changes: false,
      permission: "owner",
      can_manage: true,
      can_use: true,
      created_by_user_id: "u-1",
      created_at: "2026-09-18T00:00:00Z",
      updated_at: "2026-09-18T00:00:00Z",
    }
    let patchBody: unknown
    let deleted = false
    globalThis.fetch = (async (input, options) => {
      const url = String(input)
      if (options?.method === "DELETE") { deleted = true; return new Response(null, { status: 204 }) }
      if (options?.method === "PATCH") {
        patchBody = JSON.parse(String(options.body))
        return jsonResponse(skill)
      }
      if (url.includes("/agent-skills?")) return jsonResponse([skill])
      return jsonResponse([])
    }) as typeof fetch
    renderPage(<ToolsPage initialKind="builtin" />)
    await screen.findByRole("button", { name: "Research package" })
    fireEvent.change(screen.getByPlaceholderText("搜索名称、描述或来源"), {
      target: { value: "research" },
    })
    expect(
      Boolean(screen.queryByRole("button", { name: "Research package" }))
    ).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "Research package" }))
    await screen.findByRole("heading", { name: "编辑技能" })
    expect(screen.getByText(/assets\/data.bin/)).toBeTruthy()
    expect(screen.getByText("已发布版本：1")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))
    await waitFor(() =>
      expect(
        Boolean(screen.queryByRole("heading", { name: "编辑技能" }))
      ).toBe(false)
    )
    expect(
      (patchBody as { definition: { files: unknown } }).definition.files
    ).toEqual({ "assets/data.bin": "AP8=" })
    fireEvent.change(screen.getByPlaceholderText("搜索名称、描述或来源"), {
      target: { value: "no-match" },
    })
    expect(screen.getByText("没有匹配的技能")).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText("搜索名称、描述或来源"), { target: { value: "" } })
    openSkillMenu("Research package")
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }))
    const confirm = await screen.findByRole("dialog", { name: "确认操作" })
    fireEvent.click(within(confirm).getByRole("button", { name: "删除" }))
    await waitFor(() => expect(deleted).toBe(true))
    await waitFor(() =>
      expect(
        Boolean(screen.queryByRole("button", { name: "Research package" }))
      ).toBe(false)
    )
  })

  test("enables and disables manageable Skills and reports mutation errors", async () => {
    let status = "active"
    let fail = false
    const notifications: string[] = []
    Object.assign(session, {
      notify: (_kind: string, value: string) => {
        notifications.push(value)
      },
    })
    globalThis.fetch = (async (input, options) => {
      const url = String(input)
      if (options?.method === "PATCH") {
        if (fail) return jsonResponse({ detail: "Skill update rejected" }, 409)
        status = JSON.parse(String(options.body)).status
        return jsonResponse({ id: "skill-1" })
      }
      if (url.includes("/agent-skills?"))
        return jsonResponse([
          {
            id: "skill-1",
            name: "Toggle package",
            description: "Tasks",
            status,
            can_manage: true,
            definition: { instructions: "Do work", files: {} },
          },
        ])
      return jsonResponse([])
    }) as typeof fetch
    renderPage(<ToolsPage initialKind="builtin" />)
    await screen.findByRole("button", { name: "Toggle package" })
    openSkillMenu("Toggle package")
    fireEvent.click(screen.getByRole("menuitem", { name: "停用" }))
    await screen.findByText("已停用")
    openSkillMenu("Toggle package")
    fireEvent.click(screen.getByRole("menuitem", { name: "启用" }))
    await screen.findByText("草稿")
    expect(status).toBe("active")
    fail = true
    openSkillMenu("Toggle package")
    fireEvent.click(screen.getByRole("menuitem", { name: "停用" }))
    await waitFor(() =>
      expect(notifications).toContain("Skill update rejected")
    )
    expect(status).toBe("active")
  })

  test("does not offer mutation controls for view-only workspace Skills", async () => {
    globalThis.fetch = (async (input) =>
      String(input).includes("/agent-skills?")
        ? jsonResponse([
            {
              id: "skill-1",
              name: "View package",
              description: "Tasks",
              status: "disabled",
              current_version_number: 1,
              can_manage: false,
              definition: { instructions: "Read only", files: {} },
            },
          ])
        : jsonResponse([])) as typeof fetch
    renderPage(<ToolsPage initialKind="builtin" />)
    fireEvent.click(await screen.findByRole("button", { name: "View package" }))
    await screen.findByRole("heading", { name: "编辑技能" })
    expect(
      (screen.getByLabelText("显示名称") as HTMLInputElement).disabled
    ).toBe(true)
    expect(screen.queryByRole("button", { name: "保存并发布" })).toBeNull()
    expect(screen.queryByRole("button", { name: "启用" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() =>
      expect(
        Boolean(screen.queryByRole("heading", { name: "编辑技能" }))
      ).toBe(false)
    )
  })

  test("sorts tools and shows their update time", async () => {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tool-sources?")) return jsonResponse([])
      if (url.includes("/tools?")) {
        return jsonResponse([
          tool({
            id: "tool-alpha",
            display_name: "Alpha operation",
            source: { ...tool().source, id: "alpha", name: "Alpha" },
            created_at: "2026-09-02T00:00:00Z",
            updated_at: "2026-09-01T00:00:00Z",
          }),
          tool({
            id: "tool-bravo",
            display_name: "Bravo operation",
            source: { ...tool().source, id: "bravo", name: "Bravo" },
            created_at: "2026-09-01T00:00:00Z",
            updated_at: "2026-09-02T00:00:00Z",
          }),
          tool({
            id: "tool-charlie",
            display_name: "Charlie operation",
            source: { ...tool().source, id: "charlie", name: "Charlie" },
            created_at: "2026-09-03T00:00:00Z",
            updated_at: "2026-09-03T00:00:00Z",
          }),
        ])
      }
      return jsonResponse([])
    }) as typeof fetch
    renderPage(<ToolsPage />)

    await screen.findByText("Charlie")
    const visibleToolNames = () =>
      screen
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent)
    expect(visibleToolNames()).toEqual(["Charlie", "Bravo", "Alpha"])
    expect(screen.queryByText("Alpha operation")).toBeNull()

    const sortTrigger = screen.getByRole("button", { name: "排序" })
    fireEvent.pointerDown(sortTrigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: "创建时间" }))
    expect(visibleToolNames()).toEqual(["Charlie", "Alpha", "Bravo"])

    fireEvent.pointerDown(sortTrigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: "名称" }))
    expect(visibleToolNames()).toEqual(["Alpha", "Bravo", "Charlie"])
  })

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
    await screen.findByText("Owned source")
    expect(
      screen.queryByRole("checkbox", { name: "选择 Owned source" })
    ).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "批量管理" }))
    const service = screen.getByRole("checkbox", {
      name: "选择 Owned source",
    }) as HTMLInputElement
    fireEvent.click(service)
    expect(service.checked).toBe(true)
    expect(screen.getByText("已选择 2 项")).toBeTruthy()
    expect(screen.queryByText("Owned formatter")).toBeNull()
    expect(screen.queryByText("Second formatter")).toBeNull()
    fireEvent.click(service)
    expect(service.checked).toBe(false)
    expect(screen.getByText("已选择 0 项")).toBeTruthy()
    fireEvent.click(service)
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

  test("batch manages MCP tools while their sources stay folded", async () => {
    const requests: unknown[] = []
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
      if (url.includes("/tool-sources?")) {
        return jsonResponse([source({ tool_count: 1 })])
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findAllByText("Remote tools")
    expect(screen.queryByText("Remote lookup")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "批量管理" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 Remote tools" }))
    expect(screen.getByText("已选择 1 项")).toBeTruthy()
    expect(screen.queryByText("Remote lookup")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "移动到文件夹" }))
    const dialog = await screen.findByRole("dialog", { name: "移动到文件夹" })
    fireEvent.click(within(dialog).getByRole("button", { name: "生产工具" }))
    await waitFor(() =>
      expect(requests).toEqual([
        {
          resource_type: "tool",
          resource_ids: ["tool-mcp"],
          folder_id: "folder-1",
        },
      ])
    )
  })

  test("does not batch manage fixed built-in Skills", async () => {
    const builtinSkills = [
      ["documents_skill", "Documents Skill"],
      ["pdf_skill", "PDF Skill"],
      ["pptx_skill", "PPTX Skill"],
      ["spreadsheets_skill", "Spreadsheets Skill"],
      ["skill_creator", "Skill Creator"],
    ].map(([functionName, displayName], index) =>
      tool({
        id: `tool-builtin-skill-${index}`,
        kind: "builtin",
        function_name: functionName,
        display_name: displayName,
        source: {
          id: "source-builtin",
          name: "Builtin",
          kind: "builtin",
          transport: null,
        },
        created_by_user_id: null,
        permission: "admin",
        can_manage: true,
      })
    )
    const pythonTool = tool()
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?")) {
        return jsonResponse([...builtinSkills, pythonTool])
      }
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage initialKind="builtin" />)
    await screen.findByText("生成 PDF")
    expect(screen.queryByRole("button", { name: "批量管理" })).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "MCP" }))
    await screen.findByText("Owned source")
    expect(screen.getByRole("button", { name: "批量管理" })).toBeTruthy()
  })

  test("filters Skills and MCP while excluding retired Python tools", async () => {
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
    const timeTool = tool({
      id: "tool-current-time",
      kind: "python" as ToolSummary["kind"],
      function_name: "current_time",
      display_name: "Current time",
      created_by_user_id: null,
      permission: "use",
      can_manage: false,
      source: {
        id: "source-python-system",
        name: "Python",
        kind: "python" as ToolSummary["kind"],
        transport: null,
      },
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
        return jsonResponse([builtinTool, timeTool, remoteTool, tool()])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage initialKind="builtin" />)
    await screen.findByText("生成 PDF")
    expect(screen.queryByRole("heading", { name: "内置技能" })).toBeNull()
    expect(screen.queryByRole("heading", { name: "自定义技能" })).toBeNull()
    expect(screen.queryByText("还没有可用的技能")).toBeNull()
    const searchToolbar = screen.getByRole("search")
    expect(within(searchToolbar).getByRole("searchbox")).toBeTruthy()
    expect(
      within(searchToolbar).getByRole("button", { name: "技能" })
    ).toBeTruthy()
    expect(screen.queryByText("Remote lookup")).toBeNull()
    expect(screen.queryByText("Owned formatter")).toBeNull()
    expect(screen.queryByText("当前时间")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "MCP" }))
    await screen.findAllByText("Remote tools")
    expect(screen.queryByText("Remote lookup")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "展开 Remote tools 的工具" })
    ).toBeNull()
    expect(screen.getAllByText("Remote tools").length).toBeGreaterThan(0)
    expect(screen.queryByText("生成 PDF")).toBeNull()

    expect(screen.queryByRole("button", { name: "Python" })).toBeNull()
    expect(screen.queryByText("当前时间")).toBeNull()
  })

  test("searches and sorts all Skills together in one grid", async () => {
    const pdf = tool({
      id: "pdf-tool",
      kind: "builtin",
      function_name: "pdf_skill",
      created_at: "2026-09-02T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
    })
    globalThis.fetch = (async (input) => {
      const url = String(input)
      if (url.includes("/tools?")) return jsonResponse([pdf])
      if (url.includes("/agent-skills?")) {
        return jsonResponse([
          {
            id: "research-skill",
            name: "A research package",
            description: "Research PDF documents",
            status: "active",
            current_version_number: 1,
            can_manage: true,
            created_at: "2026-09-01T00:00:00Z",
            updated_at: "2026-09-02T00:00:00Z",
          },
        ])
      }
      return jsonResponse([])
    }) as typeof fetch
    renderPage(<ToolsPage initialKind="builtin" />)

    const researchCard = (
      await screen.findByRole("button", { name: "A research package" })
    ).closest("article")!
    const pdfCard = screen.getByText("生成 PDF").closest("article")!
    const grid = researchCard.parentElement!
    const names = () =>
      Array.from(grid.children).map(
        (card) => card.querySelector("h3, button")?.textContent
      )
    expect(pdfCard.parentElement).toBe(grid)
    expect(names()).toEqual(["A research package", "生成 PDF"])

    const sortTrigger = screen.getByRole("button", { name: "排序" })
    fireEvent.pointerDown(sortTrigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: "创建时间" }))
    expect(names()).toEqual(["生成 PDF", "A research package"])
    fireEvent.pointerDown(sortTrigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: "名称" }))
    expect(names()).toEqual(["生成 PDF", "A research package"])

    const search = screen.getByRole("searchbox")
    fireEvent.change(search, { target: { value: "PDF" } })
    expect(grid.children).toHaveLength(2)
    fireEvent.change(search, { target: { value: "research" } })
    expect(grid.children).toHaveLength(1)
    expect(screen.queryByText("生成 PDF")).toBeNull()
    fireEvent.change(search, { target: { value: "生成" } })
    expect(grid.children).toHaveLength(1)
    expect(screen.getByText("生成 PDF")).toBeTruthy()
    expect(
      screen.queryByRole("button", { name: "A research package" })
    ).toBeNull()
    fireEvent.change(search, { target: { value: "missing" } })
    expect(screen.getByText("没有匹配的技能")).toBeTruthy()
    expect(screen.queryByText("还没有可用的技能")).toBeNull()
  })

  test("hides image generation, bash and the Skill installer from the Tool catalog", async () => {
    const imageTool = tool({
      id: "tool-image",
      folder_id: null,
      kind: "builtin",
      function_name: "generate_image",
      display_name: "Generate image",
      allowed_access_sources: ["console", "public"],
      source: {
        id: "source-builtin",
        name: "Builtin",
        kind: "builtin",
        transport: null,
      },
      created_by_user_id: null,
      can_manage: false,
    })
    const pdfTool = tool({
      ...imageTool,
      id: "tool-pdf",
      function_name: "pdf_skill",
      display_name: "PDF Skill",
    })
    const installerTool = tool({
      ...imageTool,
      id: "tool-installer",
      function_name: "install_skill_dependencies",
      display_name: "Install Skill dependencies",
    })
    const bashTool = tool({
      ...imageTool,
      id: "builtin-bash",
      function_name: "bash",
      display_name: "Command line",
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?"))
        return jsonResponse([imageTool, installerTool, bashTool, pdfTool])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage initialKind="builtin" />)
    await screen.findByText("生成 PDF")
    expect(screen.queryByText("图片生成")).toBeNull()
    expect(screen.queryByText("Install Skill dependencies")).toBeNull()
    expect(screen.queryByText("命令行") === null).toBe(true)
    expect(screen.queryByRole("heading", { name: "内置工具" })).toBeNull()
  })

  test("shows MCP policy and a retained upstream-missing state on the card", async () => {
    const remote = tool({
      id: "tool-mcp-missing",
      kind: "mcp",
      function_name: "retired_lookup",
      display_name: "Retired lookup",
      availability: "unavailable",
      policy_mode: "approval_required",
      source: {
        id: "source-mcp",
        name: "Remote tools",
        kind: "mcp",
        transport: "streamable_http",
      },
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tool-sources?")) {
        return jsonResponse([source({ tool_count: 0 })])
      }
      if (url.includes("/tools?")) return jsonResponse([remote])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
    await screen.findByText("Retired lookup")
    const card = screen.getByRole("dialog", {
      name: "管理 Remote tools 的工具",
    })
    expect(within(card).getByText("每次调用前审批")).toBeTruthy()
    expect(within(card).getByText("上游未发现该工具")).toBeTruthy()
  })

  test("renders the unified empty state and member-safe add menu", async () => {
    renderPage(<ToolsPage />)
    await screen.findByText("还没有工具")
    const trigger = screen.getByRole("button", { name: "添加工具" })
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    expect(screen.queryByText("Python 工具")).toBeNull()
    expect(screen.getByText("MCP Server")).toBeTruthy()
    fireEvent.click(screen.getByRole("menuitem", { name: "技能" }))
    expect(
      await screen.findByRole("heading", { name: "创建技能" })
    ).toBeTruthy()
    expect(screen.getByRole("button", { name: /导入技能/ })).toBeTruthy()
    expect(screen.getByLabelText("技能指令")).toBeTruthy()
    expect(screen.getByRole("button", { name: "保存并发布" })).toBeTruthy()
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
      kind: "builtin",
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
    const emptySourceCard = sourceGroup("Empty MCP")
    expect(within(emptySourceCard).getByText("0 个工具")).toBeTruthy()
    expect(
      screen.getByRole("button", { name: "管理来源 Empty MCP" })
    ).toBeTruthy()
    expect(screen.queryByText("没有匹配的工具")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "展开 Empty MCP 的工具" })
    ).toBeNull()
  })

  test("lets an MCP owner manage policies and disable their own tool", async () => {
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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
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
    expect(screen.getByRole("menuitem", { name: "禁用" })).toBeTruthy()

    fireEvent.click(screen.getByRole("menuitem", { name: "每次调用前审批" }))
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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
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
    await waitFor(() => expect(requests).toEqual([{ mode: "disabled" }]))
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
    const owned = tool({ kind: "builtin" })
    const shared = tool({
      id: "tool-view",
      kind: "builtin",
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
    expect(
      await screen.findByRole("menuitem", { name: "查看详情" })
    ).toBeTruthy()
    expect(screen.getByRole("menuitem", { name: "授权" })).toBeTruthy()
    expect(screen.queryByRole("menuitem", { name: "归档" })).toBeNull()
    fireEvent.keyDown(document, { key: "Escape" })

    fireEvent.click(screen.getByText("Shared viewer").closest("article")!)
    await screen.findByRole("heading", { name: "Shared viewer" })
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
    const timeTool = tool({
      id: "tool-current-time",
      kind: "python" as ToolSummary["kind"],
      function_name: "current_time",
      display_name: "Current time",
      source: {
        id: "source-python",
        name: "Python",
        kind: "python" as ToolSummary["kind"],
        transport: null,
      },
      created_by_user_id: null,
      permission: "use",
      can_manage: false,
    })
    const skillTool = tool({
      id: "tool-skill-pdf",
      kind: "builtin",
      function_name: "pdf_skill",
      display_name: "PDF Skill",
      description: "Create PDF files",
      source: {
        id: "source-builtin",
        name: "Builtin",
        kind: "builtin",
        transport: null,
      },
      created_by_user_id: null,
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/tools?")) return jsonResponse([timeTool, skillTool])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    await screen.findByText("生成 PDF")
    expect(screen.queryByText("当前时间")).toBeNull()
    expect(screen.queryByText("内置工具")).toBeNull()
    const skillCard = screen.getByText("生成 PDF").closest("article")!
    expect(within(skillCard).getAllByText("内置").length).toBeGreaterThan(0)
  })

  test("shows built-in Skill documentation instead of schemas", async () => {
    const skillTool = tool({
      id: "tool-skill-pdf",
      kind: "builtin",
      function_name: "pdf_skill",
      display_name: "PDF Skill",
      description: "Create PDF files",
      source: {
        id: "source-builtin",
        name: "Builtin",
        kind: "builtin",
        transport: null,
      },
      created_by_user_id: null,
      permission: "use",
      can_manage: false,
    })
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/tools/tool-skill-pdf"))
        return jsonResponse(detail(skillTool))
      if (url.includes("/tools?")) return jsonResponse([skillTool])
      if (url.includes("/tool-sources?")) return jsonResponse([])
      return jsonResponse([])
    }) as typeof fetch

    renderPage(<ToolsPage />)
    fireEvent.click((await screen.findByText("生成 PDF")).closest("article")!)
    expect(
      await screen.findByRole("heading", { name: "生成 PDF 技能" })
    ).toBeTruthy()
    expect(
      await screen.findByRole("heading", { name: "PDF operations" })
    ).toBeTruthy()
    expect(screen.queryByText("输入 Schema")).toBeNull()
    expect(screen.queryByText("输出 Schema")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "关闭" }))
    expect(screen.queryByRole("dialog")).toBeNull()
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
    const sseCard = sourceGroup("SSE tools")
    expect(within(sseCard).getByText("SSE")).toBeTruthy()
    const stdioCard = sourceGroup("Local stdio")
    expect(within(stdioCard).getByText("stdio")).toBeTruthy()
    expect(screen.queryByText(/npx mcp-server/)).toBeNull()
    expect(screen.queryByText("https://tools.example.com/sse")).toBeNull()
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
    await screen.findByText("Owned source")
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
    await screen.findByText("Tavily")
    expect(screen.queryByText("tavily_search")).toBeNull()
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
      kind: "builtin",
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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
    await screen.findByText("Remote lookup")
    const card = sourceGroup("Remote tools")
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

  test("lets owners restore their disabled MCP tool policy without an admin role", async () => {
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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    expect(
      await screen.findByRole("menuitem", { name: "每次调用前审批" })
    ).toBeTruthy()
    expect(
      screen.queryByRole("menuitem", { name: "工具调用已禁用" })
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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
    await screen.findByText("Remote lookup")
    const manage = screen.getByRole("button", {
      name: "管理工具 Remote lookup",
    })
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "刷新工具" }))
    await waitFor(() => expect(requests).toEqual([{ method: "POST" }]))
    const sourceCard = sourceGroup("Remote tools")
    await waitFor(() =>
      expect(within(sourceCard).getByText("7 个工具")).toBeTruthy()
    )

    // a failing refresh keeps the card and reports the error
    refreshFails = true
    fireEvent.pointerDown(manage)
    fireEvent.click(manage)
    fireEvent.click(await screen.findByRole("menuitem", { name: "刷新工具" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "refresh failed"])
    )
    expect(within(sourceCard).getByText("7 个工具")).toBeTruthy()
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
    const sourceCard = sourceGroup("Remote tools")
    await waitFor(() =>
      expect(within(sourceCard).getByText("来源已禁用")).toBeTruthy()
    )
  })

  test("enables a disabled MCP source without confirmation", async () => {
    const src = source({
      name: "Remote tools",
      status: "disabled",
      tool_count: 1,
    })
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
    const sourceCard = sourceGroup("Remote tools")
    await waitFor(() =>
      expect(within(sourceCard).getByText("可用")).toBeTruthy()
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
    const sourceCard = sourceGroup("Remote tools")
    expect(within(sourceCard).getByText("可用")).toBeTruthy()

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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
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
    await screen.findAllByText("Remote tools")
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
    await screen.findAllByText("Remote tools")
    manageSourceTools("Remote tools")
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
    await screen.findByText("Remote tools")
    expect(screen.queryByText("Remote lookup")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "管理来源 Remote tools" })
    ).toBeNull()
    fireEvent.click(sourceGroup("Remote tools"))
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(screen.queryByText("输入 Schema")).toBeNull()
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
    fireEvent.click(screen.getByRole("button", { name: "添加 MCP Server" }))
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

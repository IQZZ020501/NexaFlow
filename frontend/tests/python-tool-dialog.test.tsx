/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { PythonToolDialog } from "@/components/tools/python-tool-dialog"
import type { ToolDetail, ToolInvocation, ToolSummary } from "@/lib/api/tools"
import {
  fireEvent,
  jsonResponse,
  renderPage,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

const summary: ToolSummary = {
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
  created_by_user_id: "user-1",
  permission: "owner",
  can_view: true,
  can_use: true,
  can_manage: true,
}

const detail: ToolDetail = {
  ...summary,
  version_id: "version-1",
  revision: 1,
  input_schema: {
    type: "object",
    properties: { text: { type: "string" } },
    required: ["text"],
  },
  output_schema: { type: "object" },
  approval: "auto",
  effect: "pure",
  workflow_callable: true,
  parallel_safe: false,
  draft: {
    display_name: "Formatter",
    description: "Formats text",
    input_schema: {
      type: "object",
      properties: { text: { type: "string" } },
      required: ["text"],
    },
    output_schema: { type: "object" },
    code: "result = inputs",
    revision: 2,
    updated_at: "2026-08-17T00:00:00Z",
  },
}

const succeededInvocation: ToolInvocation = {
  id: "invocation-1",
  tool_id: "tool-1",
  tool_version_id: "test-version-1",
  status: "succeeded",
  attempts: 1,
  result_data: { text: "hello" },
  result_summary: "ok",
  outcome: "confirmed",
  error_code: null,
  error_message: null,
  usage: {},
  created_at: "2026-08-17T00:00:00Z",
  started_at: "2026-08-17T00:00:00Z",
  finished_at: "2026-08-17T00:00:01Z",
}

const failedInvocation: ToolInvocation = {
  id: "invocation-2",
  tool_id: "tool-1",
  tool_version_id: "test-version-1",
  status: "uncertain",
  attempts: 1,
  result_data: null,
  result_summary: "unclear",
  outcome: "uncertain",
  error_code: "E_UNCERTAIN",
  error_message: "The model could not determine the result",
  usage: {},
  created_at: "2026-08-17T00:00:00Z",
  started_at: "2026-08-17T00:00:01Z",
  finished_at: "2026-08-17T00:00:02Z",
}

const queuedInvocation: ToolInvocation = {
  ...succeededInvocation,
  id: "invocation-3",
  status: "queued",
  result_data: null,
  result_summary: "",
  outcome: null,
  error_code: null,
  error_message: null,
  finished_at: null,
}

const createdDetail: ToolDetail = {
  ...detail,
  id: "tool-new",
  display_name: "My Tool",
  description: "Does things",
  current_version_id: null,
  version_id: null,
  draft: {
    ...detail.draft,
    display_name: "My Tool",
    description: "Does things",
    code: "result = inputs.get('x')",
  } as ToolDetail["draft"],
}

describe("PythonToolDialog", () => {
  test("shows an inline error and retries a failed detail request", async () => {
    let fails = true
    globalThis.fetch = (async () =>
      fails
        ? jsonResponse({ detail: "detail unavailable" }, 503)
        : jsonResponse(detail)) as unknown as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={() => undefined}
      />
    )

    await screen.findByText("detail unavailable")
    fails = false
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    await screen.findByDisplayValue("Formatter")
    expect(screen.queryByText("detail unavailable")).toBeNull()
  })

  test("keeps draft code hidden for view-only users", async () => {
    globalThis.fetch = (async () =>
      jsonResponse({
        ...detail,
        permission: "view",
        can_manage: false,
        draft: { ...detail.draft, code: "secret draft code" },
      })) as unknown as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={{ ...summary, permission: "view", can_manage: false }}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={() => undefined}
      />
    )

    await screen.findByDisplayValue("Formatter")
    expect(
      screen.getByText("你拥有查看权限；草稿与代码不会显示。")
    ).toBeTruthy()
    expect(screen.queryByLabelText("Python 代码")).toBeNull()
    expect(screen.queryByRole("button", { name: "运行测试" })).toBeNull()
    expect(screen.queryByText("secret draft code")).toBeNull()
  })

  test("saves a draft, runs a terminal test, and publishes", async () => {
    const requests: Array<{ method: string; url: string; body?: unknown }> = []
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      void input
      const url = String(input)
      const method = init?.method ?? "GET"
      requests.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (method === "PUT") return jsonResponse(detail.draft)
      if (url.endsWith("/tests") && method === "POST") {
        return jsonResponse(succeededInvocation, 202)
      }
      if (url.endsWith("/publish") && method === "POST") {
        return jsonResponse({ ...detail, current_version_id: "version-2" })
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "Formatter 2" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))
    await waitFor(() => expect(messages).toContain("工具草稿已保存"))
    expect(
      requests.some(
        (request) =>
          request.method === "PUT" &&
          request.url.endsWith("/tools/tool-1/draft") &&
          (request.body as { expected_revision?: number }).expected_revision ===
            2
      )
    ).toBe(true)

    fireEvent.change(screen.getByLabelText("测试参数"), {
      target: { value: '{"text":"hello"}' },
    })
    fireEvent.click(screen.getByRole("button", { name: "运行测试" }))
    await screen.findByText("运行成功")
    expect(messages).toContain("工具测试通过")
    expect(
      requests.some(
        (request) =>
          request.method === "POST" &&
          request.url.endsWith("/tools/tool-1/tests")
      )
    ).toBe(true)

    fireEvent.click(screen.getByRole("button", { name: "发布" }))
    await waitFor(() => expect(messages).toContain("工具已发布"))
    expect(
      requests.some(
        (request) =>
          request.method === "POST" &&
          request.url.endsWith("/tools/tool-1/publish")
      )
    ).toBe(true)
  })

  test("does not publish edits when the server draft is missing", async () => {
    const requests: string[] = []
    const messages: string[] = []
    let getCount = 0
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const method = init?.method ?? "GET"
      requests.push(`${method} ${String(input)}`)
      if (method === "GET" && ++getCount > 1) {
        return jsonResponse({ ...detail, draft: null })
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "Unsaved formatter" },
    })
    fireEvent.click(screen.getByRole("button", { name: "发布" }))
    await waitFor(() =>
      expect(messages).toContain("工具草稿不存在，请重新加载后重试")
    )
    expect(
      requests.some((request) => request.endsWith("/tools/tool-1/publish"))
    ).toBe(false)
  })

  test("creates a new python tool from an empty form", async () => {
    const requests: Array<{ method: string; url: string; body?: unknown }> = []
    const messages: string[] = []
    let changed: ToolDetail | null = null
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
      if (method === "POST" && url.endsWith("/tools/python")) {
        return jsonResponse(createdDetail)
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={null}
        onChanged={(tool) => {
          changed = tool
        }}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByRole("heading", { name: "创建 Python 工具" })
    const createButton = screen.getByRole("button", {
      name: "创建",
    }) as HTMLButtonElement
    expect(createButton.disabled).toBe(true)

    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "My Tool" },
    })
    fireEvent.change(screen.getByLabelText("工具描述"), {
      target: { value: "Does things" },
    })
    fireEvent.click(screen.getAllByRole("button", { name: "高级 Schema" })[0]!)
    fireEvent.change(screen.getByLabelText("输入参数"), {
      target: {
        value:
          '{\n  "type": "object",\n  "properties": { "x": { "type": "string" } }\n}',
      },
    })
    fireEvent.click(screen.getAllByRole("button", { name: "高级 Schema" })[1]!)
    fireEvent.change(screen.getByLabelText("输出结果"), {
      target: { value: '{\n  "type": "object"\n}' },
    })
    fireEvent.change(screen.getByLabelText("Python 代码"), {
      target: { value: "result = inputs.get('x')" },
    })
    expect(createButton.disabled).toBe(false)

    fireEvent.click(createButton)
    await waitFor(() => expect(messages).toContain("Python 工具已创建"))
    expect((changed as ToolDetail | null)?.id).toBe("tool-new")
    const createRequest = requests.find(
      (request) =>
        request.method === "POST" && request.url.endsWith("/tools/python")
    )
    expect(createRequest?.body).toEqual({
      display_name: "My Tool",
      description: "Does things",
      input_schema: {
        type: "object",
        properties: { x: { type: "string" } },
      },
      output_schema: { type: "object" },
      code: "result = inputs.get('x')",
    })
    await screen.findByDisplayValue("My Tool")
    expect(screen.queryByText("创建 Python 工具")).toBeNull()
  })

  test("disables save/publish for invalid schemas and rejects malformed test arguments", async () => {
    const messages: string[] = []
    const requests: Array<{ method: string; url: string }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      requests.push({ method: init?.method ?? "GET", url })
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getAllByRole("button", { name: "高级 Schema" })[0]!)
    const inputSchema = screen.getByLabelText("输入参数")
    const saveButton = screen.getByRole("button", {
      name: "保存草稿",
    }) as HTMLButtonElement
    const publishButton = screen.getByRole("button", {
      name: "发布",
    }) as HTMLButtonElement
    expect(saveButton.disabled).toBe(false)

    fireEvent.change(inputSchema, { target: { value: "[1, 2]" } })
    expect(saveButton.disabled).toBe(true)
    expect(publishButton.disabled).toBe(true)

    fireEvent.change(inputSchema, { target: { value: "not-json" } })
    expect(saveButton.disabled).toBe(true)

    fireEvent.change(screen.getByLabelText("测试参数"), {
      target: { value: "not-json" },
    })
    fireEvent.click(screen.getByRole("button", { name: "运行测试" }))
    await waitFor(() => expect(messages).toContain("测试参数必须是 JSON 对象"))
    expect(
      requests.some(
        (request) => request.method === "POST" && request.url.endsWith("/tests")
      )
    ).toBe(false)
  })

  test("explains Agent and Workflow usage and edits simple parameters", async () => {
    const requests: Array<{ method: string; url: string; body?: unknown }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      requests.push({
        method: init?.method ?? "GET",
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (init?.method === "PUT") return jsonResponse(detail.draft)
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={() => undefined}
      />
    )

    await screen.findByText("这个工具怎么被调用")
    expect(screen.getByText("在 Agent 中")).toBeTruthy()
    expect(screen.getByText("在工作流中")).toBeTruthy()
    expect(screen.getByText("代码约定")).toBeTruthy()

    fireEvent.change(screen.getByLabelText("参数名称 1"), {
      target: { value: "source_text" },
    })
    const addButtons = screen.getAllByRole("button", { name: "添加参数" })
    fireEvent.click(addButtons[0]!)
    fireEvent.change(screen.getByLabelText("参数名称 2"), {
      target: { value: "summary" },
    })
    fireEvent.change(screen.getByLabelText("参数说明 2"), {
      target: { value: "要生成摘要的文本" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.method === "PUT" && request.url.endsWith("/draft")
        )
      ).toBe(true)
    )
    const saveRequest = requests.find(
      (request) => request.method === "PUT" && request.url.endsWith("/draft")
    )
    expect(
      (saveRequest?.body as { input_schema: Record<string, unknown> })
        .input_schema
    ).toMatchObject({
      properties: {
        source_text: {
          type: "string",
        },
        summary: {
          type: "string",
          description: "要生成摘要的文本",
        },
      },
      required: ["source_text"],
    })
  })

  test("labels an archived tool with its status", async () => {
    globalThis.fetch = (async () =>
      jsonResponse({
        ...detail,
        status: "archived",
      })) as unknown as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={() => undefined}
      />
    )

    await screen.findByDisplayValue("Formatter")
    expect(screen.getByText("已归档")).toBeTruthy()
  })

  test("disables an active tool after confirmation and can be cancelled", async () => {
    const requests: Array<{ method: string; url: string }> = []
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      requests.push({ method, url })
      if (method === "POST" && url.endsWith("/disable")) {
        return jsonResponse({ ...detail, status: "disabled" })
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "禁用" }))
    const dialog = await screen.findByRole("dialog", { name: "确认操作" })
    expect(dialog.textContent).toContain("禁用工具“Formatter”")
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )
    expect(
      requests.some(
        (request) =>
          request.method === "POST" && request.url.endsWith("/disable")
      )
    ).toBe(false)

    fireEvent.click(screen.getByRole("button", { name: "禁用" }))
    const confirmDialog = await screen.findByRole("dialog", {
      name: "确认操作",
    })
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "禁用" }))
    await waitFor(() => expect(messages).toContain("工具已禁用"))
    expect(
      requests.some(
        (request) =>
          request.method === "POST" && request.url.endsWith("/disable")
      )
    ).toBe(true)
    expect(screen.getByText("已停用")).toBeTruthy()
    expect(screen.getByRole("button", { name: "启用" })).toBeTruthy()
  })

  test("re-enables a disabled tool without confirmation", async () => {
    const requests: Array<{ method: string; url: string }> = []
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      requests.push({ method, url })
      if (method === "POST" && url.endsWith("/enable")) {
        return jsonResponse({ ...detail, status: "active" })
      }
      return jsonResponse({ ...detail, status: "disabled" })
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    expect(screen.getByText("已停用")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "启用" }))
    await waitFor(() => expect(messages).toContain("工具已启用"))
    expect(
      requests.some(
        (request) =>
          request.method === "POST" && request.url.endsWith("/enable")
      )
    ).toBe(true)
    expect(screen.getByRole("button", { name: "禁用" })).toBeTruthy()
  })

  test("archives a tool after confirmation and reports cancellation", async () => {
    const requests: Array<{ method: string; url: string }> = []
    const messages: string[] = []
    const archivedIds: string[] = []
    const openChanges: boolean[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      requests.push({ method, url })
      if (method === "DELETE") return jsonResponse(null, 204)
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={(next) => openChanges.push(next)}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={(toolId) => archivedIds.push(toolId)}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "归档" }))
    const dialog = await screen.findByRole("dialog", { name: "确认操作" })
    expect(dialog.textContent).toContain("归档工具“Formatter”")
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
    )
    expect(archivedIds).toEqual([])
    expect(requests.some((request) => request.method === "DELETE")).toBe(false)

    fireEvent.click(screen.getByRole("button", { name: "归档" }))
    const confirmDialog = await screen.findByRole("dialog", {
      name: "确认操作",
    })
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "归档" }))
    await waitFor(() => expect(messages).toContain("工具已归档"))
    expect(archivedIds).toEqual(["tool-1"])
    expect(openChanges).toContain(false)
    expect(
      requests.some(
        (request) =>
          request.method === "DELETE" && request.url.endsWith("/tools/tool-1")
      )
    ).toBe(true)
  })

  test("surfaces a revision conflict when saving a stale draft", async () => {
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      if (method === "PUT" && url.endsWith("/draft")) {
        return jsonResponse(
          { detail: "Revision conflict: draft has been updated" },
          409
        )
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "Formatter conflict" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))
    await waitFor(() =>
      expect(messages).toContain("Revision conflict: draft has been updated")
    )
  })

  test("reports a failed publish", async () => {
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      if (method === "POST" && url.endsWith("/publish")) {
        return jsonResponse({ detail: "publish rejected by policy" }, 403)
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "发布" }))
    await waitFor(() => expect(messages).toContain("资源不存在或无权访问"))
  })

  test("reports a failed test run", async () => {
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      if (method === "POST" && url.endsWith("/tests")) {
        return jsonResponse({ detail: "sandbox unavailable" }, 503)
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "运行测试" }))
    await waitFor(() => expect(messages).toContain("sandbox unavailable"))
  })

  test("polls a queued test until it reaches a terminal state", async () => {
    const messages: string[] = []
    let polls = 0
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      if (method === "POST" && url.endsWith("/tests")) {
        return jsonResponse(queuedInvocation, 202)
      }
      if (method === "GET" && url.includes("/tests/")) {
        polls += 1
        return jsonResponse(succeededInvocation)
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "运行测试" }))
    await screen.findByText("等待执行")
    await waitFor(() => expect(messages).toContain("工具测试通过"), {
      timeout: 3000,
    })
    await screen.findByText("运行成功")
    expect(polls).toBeGreaterThan(0)
  })

  test("shows the error surface of a failed test run", async () => {
    const messages: string[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      if (method === "POST" && url.endsWith("/tests")) {
        return jsonResponse(failedInvocation, 202)
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "运行测试" }))
    await screen.findByText("工具执行结果不确定")
    await waitFor(() => expect(messages).toContain("工具测试失败"))
    expect(
      screen.getByText(/The model could not determine the result/)
    ).toBeTruthy()
    expect(screen.getByText(/E_UNCERTAIN/)).toBeTruthy()
  })

  test("shows the raw status for an unknown tool status", async () => {
    globalThis.fetch = (async () =>
      jsonResponse({
        ...detail,
        status: "provisioning",
      })) as unknown as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={() => undefined}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={() => undefined}
      />
    )

    await screen.findByDisplayValue("Formatter")
    expect(screen.getByText("provisioning")).toBeTruthy()
  })

  test("reports a failed disable and keeps the dialog open", async () => {
    const messages: string[] = []
    const openChanges: boolean[] = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      if (method === "POST" && url.endsWith("/disable")) {
        return jsonResponse({ detail: "toggle failed" }, 500)
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={(next) => openChanges.push(next)}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={() => undefined}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "禁用" }))
    const dialog = await screen.findByRole("dialog", { name: "确认操作" })
    fireEvent.click(within(dialog).getByRole("button", { name: "禁用" }))
    await waitFor(() => expect(messages).toContain("toggle failed"))
    expect(screen.getByRole("button", { name: "禁用" })).toBeTruthy()
    expect(openChanges).toEqual([])
  })

  test("reports a failed archive and keeps the dialog open", async () => {
    const messages: string[] = []
    const openChanges: boolean[] = []
    const archivedIds: string[] = []
    globalThis.fetch = (async (
      _input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE") {
        return jsonResponse({ detail: "archive failed" }, 500)
      }
      return jsonResponse(detail)
    }) as typeof fetch

    renderPage(
      <PythonToolDialog
        open
        onOpenChange={(next) => openChanges.push(next)}
        token="token"
        workspaceId="ws-1"
        tool={summary}
        onChanged={() => undefined}
        onArchived={(toolId) => archivedIds.push(toolId)}
        onMessage={(_kind, message) => messages.push(message)}
      />
    )

    await screen.findByDisplayValue("Formatter")
    fireEvent.click(screen.getByRole("button", { name: "归档" }))
    const dialog = await screen.findByRole("dialog", { name: "确认操作" })
    fireEvent.click(within(dialog).getByRole("button", { name: "归档" }))
    await waitFor(() => expect(messages).toContain("archive failed"))
    expect(archivedIds).toEqual([])
    expect(openChanges).toEqual([])
    expect(screen.getByRole("button", { name: "归档" })).toBeTruthy()
  })
})

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
})

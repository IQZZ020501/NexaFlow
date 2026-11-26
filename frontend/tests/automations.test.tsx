/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { AutomationDetailPage } from "@/components/automations/automation-detail-page"
import { AutomationsPage } from "@/components/automations/automations-page"
import type {
  Automation,
  AutomationExecutionDetail,
} from "@/lib/api/automations"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  mockNextLink,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
  within,
} from "./helpers/dom"

const pushCalls: string[] = []
const replaceCalls: string[] = []
let currentSearch = ""

mockNextNavigation({
  params: { id: "auto-1" },
  get search() {
    return currentSearch
  },
  push: (href) => pushCalls.push(href),
  replace: (href) => replaceCalls.push(href),
})
mockNextLink()
mockUseSession()

function sampleAutomation(overrides: Partial<Automation> = {}): Automation {
  return {
    id: "auto-1",
    workspace_id: "ws-1",
    owner_user_id: "u-1",
    name: "每日日报机器人",
    description: "每天早上生成日报并归档",
    target_app_id: "app-1",
    target_app_name: "Helper Agent",
    target_app_type: "agent",
    publication_version_id: "ver-1",
    workflow_version_id: null,
    target_version_number: 2,
    approval_mode: "ask_risky",
    trigger_type: "daily",
    trigger_config: { hour: 9, minute: 0, timezone: "Asia/Shanghai" },
    input_config: {
      mode: "text",
      text: "生成今日简报",
      json_payload: {},
      webhook_input_path: null,
      webhook_prompt_template: null,
    },
    notification_config: {
      on_succeeded: true,
      on_failed: true,
      on_cancelled: true,
      on_awaiting_approval: true,
      on_awaiting_input: true,
    },
    webhook_hook_id: null,
    webhook_url: null,
    webhook_secret_hint: null,
    webhook_secret_updated_at: null,
    status: "active",
    config_revision: 1,
    next_run_at: "2026-11-25T01:00:00Z",
    last_triggered_at: "2026-11-24T01:00:00Z",
    missed_run_count: 0,
    latest_execution: {
      id: "exec-1",
      automation_id: "auto-1",
      workspace_id: "ws-1",
      trigger_source: "schedule",
      dedup_key: "daily:1:2026-11-24T01:00:00Z",
      config_revision: 1,
      scheduled_at: "2026-11-24T01:00:00Z",
      received_at: "2026-11-24T01:00:01Z",
      dispatched_at: "2026-11-24T01:00:02Z",
      dispatch_status: "dispatched",
      skip_reason: null,
      run_id: "run-1",
      run_status: "succeeded",
      missed_count_before: 0,
      created_at: "2026-11-24T01:00:01Z",
      updated_at: "2026-11-24T01:00:05Z",
    },
    created_at: "2026-11-20T00:00:00Z",
    updated_at: "2026-11-24T01:00:05Z",
    ...overrides,
  }
}

function sampleExecutionDetail(
  overrides: Partial<AutomationExecutionDetail> = {}
): AutomationExecutionDetail {
  return {
    id: "exec-1",
    automation_id: "auto-1",
    workspace_id: "ws-1",
    trigger_source: "schedule",
    dedup_key: "daily:1:2026-11-24T01:00:00Z",
    config_revision: 1,
    scheduled_at: "2026-11-24T01:00:00Z",
    received_at: "2026-11-24T01:00:01Z",
    dispatched_at: "2026-11-24T01:00:02Z",
    dispatch_status: "dispatched",
    skip_reason: null,
    run_id: "run-1",
    run_status: "awaiting_approval",
    missed_count_before: 2,
    created_at: "2026-11-24T01:00:01Z",
    updated_at: "2026-11-24T01:00:05Z",
    frozen_input: { message: "生成今日简报" },
    frozen_config: { trigger_type: "daily", version_number: 2 },
    agent_run: {
      id: "run-1",
      workspace_id: "ws-1",
      agent_id: "app-1",
      requested_by_user_id: "u-1",
      conversation_id: "conv-1",
      goal: "生成今日简报",
      model_id: "m-1",
      model_name: "GPT",
      status: "awaiting_approval",
      plan: [],
      events: [],
      result: "日报初稿已完成。",
      model_usage: {},
      last_error: null,
      planned_at: null,
      started_at: "2026-11-24T01:00:03Z",
      finished_at: null,
      created_at: "2026-11-24T01:00:01Z",
      updated_at: "2026-11-24T01:00:05Z",
      trace_id: "trace-1",
    },
    workflow_run: null,
    tool_calls: [
      {
        call_id: "call-1",
        turn: 1,
        tool_name: "send_report",
        tool_kind: "builtin",
        server_name: "",
        arguments: { target: "team" },
        status: "awaiting_approval",
        approval_required: true,
        last_error: null,
        approved_at: null,
        started_at: null,
        finished_at: null,
      },
    ],
    artifacts: [
      {
        artifact_id: "art-1",
        format: "csv",
        filename: "daily-report.csv",
        media_type: "text/csv",
        download_url: "/api/v1/artifacts/art-1/content",
        expires_at: "2026-11-25T01:00:00Z",
        size_bytes: 2048,
        relative_path: "reports/daily-report.csv",
      },
    ],
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  resetFetch()
  pushCalls.length = 0
  replaceCalls.length = 0
  currentSearch = ""
})

describe("Automations UI", () => {
  test("localizes skip reasons in the list and execution details", async () => {
    const reason = "Skipped because a previous run is still active."
    const detail = sampleExecutionDetail({
      dispatch_status: "skipped",
      skip_reason: reason,
      run_id: null,
      run_status: null,
      agent_run: null,
      workflow_run: null,
      tool_calls: [],
      artifacts: [],
    })
    const automation = sampleAutomation({ latest_execution: detail })
    withFetch((url) => {
      if (url.endsWith("/automations?limit=50&offset=0")) {
        return jsonResponse({
          items: [automation],
          total: 1,
          limit: 50,
          offset: 0,
        })
      }
      if (url.endsWith("/automations/auto-1")) return jsonResponse(automation)
      if (url.endsWith("/executions/exec-1")) return jsonResponse(detail)
      if (url.includes("/executions?")) {
        return jsonResponse({ items: [detail], total: 1, limit: 20, offset: 0 })
      }
      return jsonResponse([])
    })
    renderPage(<AutomationsPage />)
    expect(await screen.findByText("上一次任务尚未结束，本次已跳过")).toBeTruthy()
    expect(screen.queryByText(reason)).toBeNull()

    cleanup()
    currentSearch = "?execution=exec-1"
    renderPage(<AutomationDetailPage automationId="auto-1" />)
    expect(
      await screen.findAllByText("上一次任务尚未结束，本次已跳过")
    ).toHaveLength(2)
    expect(screen.queryByText(reason)).toBeNull()
  })

  test("lists automations, toggles pause, and triggers execute now", async () => {
    const initial = sampleAutomation()
    let pausedState = initial

    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (url.endsWith("/automations?limit=50&offset=0") && method === "GET") {
        return jsonResponse({
          items: [pausedState],
          total: 1,
          limit: 50,
          offset: 0,
        })
      }
      if (url.endsWith("/automations/auto-1/pause") && method === "POST") {
        pausedState = { ...pausedState, status: "paused" }
        return jsonResponse(pausedState)
      }
      if (url.endsWith("/automations/auto-1/execute") && method === "POST") {
        return jsonResponse(sampleExecutionDetail({ id: "exec-now" }))
      }
      return jsonResponse({ detail: `Unhandled ${method} ${url}` }, 404)
    })

    renderPage(<AutomationsPage />)

    expect(await screen.findByText("每日日报机器人")).toBeTruthy()
    expect(screen.getByText(/Helper Agent/)).toBeTruthy()
    expect(screen.getByText("每天定时")).toBeTruthy()
    expect(screen.getByText("已成功")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "暂停" }))
    await waitFor(() => expect(screen.getByText("已暂停")).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "立即执行" }))
    await waitFor(() =>
      expect(pushCalls).toContain("/app/automations/auto-1?execution=exec-now")
    )
  })

  test("opens prefilled create modal from app detail link and discloses one-time webhook secret", async () => {
    currentSearch = "?create=1&app_id=app-1"
    let createdBody: Record<string, unknown> | null = null

    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (url.endsWith("/automations?limit=50&offset=0")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 })
      }
      if (
        url.includes("/workspaces/ws-1/agents?") ||
        url.endsWith("/workspaces/ws-1/agents?limit=100&offset=0")
      ) {
        return jsonResponse({
          items: [
            {
              id: "app-1",
              workspace_id: "ws-1",
              name: "Helper Agent",
              description: "",
              app_type: "agent",
              published: true,
              status: "active",
              current_published_version_id: "ver-2",
              can_edit: true,
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        })
      }
      if (url.endsWith("/workspaces/ws-1/agents/app-1/versions")) {
        return jsonResponse({
          items: [
            {
              id: "ver-2",
              agent_id: "app-1",
              version_number: 2,
              published_by_user_id: "u-1",
              created_at: "2026-11-23T00:00:00Z",
            },
          ],
        })
      }
      if (url.endsWith("/workspaces/ws-1/automations") && method === "POST") {
        createdBody = JSON.parse(String(init?.body ?? "{}"))
        return jsonResponse({
          ...sampleAutomation({
            id: "auto-hook",
            name: String(createdBody?.name ?? "Webhook Task"),
            trigger_type: "webhook",
            webhook_hook_id: "hook-1",
            webhook_url: "https://example.test/api/v1/hooks/automations/hook-1",
            webhook_secret_hint: "whsec_...1234",
          }),
          webhook_secret: "whsec_secret_once_9999",
        })
      }
      return jsonResponse({ items: [], total: 0 }, 200)
    })

    renderPage(<AutomationsPage />)

    const dialog = await screen.findByRole("dialog")
    fireEvent.change(within(dialog).getByLabelText("名称"), {
      target: { value: "GitHub Push Webhook" },
    })

    fireEvent.pointerDown(within(dialog).getByLabelText("触发方式"))
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Webhook 事件" })
    )

    fireEvent.change(within(dialog).getByLabelText("任务提示词"), {
      target: { value: "总结本次事件" },
    })

    await waitFor(() =>
      expect(within(dialog).getByLabelText("发布版本").textContent).toContain(
        "v2"
      )
    )

    fireEvent.click(within(dialog).getByRole("button", { name: "创建" }))

    await waitFor(() => expect(createdBody).not.toBeNull())
    const submitted = createdBody as Record<string, unknown> | null
    expect(submitted?.target_app_id).toBe("app-1")
    expect(submitted?.publication_version_id).toBe("ver-2")
    expect(submitted?.trigger_type).toBe("webhook")

    expect(await screen.findByText("whsec_secret_once_9999")).toBeTruthy()
  })

  test("renders execution detail, approves pending tool call, submits workflow form, and downloads artifact with Bearer auth", async () => {
    currentSearch = "?execution=exec-1"
    const detail = sampleExecutionDetail({
      workflow_run: {
        id: "wrun-1",
        conversation_id: "conv-1",
        workspace_id: "ws-1",
        agent_id: "app-2",
        requested_by_user_id: "u-1",
        status: "awaiting_input",
        source: "published",
        definition_revision: 1,
        version_number: 1,
        graph_hash: "h",
        inputs: {},
        outputs: {},
        max_steps: 20,
        max_model_tokens: 4000,
        step_count: 1,
        token_usage: 0,
        last_error: null,
        trace_id: "trace-w",
        started_at: "2026-11-24T01:00:03Z",
        finished_at: null,
        created_at: "2026-11-24T01:00:01Z",
        updated_at: "2026-11-24T01:00:05Z",
        pending_form: {
          runtime_node_id: "node-form-1",
          content: "请补充审批备注",
          fields: [
            {
              variable: "note",
              name: "备注",
              type: "input",
              is_required: true,
              default_value: "",
              show_default_value: false,
              optionList: [],
            },
          ],
        },
      },
    })
    let currentDetail = detail
    const approvalRequests: boolean[] = []
    const formPayloads: Array<Record<string, unknown>> = []
    let artifactAuthHeader: string | null = null

    const origCreateObjectURL = URL.createObjectURL
    const origRevokeObjectURL = URL.revokeObjectURL
    URL.createObjectURL = () => "blob:mock-url"
    URL.revokeObjectURL = () => undefined

    try {
      withFetch((url, init) => {
        const method = init?.method ?? "GET"
        if (
          url.endsWith("/workspaces/ws-1/automations/auto-1") &&
          method === "GET"
        ) {
          return jsonResponse(
            sampleAutomation({
              trigger_type: "webhook",
              webhook_url:
                "https://example.test/api/v1/hooks/automations/hook-1",
              webhook_secret_hint: "whsec_...1234",
            })
          )
        }
        if (
          url.includes(
            "/workspaces/ws-1/automations/auto-1/executions?limit=50"
          )
        ) {
          return jsonResponse({
            items: [detail],
            total: 1,
            limit: 50,
            offset: 0,
          })
        }
        if (
          url.endsWith(
            "/workspaces/ws-1/automations/auto-1/executions/exec-1"
          ) &&
          method === "GET"
        ) {
          return jsonResponse(currentDetail)
        }
        if (url.endsWith("/tool-calls/call-1/approval") && method === "POST") {
          const parsed = JSON.parse(String(init?.body ?? "{}"))
          approvalRequests.push(Boolean(parsed.approve))
          currentDetail = sampleExecutionDetail({
            run_status: "running",
            tool_calls: [
              {
                ...detail.tool_calls[0]!,
                status: "succeeded",
              },
            ],
            workflow_run: detail.workflow_run,
          })
          return jsonResponse(currentDetail)
        }
        if (url.endsWith("/executions/exec-1/form") && method === "POST") {
          formPayloads.push(JSON.parse(String(init?.body ?? "{}")))
          currentDetail = sampleExecutionDetail({
            run_status: "succeeded",
            tool_calls: [],
            workflow_run: null,
          })
          return jsonResponse(currentDetail)
        }
        if (url.endsWith("/api/v1/artifacts/art-1/content")) {
          const headers = new Headers(init?.headers)
          artifactAuthHeader = headers.get("Authorization")
          return new Response("col1,col2\n1,2\n", {
            status: 200,
            headers: { "Content-Type": "text/csv" },
          })
        }
        return jsonResponse({ detail: `Unhandled ${method} ${url}` }, 404)
      })

      renderPage(<AutomationDetailPage />)

      expect(await screen.findByText("停机恢复跳过 2 次过期调度")).toBeTruthy()
      expect(screen.getByText("daily-report.csv")).toBeTruthy()
      expect(screen.getByText("whsec_...1234")).toBeTruthy()

      fireEvent.click(screen.getByRole("button", { name: "批准并执行" }))
      await waitFor(() => expect(approvalRequests).toEqual([true]))

      fireEvent.change(screen.getByLabelText(/备注/), {
        target: { value: "同意继续" },
      })
      fireEvent.click(screen.getByRole("button", { name: "提交表单" }))
      await waitFor(() =>
        expect(formPayloads).toEqual([
          { runtime_node_id: "node-form-1", form_data: { note: "同意继续" } },
        ])
      )

      fireEvent.click(screen.getByRole("button", { name: "下载产物" }))
      await waitFor(() => expect(artifactAuthHeader).toBe("Bearer test-token"))
    } finally {
      URL.createObjectURL = origCreateObjectURL
      URL.revokeObjectURL = origRevokeObjectURL
    }
  })
  test("preserves Sunday as ISO weekday seven when editing a weekly schedule", async () => {
    const automation = sampleAutomation({
      trigger_type: "weekly",
      trigger_config: { weekdays: [7], hour: 9, minute: 0 },
    })
    const submitted: Array<Record<string, unknown>> = []
    withFetch((url, init) => {
      if (url.includes("/automations?") && (init?.method ?? "GET") === "GET") {
        return jsonResponse({
          items: [automation],
          total: 1,
          limit: 50,
          offset: 0,
        })
      }
      if (url.endsWith("/agents/app-1/versions")) {
        return jsonResponse({
          items: [
            {
              id: "ver-1",
              version_number: 2,
              created_at: automation.created_at,
            },
          ],
        })
      }
      if (url.endsWith("/automations/auto-1") && init?.method === "PATCH") {
        submitted.push(JSON.parse(String(init.body)))
        return jsonResponse(automation)
      }
      return jsonResponse({}, 404)
    })
    renderPage(<AutomationsPage />)
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }))
    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog)
        .getByRole("button", { name: "周日" })
        .getAttribute("aria-pressed")
    ).toBe("true")
    fireEvent.click(within(dialog).getByRole("button", { name: "周一" }))
    await waitFor(() =>
      expect(within(dialog).getByLabelText("发布版本").textContent).toContain(
        "v2"
      )
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    await waitFor(() => expect(submitted).toHaveLength(1))
    expect(
      (submitted[0].trigger_config as { weekdays: number[] }).weekdays
    ).toEqual([1, 7])
  })

  test("switches between executions and configuration tabs without losing selection", async () => {
    currentSearch = "?execution=exec-1"
    const detail = sampleExecutionDetail()
    const automation = sampleAutomation({
      trigger_type: "webhook",
      webhook_url: "https://example.test/api/v1/hooks/automations/hook-1",
      webhook_secret_hint: "whsec_...1234",
      input_config: {
        mode: "text",
        text: "总结本次推送变更",
        json_payload: {},
        webhook_input_path: "data.message",
        webhook_prompt_template: "请分析：{{data.message}}",
      },
    })

    withFetch((url) => {
      if (url.endsWith("/automations/auto-1")) return jsonResponse(automation)
      if (url.includes("/executions?")) {
        return jsonResponse({ items: [detail], total: 1, limit: 50, offset: 0 })
      }
      if (url.endsWith("/executions/exec-1")) return jsonResponse(detail)
      return jsonResponse({}, 404)
    })

    renderPage(<AutomationDetailPage automationId="auto-1" />)
    expect(await screen.findByText("日报初稿已完成。")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "配置与接入" }))
    expect(await screen.findByText("运行策略")).toBeTruthy()
    expect(screen.getByText("按策略自动执行")).toBeTruthy()
    expect(screen.getByText("总结本次推送变更")).toBeTruthy()
    expect(screen.getByText(/hmac\.new/)).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: /执行记录/ }))
    expect(await screen.findByText("日报初稿已完成。")).toBeTruthy()
  })

  test("switches inspector sub-tabs to show expandable tool call inputs and errors", async () => {
    currentSearch = "?execution=exec-1"
    const detail = sampleExecutionDetail({
      run_status: "failed",
      tool_calls: [
        {
          call_id: "call-fail-1",
          turn: 1,
          tool_name: "bash",
          tool_kind: "builtin",
          server_name: "",
          arguments: { command: "cat report.txt" },
          status: "failed",
          approval_required: false,
          last_error: "Tool invocation deadline expired.",
          approved_at: null,
          started_at: "2026-11-24T01:00:03Z",
          finished_at: "2026-11-24T01:00:04Z",
        },
      ],
    })
    const automation = sampleAutomation()

    withFetch((url) => {
      if (url.endsWith("/automations/auto-1")) return jsonResponse(automation)
      if (url.includes("/executions?")) {
        return jsonResponse({ items: [detail], total: 1, limit: 50, offset: 0 })
      }
      if (url.endsWith("/executions/exec-1")) return jsonResponse(detail)
      return jsonResponse({}, 404)
    })

    renderPage(<AutomationDetailPage automationId="auto-1" />)
    expect(await screen.findByText("日报初稿已完成。")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: /执行过程/ }))
    const toolRowTrigger = await screen.findByRole("button", {
      name: /运行命令/,
    })
    fireEvent.click(toolRowTrigger)
    expect(await screen.findByText(/工具执行已超时/)).toBeTruthy()
    expect(screen.getByText(/cat report\.txt/)).toBeTruthy()
  })

  test("filters execution history list by status", async () => {
    const okExec = {
      ...sampleExecutionDetail({
        id: "exec-ok",
        run_status: "succeeded",
        scheduled_at: "2026-11-24T01:00:00Z",
      }),
    }
    const approvalExec = {
      ...sampleExecutionDetail({
        id: "exec-wait",
        run_status: "awaiting_approval",
        scheduled_at: "2026-11-24T02:00:00Z",
      }),
    }
    const failedExec = {
      ...sampleExecutionDetail({
        id: "exec-fail",
        run_status: "failed",
        scheduled_at: "2026-11-24T03:00:00Z",
      }),
    }

    withFetch((url) => {
      if (url.endsWith("/automations/auto-1")) {
        return jsonResponse(sampleAutomation())
      }
      if (url.includes("/executions?")) {
        return jsonResponse({
          items: [okExec, approvalExec, failedExec],
          total: 3,
          limit: 50,
          offset: 0,
        })
      }
      if (url.endsWith("/executions/exec-ok")) return jsonResponse(okExec)
      return jsonResponse({}, 404)
    })

    renderPage(<AutomationDetailPage automationId="auto-1" />)
    await screen.findByText("共 3 条")
    const sidebar = screen.getByText("执行历史").closest("aside")!
    expect(within(sidebar).getByText("已成功")).toBeTruthy()
    expect(within(sidebar).getByText("待审批")).toBeTruthy()
    expect(within(sidebar).getByText("已失败")).toBeTruthy()

    fireEvent.click(within(sidebar).getByRole("button", { name: /待处理/ }))
    expect(within(sidebar).getByText("待审批")).toBeTruthy()
    expect(within(sidebar).queryByText("已成功")).toBeNull()
    expect(within(sidebar).queryByText("已失败")).toBeNull()

    fireEvent.click(within(sidebar).getByRole("button", { name: /^失败/ }))
    expect(within(sidebar).getByText("已失败")).toBeTruthy()
    expect(within(sidebar).queryByText("待审批")).toBeNull()

    fireEvent.click(within(sidebar).getByRole("button", { name: "全部" }))
    expect(within(sidebar).getByText("已成功")).toBeTruthy()
  })

  test("renders preview button alongside download button for previewable artifacts", async () => {
    currentSearch = "?execution=exec-1"
    const detail = sampleExecutionDetail({
      artifacts: [
        {
          artifact_id: "11111111-1111-4111-8111-111111111111",
          format: "pdf",
          filename: "briefing.pdf",
          media_type: "application/pdf",
          download_url:
            "/api/v1/artifacts/11111111-1111-4111-8111-111111111111/content",
          expires_at: "2026-11-25T01:00:00Z",
          size_bytes: 4096,
          relative_path: "reports/briefing.pdf",
        },
      ],
    })

    withFetch((url) => {
      if (url.endsWith("/automations/auto-1")) {
        return jsonResponse(sampleAutomation())
      }
      if (url.includes("/executions?")) {
        return jsonResponse({ items: [detail], total: 1, limit: 50, offset: 0 })
      }
      if (url.endsWith("/executions/exec-1")) return jsonResponse(detail)
      return jsonResponse({}, 404)
    })

    renderPage(<AutomationDetailPage automationId="auto-1" />)
    expect(await screen.findByText("briefing.pdf")).toBeTruthy()
    expect(screen.getByRole("button", { name: "预览" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "下载产物" })).toBeTruthy()
  })

  test("renders clickable markdown, inline-code, bare URLs, and quick-jump project link cards", async () => {
    currentSearch = "?execution=exec-1"
    const base = sampleExecutionDetail()
    const detail = sampleExecutionDetail({
      agent_run: {
        ...base.agent_run!,
        result: [
          "### 今日热门项目",
          "- [awesome-agent](https://github.com/acme/awesome-agent) —— 开源 Agent 框架",
          "- 代码地址：`https://github.com/acme/runtime-kit`",
          "- 官方文档见 https://docs.acme.dev/guide/start。",
        ].join("\n"),
      },
    })

    withFetch((url) => {
      if (url.endsWith("/automations/auto-1")) {
        return jsonResponse(sampleAutomation())
      }
      if (url.includes("/executions?")) {
        return jsonResponse({ items: [detail], total: 1, limit: 50, offset: 0 })
      }
      if (url.endsWith("/executions/exec-1")) return jsonResponse(detail)
      return jsonResponse({}, 404)
    })

    renderPage(<AutomationDetailPage automationId="auto-1" />)
    expect(await screen.findByText("相关链接")).toBeTruthy()

    const links = screen.getAllByRole("link", { name: /awesome-agent/i })
    expect(links.length).toBeGreaterThanOrEqual(2)
    for (const anchor of links) {
      expect(anchor.getAttribute("href")).toBe(
        "https://github.com/acme/awesome-agent"
      )
      expect(anchor.getAttribute("target")).toBe("_blank")
    }

    const runtimeLinks = screen.getAllByRole("link", { name: /runtime-kit/i })
    expect(runtimeLinks.length).toBeGreaterThanOrEqual(2)
    expect(runtimeLinks[0]!.getAttribute("href")).toBe(
      "https://github.com/acme/runtime-kit"
    )

    const docLinks = screen.getAllByRole("link", {
      name: /docs\.acme\.dev\/guide\/start/i,
    })
    expect(docLinks.length).toBeGreaterThanOrEqual(2)
    expect(docLinks[0]!.getAttribute("href")).toBe(
      "https://docs.acme.dev/guide/start"
    )
  })

  test("upgrades plain-text domain citations when matching URLs exist in run events", async () => {
    currentSearch = "?execution=exec-1"
    const base = sampleExecutionDetail()
    const detail = sampleExecutionDetail({
      agent_run: {
        ...base.agent_run!,
        result:
          "- Google 发布 Gemini 4 Neon，定位为前沿级智能（blog.google）。\n- 未检索到的站点（unknown.example）保持原文。",
        events: [
          {
            type: "tool",
            turn: 1,
            tool_name: "tavily_search",
            status: "succeeded",
            summary: "搜索网页",
            call_id: "call-search-1",
            tool_label: "搜索网页",
            tool_kind: "builtin",
            server_name: "",
            input: { query: "Gemini 4 Neon" },
            output: {
              results: [
                {
                  title: "Gemini 4 Neon Announcement",
                  url: "https://blog.google/technology/ai/gemini-4-neon/",
                },
              ],
            },
            duration_ms: 320,
          },
        ],
      },
    })

    withFetch((url) => {
      if (url.endsWith("/automations/auto-1")) {
        return jsonResponse(sampleAutomation())
      }
      if (url.includes("/executions?")) {
        return jsonResponse({ items: [detail], total: 1, limit: 50, offset: 0 })
      }
      if (url.endsWith("/executions/exec-1")) return jsonResponse(detail)
      return jsonResponse({}, 404)
    })

    renderPage(<AutomationDetailPage automationId="auto-1" />)
    expect(await screen.findByText("相关链接")).toBeTruthy()

    const blogLinks = screen.getAllByRole("link", { name: /blog\.google/i })
    expect(blogLinks.length).toBeGreaterThanOrEqual(2)
    expect(blogLinks[0]!.getAttribute("href")).toBe(
      "https://blog.google/technology/ai/gemini-4-neon/"
    )
    expect(screen.queryByRole("link", { name: /unknown\.example/i })).toBeNull()
  })

  test("makes GitHub-style owner/repo project names directly clickable without matching non-repo pairs", async () => {
    currentSearch = "?execution=exec-1"
    const base = sampleExecutionDetail()
    const detail = sampleExecutionDetail({
      agent_run: {
        ...base.agent_run!,
        result: [
          "- **dream-num/univer** — TypeScript, 31.1k star。",
          "- **GoogleChrome/modern-web-guidance-src** — TypeScript, 9.9k。",
          "- **meta/astryx** — TypeScript, 31.8k。",
          "- **acme/demo-app** — 自托管项目。",
          "- 交互模式支持 **UI/UX** 与 **Agent/Workflow** 协同。",
        ].join("\n"),
        events: [
          {
            type: "tool",
            turn: 1,
            tool_name: "tavily_search",
            status: "succeeded",
            summary: "搜索网页",
            call_id: "call-repo-1",
            tool_label: "搜索网页",
            tool_kind: "builtin",
            server_name: "",
            input: { query: "acme demo-app" },
            output: {
              results: [
                {
                  title: "acme/demo-app",
                  url: "https://gitlab.com/acme/demo-app",
                },
              ],
            },
            duration_ms: 210,
          },
        ],
      },
    })

    withFetch((url) => {
      if (url.endsWith("/automations/auto-1")) {
        return jsonResponse(sampleAutomation())
      }
      if (url.includes("/executions?")) {
        return jsonResponse({ items: [detail], total: 1, limit: 50, offset: 0 })
      }
      if (url.endsWith("/executions/exec-1")) return jsonResponse(detail)
      return jsonResponse({}, 404)
    })

    renderPage(<AutomationDetailPage automationId="auto-1" />)
    expect(await screen.findByText("相关链接")).toBeTruthy()

    const univerLinks = screen.getAllByRole("link", {
      name: /dream-num\/univer/i,
    })
    expect(univerLinks.length).toBeGreaterThanOrEqual(2)
    expect(univerLinks[0]!.getAttribute("href")).toBe(
      "https://github.com/dream-num/univer"
    )
    expect(univerLinks[0]!.getAttribute("target")).toBe("_blank")

    const chromeLinks = screen.getAllByRole("link", {
      name: /GoogleChrome\/modern-web-guidance-src/i,
    })
    expect(chromeLinks[0]!.getAttribute("href")).toBe(
      "https://github.com/GoogleChrome/modern-web-guidance-src"
    )

    const astryxLinks = screen.getAllByRole("link", {
      name: /meta\/astryx/i,
    })
    expect(astryxLinks[0]!.getAttribute("href")).toBe(
      "https://github.com/meta/astryx"
    )

    const gitlabLinks = screen.getAllByRole("link", {
      name: /acme\/demo-app/i,
    })
    expect(gitlabLinks[0]!.getAttribute("href")).toBe(
      "https://gitlab.com/acme/demo-app"
    )

    expect(screen.queryByRole("link", { name: /UI\/UX/i })).toBeNull()
    expect(screen.queryByRole("link", { name: /Agent\/Workflow/i })).toBeNull()
  })
})

/* @jsxImportSource react */
import * as React from "react"
import { afterEach, beforeEach, expect, mock, test } from "bun:test"

import { ToolsCatalogTabs } from "@/components/tools/catalog-tabs"
import { ToolPicker } from "@/components/tools/tool-picker"
import { IntegrationOAuthCallbackPage } from "@/components/tools/integration-oauth-callback"
import { InlineToolApproval } from "@/components/agents/inline-tool-approval"
import {
  IntegrationsCatalog,
  IntegrationsPage,
} from "@/components/tools/integrations-page"
import { LanguageProvider } from "@/contexts/language-provider"
import type { Integration } from "@/lib/api/integrations"
import type { AgentToolCall } from "@/lib/api/agents"
import type { ToolSummary } from "@/lib/api/tools"
import { translate, type Language, type TFunction } from "@/i18n"
import { integrationToolName } from "@/lib/integrations"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  makeSession,
  mockNextImage,
  mockNextLink,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  withFetch,
  within,
} from "./helpers/dom"

const workspace = "11111111-1111-4111-8111-111111111111"
const state = `${workspace}.dida.${"s".repeat(43)}`
const navigation = { search: "", pathname: "/app/tools/integrations" }
const notifications: Array<[string, string]> = []
const session = makeSession({
  selectedWorkspaceId: workspace,
  notify: (kind: string, message: string) =>
    notifications.push([kind, message]),
})
mockUseSession(session)
mockNextNavigation(navigation)
mockNextImage()
mockNextLink()
const originalAssign = window.location.assign
const originalOpen = window.open
const requests: Array<{ url: string; method: string; body: unknown }> = []
let installations: Integration[]

beforeEach(() => {
  installations = ["dida", "feishu", "tencent_meeting"].map((provider) => ({
    provider,
    status: "disconnected",
    configured: true,
    expires_at: null,
    source_id: null,
  })) as Integration[]
  requests.length = 0
  notifications.length = 0
  navigation.search = ""
  session.selectedWorkspaceId = workspace
  window.location.assign = mock(() => {})
  window.open = mock(() => null)
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    requests.push({
      url,
      method,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    })
    if (url.endsWith("/authorize"))
      return jsonResponse({
        authorization_url:
          "https://dida365.com/oauth/authorize?client_id=application",
        state,
        mode: "redirect",
        poll_seconds: 5,
      })
    if (url.endsWith("/callback"))
      return jsonResponse({
        ...installations[0],
        status: "connected",
        source_id: "source",
      })
    if (method === "DELETE") {
      const provider = url.split("/").at(-1)
      installations = installations.map((entry) =>
        entry.provider === provider
          ? { ...entry, status: "disconnected", source_id: null }
          : entry
      )
      return jsonResponse(
        installations.find((entry) => entry.provider === provider)
      )
    }
    if (url.endsWith("/application"))
      return jsonResponse({
        client_id: "existing-client",
        has_client_secret: true,
        scopes: ["tasks:read", "tasks:write"],
        redirect_uri:
          "https://nexaflow.example/app/tools/integrations/callback",
      })
    if (url.endsWith("/sync"))
      return jsonResponse(
        installations.find((entry) => entry.provider === url.split("/").at(-2))
      )
    return jsonResponse(installations)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  window.location.assign = originalAssign
  window.open = originalOpen
})

function catalog(canConfigure = false) {
  return renderPage(
    <IntegrationsCatalog
      token="token"
      workspaceId={workspace}
      canConfigure={canConfigure}
    />
  )
}

async function card(name = "滴答清单") {
  return await screen.findByRole("article", { name })
}

test("places a stable integration link to the right of MCP without authorizing anything by default", async () => {
  const changed = mock(() => {})
  const view = renderPage(
    <ToolsCatalogTabs activeKind="builtin" onKindChange={changed} />
  )
  const controls = Array.from(
    screen.getByRole("group", { name: "工具" }).children
  )
  expect(controls.map((control) => control.textContent)).toEqual([
    "技能",
    "MCP",
    "集成",
  ])
  expect(screen.getByRole("link", { name: "集成" }).getAttribute("href")).toBe(
    "/app/tools/integrations"
  )
  fireEvent.click(screen.getByRole("button", { name: "MCP" }))
  expect(changed).toHaveBeenCalledWith("mcp")
  view.unmount()
  catalog()
  await card()
  expect(screen.getAllByText("未安装")).toHaveLength(3)
  expect(requests[0]?.url).toBe(`/api/v1/workspaces/${workspace}/integrations`)
  expect(requests.every((request) => request.method === "GET")).toBe(true)
})

test("installation starts platform authorization and stays uninstalled until a verified callback", async () => {
  catalog()
  fireEvent.click(within(await card()).getByRole("button", { name: "安装" }))
  await waitFor(() => expect(window.location.assign).toHaveBeenCalledTimes(1))
  expect(window.location.assign).toHaveBeenCalledWith(
    "https://dida365.com/oauth/authorize?client_id=application"
  )
  expect(requests.filter((request) => request.method === "POST")).toHaveLength(
    1
  )
  expect(requests.find((request) => request.method === "POST")?.url).toBe(
    `/api/v1/workspaces/${workspace}/integrations/dida/authorize`
  )
  expect(within(await card()).getByText("未安装")).toBeTruthy()
  expect(screen.queryByText("已安装")).toBeNull()
})

test("an authorization failure leaves installation state unchanged", async () => {
  const fetch = globalThis.fetch
  globalThis.fetch = (async (input, init) =>
    String(input).endsWith("/authorize")
      ? jsonResponse(
          {
            detail: "Integration authorization failed. Please authorize again.",
          },
          502
        )
      : fetch(input, init)) as typeof fetch
  catalog()
  fireEvent.click(within(await card()).getByRole("button", { name: "安装" }))
  await waitFor(() =>
    expect(notifications).toEqual([["error", "平台授权失败，请重新安装。"]])
  )
  expect(window.location.assign).not.toHaveBeenCalled()
  expect(
    within(await card())
      .getByRole("button", { name: "安装" })
      .hasAttribute("disabled")
  ).toBe(false)
})

test("reload reads the persisted installation and uninstall waits for confirmation and server success", async () => {
  installations[0] = {
    ...installations[0]!,
    status: "connected",
    source_id: "source",
  }
  const view = catalog()
  expect(within(await card()).getByText("已安装")).toBeTruthy()
  view.unmount()
  catalog()
  fireEvent.click(within(await card()).getByRole("button", { name: "卸载" }))
  const dialog = await screen.findByRole("dialog", { name: "卸载 滴答清单？" })
  expect(requests.some((request) => request.method === "DELETE")).toBe(false)
  fireEvent.click(within(dialog).getByRole("button", { name: "卸载" }))
  await waitFor(() =>
    expect(
      within(screen.getByRole("article", { name: "滴答清单" })).getByText(
        "未安装"
      )
    ).toBeTruthy()
  )
  expect(
    requests.filter((request) => request.method === "DELETE")
  ).toHaveLength(1)
})

test("failed uninstall keeps the existing installation visible", async () => {
  installations[0] = {
    ...installations[0]!,
    status: "connected",
    source_id: "source",
  }
  const fetch = globalThis.fetch
  globalThis.fetch = (async (input, init) =>
    init?.method === "DELETE"
      ? jsonResponse({ detail: "Integration response was unavailable." }, 502)
      : fetch(input, init)) as typeof fetch
  catalog()
  fireEvent.click(within(await card()).getByRole("button", { name: "卸载" }))
  fireEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "卸载",
    })
  )
  await waitFor(() => expect(notifications.length).toBe(1))
  expect(within(await card()).getByText("已安装")).toBeTruthy()
})

test("members get configuration guidance while administrators can save an application without installing it", async () => {
  installations[0] = { ...installations[0]!, configured: false }
  const view = catalog()
  fireEvent.click(within(await card()).getByRole("button", { name: "安装" }))
  expect(notifications).toEqual([
    ["error", "请联系空间管理员配置此集成的开发者应用。"],
  ])
  expect(screen.queryByRole("button", { name: "配置 滴答清单" })).toBeNull()
  view.unmount()
  catalog(true)
  fireEvent.click(within(await card()).getByRole("button", { name: "安装" }))
  const clientId = await screen.findByLabelText("应用 Client ID")
  await waitFor(() =>
    expect((clientId as HTMLInputElement).value).toBe("existing-client")
  )
  expect(
    (screen.getByLabelText("应用 Client Secret") as HTMLInputElement).value
  ).toBe("")
  fireEvent.change(clientId, { target: { value: "new-client" } })
  fireEvent.change(screen.getByLabelText("应用 Client Secret"), {
    target: { value: "new-private-secret" },
  })
  fireEvent.submit(clientId.closest("form")!)
  await waitFor(() =>
    expect(requests.some((request) => request.method === "PUT")).toBe(true)
  )
  expect(requests.find((request) => request.method === "PUT")?.body).toEqual({
    client_id: "new-client",
    client_secret: "new-private-secret",
    scopes: ["tasks:read", "tasks:write"],
  })
  expect(window.location.assign).not.toHaveBeenCalled()
  expect(screen.queryByText("已安装")).toBeNull()
})

test("a completed request from the previous workspace cannot redirect the current account context", async () => {
  let resolveAuthorization!: (response: Response) => void
  const fetch = globalThis.fetch
  globalThis.fetch = ((input, init) =>
    String(input).endsWith("/authorize")
      ? new Promise<Response>((resolve) => {
          resolveAuthorization = resolve
        })
      : fetch(input, init)) as typeof fetch
  const view = renderPage(<IntegrationsPage />)
  fireEvent.click(within(await card()).getByRole("button", { name: "安装" }))
  session.selectedWorkspaceId = "22222222-2222-4222-8222-222222222222"
  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      <IntegrationsPage />
    </LanguageProvider>
  )
  await card()
  resolveAuthorization(
    jsonResponse({
      authorization_url: "https://dida365.com/oauth/authorize",
      state,
      mode: "redirect",
      poll_seconds: 5,
    })
  )
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(window.location.assign).not.toHaveBeenCalled()
})

test("device authorization is pending until the provider confirms it, and can be cancelled", async () => {
  const fetch = globalThis.fetch
  globalThis.fetch = (async (input, init) =>
    String(input).endsWith("/authorize")
      ? jsonResponse({
          authorization_url:
            "https://meeting.tencent.com/marketplace/tencentmeeting-cli-auth.html?code=user-code",
          state: `${workspace}.tencent_meeting.${"s".repeat(43)}`,
          mode: "device",
          poll_seconds: 5,
        })
      : fetch(input, init)) as typeof fetch
  catalog()
  fireEvent.click(
    within(await card("腾讯会议")).getByRole("button", { name: "安装" })
  )
  const dialog = await screen.findByRole("dialog", { name: "安装 腾讯会议" })
  expect(within(dialog).getByText("等待平台授权")).toBeTruthy()
  expect(
    within(dialog).getByRole("link", { name: "前往授权" }).getAttribute("rel")
  ).toBe("noopener noreferrer")
  fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
  await waitFor(() =>
    expect(requests.some((request) => request.method === "DELETE")).toBe(true)
  )
  expect(within(await card("腾讯会议")).getByText("未安装")).toBeTruthy()
  expect(requests.some((request) => request.url.endsWith("/callback"))).toBe(
    false
  )
})

test("the callback exchanges a code once under StrictMode and removes it from the URL", async () => {
  navigation.search = `state=${state}&code=temporary-code`
  window.history.replaceState(
    null,
    "",
    `/app/tools/integrations/callback?${navigation.search}`
  )
  renderPage(
    <React.StrictMode>
      <IntegrationOAuthCallbackPage />
    </React.StrictMode>
  )
  await screen.findByText("授权完成，集成已安装。")
  expect(
    requests.filter((request) => request.url.endsWith("/callback"))
  ).toHaveLength(1)
  expect(window.location.search).toBe("")
  expect(
    screen.getByRole("link", { name: "返回集成" }).getAttribute("href")
  ).toBe("/app/tools/integrations")
})

test("denied platform authorization never reports an installation or exchanges a code", async () => {
  navigation.search = `state=${state}&error=access_denied`
  renderPage(<IntegrationOAuthCallbackPage />)
  await screen.findByRole("alert")
  expect(screen.queryByText("授权完成，集成已安装。")).toBeNull()
  expect(requests).toHaveLength(0)
})

test("search matches translated integration names", async () => {
  catalog()
  await card()
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "飞书" } })
  expect(screen.getAllByRole("article")).toHaveLength(1)
  expect(screen.getByRole("article", { name: "飞书" })).toBeTruthy()
})

test("installed integration operations are selectable as one localized Agent capability", async () => {
  const tools: ToolSummary[] = ["list_projects", "create_task"].map(
    (operation, index) => ({
      id: `operation-${index}`,
      workspace_id: workspace,
      kind: "integration",
      function_name: `dida_${operation}_${"a".repeat(32)}`,
      display_name: `Dida365: ${operation}`,
      description: "Provider operation",
      current_version_id: `version-${index}`,
      status: "active",
      availability: "available",
      source: {
        id: "source",
        name: "Dida365",
        kind: "integration",
        transport: null,
      },
      created_by_user_id: "u-1",
      permission: "owner",
      can_view: true,
      can_use: true,
      can_manage: true,
    })
  )
  withFetch(() => jsonResponse(tools))
  const changed = mock(() => {})
  renderPage(
    <ToolPicker
      open
      onOpenChange={() => {}}
      token="token"
      workspaceId={workspace}
      value={[]}
      onChange={changed}
    />
  )
  const checkbox = await screen.findByRole("checkbox", { name: "滴答清单" })
  expect(screen.getAllByRole("checkbox")).toHaveLength(1)
  fireEvent.click(checkbox)
  expect(changed).toHaveBeenCalledWith([
    { tool_id: "operation-0", version_id: "version-0" },
    { tool_id: "operation-1", version_id: "version-1" },
  ])
  expect(screen.queryByText("Dida365: create_task")).toBeNull()
})

test("integration operation labels follow all three interface languages", () => {
  for (const [language, expected] of [
    ["zh-Hans", "发送飞书消息"],
    ["zh-Hant", "傳送飛書訊息"],
    ["en", "Send Feishu message"],
  ] as const) {
    const t: TFunction = (key, values) =>
      translate(language as Language, key, values)
    expect(
      integrationToolName(`feishu_send_message_${"a".repeat(32)}`, t)
    ).toBe(expected)
  }
})

test("installed Tencent accounts can update tools without starting platform authorization", async () => {
  installations[2] = {
    ...installations[2]!,
    status: "connected",
    source_id: "tencent-source",
  }
  catalog()
  const meeting = within(await card("腾讯会议"))
  expect(
    meeting.getByText(
      "管理会议、受邀成员和录制，读取纪要、转写及参会报告，查询通讯录并执行会中控制。"
    )
  ).toBeTruthy()
  fireEvent.click(meeting.getByRole("button", { name: "更新工具" }))
  await waitFor(() =>
    expect(notifications).toEqual([
      ["success", "工具已更新，请在 Agent 中取消并重新勾选此集成，然后保存。"],
    ])
  )
  expect(requests.filter((request) => request.method === "POST")).toEqual([
    {
      url: `/api/v1/workspaces/${workspace}/integrations/tencent_meeting/sync`,
      method: "POST",
      body: null,
    },
  ])
  expect(meeting.getByText("已安装")).toBeTruthy()
  expect(window.open).not.toHaveBeenCalled()
  expect(window.location.assign).not.toHaveBeenCalled()
  expect(
    within(await card("滴答清单")).queryByRole("button", { name: "更新工具" })
  ).toBeNull()
})

test("failed catalog updates preserve the account and show a translated error", async () => {
  installations[2] = {
    ...installations[2]!,
    status: "connected",
    source_id: "tencent-source",
  }
  const fetch = globalThis.fetch
  globalThis.fetch = (async (input, init) =>
    String(input).endsWith("/sync")
      ? jsonResponse(
          {
            detail:
              "Integration is not installed for this user. Please install again.",
          },
          409
        )
      : fetch(input, init)) as typeof fetch
  catalog()
  const meeting = within(await card("腾讯会议"))
  fireEvent.click(meeting.getByRole("button", { name: "更新工具" }))
  await waitFor(() =>
    expect(notifications).toEqual([
      ["error", "当前用户尚未安装此集成，请重新安装。"],
    ])
  )
  expect(meeting.getByText("已安装")).toBeTruthy()
  expect(
    meeting.getByRole("button", { name: "更新工具" }).hasAttribute("disabled")
  ).toBe(false)
})

test("approval cards localize integration names and authorization errors while preserving the call ID", () => {
  const call: AgentToolCall = {
    call_id: "approval-call",
    turn: 1,
    tool_name: `tencent_meeting_list_meetings_${"a".repeat(32)}`,
    tool_kind: "integration",
    server_name: "Tencent Meeting",
    arguments: {},
    status: "awaiting_approval",
    approval_required: true,
    last_error: "Integration authorization expired. Please install again.",
    approved_at: null,
    started_at: null,
    finished_at: null,
  }
  for (const language of ["zh-Hans", "zh-Hant", "en"] as const) {
    const t: TFunction = (key, values) => translate(language, key, values)
    const decision = mock(() => {})
    const view = renderPage(
      <InlineToolApproval
        runId="run"
        call={call}
        resolvingCallId={null}
        onDecision={decision}
        t={t}
      />
    )
    expect(
      screen.getByText(`${t("查看腾讯会议列表")} @ ${t("腾讯会议")}`)
    ).toBeTruthy()
    expect(screen.queryByText(call.tool_name, { exact: false })).toBeNull()
    expect(screen.getByText(t("集成授权已过期，请重新认证。"))).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: t("批准并执行") }))
    expect(decision).toHaveBeenCalledWith("approval-call", "approve")
    view.unmount()
  }
})

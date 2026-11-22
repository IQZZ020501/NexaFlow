/* @jsxImportSource react */
import * as React from "react"
import { afterEach, expect, test } from "bun:test"
import { McpConnectionDialog } from "@/components/tools/mcp-source-dialog"
import { McpOAuthDialog } from "@/components/tools/mcp-oauth"
import { McpOAuthCallbackPage } from "@/components/tools/mcp-oauth-callback"
import { McpLongTasksDialog } from "@/components/tools/mcp-long-tasks"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

const workspace = "11111111-1111-4111-8111-111111111111"
const server = "22222222-2222-4222-8222-222222222222"
const state = `${workspace}.${server}.${"s".repeat(43)}`
const messages: Array<[string, string]> = []
const onMessage = (kind: string, message: string) => {
  messages.push([kind, message])
}
mockNextNavigation({ search: `state=${state}&code=temporary-code` })
mockUseSession()
afterEach(() => {
  cleanup()
  resetFetch()
  messages.length = 0
})
const configuration = {
  authorization_endpoint: "https://provider.example/authorize",
  token_endpoint: "https://provider.example/token",
  revocation_endpoint: "https://provider.example/revoke",
  client_id: "client",
  client_auth_method: "none",
  scopes: [],
}

test("long task configuration preserves other contracts when enabling and removing a tool", async () => {
  const old = {
    status_tool: "status",
    result_tool: "result",
    cancel_tool: "cancel",
    poll_seconds: 3,
  }
  const bodies: Array<{ contracts: Record<string, typeof old> }> = []
  withFetch((_url, init) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(init.body as string)
      bodies.push(body)
      return jsonResponse({
        tools: ["submit", "status", "result", "cancel"],
        contracts: body.contracts,
      })
    }
    return jsonResponse({
      tools: ["submit", "status", "result", "cancel"],
      contracts: { retained: old },
    })
  })
  renderPage(
    <McpLongTasksDialog
      onMessage={onMessage}
      token="test-token"
      workspaceId={workspace}
      serverId={server}
      onClose={() => {}}
      onChanged={() => {}}
    />
  )
  await screen.findByLabelText("提交任务工具")
  fireEvent.change(screen.getByLabelText("提交任务工具"), {
    target: { value: "submit" },
  })
  for (const [label, value] of [
    ["状态查询工具", "status"],
    ["结果读取工具", "result"],
    ["取消任务工具", "cancel"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } })
  fireEvent.submit(screen.getByLabelText("提交任务工具").closest("form")!)
  await waitFor(() => expect(bodies.length).toBe(1))
  expect(bodies[0].contracts).toEqual({ retained: old, submit: old })
  fireEvent.click(await screen.findByRole("button", { name: "恢复普通调用" }))
  await waitFor(() => expect(bodies.length).toBe(2))
  expect(bodies[1].contracts).toEqual({ retained: old })
  expect(messages).toEqual([
    ["success", "长任务契约已保存"],
    ["success", "已恢复普通调用"],
  ])
})

test("OAuth create sends registered endpoints and clears the old bearer credential", async () => {
  const submitted: unknown[] = []
  renderPage(
    <McpConnectionDialog
      open
      canUsePrivileged
      onOpenChange={() => {}}
      onSubmit={async (value) => {
        submitted.push(value)
      }}
      onError={(message) => {
        throw new Error(message)
      }}
    />
  )
  fireEvent.change(screen.getByLabelText("名称"), {
    target: { value: "Connector" },
  })
  fireEvent.change(screen.getByLabelText("MCP 地址"), {
    target: { value: "https://mcp.example/mcp" },
  })
  fireEvent.change(screen.getByLabelText("Bearer Token（可选）"), {
    target: { value: "old-token" },
  })
  fireEvent.change(screen.getByLabelText("认证方式"), {
    target: { value: "oauth" },
  })
  for (const [label, value] of [
    ["授权地址", configuration.authorization_endpoint],
    ["令牌地址", configuration.token_endpoint],
    ["撤销地址", configuration.revocation_endpoint],
    ["客户端 ID", configuration.client_id],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } })
  fireEvent.submit(screen.getByLabelText("MCP 地址").closest("form")!)
  await waitFor(() => expect(submitted.length).toBe(1))
  expect(submitted[0]).toEqual({
    name: "Connector",
    url: "https://mcp.example/mcp",
    transport: "streamable_http",
    oauth: configuration,
  })
})

test("failed long task saves show an error without reporting success", async () => {
  withFetch((_url, init) =>
    init?.method === "PUT"
      ? jsonResponse({ detail: "contract rejected" }, 409)
      : jsonResponse({
          tools: ["submit", "status", "result", "cancel"],
          contracts: {},
        })
  )
  renderPage(
    <McpLongTasksDialog
      token="test"
      workspaceId={workspace}
      serverId={server}
      onClose={() => {}}
      onChanged={() => {}}
      onMessage={onMessage}
    />
  )
  fireEvent.change(await screen.findByLabelText("提交任务工具"), {
    target: { value: "submit" },
  })
  fireEvent.submit(screen.getByLabelText("提交任务工具").closest("form")!)
  await screen.findByRole("alert")
  expect(messages).toEqual([["error", "contract rejected"]])
})

test("OAuth configuration changes must be saved before authorization", async () => {
  const saved: unknown[] = []
  withFetch((url, init) => {
    expect(new Headers(init?.headers).get("Authorization")).toBe(
      "Bearer private-token"
    )
    expect(url).toBe(
      `/api/v1/workspaces/${workspace}/mcp-servers/${server}/oauth`
    )
    if (init?.method === "PUT") {
      const value = JSON.parse(init.body as string)
      saved.push(value)
      const publicConfiguration = { ...value }
      delete publicConfiguration.client_secret
      return jsonResponse({
        status: "disconnected",
        configuration: publicConfiguration,
        expires_at: null,
      })
    }
    return jsonResponse({
      status: "disconnected",
      configuration,
      expires_at: null,
    })
  })
  renderPage(
    <McpOAuthDialog
      onMessage={onMessage}
      token="private-token"
      workspaceId={workspace}
      serverId={server}
      onClose={() => {}}
      onChanged={() => {}}
    />
  )
  const connect = await screen.findByRole("button", { name: "前往授权" })
  expect((connect as HTMLButtonElement).disabled).toBe(false)
  fireEvent.change(screen.getByLabelText("客户端 ID"), {
    target: { value: "new-client" },
  })
  expect((connect as HTMLButtonElement).disabled).toBe(true)
  fireEvent.submit(screen.getByLabelText("客户端 ID").closest("form")!)
  await waitFor(() => expect(saved.length).toBe(1))
  await waitFor(() =>
    expect((connect as HTMLButtonElement).disabled).toBe(false)
  )
  expect(saved[0]).toMatchObject({ client_id: "new-client" })
  expect(messages).toEqual([["success", "OAuth 配置已保存"]])
})

test("disconnecting OAuth reports success only after the server confirms", async () => {
  withFetch((_url, init) =>
    jsonResponse({
      status: init?.method === "DELETE" ? "disconnected" : "connected",
      configuration,
      expires_at: null,
    })
  )
  renderPage(
    <McpOAuthDialog
      token="test"
      workspaceId={workspace}
      serverId={server}
      onClose={() => {}}
      onChanged={() => {}}
      onMessage={onMessage}
    />
  )
  fireEvent.click(await screen.findByRole("button", { name: "断开连接" }))
  await waitFor(() =>
    expect(messages).toEqual([["success", "OAuth 连接已断开"]])
  )
})

test("failed OAuth saves show an error without a success notification", async () => {
  withFetch((_url, init) =>
    init?.method === "PUT"
      ? jsonResponse({ detail: "configuration rejected" }, 409)
      : jsonResponse({
          status: "disconnected",
          configuration,
          expires_at: null,
        })
  )
  renderPage(
    <McpOAuthDialog
      token="test"
      workspaceId={workspace}
      serverId={server}
      onClose={() => {}}
      onChanged={() => {}}
      onMessage={onMessage}
    />
  )
  fireEvent.click(await screen.findByRole("button", { name: "保存配置" }))
  await screen.findByRole("alert")
  expect(messages).toEqual([["error", "configuration rejected"]])
})

test("OAuth callback exchanges once under StrictMode and removes callback secrets from the URL", async () => {
  let exchanges = 0,
    discoveries = 0
  window.history.replaceState(
    null,
    "",
    `/app/mcp/oauth/callback?state=${state}&code=temporary-code`
  )
  withFetch((url, init) => {
    if (url.endsWith("/oauth/callback")) {
      exchanges++
      expect(JSON.parse(init?.body as string)).toEqual({
        state,
        code: "temporary-code",
      })
      expect(url).toContain(`/workspaces/${workspace}/mcp-servers/${server}/`)
      return jsonResponse({
        status: "connected",
        configuration,
        expires_at: null,
      })
    }
    if (url.endsWith("/refresh")) {
      discoveries++
      return jsonResponse({ id: server })
    }
    throw new Error(`Unexpected request ${url}`)
  })
  renderPage(
    <React.StrictMode>
      <McpOAuthCallbackPage />
    </React.StrictMode>
  )
  await screen.findByText("授权已完成，工具已刷新。")
  expect(exchanges).toBe(1)
  expect(discoveries).toBe(1)
  expect(window.location.search).toBe("")
})

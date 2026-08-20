/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"

import { SmtpSettingsPage } from "@/components/system/smtp-settings-page"
import type { MeResponse } from "@/lib/api/auth"
import type { SmtpSettings } from "@/lib/api/system"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  makeSession,
  mockNextLink,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

const session = makeSession()
mockUseSession(session)
const replaced: string[] = []
mockNextNavigation({
  pathname: "/system/email",
  replace: (href: string) => replaced.push(href),
})
mockNextLink()

const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  notify: (kind: "success" | "error", message: string) => void
}
const adminMe = session.me as MeResponse

const settings: SmtpSettings = {
  host: "smtp.example.com",
  port: 587,
  username: "mailer",
  security: "starttls",
  from_email: "noreply@example.com",
  from_name: "NexaFlow",
  enabled: true,
  timeout_seconds: 10,
  has_password: true,
  password_hint: "****word",
  configured: true,
  site_url: "https://nexaflow.example.com",
  identity_configured: true,
  updated_at: "2026-08-20T00:00:00Z",
}

const notifications: Array<[string, string]> = []

beforeEach(() => {
  notifications.length = 0
  replaced.length = 0
  sessionState.me = adminMe
  sessionState.token = "test-token"
  sessionState.notify = (kind, message) => notifications.push([kind, message])
})

afterEach(() => {
  cleanup()
  resetFetch()
})

describe("SMTP settings extra", () => {
  test("shows a retryable error when settings cannot be loaded", async () => {
    let fails = true
    withFetch(() => {
      if (fails) return jsonResponse({ detail: "smtp offline" }, 503)
      return jsonResponse(settings)
    })

    renderPage(<SmtpSettingsPage />)

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy())
    expect(screen.getByText("smtp offline")).toBeTruthy()
    expect(notifications).toContainEqual(["error", "smtp offline"])
    expect(screen.queryByLabelText("SMTP 主机")).toBeNull()

    fails = false
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    await waitFor(() =>
      expect(screen.getByDisplayValue("smtp.example.com")).toBeTruthy()
    )
    expect(screen.queryByRole("alert")).toBeNull()
  })

  test("stops submission when the port fails native validation", async () => {
    let patchRequests = 0
    withFetch((url, init) => {
      if (url === "/api/v1/admin/smtp" && init?.method === "PATCH") {
        patchRequests += 1
        return jsonResponse(settings)
      }
      return jsonResponse(settings)
    })

    renderPage(<SmtpSettingsPage />)
    await waitFor(() =>
      expect(screen.getByDisplayValue("smtp.example.com")).toBeTruthy()
    )
    fireEvent.change(screen.getByLabelText("端口"), {
      target: { value: "70000" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存 SMTP 配置" }))

    await waitFor(() =>
      expect(screen.queryByRole("alert")).toBeNull()
    )
    expect(patchRequests).toBe(0)
  })

  test("rejects a zero timeout with a validation message", async () => {
    withFetch(() => jsonResponse(settings))

    renderPage(<SmtpSettingsPage />)
    await waitFor(() =>
      expect(screen.getByDisplayValue("smtp.example.com")).toBeTruthy()
    )
    fireEvent.change(screen.getByLabelText("连接超时（秒）"), {
      target: { value: "0" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存 SMTP 配置" }))

    await waitFor(() =>
      expect(
        screen.getByText("超时时间必须大于 0 且不超过 120 秒")
      ).toBeTruthy()
    )
  })

  test("reports a save failure on the form and through the notification", async () => {
    withFetch((url, init) => {
      if (url === "/api/v1/admin/smtp" && init?.method === "PATCH") {
        return jsonResponse({ detail: "Invalid SMTP sender address." }, 422)
      }
      return jsonResponse(settings)
    })

    renderPage(<SmtpSettingsPage />)
    await waitFor(() =>
      expect(screen.getByDisplayValue("smtp.example.com")).toBeTruthy()
    )
    fireEvent.change(screen.getByLabelText("SMTP 密码"), {
      target: { value: "new-secret" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存 SMTP 配置" }))

    await waitFor(() =>
      expect(screen.getByText("发件人邮箱格式无效")).toBeTruthy()
    )
    expect(notifications).toContainEqual(["error", "发件人邮箱格式无效"])
  })

  test("saves a toggled enable state and edited fields", async () => {
    let patchBody: unknown = null
    withFetch((url, init) => {
      if (url === "/api/v1/admin/smtp" && init?.method === "PATCH") {
        patchBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return jsonResponse({ ...settings, enabled: false })
      }
      return jsonResponse(settings)
    })

    renderPage(<SmtpSettingsPage />)
    await waitFor(() => expect(screen.getByText("已启用")).toBeTruthy())
    expect(screen.getByText("SMTP 已启用")).toBeTruthy()

    const toggle = screen.getByRole("switch", { name: "启用 SMTP" })
    fireEvent.click(toggle)
    expect(toggle.getAttribute("aria-checked")).toBe("false")
    expect(screen.getByText("已停用")).toBeTruthy()

    fireEvent.change(screen.getByLabelText("SMTP 主机"), {
      target: { value: "smtp2.example.com" },
    })
    fireEvent.change(screen.getByLabelText("SMTP 用户名"), {
      target: { value: "relay" },
    })
    fireEvent.change(screen.getByLabelText("发件人邮箱"), {
      target: { value: "team@example.com" },
    })
    fireEvent.change(screen.getByLabelText("发件人名称"), {
      target: { value: "NexaFlow Team" },
    })
    fireEvent.change(screen.getByLabelText("站点地址"), {
      target: { value: "https://app.example.com" },
    })
    fireEvent.change(screen.getByLabelText("端口"), {
      target: { value: "465" },
    })

    const securitySelect = screen.getByRole("button", { name: "加密方式" })
    fireEvent.pointerDown(securitySelect)
    fireEvent.click(securitySelect)
    fireEvent.click(await screen.findByRole("menuitem", { name: "SSL/TLS" }))

    fireEvent.click(screen.getByRole("button", { name: "保存 SMTP 配置" }))

    await waitFor(() => expect(patchBody).not.toBeNull())
    expect(patchBody).toEqual({
      host: "smtp2.example.com",
      port: 465,
      username: "relay",
      security: "ssl",
      from_email: "team@example.com",
      from_name: "NexaFlow Team",
      enabled: false,
      timeout_seconds: 10,
      site_url: "https://app.example.com",
    })
    expect(notifications).toContainEqual(["success", "SMTP 配置已保存"])
  })

  test("keeps the test form disabled until SMTP is configured", async () => {
    let testRequests = 0
    withFetch((url) => {
      if (url === "/api/v1/admin/smtp/test") {
        testRequests += 1
        return jsonResponse({ success: true })
      }
      return jsonResponse({
        ...settings,
        configured: false,
        enabled: false,
        identity_configured: false,
      })
    })

    renderPage(<SmtpSettingsPage />)
    await waitFor(() =>
      expect(screen.getByText("请先填写主机和发件人邮箱并保存")).toBeTruthy()
    )
    const testButton = screen.getByRole("button", { name: "发送测试邮件" })
    expect((testButton as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText("身份邮件尚未就绪")).toBeTruthy()

    const testForm = testButton.closest("form")
    if (testForm) fireEvent.submit(testForm)
    await waitFor(() => expect(testRequests).toBe(0))
    expect(notifications).toHaveLength(0)
  })

  test("redirects a workspace administrator away from the SMTP page", async () => {
    sessionState.me = {
      ...adminMe,
      user: { ...adminMe.user, is_global_admin: false },
    }
    withFetch(() => {
      throw new Error("Unexpected request")
    })

    renderPage(<SmtpSettingsPage />)

    await waitFor(() => expect(replaced).toContain("/system/teams"))
    expect(screen.queryByLabelText("SMTP 主机")).toBeNull()
  })

  test("clears the saved password through the checkbox", async () => {
    let patchBody: unknown = null
    withFetch((url, init) => {
      if (url === "/api/v1/admin/smtp" && init?.method === "PATCH") {
        patchBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return jsonResponse({ ...settings, has_password: false })
      }
      return jsonResponse(settings)
    })

    renderPage(<SmtpSettingsPage />)
    await waitFor(() =>
      expect(screen.getByLabelText("清除已保存的密码")).toBeTruthy()
    )
    fireEvent.click(screen.getByLabelText("清除已保存的密码"))
    fireEvent.click(screen.getByRole("button", { name: "保存 SMTP 配置" }))

    await waitFor(() => expect(patchBody).not.toBeNull())
    expect(patchBody).toEqual({
      host: "smtp.example.com",
      port: 587,
      username: "mailer",
      security: "starttls",
      from_email: "noreply@example.com",
      from_name: "NexaFlow",
      enabled: true,
      timeout_seconds: 10,
      site_url: "https://nexaflow.example.com",
      clear_password: true,
    })
  })

  test("reports a failed test delivery", async () => {
    withFetch((url) => {
      if (url === "/api/v1/admin/smtp/test") {
        return jsonResponse({ detail: "SMTP test failed." }, 502)
      }
      return jsonResponse(settings)
    })

    renderPage(<SmtpSettingsPage />)
    await waitFor(() =>
      expect(screen.getByLabelText("收件人邮箱")).toBeTruthy()
    )
    fireEvent.change(screen.getByLabelText("收件人邮箱"), {
      target: { value: "owner@example.com" },
    })
    fireEvent.click(screen.getByRole("button", { name: "发送测试邮件" }))

    await waitFor(() =>
      expect(
        screen.getByText("SMTP 测试失败，请检查服务器、端口、加密方式和凭据")
      ).toBeTruthy()
    )
    expect(notifications).toContainEqual([
      "error",
      "SMTP 测试失败，请检查服务器、端口、加密方式和凭据",
    ])
  })
})

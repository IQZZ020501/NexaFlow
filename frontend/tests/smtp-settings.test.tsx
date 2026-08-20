/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"

import { SmtpSettingsPage } from "@/components/system/smtp-settings-page"
import { SystemGovernancePage } from "@/components/system/system-governance-page"
import { SystemShell } from "@/components/system/system-shell"
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
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

const replacements: string[] = []
const session = makeSession()
mockUseSession(session)
mockNextNavigation({
  pathname: "/system/email",
  replace: (href) => replacements.push(href),
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
  enabled: false,
  timeout_seconds: 10,
  has_password: true,
  password_hint: "****word",
  configured: true,
  site_url: "https://nexaflow.example.com",
  identity_configured: false,
  updated_at: "2026-08-20T00:00:00Z",
}

beforeEach(() => {
  replacements.length = 0
  sessionState.me = adminMe
  sessionState.token = "test-token"
  sessionState.notify = () => undefined
})

afterEach(() => cleanup())

describe("SMTP system settings", () => {
  test("loads masked settings and saves a replacement password", async () => {
    let patchBody: unknown = null
    const notifications: Array<[string, string]> = []
    sessionState.notify = (kind, message) => notifications.push([kind, message])
    withFetch((url, init) => {
      if (url === "/api/v1/admin/smtp" && init?.method === "PATCH") {
        patchBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return jsonResponse({ ...settings, password_hint: "****cret" })
      }
      if (url === "/api/v1/admin/smtp") {
        expect(new Headers(init?.headers).get("Authorization")).toBe(
          "Bearer test-token"
        )
        return jsonResponse(settings)
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SmtpSettingsPage />)

    await waitFor(() =>
      expect(screen.getByDisplayValue("smtp.example.com")).toBeTruthy()
    )
    expect(screen.getByText("当前密码提示：****word")).toBeTruthy()
    expect(
      screen.getByDisplayValue("https://nexaflow.example.com")
    ).toBeTruthy()
    expect(screen.getByText("身份邮件尚未就绪")).toBeTruthy()
    fireEvent.change(screen.getByLabelText("SMTP 密码"), {
      target: { value: "new-secret" },
    })
    const saveButton = screen.getByRole("button", { name: "保存 SMTP 配置" })
    const configForm = saveButton.closest("form")
    expect(
      Array.from(configForm?.elements ?? [])
        .filter(
          (element) =>
            element instanceof HTMLInputElement && !element.checkValidity()
        )
        .map((element) => (element as HTMLInputElement).id)
    ).toEqual([])
    fireEvent.click(saveButton)

    await waitFor(() => expect(patchBody).not.toBeNull())
    expect(patchBody).toEqual({
      host: "smtp.example.com",
      port: 587,
      username: "mailer",
      password: "new-secret",
      security: "starttls",
      from_email: "noreply@example.com",
      from_name: "NexaFlow",
      enabled: false,
      timeout_seconds: 10,
      site_url: "https://nexaflow.example.com",
    })
    expect(notifications).toContainEqual(["success", "SMTP 配置已保存"])
  })

  test("clears the stored password without sending a conflicting value", async () => {
    let patchBody: unknown = null
    withFetch((url, init) => {
      if (url === "/api/v1/admin/smtp" && init?.method === "PATCH") {
        patchBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return jsonResponse({
          ...settings,
          has_password: false,
          password_hint: null,
        })
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
    expect((patchBody as Record<string, unknown>).clear_password).toBe(true)
    expect(patchBody as Record<string, unknown>).not.toHaveProperty("password")
  })

  test("sends a test message through the saved configuration", async () => {
    let testBody: unknown = null
    withFetch((url, init) => {
      if (url === "/api/v1/admin/smtp/test") {
        testBody = JSON.parse(String(init?.body))
        return jsonResponse({ success: true })
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
      expect(testBody).toEqual({ to_email: "owner@example.com" })
    )
  })

  test("shows when identity email delivery is ready", async () => {
    withFetch(() =>
      jsonResponse({
        ...settings,
        enabled: true,
        identity_configured: true,
      })
    )

    renderPage(<SmtpSettingsPage />)

    await waitFor(() => expect(screen.getByText("身份邮件已就绪")).toBeTruthy())
    expect(screen.getByText("系统可以发送邀请和密码重置邮件")).toBeTruthy()
  })

  test("shows both system navigation entry points only to global administrators", async () => {
    withFetch(() => jsonResponse(settings))

    const governanceView = renderPage(<SystemGovernancePage section="email" />)
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "SMTP 邮件" })).toBeTruthy()
    )
    governanceView.unmount()

    renderPage(<SystemShell activeTab="workspaces" />)
    expect(screen.getByRole("link", { name: "SMTP 邮件" })).toBeTruthy()
  })

  test("redirects a workspace administrator and hides SMTP configuration", async () => {
    sessionState.me = {
      ...adminMe,
      user: { ...adminMe.user, is_global_admin: false },
    }
    let requested = false
    withFetch(() => {
      requested = true
      return jsonResponse(settings)
    })

    renderPage(<SystemGovernancePage section="email" />)

    await waitFor(() => expect(replacements).toContain("/system/teams"))
    expect(screen.queryByRole("link", { name: "SMTP 邮件" })).toBeNull()
    expect(screen.queryByLabelText("SMTP 主机")).toBeNull()
    expect(requested).toBe(false)
  })
})

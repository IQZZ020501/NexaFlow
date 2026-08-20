/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { ForgotPasswordPage } from "@/components/auth/forgot-password-page"
import { LoginScreen } from "@/components/auth/login-screen"
import { ResetPasswordPage } from "@/components/auth/reset-password-page"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  mockNextImage,
  mockNextLink,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

mockNextImage()
mockNextLink()

afterEach(() => {
  cleanup()
  resetFetch()
})

describe("password reset", () => {
  test("links the login form to password recovery", () => {
    renderPage(
      <LoginScreen onLogin={() => undefined} onNotify={() => undefined} />
    )

    const link = screen.getByRole("link", { name: "忘记密码" })
    const passwordInput = screen.getByLabelText("密码")
    expect(link.getAttribute("href")).toBe("/forgot-password")
    expect(passwordInput.nextElementSibling?.contains(link)).toBe(true)
    expect(screen.queryByRole("button", { name: "修改密码" })).toBeNull()
  })

  test("requests a reset email and shows an enumeration-safe success state", async () => {
    let requestBody: unknown = null
    let authorization: string | null = "unexpected"
    withFetch((url, init) => {
      expect(url).toBe("/api/v1/auth/password-reset/request")
      requestBody = JSON.parse(String(init?.body))
      authorization = new Headers(init?.headers).get("Authorization")
      return new Response(null, { status: 202 })
    })

    renderPage(<ForgotPasswordPage />)
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: " owner@example.com " },
    })
    fireEvent.click(screen.getByRole("button", { name: "发送重置链接" }))

    await waitFor(() => expect(screen.getByText("重置链接已发送")).toBeTruthy())
    expect(requestBody).toEqual({ email: "owner@example.com" })
    expect(authorization).toBeNull()
    expect(
      screen.getByText("如果该邮箱已注册，我们已发送重置链接，请检查邮箱")
    ).toBeTruthy()
  })

  test("shows a localized service error and keeps the request form", async () => {
    withFetch(() =>
      jsonResponse({ detail: "Email service is not configured." }, 503)
    )

    renderPage(<ForgotPasswordPage />)
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: "owner@example.com" },
    })
    fireEvent.click(screen.getByRole("button", { name: "发送重置链接" }))

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        "邮件服务尚未配置，请联系系统管理员"
      )
    )
    expect(screen.getByLabelText("邮箱")).toBeTruthy()
  })

  test("validates the new password before calling the confirmation API", async () => {
    let requested = false
    withFetch(() => {
      requested = true
      return new Response(null, { status: 204 })
    })

    renderPage(<ResetPasswordPage token="secret-reset-token" />)
    fireEvent.change(screen.getByLabelText("新密码"), {
      target: { value: "Password1" },
    })
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "Password2" },
    })
    fireEvent.click(screen.getByRole("button", { name: "重置密码" }))

    expect(screen.getByRole("alert").textContent).toBe("两次输入的新密码不一致")
    expect(requested).toBe(false)
  })

  test("confirms the reset token and returns to login after success", async () => {
    let requestBody: unknown = null
    withFetch((url, init) => {
      expect(url).toBe("/api/v1/auth/password-reset/confirm")
      requestBody = JSON.parse(String(init?.body))
      return new Response(null, { status: 204 })
    })

    renderPage(<ResetPasswordPage token="secret-reset-token" />)
    expect(screen.queryByText("secret-reset-token")).toBeNull()
    fireEvent.change(screen.getByLabelText("新密码"), {
      target: { value: "Password1" },
    })
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "Password1" },
    })
    fireEvent.click(screen.getByRole("button", { name: "重置密码" }))

    await waitFor(() => expect(screen.getByText("密码已重置")).toBeTruthy())
    expect(requestBody).toEqual({
      token: "secret-reset-token",
      new_password: "Password1",
    })
    expect(
      screen.getByRole("link", { name: "前往登录" }).getAttribute("href")
    ).toBe("/login")
  })

  test("localizes an invalid or expired reset token", async () => {
    withFetch(() =>
      jsonResponse(
        { detail: "Password reset link is invalid or expired." },
        400
      )
    )

    renderPage(<ResetPasswordPage token="expired-reset-token" />)
    fireEvent.change(screen.getByLabelText("新密码"), {
      target: { value: "Password1" },
    })
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "Password1" },
    })
    fireEvent.click(screen.getByRole("button", { name: "重置密码" }))

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        "密码重置链接无效或已过期"
      )
    )
    expect(screen.getByLabelText("新密码")).toBeTruthy()
  })
})

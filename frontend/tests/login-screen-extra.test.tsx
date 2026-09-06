/* @jsxImportSource react */
import { afterEach, describe, expect, mock, test } from "bun:test"

import { LoginPageContent } from "@/components/auth/login-page-content"
import { LoginScreen } from "@/components/auth/login-screen"
import { safeAuthDestination } from "@/lib/auth-path"
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
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

mockNextImage()
mockNextLink()
mockNextNavigation()
mockUseSession(
  makeSession({
    token: null,
    isSessionRestored: true,
  })
)

const originalLocationAssign = window.location.assign

afterEach(() => {
  cleanup()
  resetFetch()
  delete window.QRLogin
  window.location.assign = originalLocationAssign
})

function submitCredentials(username: string, password: string) {
  fireEvent.change(screen.getByLabelText("用户名"), {
    target: { value: username },
  })
  fireEvent.change(screen.getByLabelText("密码"), {
    target: { value: password },
  })
  fireEvent.click(screen.getByRole("button", { name: "登录" }))
}

describe("LoginScreen submission", () => {
  test("rejects unsafe post-login destinations", () => {
    expect(safeAuthDestination("/app/agents")).toBe("/app/agents")
    for (const value of [
      "https://evil.example",
      "//evil.example",
      "/\\evil.example",
      "/\t/evil.example",
      "/app/agents\\evil",
      `/${"a".repeat(2048)}`,
    ]) {
      expect(safeAuthDestination(value)).toBe("/app/apps")
    }
  })

  test("renders Feishu as a QR button and other providers as links", () => {
    renderPage(
      <LoginScreen
        onLogin={() => undefined}
        onNotify={() => undefined}
        next="/app/agents"
        enterpriseConnections={[
          {
            id: "connection-1",
            provider: "feishu",
            name: "公司飞书",
            start_url: "/api/v1/auth/enterprise/connection-1/start",
          },
          {
            id: "connection-2",
            provider: "dingtalk",
            name: "公司钉钉",
            start_url: "/api/v1/auth/enterprise/connection-2/start",
          },
          {
            id: "connection-3",
            provider: "wecom",
            name: "公司企微",
            start_url: "/api/v1/auth/enterprise/connection-3/start",
          },
        ]}
      />
    )

    const feishuButton = screen.getByRole("button", {
      name: "使用 公司飞书 扫码登录",
    })
    expect(feishuButton.getAttribute("title")).toBe("公司飞书")
    expect(
      document.querySelector('[data-provider-icon="feishu"]')
    ).not.toBeNull()
    expect(
      document.querySelector('[data-provider-icon="dingtalk"]')
    ).not.toBeNull()
    expect(
      document.querySelector('[data-provider-icon="wecom"]')
    ).not.toBeNull()
    expect(
      screen
        .getByRole("link", { name: "使用 公司钉钉 扫码登录" })
        .getAttribute("href")
    ).toBe("/api/v1/auth/enterprise/connection-2/start?next=%2Fapp%2Fagents")
    expect(
      screen
        .getByRole("link", { name: "使用 公司企微 扫码登录" })
        .getAttribute("href")
    ).toBe("/api/v1/auth/enterprise/connection-3/start?next=%2Fapp%2Fagents")
  })

  test("embeds the official Feishu QR flow and handles a verified scan", async () => {
    const requests: { url: string; init?: RequestInit }[] = []
    const authorizationUrl =
      "https://passport.feishu.cn/suite/passport/oauth/authorize?state=qr-state"
    const assign = mock(() => undefined)
    window.location.assign = assign
    let qrOptions:
      | {
          id: string
          goto: string
          width: string
          height: string
          style: string
        }
      | undefined
    window.QRLogin = (options) => {
      qrOptions = options
      return {
        matchOrigin: (origin) => origin === "https://passport.feishu.cn",
        matchData: (data) =>
          Boolean(data && typeof data === "object" && "tmp_code" in data),
      }
    }
    withFetch((url, init) => {
      requests.push({ url, init })
      return jsonResponse({ authorization_url: authorizationUrl })
    })

    renderPage(
      <LoginScreen
        onLogin={() => undefined}
        onNotify={() => undefined}
        next="/app/agents"
        enterpriseConnections={[
          {
            id: "connection-1",
            provider: "feishu",
            name: "公司飞书",
            start_url: "/api/v1/auth/enterprise/connection-1/start",
          },
        ]}
      />
    )

    fireEvent.click(
      screen.getByRole("button", { name: "使用 公司飞书 扫码登录" })
    )

    await waitFor(() => expect(qrOptions?.goto).toBe(authorizationUrl))
    expect(requests).toEqual([
      {
        url: "/api/v1/auth/enterprise/connection-1/qr?next=%2Fapp%2Fagents",
        init: expect.objectContaining({ method: "POST" }),
      },
    ])
    expect(document.getElementById(qrOptions!.id)).not.toBeNull()

    fireEvent(
      window,
      new MessageEvent("message", {
        origin: "https://attacker.example",
        data: { tmp_code: "forged" },
      })
    )
    expect(assign).not.toHaveBeenCalled()

    fireEvent(
      window,
      new MessageEvent("message", {
        origin: "https://passport.feishu.cn",
        data: { tmp_code: "temporary code" },
      })
    )
    expect(assign).toHaveBeenCalledWith(
      `${authorizationUrl}&tmp_code=temporary%20code`
    )
  })

  test("discovers enabled providers on the main login page", async () => {
    const requestedUrls: string[] = []
    withFetch((url) => {
      requestedUrls.push(url)
      return jsonResponse({
        workspace_id: null,
        workspace_name: null,
        connections: [
          {
            id: "connection-1",
            provider: "feishu",
            name: "公司飞书",
            start_url: "/api/v1/auth/enterprise/connection-1/start",
          },
        ],
      })
    })

    renderPage(<LoginPageContent />)

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "使用 公司飞书 扫码登录" })
      ).toBeTruthy()
    )
    expect(requestedUrls).toEqual(["/api/v1/auth/enterprise/connections"])
  })

  test("submits credentials and reports a successful login", async () => {
    const calls: { url: string; init?: RequestInit }[] = []
    withFetch((url, init) => {
      calls.push({ url, init })
      return jsonResponse({
        access_token: "token-123",
        token_type: "bearer",
        expires_in: 3600,
        must_change_password: false,
      })
    })

    let loginPayload: [string, boolean, number] | null = null
    const notifications: string[] = []
    renderPage(
      <LoginScreen
        onLogin={(token, mustChange, expiresIn) => {
          loginPayload = [token, mustChange, expiresIn]
        }}
        onNotify={(kind, message) => {
          notifications.push(`${kind}:${message}`)
        }}
      />
    )

    submitCredentials("alice", "s3cret")

    await waitFor(() =>
      expect(loginPayload).toEqual(["token-123", false, 3600])
    )
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe("/api/v1/auth/login")
    expect(calls[0].init?.method).toBe("POST")
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      username: "alice",
      password: "s3cret",
    })
    expect(notifications).toEqual([])
  })

  test("forwards the must-change-password requirement", async () => {
    withFetch(() =>
      jsonResponse({
        access_token: "token-456",
        token_type: "bearer",
        expires_in: 900,
        must_change_password: true,
      })
    )

    let mustChange: boolean | null = null
    renderPage(
      <LoginScreen
        onLogin={(_token, mustChangePassword) => {
          mustChange = mustChangePassword
        }}
        onNotify={() => undefined}
      />
    )

    submitCredentials("bob", "Password1")

    await waitFor(() => expect(mustChange).toBe(true))
  })

  test("shows a localized error and re-enables the form after a failed login", async () => {
    withFetch(() => jsonResponse({ detail: "Invalid credentials." }, 401))

    const notifications: string[] = []
    renderPage(
      <LoginScreen
        onLogin={() => undefined}
        onNotify={(kind, message) => {
          notifications.push(`${kind}:${message}`)
        }}
      />
    )

    submitCredentials("alice", "wrong")

    await waitFor(() =>
      expect(notifications).toEqual(["error:用户名或密码错误"])
    )
    expect(
      (screen.getByRole("button", { name: "登录" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  })

  test("keeps generic API errors as notification messages", async () => {
    withFetch(() => jsonResponse({ detail: "Maintenance window." }, 503))

    const notifications: string[] = []
    renderPage(
      <LoginScreen
        onLogin={() => undefined}
        onNotify={(kind, message) => {
          notifications.push(`${kind}:${message}`)
        }}
      />
    )

    submitCredentials("alice", "pw")

    await waitFor(() =>
      expect(notifications).toEqual(["error:Maintenance window."])
    )
  })

  test("disables the submit button and shows a spinner while submitting", async () => {
    let resolveFetch!: (response: Response) => void
    withFetch(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve
        })
    )

    let loginCalled = false
    renderPage(
      <LoginScreen
        onLogin={() => {
          loginCalled = true
        }}
        onNotify={() => undefined}
      />
    )

    submitCredentials("alice", "pw")

    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: "登录" }) as HTMLButtonElement)
          .disabled
      ).toBe(true)
    })
    expect(document.querySelector('[data-icon="inline-start"]')).not.toBeNull()
    expect(loginCalled).toBe(false)

    resolveFetch(
      jsonResponse({
        access_token: "token-789",
        token_type: "bearer",
        expires_in: 60,
        must_change_password: false,
      })
    )

    await waitFor(() => expect(loginCalled).toBe(true))
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: "登录" }) as HTMLButtonElement)
          .disabled
      ).toBe(false)
    })
    expect(document.querySelector('[data-icon="inline-start"]')).toBeNull()
  })
})

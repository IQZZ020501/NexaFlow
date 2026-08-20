import { afterEach, describe, expect, test } from "bun:test"

import {
  acceptWorkspaceInvitation,
  changePassword,
  confirmPasswordReset,
  getMe,
  login,
  logout,
  refreshAccessToken,
  requestPasswordReset,
  type User,
} from "../src/lib/api/auth"
import { ApiError } from "../src/lib/api-client"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

type Call = { url: string; init?: RequestInit }

/** Installs a fetch stub that records every call and routes to the handler. */
function stubFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>
): Call[] {
  const calls: Call[] = []
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    calls.push({ url, init })
    return Promise.resolve(handler(url, init))
  }) as unknown as typeof fetch
  return calls
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

const user: User = {
  id: "u-1",
  username: "admin",
  email: "admin@example.com",
  name: "NexaFlow Admin",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  workspaces: [],
  teams: [],
}

describe("auth api", () => {
  test("logs in with username and password", async () => {
    const calls = stubFetch(() =>
      jsonResponse({
        access_token: "token-1",
        token_type: "bearer",
        expires_in: 3600,
        must_change_password: true,
      })
    )

    const result = await login("alice", "s3cret")

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe("/api/v1/auth/login")
    expect(calls[0].init?.method).toBe("POST")
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      username: "alice",
      password: "s3cret",
    })
    expect(result).toEqual({
      access_token: "token-1",
      token_type: "bearer",
      expires_in: 3600,
      must_change_password: true,
    })
  })

  test("rejects login with an API error on failure", async () => {
    stubFetch(() => jsonResponse({ detail: "Invalid credentials." }, 401))

    try {
      await login("alice", "wrong")
      throw new Error("login should reject")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(401)
      expect((error as ApiError).message).toBe("Invalid credentials.")
    }
  })

  test("refreshes the access token", async () => {
    const refreshed = {
      access_token: "token-refreshed",
      token_type: "bearer",
      expires_in: 3600,
      must_change_password: false,
    }
    const calls = stubFetch(() => jsonResponse(refreshed))

    const result = await refreshAccessToken()

    expect(calls[0].url).toBe("/api/v1/auth/refresh")
    expect(calls[0].init?.method).toBe("POST")
    expect(result).toEqual(refreshed)
  })

  test("logs out the current session", async () => {
    const calls = stubFetch(() => new Response(null, { status: 204 }))

    await logout()

    expect(calls[0].url).toBe("/api/v1/auth/logout")
    expect(calls[0].init?.method).toBe("POST")
  })

  test("changes the password with the current password and bearer token", async () => {
    const calls = stubFetch(() => new Response(null, { status: 204 }))

    await changePassword("token-2", "NewPass1!", "OldPass1")

    expect(calls[0].url).toBe("/api/v1/auth/change-password")
    expect(calls[0].init?.method).toBe("POST")
    expect(new Headers(calls[0].init?.headers).get("Authorization")).toBe(
      "Bearer token-2"
    )
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      new_password: "NewPass1!",
      current_password: "OldPass1",
    })
  })

  test("changes the password without a current password", async () => {
    const calls = stubFetch(() => new Response(null, { status: 204 }))

    await changePassword("token-3", "NewPass2")

    expect(new Headers(calls[0].init?.headers).get("Authorization")).toBe(
      "Bearer token-3"
    )
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      new_password: "NewPass2",
    })
  })

  test("fetches the current user with the bearer token", async () => {
    const calls = stubFetch(() =>
      jsonResponse({
        user,
        memberships: [{ workspace_id: "ws-1", role: "admin" }],
      })
    )

    const me = await getMe("token-4")

    expect(calls[0].url).toBe("/api/v1/auth/me")
    expect(new Headers(calls[0].init?.headers).get("Authorization")).toBe(
      "Bearer token-4"
    )
    expect(me.user.username).toBe("admin")
    expect(me.memberships).toEqual([{ workspace_id: "ws-1", role: "admin" }])
  })

  test("requests a password reset email", async () => {
    const calls = stubFetch(() => new Response(null, { status: 202 }))

    await requestPasswordReset("owner@example.com")

    expect(calls[0].url).toBe("/api/v1/auth/password-reset/request")
    expect(calls[0].init?.method).toBe("POST")
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      email: "owner@example.com",
    })
  })

  test("confirms a password reset with the token and new password", async () => {
    const calls = stubFetch(() => new Response(null, { status: 204 }))

    await confirmPasswordReset("reset-token", "NewPass1")

    expect(calls[0].url).toBe("/api/v1/auth/password-reset/confirm")
    expect(calls[0].init?.method).toBe("POST")
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      token: "reset-token",
      new_password: "NewPass1",
    })
  })

  test("accepts a workspace invitation with identity details", async () => {
    const calls = stubFetch(() => jsonResponse({ ...user, username: "newbie" }))

    const created = await acceptWorkspaceInvitation("inv-token", "Pass123", {
      username: "newbie",
      email: "newbie@example.com",
      name: "Newbie User",
    })
    expect(calls[0].url).toBe("/api/v1/auth/invitations/accept")

    expect(calls[0].init?.method).toBe("POST")
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      token: "inv-token",
      password: "Pass123",
      username: "newbie",
      email: "newbie@example.com",
      name: "Newbie User",
    })
    expect(created.username).toBe("newbie")
  })

  test("accepts a workspace invitation without identity details", async () => {
    const calls = stubFetch(() => new Response(null, { status: 204 }))

    await acceptWorkspaceInvitation("inv-token", "Pass123")

    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      token: "inv-token",
      password: "Pass123",
    })
  })

  test("surfaces non-2xx responses as API errors", async () => {
    stubFetch(() => jsonResponse({ detail: "Server exploded." }, 500))

    try {
      await changePassword("token-5", "NewPass1")
      throw new Error("changePassword should reject")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(500)
      expect((error as ApiError).message).toBe("Server exploded.")
    }
  })
})

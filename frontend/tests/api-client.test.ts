import { afterEach, describe, expect, test } from "bun:test"

import { ApiError, request } from "../src/lib/api-client"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe("api client", () => {
  test("adds auth headers and returns API error details", async () => {
    let headers = new Headers()
    let credentials: RequestCredentials | undefined

    globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
      headers = new Headers(init?.headers)
      credentials = init?.credentials
      return new Response(JSON.stringify({ detail: "Invalid request." }), {
        status: 400,
        statusText: "Bad Request",
      })
    }) as unknown as typeof fetch

    try {
      await request("/users", {
        method: "POST",
        token: "test-token",
        body: JSON.stringify({ username: "ada" }),
      })
      throw new Error("request should fail")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(400)
      expect((error as ApiError).message).toBe("Invalid request.")
    }

    expect(headers.get("Authorization")).toBe("Bearer test-token")
    expect(headers.get("Content-Type")).toBe("application/json")
    expect(credentials).toBe("include")
  })

  test("returns undefined for empty success responses", async () => {
    globalThis.fetch = (async () =>
      new Response(null, { status: 204 })) as unknown as typeof fetch

    expect(await request("/users/1", { method: "DELETE" })).toBeUndefined()
  })

  test("preserves plain-text error responses as API errors", async () => {
    globalThis.fetch = (async () =>
      new Response("upstream unavailable", {
        status: 502,
        statusText: "Bad Gateway",
      })) as unknown as typeof fetch

    try {
      await request("/users")
      throw new Error("request should fail")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(502)
      expect((error as ApiError).message).toBe("upstream unavailable")
    }
  })
})

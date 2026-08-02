import { afterEach, describe, expect, test } from "bun:test"

import { ApiError, request } from "../src/lib/api-client"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe("api client", () => {
  test("adds auth headers and returns API error details", async () => {
    let headers = new Headers()

    globalThis.fetch = (async (_url, init) => {
      headers = new Headers(init?.headers)
      return new Response(JSON.stringify({ detail: "Invalid request." }), {
        status: 400,
        statusText: "Bad Request",
      })
    }) as typeof fetch

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
  })

  test("returns undefined for empty success responses", async () => {
    globalThis.fetch = (async () =>
      new Response(null, { status: 204 })) as typeof fetch

    expect(await request("/users/1", { method: "DELETE" })).toBeUndefined()
  })
})

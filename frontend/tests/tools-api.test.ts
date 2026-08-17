import { afterEach, describe, expect, test } from "bun:test"

import {
  archivePythonTool,
  createMcpSource,
  createPythonTool,
  deleteToolSource,
  getPythonToolTest,
  getTool,
  listAllToolPermissions,
  listAllTools,
  listToolPermissions,
  listTools,
  publishPythonTool,
  refreshToolSource,
  revokeToolPermission,
  setPythonToolEnabled,
  setToolPermission,
  setToolSourceEnabled,
  testPythonTool,
  updatePythonToolDraft,
  updateToolPolicy,
} from "@/lib/api/tools"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

type CapturedRequest = {
  url: string
  method: string
  body: unknown
  authorization: string | null
}

function captureRequests() {
  const requests: CapturedRequest[] = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    requests.push({
      url: String(input),
      method: init?.method ?? "GET",
      body,
      authorization: new Headers(init?.headers).get("Authorization"),
    })
    return init?.method === "DELETE"
      ? new Response(null, { status: 204 })
      : Response.json({})
  }) as typeof fetch
  return requests
}

describe("unified Tool API", () => {
  test("loads every catalog page for selection surfaces", async () => {
    const requestedOffsets: string[] = []
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost")
      const offset = url.searchParams.get("offset") ?? "0"
      requestedOffsets.push(offset)
      const items =
        offset === "0"
          ? Array.from({ length: 200 }, (_, index) => ({ id: `tool-${index}` }))
          : [{ id: "tool-200" }]
      return Response.json(items)
    }) as typeof fetch

    const tools = await listAllTools("token", "ws-1")

    expect(tools).toHaveLength(201)
    expect(tools.at(-1)?.id).toBe("tool-200")
    expect(requestedOffsets).toEqual(["0", "200"])
  })

  test("loads every Tool permission page", async () => {
    const requestedOffsets: string[] = []
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost")
      const offset = url.searchParams.get("offset") ?? "0"
      requestedOffsets.push(offset)
      return Response.json(
        offset === "0"
          ? Array.from({ length: 200 }, (_, index) => ({
              user: { id: `user-${index}` },
              permission: "view",
            }))
          : [{ user: { id: "user-200" }, permission: "use" }]
      )
    }) as typeof fetch

    const permissions = await listAllToolPermissions(
      "token",
      "ws-1",
      "tool-1"
    )

    expect(permissions).toHaveLength(201)
    expect(requestedOffsets).toEqual(["0", "200"])
  })

  test("uses canonical catalog and Tool Source routes", async () => {
    const requests = captureRequests()

    await listTools("token", "ws-1", { limit: 50, offset: 10 })
    await getTool("token", "ws-1", "tool-1")
    await createMcpSource("token", "ws-1", {
      name: "Search",
      transport: "streamable_http",
      url: "https://example.com/mcp",
      bearer_token: "secret",
    })
    await refreshToolSource("token", "ws-1", "source-1")
    await setToolSourceEnabled("token", "ws-1", "source-1", false)
    await setToolSourceEnabled("token", "ws-1", "source-1", true)
    await deleteToolSource("token", "ws-1", "source-1")

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["GET", "/api/v1/workspaces/ws-1/tools?limit=50&offset=10"],
      ["GET", "/api/v1/workspaces/ws-1/tools/tool-1"],
      ["POST", "/api/v1/workspaces/ws-1/tool-sources/mcp"],
      ["POST", "/api/v1/workspaces/ws-1/tool-sources/source-1/refresh"],
      ["POST", "/api/v1/workspaces/ws-1/tool-sources/source-1/disable"],
      ["POST", "/api/v1/workspaces/ws-1/tool-sources/source-1/enable"],
      ["DELETE", "/api/v1/workspaces/ws-1/tool-sources/source-1"],
    ])
    expect(requests[2]?.body).toEqual({
      name: "Search",
      transport: "streamable_http",
      url: "https://example.com/mcp",
      bearer_token: "secret",
    })
    expect(
      requests.every((request) => request.authorization === "Bearer token")
    ).toBe(true)
  })

  test("pins Python lifecycle, policy, and permissions to tool ids", async () => {
    const requests = captureRequests()
    const draft = {
      display_name: "Formatter",
      description: "Formats text",
      input_schema: { type: "object" },
      output_schema: { type: "object" },
      code: "result = inputs",
    }

    await createPythonTool("token", "ws-1", draft)
    await updatePythonToolDraft("token", "ws-1", "tool-1", {
      ...draft,
      expected_revision: 3,
    })
    await testPythonTool("token", "ws-1", "tool-1", { text: "hello" })
    await getPythonToolTest("token", "ws-1", "tool-1", "invocation-1")
    await publishPythonTool("token", "ws-1", "tool-1")
    await setPythonToolEnabled("token", "ws-1", "tool-1", false)
    await updateToolPolicy("token", "ws-1", "tool-1", "read_only")
    await listToolPermissions("token", "ws-1", "tool-1")
    await setToolPermission("token", "ws-1", "tool-1", "user-2", "use")
    await revokeToolPermission("token", "ws-1", "tool-1", "user-2")
    await archivePythonTool("token", "ws-1", "tool-1")

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["POST", "/api/v1/workspaces/ws-1/tools/python"],
      ["PUT", "/api/v1/workspaces/ws-1/tools/tool-1/draft"],
      ["POST", "/api/v1/workspaces/ws-1/tools/tool-1/tests"],
      ["GET", "/api/v1/workspaces/ws-1/tools/tool-1/tests/invocation-1"],
      ["POST", "/api/v1/workspaces/ws-1/tools/tool-1/publish"],
      ["POST", "/api/v1/workspaces/ws-1/tools/tool-1/disable"],
      ["PUT", "/api/v1/workspaces/ws-1/tools/tool-1/policy"],
      ["GET", "/api/v1/workspaces/ws-1/tools/tool-1/permissions"],
      ["PUT", "/api/v1/workspaces/ws-1/tools/tool-1/permissions/user-2"],
      ["DELETE", "/api/v1/workspaces/ws-1/tools/tool-1/permissions/user-2"],
      ["DELETE", "/api/v1/workspaces/ws-1/tools/tool-1"],
    ])
    expect(requests[1]?.body).toEqual({ ...draft, expected_revision: 3 })
    expect(requests[2]?.body).toEqual({ arguments: { text: "hello" } })
    expect(requests[6]?.body).toEqual({ mode: "read_only" })
    expect(requests[8]?.body).toEqual({ permission: "use" })
  })
})

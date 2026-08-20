import { afterEach, describe, expect, test } from "bun:test"

import { listAgents, listAllAgents } from "../src/lib/api/agents"
import { listKnowledgeBases } from "../src/lib/api/knowledge"
import { listRegisteredModels } from "../src/lib/api/llm"
import { listMcpServers } from "../src/lib/api/mcp"
import { CARD_BATCH_SIZE } from "../src/lib/use-infinite-scroll"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe("card list batch loading", () => {
  test("loads card lists in batches of 50", () => {
    expect(CARD_BATCH_SIZE).toBe(50)
  })

  test("loads every Agent page for selection surfaces", async () => {
    const requestedOffsets: string[] = []
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost")
      const offset = url.searchParams.get("offset") ?? "0"
      requestedOffsets.push(offset)
      const items =
        offset === "0"
          ? Array.from({ length: 200 }, (_, index) => ({
              id: `agent-${index}`,
            }))
          : [{ id: "agent-200" }]
      return Response.json(items)
    }) as typeof fetch

    const agents = await listAllAgents("token", "ws")

    expect(agents).toHaveLength(201)
    expect(agents.at(-1)?.id).toBe("agent-200")
    expect(requestedOffsets).toEqual(["0", "200"])
  })

  const listCalls: Array<{
    name: string
    firstCall: () => Promise<unknown>
    call: (limit: number, offset: number) => Promise<unknown>
    basePath: string
  }> = [
    {
      name: "agents",
      firstCall: () => listAgents("token", "ws"),
      call: (limit, offset) => listAgents("token", "ws", { limit, offset }),
      basePath: "/api/v1/workspaces/ws/agents",
    },
    {
      name: "knowledge bases",
      firstCall: () => listKnowledgeBases("token", "ws"),
      call: (limit, offset) =>
        listKnowledgeBases("token", "ws", { limit, offset }),
      basePath: "/api/v1/workspaces/ws/knowledge-bases",
    },
    {
      name: "registered models",
      firstCall: () => listRegisteredModels("token", "ws"),
      call: (limit, offset) =>
        listRegisteredModels("token", "ws", { limit, offset }),
      basePath: "/api/v1/workspaces/ws/models",
    },
    {
      name: "mcp servers",
      firstCall: () => listMcpServers("token", "ws"),
      call: (limit, offset) => listMcpServers("token", "ws", { limit, offset }),
      basePath: "/api/v1/workspaces/ws/mcp-servers",
    },
  ]

  for (const { name, firstCall, call, basePath } of listCalls) {
    test(`${name} list requests the first batch without query parameters`, async () => {
      let requestedUrl = ""
      globalThis.fetch = (async (url: RequestInfo | URL) => {
        requestedUrl = String(url)
        return new Response("[]", { status: 200 })
      }) as unknown as typeof fetch

      await firstCall()
      expect(requestedUrl).toBe(basePath)
    })

    test(`${name} list passes limit and offset for subsequent batches`, async () => {
      let requestedUrl = ""
      globalThis.fetch = (async (url: RequestInfo | URL) => {
        requestedUrl = String(url)
        return new Response("[]", { status: 200 })
      }) as unknown as typeof fetch

      await call(50, 100)
      expect(requestedUrl).toBe(`${basePath}?limit=50&offset=100`)
    })
  }
})

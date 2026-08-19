import { afterEach, describe, expect, test } from "bun:test"

import {
  createWorkflowRun,
  observeWorkflowRun,
  uploadWorkflowFiles,
  updateWorkflowDefinition,
} from "../src/lib/api/workflows"
import {
  createPublicWorkflowRun,
  getWorkflowApiDocumentation,
} from "../src/lib/api/public-workflows"

const originalFetch = globalThis.fetch
const originalSetTimeout = globalThis.setTimeout

afterEach(() => {
  globalThis.fetch = originalFetch
  globalThis.setTimeout = originalSetTimeout
})

function ndjsonResponse(events: object[]) {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const event of events) {
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`))
        }
        controller.close()
      },
    })
  )
}

describe("workflow API", () => {
  test("saves drafts with an optimistic revision", async () => {
    let body = ""
    let url = ""
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      url = String(input)
      body = String(init?.body)
      return Response.json({})
    }) as typeof fetch

    await updateWorkflowDefinition("token", "ws-1", "workflow-1", 7, {
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    })

    expect(url).toContain("/workflows/workflow-1/definition")
    expect(JSON.parse(body).expected_revision).toBe(7)
  })

  test("sends legacy graphs and consumes the server-normalized Tool graph", async () => {
    let requestBody = ""
    globalThis.fetch = (async (
      _input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      requestBody = String(init?.body)
      return Response.json({
        id: "definition-1",
        workspace_id: "ws-1",
        agent_id: "workflow-1",
        revision: 2,
        graph: {
          nodes: [
            {
              id: "tool-1",
              type: "workflow",
              position: { x: 0, y: 0 },
              data: {
                type: "tool",
                title: "Search",
                config: {
                  tool: { tool_id: "tool-1", version_id: "version-1" },
                  arguments: {},
                },
              },
            },
          ],
          edges: [],
          viewport: { x: 0, y: 0, zoom: 1 },
        },
        graph_hash: "hash",
        updated_by_user_id: "user-1",
        created_at: "2026-08-17T00:00:00Z",
        updated_at: "2026-08-17T00:00:00Z",
      })
    }) as typeof fetch

    const updated = await updateWorkflowDefinition(
      "token",
      "ws-1",
      "workflow-1",
      1,
      {
        nodes: [
          {
            id: "legacy-mcp",
            type: "workflow",
            position: { x: 0, y: 0 },
            data: {
              type: "mcp",
              title: "Legacy MCP",
              config: {
                server_id: "server-1",
                tool_name: "search",
                arguments: {},
              },
            },
          },
          {
            id: "legacy-code",
            type: "workflow",
            position: { x: 240, y: 0 },
            data: {
              type: "code",
              title: "Legacy code",
              config: { code: "result = inputs", inputs: {} },
            },
          },
        ],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      }
    )

    expect(
      JSON.parse(requestBody).graph.nodes.map(
        (node: { data: { type: string } }) => node.data.type
      )
    ).toEqual(["mcp", "code"])
    expect(updated.graph.nodes.map((node) => node.data.type)).toEqual(["tool"])
  })

  test("selects an immutable version for production runs", async () => {
    let body = ""
    globalThis.fetch = (async (
      _input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      body = String(init?.body)
      return Response.json({})
    }) as typeof fetch

    await createWorkflowRun(
      "token",
      "ws-1",
      "workflow-1",
      "release",
      "published",
      3
    )

    expect(JSON.parse(body)).toEqual({
      question: "release",
      source: "published",
      version_number: 3,
    })
  })

  test("uploads debug attachments and passes their ids to the run", async () => {
    const requests: Array<{ url: string; body: BodyInit | null | undefined }> =
      []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      requests.push({ url: String(input), body: init?.body })
      return Response.json([{ id: "upload-1" }])
    }) as typeof fetch

    const files = [new File(["debug"], "debug.txt", { type: "text/plain" })]
    const uploaded = await uploadWorkflowFiles(
      "token",
      "ws-1",
      "workflow-1",
      files
    )
    await createWorkflowRun(
      "token",
      "ws-1",
      "workflow-1",
      "inspect attachment",
      "draft",
      undefined,
      uploaded.map((item) => item.id)
    )

    expect(requests[0]?.url).toContain("/workflows/workflow-1/uploads")
    expect(requests[0]?.body).toBeInstanceOf(FormData)
    expect((requests[0]?.body as FormData).getAll("files")).toEqual(files)
    expect(JSON.parse(String(requests[1]?.body))).toEqual({
      question: "inspect attachment",
      source: "draft",
      file_ids: ["upload-1"],
    })
  })

  test("uses workflow-specific public and API routes", async () => {
    const requests: Array<{
      url: string
      body?: string
      authorization?: string
    }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      requests.push({
        url: String(input),
        body: init?.body ? String(init.body) : undefined,
        authorization:
          new Headers(init?.headers).get("Authorization") ?? undefined,
      })
      return Response.json({})
    }) as typeof fetch

    await createPublicWorkflowRun(
      "workflow-1",
      "session-token",
      "release",
      "conversation-1"
    )
    await getWorkflowApiDocumentation("workflow-1", "nxf_key")

    expect(requests[0]?.url).toContain("/public/workflows/workflow-1/runs")
    expect(JSON.parse(requests[0]?.body ?? "{}")).toEqual({
      question: "release",
      conversation_id: "conversation-1",
    })
    expect(requests[1]?.url).toContain("/workflow-api/workflow-1/documentation")
    expect(requests[1]?.authorization).toBe("Bearer nxf_key")
  })

  test("reconnects workflow output streams from the last live delta", async () => {
    const urls: string[] = []
    const eventTypes: string[] = []
    globalThis.setTimeout = ((callback: () => void) => {
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      urls.push(String(input))
      return urls.length === 1
        ? ndjsonResponse([
            {
              type: "answer_delta",
              live_sequence: "1700000000000-0",
              stream_epoch: "worker-1",
              node_id: "llm-1",
              delta: "# 标题",
            },
          ])
        : ndjsonResponse([{ type: "complete", sequence: 3, run: {} }])
    }) as typeof fetch

    await observeWorkflowRun("token", "ws-1", "workflow-1", "run-1", (event) =>
      eventTypes.push(event.type)
    )

    expect(eventTypes).toEqual(["answer_delta", "complete"])
    expect(urls[1]).toContain("after=0")
    expect(urls[1]).toContain("live_after=1700000000000-0")
  })
})

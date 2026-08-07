import { afterEach, describe, expect, test } from "bun:test"

import {
  streamAgentRun,
  type AgentRun,
  type AgentRunStreamEvent,
} from "../lib/api/agents"

const originalFetch = globalThis.fetch
const originalSetTimeout = globalThis.setTimeout

afterEach(() => {
  globalThis.fetch = originalFetch
  globalThis.setTimeout = originalSetTimeout
})

function ndjsonResponse(lines: string[]): Response {
  return rawStreamResponse(lines.map((line) => `${line}\n`))
}

function rawStreamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
  return new Response(body, { status: 200 })
}

function runSnapshot(status: AgentRun["status"]): AgentRun {
  return {
    id: "run-1",
    workspace_id: "ws-1",
    agent_id: "agent-1",
    requested_by_user_id: "user-1",
    goal: "question",
    model_id: "model-1",
    model_name: "deepseek-chat",
    knowledge_query_mode: "required",
    status,
    plan: [],
    events: [],
    result: "",
    last_error: null,
    planned_at: null,
    started_at: new Date().toISOString(),
    finished_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    trace_id: "trace-1",
  }
}

describe("streamAgentRun", () => {
  test("delivers events and accepts a terminal complete event", async () => {
    const events: AgentRunStreamEvent[] = []
    let requestCount = 0
    globalThis.fetch = (async () => {
      requestCount += 1
      if (requestCount === 1) {
        return Response.json(runSnapshot("queued"), { status: 201 })
      }
      return ndjsonResponse([
        JSON.stringify({
          type: "run",
          sequence: 0,
          run: runSnapshot("running"),
        }),
        JSON.stringify({ type: "answer_delta", delta: "hello" }),
        JSON.stringify({
          type: "complete",
          sequence: 3,
          run: runSnapshot("succeeded"),
        }),
      ])
    }) as unknown as typeof fetch

    await streamAgentRun("token", "ws-1", "agent-1", "question", (event) =>
      events.push(event)
    )
    expect(events.map((event) => event.type)).toEqual([
      "run",
      "run",
      "answer_delta",
      "complete",
    ])
  })

  test("reconnects from the last durable event cursor", async () => {
    const urls: string[] = []
    let requestCount = 0
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      urls.push(String(input))
      requestCount += 1
      if (requestCount === 1) {
        return Response.json(runSnapshot("queued"), { status: 201 })
      }
      if (requestCount === 2) {
        return ndjsonResponse([
          JSON.stringify({
            type: "process",
            sequence: 7,
            event: {
              type: "thought",
              turn: 1,
              tool_name: "",
              status: "succeeded",
              summary: "agent.tools_selected",
              call_id: "",
              tool_label: "",
              tool_kind: "unknown",
              server_name: "",
              input: {},
              output: null,
              duration_ms: 0,
            },
          }),
          JSON.stringify({
            type: "answer_delta",
            live_sequence: "1700000000000-0",
            stream_epoch: "worker-1",
            delta: "partial",
          }),
        ])
      }
      return ndjsonResponse([
        JSON.stringify({
          type: "complete",
          sequence: 8,
          run: runSnapshot("succeeded"),
        }),
      ])
    }) as unknown as typeof fetch

    await streamAgentRun("token", "ws-1", "agent-1", "question", () => {})
    expect(urls[2]).toContain("after=7")
    expect(urls[2]).toContain("live_after=1700000000000-0")
  })

  test("reconnects after a truncated final NDJSON line", async () => {
    const urls: string[] = []
    const events: AgentRunStreamEvent[] = []
    let requestCount = 0
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      urls.push(String(input))
      requestCount += 1
      if (requestCount === 1) {
        return Response.json(runSnapshot("queued"), { status: 201 })
      }
      if (requestCount === 2) {
        return rawStreamResponse([
          `${JSON.stringify({
            type: "process",
            sequence: 7,
            event: {
              type: "thought",
              turn: 1,
              tool_name: "",
              status: "succeeded",
              summary: "agent.answer_ready",
              call_id: "",
              tool_label: "",
              tool_kind: "unknown",
              server_name: "",
              input: {},
              output: null,
              duration_ms: 0,
            },
          })}\n`,
          '{"type":"complete"',
        ])
      }
      return ndjsonResponse([
        JSON.stringify({
          type: "complete",
          sequence: 8,
          run: runSnapshot("succeeded"),
        }),
      ])
    }) as unknown as typeof fetch

    await streamAgentRun("token", "ws-1", "agent-1", "question", (event) =>
      events.push(event)
    )

    expect(requestCount).toBe(3)
    expect(urls[2]).toContain("after=7")
    expect(events.at(-1)?.type).toBe("complete")
  })

  test("backs off retryable stream failures", async () => {
    const delays: number[] = []
    let requestCount = 0
    globalThis.setTimeout = ((callback: () => void, delay?: number) => {
      delays.push(delay ?? 0)
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout
    globalThis.fetch = (async () => {
      requestCount += 1
      if (requestCount === 1) {
        return Response.json(runSnapshot("queued"), { status: 201 })
      }
      if (requestCount < 4) return new Response("", { status: 503 })
      return ndjsonResponse([
        JSON.stringify({
          type: "complete",
          sequence: 1,
          run: runSnapshot("succeeded"),
        }),
      ])
    }) as unknown as typeof fetch

    await streamAgentRun("token", "ws-1", "agent-1", "question", () => {})
    expect(delays).toEqual([250, 500])
  })

  test("rejects on non-retryable stream responses", async () => {
    let requestCount = 0
    globalThis.fetch = (async () => {
      requestCount += 1
      return requestCount === 1
        ? Response.json(runSnapshot("queued"), { status: 201 })
        : new Response("", { status: 403 })
    }) as unknown as typeof fetch

    try {
      await streamAgentRun("token", "ws-1", "agent-1", "question", () => {})
      throw new Error("streamAgentRun should reject")
    } catch (error) {
      expect((error as Error).message).toContain("status 403")
    }
  })

  test("forwards the caller's abort signal to fetch", async () => {
    let receivedSignal: AbortSignal | null | undefined
    globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
      receivedSignal = init?.signal
      return Response.json(runSnapshot("succeeded"), { status: 201 })
    }) as unknown as typeof fetch

    const controller = new AbortController()
    await streamAgentRun(
      "token",
      "ws-1",
      "agent-1",
      "question",
      () => {},
      controller.signal
    )
    expect(receivedSignal?.aborted).toBe(false)
    controller.abort()
    expect(receivedSignal?.aborted).toBe(true)
  })
})

import { afterEach, describe, expect, test } from "bun:test"

import {
  AGENT_STREAM_TIMEOUT_MS,
  streamAgentRun,
  type AgentRun,
  type AgentRunStreamEvent,
} from "../lib/api/agents"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

function ndjsonResponse(lines: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream({
    start(controller) {
      for (const line of lines) {
        controller.enqueue(encoder.encode(`${line}\n`))
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
  }
}

describe("streamAgentRun", () => {
  test("delivers events and accepts a terminal complete event", async () => {
    const events: AgentRunStreamEvent[] = []
    globalThis.fetch = (async () =>
      ndjsonResponse([
        JSON.stringify({ type: "run", run: runSnapshot("running") }),
        JSON.stringify({ type: "answer_delta", delta: "hello" }),
        JSON.stringify({ type: "complete", run: runSnapshot("succeeded") }),
      ])) as unknown as typeof fetch

    await streamAgentRun("token", "ws-1", "agent-1", "question", (event) =>
      events.push(event)
    )
    expect(events.map((event) => event.type)).toEqual([
      "run",
      "answer_delta",
      "complete",
    ])
  })

  test("rejects when the stream ends without a terminal event", async () => {
    globalThis.fetch = (async () =>
      ndjsonResponse([
        JSON.stringify({ type: "run", run: runSnapshot("running") }),
      ])) as unknown as typeof fetch

    try {
      await streamAgentRun("token", "ws-1", "agent-1", "question", () => {})
      throw new Error("streamAgentRun should reject")
    } catch (error) {
      expect((error as Error).message).toContain(
        "ended without a completion event"
      )
    }
  })

  test("rejects on non-2xx responses", async () => {
    globalThis.fetch = (async () =>
      new Response("", { status: 500 })) as unknown as typeof fetch

    try {
      await streamAgentRun("token", "ws-1", "agent-1", "question", () => {})
      throw new Error("streamAgentRun should reject")
    } catch (error) {
      expect((error as Error).message).toContain("status 500")
    }
  })

  test("forwards the caller's abort signal to fetch", async () => {
    let receivedSignal: AbortSignal | null | undefined
    globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
      receivedSignal = init?.signal
      return ndjsonResponse([
        JSON.stringify({ type: "complete", run: runSnapshot("succeeded") }),
      ])
    }) as unknown as typeof fetch

    const controller = new AbortController()
    await streamAgentRun(
      "token",
      "ws-1",
      "agent-1",
      "question",
      () => {},
      false,
      controller.signal
    )
    expect(receivedSignal?.aborted).toBe(false)
    controller.abort()
    expect(receivedSignal?.aborted).toBe(true)
  })

  test("exposes a finite stream timeout", () => {
    expect(AGENT_STREAM_TIMEOUT_MS).toBeGreaterThan(0)
    expect(AGENT_STREAM_TIMEOUT_MS).toBeLessThanOrEqual(300_000)
  })
})

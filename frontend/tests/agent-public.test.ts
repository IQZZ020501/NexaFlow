import { afterEach, describe, expect, test } from "bun:test"

import { appViewPath, parseAgentDetailView } from "../lib/agent-views"
import {
  cancelPublicAgentStream,
  mergePublicRunEvent,
} from "../components/agents/public-agent-chat"
import {
  initializePublicAgent,
  observePublicAgentRun,
} from "../lib/api/public-agents"
import { getAgent, getAgentApiDocumentation } from "../lib/api/agents"

const originalFetch = globalThis.fetch
const originalSetTimeout = globalThis.setTimeout

afterEach(() => {
  globalThis.fetch = originalFetch
  globalThis.setTimeout = originalSetTimeout
})

describe("public agent API", () => {
  test("loads an Agent directly for a deep detail link", async () => {
    let requestedUrl = ""
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      requestedUrl = String(input)
      return Response.json({})
    }) as unknown as typeof fetch

    await getAgent("token", "workspace-1", "agent-51")

    expect(requestedUrl).toContain(
      "/api/v1/workspaces/workspace-1/agents/agent-51"
    )
  })

  test("unlocks only the requested Agent documentation with its API key", async () => {
    let requestedUrl = ""
    let authorization = ""
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      requestedUrl = String(input)
      authorization = new Headers(init?.headers).get("Authorization") ?? ""
      return Response.json({
        agent_id: "agent-1",
        agent_name: "Support",
        base_path: "/api/v1/agent-api/agent-1",
      })
    }) as unknown as typeof fetch

    await getAgentApiDocumentation("agent-1", "nxf_agent_key")

    expect(requestedUrl).toContain(
      "/api/v1/agent-api/agent-1/documentation"
    )
    expect(authorization).toBe("Bearer nxf_agent_key")
  })

  test("clears an interrupted stream before switching conversations", () => {
    const controller = new AbortController()
    const streamRef = { current: controller }

    cancelPublicAgentStream(streamRef)

    expect(streamRef.current).toBeNull()
    expect(controller.signal.aborted).toBe(true)
  })

  test("keeps stream epochs and resets text after worker takeover", () => {
    const run = {
      id: "run-1",
      conversation_id: "conversation-1",
      question: "hello",
      status: "running",
      result: "Hello",
      error: null,
      progress: [],
      created_at: "2026-08-10T00:00:00Z",
      started_at: null,
      finished_at: null,
      updated_at: "2026-08-10T00:00:00Z",
      live_stream_epoch: "worker-1",
      live_stream_cursor: "1700000000000-1",
    }
    const duplicate = mergePublicRunEvent(
      [run],
      run.id,
      {
        type: "answer_delta",
        stream_epoch: "worker-1",
        live_sequence: "1700000000000-1",
        delta: " duplicate",
      },
      "pending-1"
    )[0]
    expect(duplicate.result).toBe("Hello")

    const takenOver = mergePublicRunEvent(
      [duplicate],
      run.id,
      {
        type: "answer_delta",
        stream_epoch: "worker-2",
        live_sequence: "1700000000001-0",
        delta: "Restarted",
      },
      "pending-1"
    )[0]
    expect(takenOver.result).toBe("Restarted")
    expect(takenOver.live_stream_epoch).toBe("worker-2")

    const completed = mergePublicRunEvent(
      [takenOver],
      run.id,
      {
        type: "complete",
        sequence: 2,
        live_sequence: "1700000000002-0",
        stream_epoch: "worker-2",
        run: { ...takenOver, status: "succeeded", result: "Restarted answer" },
      },
      "pending-1"
    )[0]
    expect(completed.live_stream_epoch).toBe("worker-2")
    expect(completed.live_stream_cursor).toBe("1700000000002-0")
  })

  test("updates the sanitized public execution timeline", () => {
    const run = {
      id: "run-1",
      conversation_id: "conversation-1",
      question: "hello",
      status: "running",
      result: "",
      error: null,
      progress: [],
      created_at: "2026-08-10T00:00:00Z",
      started_at: null,
      finished_at: null,
      updated_at: "2026-08-10T00:00:00Z",
    }
    const running = mergePublicRunEvent(
      [run],
      run.id,
      {
        type: "progress",
        sequence: 1,
        event: {
          id: "knowledge-1",
          type: "knowledge",
          status: "running",
          stage: "running",
          turn: 1,
          count: null,
          hits: [],
        },
      },
      "pending-1"
    )[0]
    const succeeded = mergePublicRunEvent(
      [running],
      run.id,
      {
        type: "progress",
        sequence: 2,
        event: {
          id: "knowledge-1",
          type: "knowledge",
          status: "succeeded",
          stage: "succeeded",
          turn: 1,
          count: 3,
          hits: [],
        },
      },
      "pending-1"
    )[0]

    expect(succeeded.progress).toHaveLength(1)
    expect(succeeded.progress[0]).toMatchObject({
      status: "succeeded",
      count: 3,
    })
  })

  test("accumulates reasoning deltas onto the analysis progress", () => {
    const run = {
      id: "run-1",
      conversation_id: "conversation-1",
      question: "hello",
      status: "running",
      result: "",
      error: null,
      progress: [
        {
          id: "analysis-1",
          type: "analysis" as const,
          status: "running" as const,
          stage: "analyzing" as const,
          turn: 1,
          count: null,
          hits: [],
        },
      ],
      created_at: "2026-08-10T00:00:00Z",
      started_at: null,
      finished_at: null,
      updated_at: "2026-08-10T00:00:00Z",
      live_stream_epoch: "worker-1",
      live_stream_cursor: "1700000000000-1",
    }
    const first = mergePublicRunEvent(
      [run],
      run.id,
      {
        type: "reasoning_delta",
        stream_epoch: "worker-1",
        live_sequence: "1700000000001-0",
        turn: 1,
        delta: "Let me",
      },
      "pending-1"
    )[0]
    expect(first.progress[0]?.reasoning).toBe("Let me")
    expect(first.live_stream_cursor).toBe("1700000000001-0")

    const second = mergePublicRunEvent(
      [first],
      run.id,
      {
        type: "reasoning_delta",
        stream_epoch: "worker-1",
        live_sequence: "1700000000002-0",
        turn: 1,
        delta: " think",
      },
      "pending-1"
    )[0]
    expect(second.progress[0]?.reasoning).toBe("Let me think")

    const stale = mergePublicRunEvent(
      [second],
      run.id,
      {
        type: "reasoning_delta",
        stream_epoch: "worker-1",
        live_sequence: "1700000000001-9",
        turn: 1,
        delta: " stale",
      },
      "pending-1"
    )[0]
    expect(stale.progress[0]?.reasoning).toBe("Let me think")

    const takenOver = mergePublicRunEvent(
      [stale],
      run.id,
      {
        type: "reasoning_delta",
        stream_epoch: "worker-2",
        live_sequence: "1700000000100-0",
        turn: 1,
        delta: "Restarted",
      },
      "pending-1"
    )[0]
    expect(takenOver.progress[0]?.reasoning).toBe("Restarted")
    expect(takenOver.live_stream_epoch).toBe("worker-2")
  })

  test("moves reasoning onto the answer event once the server snapshot arrives", () => {
    const run = {
      id: "run-1",
      conversation_id: "conversation-1",
      question: "hello",
      status: "running",
      result: "",
      error: null,
      progress: [
        {
          id: "analysis-1",
          type: "analysis" as const,
          status: "running" as const,
          stage: "analyzing" as const,
          turn: 1,
          count: null,
          reasoning: "Let me think",
          hits: [],
        },
      ],
      created_at: "2026-08-10T00:00:00Z",
      started_at: null,
      finished_at: null,
      updated_at: "2026-08-10T00:00:00Z",
    }
    const merged = mergePublicRunEvent(
      [run],
      run.id,
      {
        type: "progress",
        sequence: 1,
        event: {
          id: "answer-1",
          type: "answer",
          status: "succeeded",
          stage: "succeeded",
          turn: 1,
          count: null,
          reasoning: "Let me think",
          hits: [],
        },
      },
      "pending-1"
    )[0]

    expect(merged.progress).toHaveLength(2)
    expect(merged.progress[0]).toMatchObject({
      type: "analysis",
      reasoning: "",
    })
    expect(merged.progress[1]).toMatchObject({
      type: "answer",
      reasoning: "Let me think",
    })
  })

  test("falls back to overview for unknown detail views", () => {
    expect(parseAgentDetailView(undefined)).toBe("overview")
    expect(parseAgentDetailView("monitoring")).toBe("monitoring")
    expect(parseAgentDetailView(["users", "ignored"])).toBe("users")
    expect(parseAgentDetailView("unknown")).toBe("overview")
  })

  test("builds routes for every application detail view", () => {
    expect(appViewPath("workflow-1", "workflow", "settings")).toBe(
      "/workflow/workflow-1"
    )
    expect(appViewPath("workflow-1", "workflow", "overview")).toBe(
      "/app/apps/workflow-1"
    )
    expect(appViewPath("agent-1", "agent", "settings")).toBe(
      "/app/apps/agent-1/settings"
    )
    expect(appViewPath("agent-1", "agent", "logs")).toBe(
      "/app/apps/agent-1/logs"
    )
    expect(appViewPath("agent-1", "agent", "monitoring")).toBe(
      "/app/apps/agent-1/monitoring"
    )
    expect(appViewPath("agent-1", "agent", "users")).toBe(
      "/app/apps/agent-1/users"
    )
    expect(appViewPath("agent-1", "agent", "overview", "conversation-1")).toBe(
      "/app/apps/agent-1?conversation_id=conversation-1"
    )
    expect(
      appViewPath("agent-1", "agent", "settings", "conversation-1")
    ).toBe("/app/apps/agent-1/settings?conversation_id=conversation-1")
  })

  test("uses the overview route for unknown detail views", () => {
    expect(appViewPath("agent-1", "agent", parseAgentDetailView("unknown"))).toBe(
      "/app/apps/agent-1"
    )
  })

  test("loads the profile and conversations with the session token", async () => {
    const requests: Array<{
      url: string
      method: string
      auth: string | null
      credentials: RequestCredentials | undefined
    }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const headers = new Headers(init?.headers)
      requests.push({
        url: String(input),
        method: init?.method ?? "GET",
        auth: headers.get("Authorization"),
        credentials: init?.credentials,
      })
      return String(input).includes("/conversations")
        ? Response.json({ items: [], total: 0 })
        : Response.json({ id: "agent-1", name: "Public", description: "" })
    }) as unknown as typeof fetch

    await initializePublicAgent("agent-1", "access-token")

    expect(requests.map(({ method }) => method)).toEqual(["GET", "GET"])
    expect(requests.every(({ auth }) => auth === "Bearer access-token")).toBe(
      true
    )
    expect(
      requests.every(({ credentials }) => credentials === "include")
    ).toBe(true)
  })

  test("sends Authorization while reconnecting a public stream", async () => {
    const requests: Array<{ url: string; auth: string | null }> = []
    let streamRequest = 0
    globalThis.setTimeout = ((callback: () => void) => {
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      const headers = new Headers(init?.headers)
      requests.push({ url: String(input), auth: headers.get("Authorization") })
      if (
        String(input).includes("/runs") &&
        !String(input).includes("stream")
      ) {
        return Response.json({
          id: "run-1",
          conversation_id: "conversation-1",
          question: "hello",
          status: "running",
          result: "",
          error: null,
          created_at: "2026-08-10T00:00:00Z",
          started_at: null,
          finished_at: null,
          updated_at: "2026-08-10T00:00:00Z",
        })
      }
      streamRequest += 1
      if (streamRequest === 1) return new Response("", { status: 503 })
      const body = `${JSON.stringify({
        type: "complete",
        sequence: 4,
        run: {
          id: "run-1",
          conversation_id: "conversation-1",
          question: "hello",
          status: "succeeded",
          result: "done",
          error: null,
          created_at: "2026-08-10T00:00:00Z",
          started_at: null,
          finished_at: "2026-08-10T00:00:01Z",
          updated_at: "2026-08-10T00:00:01Z",
        },
      })}\n`
      return new Response(body, { status: 200 })
    }) as unknown as typeof fetch

    const events: string[] = []
    const response = await import("../lib/api/public-agents")
    await response.streamPublicAgentRun("agent-1", "access-token", "hello", (event) =>
      events.push(event.type)
    )

    expect(events).toEqual(["run", "complete"])
    expect(
      requests.every(({ auth }) => auth === "Bearer access-token")
    ).toBe(true)
    expect(requests.at(-1)?.url).toContain("after=0")
  })

  test("reconnects a public stream using the durable cursor", async () => {
    const urls: string[] = []
    let requestCount = 0
    globalThis.setTimeout = ((callback: () => void) => {
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      urls.push(String(input))
      requestCount += 1
      if (requestCount === 1) {
        return new Response(
          `${JSON.stringify({ type: "answer_delta", sequence: 9, delta: "part" })}\n`
        )
      }
      return new Response(
        `${JSON.stringify({
          type: "complete",
          sequence: 10,
          run: {
            id: "run-1",
            conversation_id: "conversation-1",
            question: "hello",
            status: "succeeded",
            result: "done",
            error: null,
            created_at: "2026-08-10T00:00:00Z",
            started_at: null,
            finished_at: null,
            updated_at: "2026-08-10T00:00:01Z",
          },
        })}\n`
      )
    }) as unknown as typeof fetch

    const events: string[] = []
    await observePublicAgentRun("agent-1", "access-token", "run-1", (event) =>
      events.push(event.type)
    )
    expect(events).toEqual(["answer_delta", "complete"])
    expect(urls[1]).toContain("after=9")
  })

  test("normalizes an immediately completed public run", async () => {
    globalThis.fetch = (async () =>
      Response.json(
        {
          id: "run-1",
          conversation_id: "conversation-1",
          question: "hello",
          status: "succeeded",
          result: "done",
          error: null,
          progress: [],
          created_at: "2026-08-10T00:00:00Z",
          started_at: null,
          finished_at: "2026-08-10T00:00:01Z",
          updated_at: "2026-08-10T00:00:01Z",
        },
        { status: 201 }
      )) as unknown as typeof fetch
    const events: string[] = []

    const response = await import("../lib/api/public-agents")
    await response.streamPublicAgentRun(
      "agent-1",
      "access-token",
      "hello",
      (event) => events.push(event.type)
    )

    expect(events).toEqual(["run", "complete"])
  })
})

/* @jsxImportSource react */
/**
 * Supplementary coverage for components/agents/public-agent-chat.tsx: run
 * regeneration and feedback (success, failure, and guard paths) plus extra
 * branches of the exported pure helpers.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react"

import {
  PublicAgentChat,
  cancelPublicAgentStream,
  hasPublicToolDetails,
  mergePublicRunEvent,
  publicToolName,
} from "@/components/agents/public-agent-chat"
import type {
  ExternalAgentProgressEvent,
  ExternalAgentRun,
  PublicAgentConversation,
  PublicAgentProfile,
} from "@/lib/api/public-agents"
import type { AgentToolCall } from "@/lib/api/agents"

import {
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  type FetchHandler,
} from "./helpers/dom"

/* ------------------------------------------------------------------ */
/* Fixtures                                                           */
/* ------------------------------------------------------------------ */

const PROFILE: PublicAgentProfile = {
  id: "agent-1",
  name: "公开助手",
  description: "这是一个公开助手。",
  interaction_config: {
    prologue: "",
    tts_type: "BROWSER",
    file_upload: true,
    file_upload_setting: { file_upload_type: ["document", "image"] },
    user_input_title: "",
  },
}

function conversation(id: string, question: string): PublicAgentConversation {
  return {
    conversation_id: id,
    question,
    status: "completed",
    result: "",
    run_count: 1,
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
  }
}

function run(overrides: Partial<ExternalAgentRun> = {}): ExternalAgentRun {
  return {
    id: "run-1",
    conversation_id: "conv-1",
    question: "你好",
    status: "succeeded",
    result: "回答内容",
    error: null,
    progress: [],
    created_at: "2026-08-10T00:00:00Z",
    started_at: "2026-08-10T00:00:00Z",
    finished_at: "2026-08-10T00:00:01Z",
    updated_at: "2026-08-10T00:00:01Z",
    ...overrides,
  }
}

const TOOL_CALL: AgentToolCall = {
  call_id: "call-1",
  turn: 1,
  tool_name: "web_search",
  tool_kind: "mcp",
  server_name: "Tavily",
  arguments: { query: "NexaFlow" },
  status: "awaiting_approval",
  approval_required: true,
  last_error: null,
  approved_at: null,
  started_at: null,
  finished_at: null,
}

function ndjsonResponse(events: unknown[]): Response {
  const body = events.map((event) => `${JSON.stringify(event)}\n`).join("")
  return new Response(body, { status: 200 })
}

/* ------------------------------------------------------------------ */
/* Test harness                                                       */
/* ------------------------------------------------------------------ */

const session = makeSession()
mockUseSession(session)
const replaced: string[] = []
mockNextNavigation({ replace: (href: string) => replaced.push(href) })

let fetchHandler: FetchHandler = () => jsonResponse({})
const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
  cleanup()
})
beforeEach(() => {
  Object.assign(session, { token: "test-token", isSessionRestored: true })
  replaced.length = 0
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    return Promise.resolve(fetchHandler(url, init))
  }) as typeof fetch
})

type AgentFetchRoutes = {
  profile?: unknown
  conversations?: { items: PublicAgentConversation[] }
  history?: { items: ExternalAgentRun[] } | (() => Response | Promise<Response>)
  streamResponses?: Array<() => Response | Promise<Response>>
  toolCalls?: () => Response | Promise<Response>
  resolveRun?: () => Response | Promise<Response>
}

function agentFetchHandler(routes: AgentFetchRoutes, requests: string[] = []) {
  let streamCalls = 0
  return (url: string, init?: RequestInit): Response | Promise<Response> => {
    const method = init?.method ?? "GET"
    requests.push(`${method} ${url}`)
    if (url.endsWith("/profile")) {
      return jsonResponse(routes.profile ?? PROFILE)
    }
    if (url.includes("/conversations")) {
      return jsonResponse(routes.conversations ?? { items: [] })
    }
    if (url.includes("/stream")) {
      const responses = routes.streamResponses ?? []
      const response = responses[streamCalls]
      streamCalls += 1
      return response
        ? response()
        : ndjsonResponse([
            {
              type: "complete",
              sequence: 1,
              run: run({ status: "succeeded", result: "完成" }),
            },
          ])
    }
    if (url.includes("/regenerate")) {
      return jsonResponse(
        run({
          id: "run-2",
          regenerated_from_run_id: "run-1",
          status: "queued",
          result: "",
        })
      )
    }
    if (url.includes("/feedback")) {
      return jsonResponse(run({ id: "run-1", feedback: "positive" }))
    }
    const decision = url.match(/\/tool-calls\/([^/]+)\/(approve|reject)$/)
    if (decision) {
      const respond =
        routes.resolveRun ??
        (() => jsonResponse(run({ status: "running", result: "" })))
      return respond()
    }
    if (url.includes("/tool-calls")) {
      const respond = routes.toolCalls ?? (() => jsonResponse([]))
      return respond()
    }
    if (url.includes("/runs")) {
      const history = routes.history
      return typeof history === "function"
        ? history()
        : jsonResponse(
            history ?? { items: [], total: 0, offset: 0, limit: 200 }
          )
    }
    return jsonResponse({})
  }
}

function articleOf(text: string): HTMLElement {
  const element = screen.getByText(text)
  const article = element.closest("article")
  if (!article) throw new Error(`article not found for ${text}`)
  return article as HTMLElement
}

/* ------------------------------------------------------------------ */
/* Pure helpers                                                        */
/* ------------------------------------------------------------------ */

describe("public chat pure helpers", () => {
  test("publicToolName prefers the label and falls back to the tool name", () => {
    const base = {
      id: "t1",
      type: "tool" as const,
      status: "succeeded" as const,
      stage: "succeeded" as const,
      turn: 1,
      count: null,
      hits: [],
    }
    expect(
      publicToolName({ ...base, tool_name: "web_search", tool_label: "Search" })
    ).toBe("Search")
    expect(publicToolName({ ...base, tool_name: "web_search" })).toBe(
      "web_search"
    )
    expect(publicToolName(base)).toBe("")
  })

  test("hasPublicToolDetails depends on type, status and payload", () => {
    const base = {
      id: "t1",
      turn: 1,
      count: null,
      hits: [],
    }
    const knowledge = (status: ExternalAgentProgressEvent["status"]) => ({
      ...base,
      type: "knowledge" as const,
      status,
      stage: status,
    })
    expect(hasPublicToolDetails(knowledge("succeeded"))).toBe(true)
    expect(hasPublicToolDetails(knowledge("failed"))).toBe(false)
    expect(
      hasPublicToolDetails({
        ...base,
        type: "tool",
        status: "succeeded",
        stage: "succeeded",
        input: { q: "x" },
        tool_name: "search",
      })
    ).toBe(true)
    expect(
      hasPublicToolDetails({
        ...base,
        type: "tool",
        status: "succeeded",
        stage: "succeeded",
        output: { ok: true },
        tool_name: "search",
      })
    ).toBe(true)
    expect(
      hasPublicToolDetails({
        ...base,
        type: "tool",
        status: "running",
        stage: "running",
        tool_name: "search",
        input: {},
      })
    ).toBe(false)
    expect(
      hasPublicToolDetails({
        ...base,
        type: "analysis",
        status: "running",
        stage: "analyzing",
      })
    ).toBe(false)
  })

  test("mergePublicRunEvent keeps placeholders live and other runs intact", () => {
    const placeholder = run({
      id: "pending-1",
      status: "running",
      result: "",
      progress: [],
    })
    const other = run({ id: "run-2", status: "running", result: "" })
    const snapshot = run({
      id: "run-1",
      status: "running",
      result: "",
      progress: [],
    })
    const merged = mergePublicRunEvent(
      [placeholder, other],
      "run-1",
      { type: "run", sequence: 1, run: snapshot },
      "pending-1"
    )
    expect(merged.map((item) => item.id)).toEqual(["run-1", "run-2"])
    expect(merged[1]).toBe(other)

    const withCursor = mergePublicRunEvent(
      [snapshot],
      "run-1",
      {
        type: "run",
        sequence: 2,
        stream_epoch: "w-1",
        live_sequence: "1000-0",
        run: run({ id: "run-1", status: "queued", result: "", progress: [] }),
      },
      "pending-1"
    )
    expect(withCursor[0].live_stream_epoch).toBe("w-1")
    expect(withCursor[0].live_stream_cursor).toBe("1000-0")
  })

  test("mergePublicRunEvent replaces progress by id and hands off reasoning", () => {
    const base = run({
      status: "running",
      result: "",
      progress: [
        {
          id: "a1",
          type: "analysis",
          status: "running",
          stage: "analyzing",
          turn: 1,
          count: null,
          reasoning: "Thinking",
          hits: [],
        },
      ],
    })
    const replaced = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "progress",
        sequence: 1,
        event: {
          id: "a1",
          type: "analysis",
          status: "succeeded",
          stage: "completed",
          turn: 1,
          count: null,
          reasoning: "Done thinking",
          hits: [],
        },
      },
      "pending-1"
    )
    expect(replaced[0].progress).toHaveLength(1)
    expect(replaced[0].progress[0].reasoning).toBe("Done thinking")

    const handedOff = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "progress",
        sequence: 2,
        event: {
          id: "ans-1",
          type: "answer",
          status: "succeeded",
          stage: "succeeded",
          turn: 1,
          count: null,
          reasoning: "Answer reasoning",
          hits: [],
        },
      },
      "pending-1"
    )
    expect(
      handedOff[0].progress.find(
        (item) => item.type === "analysis" && item.turn === 1
      )?.reasoning
    ).toBe("")
  })

  test("mergePublicRunEvent streams a preparing tool input after analysis", () => {
    const base = run({
      status: "running",
      result: "",
      progress: [
        {
          id: "analysis-1",
          type: "analysis",
          status: "succeeded",
          stage: "completed",
          turn: 1,
          count: null,
          reasoning: "Done thinking",
          hits: [],
        },
      ],
    })
    const first = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "tool_input_delta",
        id: "tool-1",
        live_sequence: "1000-1",
        stream_epoch: "worker-1",
        turn: 1,
        tool_name: "web_search",
        field: "query",
        delta: "release ",
        replace: false,
      },
      "pending-1"
    )
    expect(first[0].progress).toHaveLength(2)
    expect(first[0].progress[1]).toMatchObject({
      id: "tool-1",
      type: "tool",
      stage: "preparing",
      input: { query: "release " },
    })

    const second = mergePublicRunEvent(
      first,
      "run-1",
      {
        type: "tool_input_delta",
        id: "tool-1",
        live_sequence: "1000-2",
        stream_epoch: "worker-1",
        turn: 1,
        tool_name: "web_search",
        field: "query",
        delta: "notes",
        replace: false,
        input_truncated: true,
      },
      "pending-1"
    )
    expect(second[0].progress[1].input).toEqual({ query: "release notes" })
    expect(second[0].progress[1].input_truncated).toBe(true)
  })

  test("mergePublicRunEvent answers reset on a new stream epoch", () => {
    const base = run({
      status: "running",
      result: "Partial",
      live_stream_epoch: "w-1",
      live_stream_cursor: "1000-1",
    })
    const takeover = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "answer_delta",
        sequence: 2,
        stream_epoch: "w-2",
        live_sequence: "1000-2",
        delta: "fresh",
      },
      "pending-1"
    )
    expect(takeover[0].result).toBe("fresh")
    expect(takeover[0].live_stream_epoch).toBe("w-2")
    expect(takeover[0].live_stream_cursor).toBe("1000-2")

    const untouched = mergePublicRunEvent(
      [base],
      "run-9",
      { type: "answer_delta", sequence: 3, delta: "x" },
      "pending-1"
    )
    expect(untouched).toEqual([base])
  })

  test("mergePublicRunEvent reasoning deltas create and merge analysis rows", () => {
    const empty = run({ status: "running", result: "", progress: [] })
    const created = mergePublicRunEvent(
      [empty],
      "run-1",
      { type: "reasoning_delta", sequence: 1, turn: 1, delta: "Step 1" },
      "pending-1"
    )
    expect(created[0].progress).toHaveLength(1)
    expect(created[0].progress[0]).toMatchObject({
      type: "analysis",
      turn: 1,
      reasoning: "Step 1",
    })

    const appended = mergePublicRunEvent(
      created,
      "run-1",
      { type: "reasoning_delta", sequence: 2, turn: 1, delta: " Step 2" },
      "pending-1"
    )
    expect(appended[0].progress[0].reasoning).toBe("Step 1 Step 2")

    const stale = mergePublicRunEvent(
      [
        run({
          status: "running",
          result: "",
          progress: [],
          live_stream_epoch: "w-1",
          live_stream_cursor: "1000-5",
        }),
      ],
      "run-1",
      {
        type: "reasoning_delta",
        sequence: 3,
        stream_epoch: "w-1",
        live_sequence: "1000-4",
        turn: 1,
        delta: "old",
      },
      "pending-1"
    )
    expect(stale[0].progress).toEqual([])
  })

  test("mergePublicRunEvent approval and terminal events update only the target", () => {
    const runs = [
      run({ id: "run-1", status: "running", result: "" }),
      run({ id: "run-2", status: "running", result: "" }),
    ]
    const approval = mergePublicRunEvent(
      runs,
      "run-1",
      {
        type: "approval_required",
        sequence: 1,
        call_id: "call-1",
        reason: "needs approval",
      },
      "pending-1"
    )
    expect(approval[0].status).toBe("awaiting_approval")
    expect(approval[1]).toBe(runs[1])

    const terminal = mergePublicRunEvent(
      approval,
      "run-1",
      {
        type: "complete",
        sequence: 2,
        run: run({ id: "run-1", status: "succeeded", result: "final" }),
      },
      "pending-1"
    )
    expect(terminal[0].result).toBe("final")
    expect(terminal[0].live_stream_epoch).toBeUndefined()
  })

  test("cancelPublicAgentStream aborts the active controller and clears the ref", () => {
    const controller = new AbortController()
    const ref = { current: controller }
    cancelPublicAgentStream(ref)
    expect(controller.signal.aborted).toBe(true)
    expect(ref.current).toBeNull()

    const emptyRef = { current: null }
    cancelPublicAgentStream(emptyRef)
    expect(emptyRef.current).toBeNull()
  })
})

/* ------------------------------------------------------------------ */
/* UI: timestamps                                                      */
/* ------------------------------------------------------------------ */

describe("PublicAgentChat timestamps", () => {
  test("shows the submit and first-token timestamps below the messages", async () => {
    const historyRun = run({
      created_at: "2026-08-10T00:00:00Z",
      progress: [
        {
          id: "answer-1",
          type: "answer",
          status: "succeeded",
          stage: "succeeded",
          turn: 1,
          count: null,
          hits: [],
          created_at: "2026-08-10T00:00:01Z",
        },
      ],
    })
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: { items: [historyRun] },
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("回答内容")
    const article = articleOf("回答内容")
    const timestamps = article.querySelectorAll("time")

    expect(timestamps).toHaveLength(2)
    expect(timestamps[0]?.getAttribute("datetime")).toBe(historyRun.created_at)
    expect(timestamps[1]?.getAttribute("datetime")).toBe(
      "2026-08-10T00:00:01Z"
    )
  })
})

/* ------------------------------------------------------------------ */
/* UI: regenerate                                                      */
/* ------------------------------------------------------------------ */

describe("PublicAgentChat regeneration", () => {
  test("regenerates a run and renders the streamed replacement", async () => {
    const requests: string[] = []
    fetchHandler = agentFetchHandler(
      {
        conversations: { items: [conversation("conv-1", "第一个会话")] },
        history: {
          items: [run({ result: "Original answer" })],
        },
        streamResponses: [
          () =>
            ndjsonResponse([
              {
                type: "complete",
                sequence: 1,
                run: run({
                  id: "run-2",
                  regenerated_from_run_id: "run-1",
                  status: "succeeded",
                  result: "Regenerated answer",
                }),
              },
            ]),
        ],
      },
      requests
    )
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    fireEvent.click(
      within(articleOf("Original answer")).getByRole("button", {
        name: "重新生成",
      })
    )
    await waitFor(() =>
      expect(screen.getByText("Regenerated answer")).toBeTruthy()
    )
    expect(
      requests.some(
        (request) =>
          request === "POST /api/v1/public/agents/agent-1/runs/run-1/regenerate"
      )
    ).toBe(true)
    expect(
      requests.some((request) =>
        request.startsWith(
          "GET /api/v1/public/agents/agent-1/runs/run-2/stream"
        )
      )
    ).toBe(true)
    expect(
      (
        within(articleOf("Regenerated answer")).getByRole("button", {
          name: "重新生成",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false)
  })

  test("restores the previous answer and surfaces the error when the regenerated run fails", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [run({ result: "Original answer" })],
      },
      streamResponses: [
        () =>
          ndjsonResponse([
            {
              type: "error",
              sequence: 1,
              run: run({
                id: "run-2",
                regenerated_from_run_id: "run-1",
                status: "failed",
                result: "",
                error: "regeneration exploded",
              }),
            },
          ]),
      ],
    })
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    fireEvent.click(
      within(articleOf("Original answer")).getByRole("button", {
        name: "重新生成",
      })
    )
    await waitFor(() =>
      expect(screen.getByText("regeneration exploded")).toBeTruthy()
    )
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
  })

  test("restores the previous answer when observing regeneration fails", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [run({ result: "Original answer" })],
      },
      streamResponses: [() => jsonResponse({ detail: "stream boom" }, 404)],
    })
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    fireEvent.click(
      within(articleOf("Original answer")).getByRole("button", {
        name: "重新生成",
      })
    )
    await waitFor(() =>
      expect(screen.getByText(/failed with status 404/)).toBeTruthy()
    )
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
  })

  test("reports an error when the regenerate request fails", async () => {
    let regenerateCalls = 0
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [run({ result: "Original answer" })],
      },
      streamResponses: [() => jsonResponse({ detail: "unused" }, 500)],
    })
    const original = fetchHandler
    fetchHandler = (url: string, init?: RequestInit) => {
      if (url.endsWith("/regenerate")) {
        regenerateCalls += 1
        return jsonResponse({ detail: "regenerate boom" }, 500)
      }
      return original(url, init)
    }
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    fireEvent.click(
      within(articleOf("Original answer")).getByRole("button", {
        name: "重新生成",
      })
    )
    await waitFor(() =>
      expect(screen.getByText("regenerate boom")).toBeTruthy()
    )
    expect(regenerateCalls).toBe(1)
    expect(screen.getByText("Original answer")).toBeTruthy()
  })

  test("ignores regenerate while feedback is pending", async () => {
    let resolveFeedback: (value: Response) => void = () => undefined
    let regenerateCalls = 0
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({ id: "run-1", result: "First answer" }),
          run({ id: "run-2", result: "Second answer" }),
        ],
      },
    })
    const original = fetchHandler
    fetchHandler = (url: string, init?: RequestInit) => {
      if (url.endsWith("/runs/run-1/feedback")) {
        return new Promise<Response>((resolve) => {
          resolveFeedback = resolve
        })
      }
      if (url.endsWith("/runs/run-2/regenerate")) {
        regenerateCalls += 1
        return jsonResponse(run({ id: "run-2", status: "queued", result: "" }))
      }
      return original(url, init)
    }
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() => expect(screen.getByText("First answer")).toBeTruthy())

    fireEvent.click(
      within(articleOf("First answer")).getByRole("button", { name: "点赞" })
    )
    await waitFor(() =>
      expect(
        (
          within(articleOf("First answer")).getByRole("button", {
            name: "取消点赞",
          }) as HTMLButtonElement
        ).disabled
      ).toBe(true)
    )
    fireEvent.click(
      within(articleOf("Second answer")).getByRole("button", {
        name: "重新生成",
      })
    )
    expect(regenerateCalls).toBe(0)

    resolveFeedback!(jsonResponse(run({ id: "run-1", feedback: "positive" })))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点赞" })).toBeTruthy()
    )
  })

  test("ignores regenerate while a resumed run is still observed", async () => {
    let regenerateCalls = 0
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({
            id: "run-1",
            status: "awaiting_approval",
            result: "",
            error: null,
          }),
        ],
      },
      toolCalls: () => jsonResponse([TOOL_CALL]),
      resolveRun: () =>
        jsonResponse(
          run({ id: "run-1", status: "succeeded", result: "Approved answer" })
        ),
      streamResponses: [
        () => new Promise<Response>(() => undefined),
        () => new Promise<Response>(() => undefined),
      ],
    })
    const original = fetchHandler
    fetchHandler = (url: string, init?: RequestInit) => {
      if (url.endsWith("/regenerate")) {
        regenerateCalls += 1
        return jsonResponse(run({ id: "run-1", status: "queued", result: "" }))
      }
      return original(url, init)
    }
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("工具调用需要确认")).toBeTruthy()
    )
    fireEvent.click(screen.getByText("批准并执行").closest("button")!)
    await waitFor(() =>
      expect(screen.getByText("Approved answer")).toBeTruthy()
    )

    fireEvent.click(
      within(articleOf("Approved answer")).getByRole("button", {
        name: "重新生成",
      })
    )
    expect(regenerateCalls).toBe(0)
  })
})

/* ------------------------------------------------------------------ */
/* UI: feedback                                                        */
/* ------------------------------------------------------------------ */

describe("PublicAgentChat feedback", () => {
  test("applies positive feedback from the server", async () => {
    const requests: string[] = []
    fetchHandler = agentFetchHandler(
      {
        conversations: { items: [conversation("conv-1", "第一个会话")] },
        history: {
          items: [run({ result: "Original answer" })],
        },
      },
      requests
    )
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    fireEvent.click(
      within(articleOf("Original answer")).getByRole("button", {
        name: "点赞",
      })
    )
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点赞" })).toBeTruthy()
    )
    expect(
      requests.includes(
        "POST /api/v1/public/agents/agent-1/runs/run-1/feedback"
      )
    ).toBe(true)
  })

  test("toggles to negative feedback", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [run({ result: "Original answer" })],
      },
    })
    const original = fetchHandler
    fetchHandler = (url: string, init?: RequestInit) => {
      if (url.endsWith("/feedback")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as {
          value?: string
        }
        return jsonResponse(
          run({
            id: "run-1",
            result: "Original answer",
            feedback: body.value as "positive" | "negative",
          })
        )
      }
      return original(url, init)
    }
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    const article = articleOf("Original answer")
    fireEvent.click(within(article).getByRole("button", { name: "点赞" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点赞" })).toBeTruthy()
    )
    fireEvent.click(
      within(articleOf("Original answer")).getByRole("button", {
        name: "点踩",
      })
    )
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点踩" })).toBeTruthy()
    )
  })

  test("reverts feedback and surfaces an error when the request fails", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [run({ result: "Original answer" })],
      },
    })
    const original = fetchHandler
    fetchHandler = (url: string, init?: RequestInit) => {
      if (url.endsWith("/feedback")) {
        return jsonResponse({ detail: "feedback boom" }, 500)
      }
      return original(url, init)
    }
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    const article = articleOf("Original answer")
    fireEvent.click(within(article).getByRole("button", { name: "点赞" }))
    await waitFor(() => expect(screen.getByText("feedback boom")).toBeTruthy())
    expect(
      within(articleOf("Original answer")).getByRole("button", {
        name: "点赞",
      })
    ).toBeTruthy()
  })

  test("ignores feedback while another feedback request is pending", async () => {
    let resolveFirst: (value: Response) => void = () => undefined
    let secondCalls = 0
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({ id: "run-1", result: "First answer" }),
          run({ id: "run-2", result: "Second answer" }),
        ],
      },
    })
    const original = fetchHandler
    fetchHandler = (url: string, init?: RequestInit) => {
      if (url.endsWith("/runs/run-1/feedback")) {
        return new Promise<Response>((resolve) => {
          resolveFirst = resolve
        })
      }
      if (url.endsWith("/runs/run-2/feedback")) {
        secondCalls += 1
        return jsonResponse(run({ id: "run-2", feedback: "negative" }))
      }
      return original(url, init)
    }
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() => expect(screen.getByText("First answer")).toBeTruthy())

    fireEvent.click(
      within(articleOf("First answer")).getByRole("button", { name: "点赞" })
    )
    await waitFor(() =>
      expect(
        (
          within(articleOf("First answer")).getByRole("button", {
            name: "取消点赞",
          }) as HTMLButtonElement
        ).disabled
      ).toBe(true)
    )
    fireEvent.click(
      within(articleOf("Second answer")).getByRole("button", { name: "点赞" })
    )
    expect(secondCalls).toBe(0)

    resolveFirst!(jsonResponse(run({ id: "run-1", feedback: "positive" })))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点赞" })).toBeTruthy()
    )
  })

  test("ignores feedback on other runs while regenerating", async () => {
    let feedbackCalls = 0
    let resolveRegenerate: (value: Response) => void = () => undefined
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({ id: "run-1", result: "First answer" }),
          run({ id: "run-2", result: "Second answer" }),
        ],
      },
      streamResponses: [
        () =>
          ndjsonResponse([
            {
              type: "complete",
              sequence: 1,
              run: run({
                id: "run-3",
                regenerated_from_run_id: "run-1",
                status: "succeeded",
                result: "Regenerated answer",
              }),
            },
          ]),
      ],
    })
    const original = fetchHandler
    fetchHandler = (url: string, init?: RequestInit) => {
      if (url.endsWith("/runs/run-1/regenerate")) {
        return new Promise<Response>((resolve) => {
          resolveRegenerate = resolve
        })
      }
      if (url.includes("/feedback")) {
        feedbackCalls += 1
        return jsonResponse(run({ id: "run-2", feedback: "positive" }))
      }
      return original(url, init)
    }
    renderPage(<PublicAgentChat agentId="agent-1" />)
    await waitFor(() => expect(screen.getByText("First answer")).toBeTruthy())

    fireEvent.click(
      within(articleOf("First answer")).getByRole("button", {
        name: "重新生成",
      })
    )
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "正在重新生成" })).toBeTruthy()
    )
    fireEvent.click(
      within(articleOf("Second answer")).getByRole("button", { name: "点赞" })
    )
    expect(feedbackCalls).toBe(0)

    resolveRegenerate!(
      jsonResponse(
        run({
          id: "run-3",
          regenerated_from_run_id: "run-1",
          status: "queued",
          result: "",
        })
      )
    )
    await waitFor(() =>
      expect(screen.getByText("Regenerated answer")).toBeTruthy()
    )
  })
})

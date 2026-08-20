/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { ApiError } from "@/lib/api-client"
import {
  createPublicAgentRun,
  getPublicAgentProfile,
  getPublicAgentRun,
  initializePublicAgent,
  listPublicAgentConversations,
  listPublicAgentRunToolCalls,
  listPublicAgentRuns,
  observePublicAgentRun,
  regeneratePublicAgentRun,
  resolvePublicAgentRunToolCall,
  setPublicAgentRunFeedback,
  streamPublicAgentRun,
  uploadPublicAgentFiles,
} from "@/lib/api/public-agents"
import {
  jsonResponse,
  resetFetch,
  withFetch,
} from "./helpers/dom"

const originalSetTimeout = globalThis.setTimeout

afterEach(() => {
  resetFetch()
  globalThis.setTimeout = originalSetTimeout
})

type CapturedRequest = {
  url: string
  method: string
  body: unknown
  authorization: string | null
}

function capture(): CapturedRequest[] {
  const requests: CapturedRequest[] = []
  withFetch((url, init) => {
    requests.push({
      url,
      method: init?.method ?? "GET",
      body:
        init?.body instanceof FormData
          ? init.body
          : init?.body
            ? JSON.parse(String(init.body))
            : undefined,
      authorization: new Headers(init?.headers).get("Authorization"),
    })
    return jsonResponse({})
  })
  return requests
}

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

const interactionConfig = {
  prologue: "",
  tts_type: "NONE" as const,
  file_upload: false,
  file_upload_setting: { file_upload_type: ["document"] as Array<"document" | "image" | "audio"> },
  user_input_title: "输入",
}

const profile = {
  id: "agent-1",
  name: "Support Agent",
  description: "Answers support questions",
  interaction_config: interactionConfig,
}

const conversations = {
  items: [
    {
      conversation_id: "conv-1",
      question: "Hi",
      status: "succeeded",
      result: "Hello",
      run_count: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
}

describe("public agent API", () => {
  test("loads public agent profiles and conversations", async () => {
    const urls: string[] = []
    withFetch((url) => {
      urls.push(url)
      return jsonResponse(url.endsWith("/profile") ? profile : conversations)
    })

    await expect(
      getPublicAgentProfile("agent-1", "token-1")
    ).resolves.toEqual(profile)
    await expect(
      listPublicAgentConversations("agent-1", "token-1")
    ).resolves.toEqual(conversations)
    const initialized = await initializePublicAgent("agent-1", "token-1")

    expect(urls).toEqual([
      "/api/v1/public/agents/agent-1/profile",
      "/api/v1/public/agents/agent-1/conversations",
      "/api/v1/public/agents/agent-1/profile",
      "/api/v1/public/agents/agent-1/conversations",
    ])
    expect(initialized).toEqual({ profile, conversations })
  })

  test("paginates public agent runs by conversation", async () => {
    const requests = capture()

    await listPublicAgentRuns("agent-1", "conv-1", "token-1")
    await listPublicAgentRuns("agent-1", "conv-1", "token-1", {
      limit: 20,
      offset: 5,
    })

    expect(requests.map(({ url }) => url)).toEqual([
      "/api/v1/public/agents/agent-1/runs?conversation_id=conv-1",
      "/api/v1/public/agents/agent-1/runs?limit=20&offset=5&conversation_id=conv-1",
    ])
  })

  test("creates public agent runs with conversation and file context", async () => {
    const requests = capture()

    await createPublicAgentRun("agent-1", "token-1", "research")
    await createPublicAgentRun(
      "agent-1",
      "token-1",
      "continue research",
      "conv-1",
      undefined,
      ["file-1"]
    )

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["POST", "/api/v1/public/agents/agent-1/runs"],
      ["POST", "/api/v1/public/agents/agent-1/runs"],
    ])
    expect(requests[0]?.body).toEqual({ goal: "research" })
    expect(requests[1]?.body).toEqual({
      goal: "continue research",
      conversation_id: "conv-1",
      file_ids: ["file-1"],
    })
  })

  test("uploads public agent attachments as form data", async () => {
    const requests: Array<{ url: string; body: BodyInit | null | undefined }> =
      []
    withFetch((url, init) => {
      requests.push({ url, body: init?.body })
      return jsonResponse([
        {
          id: "upload-1",
          filename: "doc.pdf",
          content_type: "application/pdf",
          size_bytes: 4,
          category: "document",
        },
      ])
    })

    const files = [new File(["data"], "doc.pdf", { type: "application/pdf" })]
    const uploaded = await uploadPublicAgentFiles(
      "agent-1",
      "token-1",
      files
    )

    expect(requests[0]?.url).toBe("/api/v1/public/agents/agent-1/uploads")
    expect(requests[0]?.body).toBeInstanceOf(FormData)
    expect((requests[0]?.body as FormData).getAll("files")).toEqual(files)
    expect(uploaded).toEqual([
      {
        id: "upload-1",
        filename: "doc.pdf",
        content_type: "application/pdf",
        size_bytes: 4,
        category: "document",
      },
    ])
  })

  test("regenerates, rates, and resolves public agent runs", async () => {
    const requests = capture()

    await getPublicAgentRun("agent-1", "token-1", "run-1")
    await regeneratePublicAgentRun("agent-1", "token-1", "run-1")
    await setPublicAgentRunFeedback("agent-1", "token-1", "run-1", "positive")
    await setPublicAgentRunFeedback("agent-1", "token-1", "run-1", null)
    await listPublicAgentRunToolCalls("agent-1", "token-1", "run-1")
    await resolvePublicAgentRunToolCall(
      "agent-1",
      "token-1",
      "run-1",
      "call-1",
      "approve"
    )
    await resolvePublicAgentRunToolCall(
      "agent-1",
      "token-1",
      "run-1",
      "call-1",
      "reject"
    )

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["GET", "/api/v1/public/agents/agent-1/runs/run-1"],
      ["POST", "/api/v1/public/agents/agent-1/runs/run-1/regenerate"],
      ["POST", "/api/v1/public/agents/agent-1/runs/run-1/feedback"],
      ["POST", "/api/v1/public/agents/agent-1/runs/run-1/feedback"],
      ["GET", "/api/v1/public/agents/agent-1/runs/run-1/tool-calls"],
      ["POST", "/api/v1/public/agents/agent-1/runs/run-1/tool-calls/call-1/approve"],
      ["POST", "/api/v1/public/agents/agent-1/runs/run-1/tool-calls/call-1/reject"],
    ])
    expect(requests[2]?.body).toEqual({ value: "positive" })
    expect(requests[3]?.body).toEqual({ value: null })
  })

  test("observes public agent run streams", async () => {
    const urls: string[] = []
    globalThis.setTimeout = ((callback: () => void) => {
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout
    withFetch((url) => {
      urls.push(url)
      return ndjsonResponse([
        {
          type: "answer_delta",
          live_sequence: "1700000000000-0",
          stream_epoch: "worker-1",
          delta: "hi",
        },
        { type: "complete", sequence: 2, run: { id: "run-1" } },
      ])
    })

    const eventTypes: string[] = []
    await observePublicAgentRun(
      "agent-1",
      "token-1",
      "run-1",
      (event) => eventTypes.push(event.type)
    )

    expect(eventTypes).toEqual(["answer_delta", "complete"])
    expect(urls[0]).toContain(
      "/public/agents/agent-1/runs/run-1/stream?after=0&live_after=0-0"
    )
  })

  test("streams public agent runs to terminal completion", async () => {
    const run = (status: string) => ({
      id: "run-1",
      conversation_id: "conv-1",
      question: "q",
      status,
      result: "",
      error: null,
      progress: [],
      created_at: "2026-01-01T00:00:00Z",
      started_at: null,
      finished_at: null,
      updated_at: "2026-01-01T00:00:00Z",
    })
    const install = (status: string, streamEvents: object[] = []) => {
      const urls: string[] = []
      withFetch((url, init) => {
        urls.push(url)
        return init?.method === "POST"
          ? jsonResponse(run(status))
          : ndjsonResponse(streamEvents)
      })
      return urls
    }
    globalThis.setTimeout = ((callback: () => void) => {
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout

    const succeededUrls = install("succeeded")
    const succeededEvents: string[] = []
    await streamPublicAgentRun(
      "agent-1",
      "token-1",
      "q",
      (event) => succeededEvents.push(event.type)
    )
    expect(succeededEvents).toEqual(["run", "complete"])
    expect(succeededUrls).toHaveLength(1)

    const failedEvents: string[] = []
    install("failed")
    await streamPublicAgentRun(
      "agent-1",
      "token-1",
      "q",
      (event) => failedEvents.push(event.type)
    )
    expect(failedEvents).toEqual(["run", "error"])

    const cancelledEvents: string[] = []
    install("cancelled")
    await streamPublicAgentRun(
      "agent-1",
      "token-1",
      "q",
      (event) => cancelledEvents.push(event.type)
    )
    expect(cancelledEvents).toEqual(["run", "error"])

    const queuedEvents: string[] = []
    const queuedUrls = install("queued", [
      { type: "complete", sequence: 1, run: {} },
    ])
    await streamPublicAgentRun(
      "agent-1",
      "token-1",
      "q",
      (event) => queuedEvents.push(event.type)
    )
    expect(queuedEvents).toEqual(["run", "complete"])
    expect(queuedUrls).toHaveLength(2)
    expect(queuedUrls[1]).toContain("/runs/run-1/stream?after=0")
  })

  test("surfaces non-2xx public agent responses as API errors", async () => {
    withFetch(() => jsonResponse({ detail: "Agent not found." }, 404))

    try {
      await getPublicAgentProfile("agent-1", "token-1")
      throw new Error("request should fail")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(404)
      expect((error as ApiError).message).toBe("Agent not found.")
    }
  })
})

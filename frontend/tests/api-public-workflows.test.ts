/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { ApiError } from "@/lib/api-client"
import {
  createPublicWorkflowRun,
  deletePublicWorkflowConversation,
  getPublicWorkflowProfile,
  getWorkflowApiDocumentation,
  initializePublicWorkflow,
  listPublicWorkflowConversations,
  listPublicWorkflowRuns,
  observePublicWorkflowRun,
  regeneratePublicWorkflowRun,
  setPublicWorkflowRunFeedback,
  submitPublicWorkflowForm,
  uploadPublicWorkflowFiles,
} from "@/lib/api/public-workflows"
import { jsonResponse, resetFetch, withFetch } from "./helpers/dom"

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
  file_upload_setting: {
    file_upload_type: ["document"] as Array<"document" | "image" | "audio">,
  },
  user_input_title: "输入",
}

const profile = {
  id: "wf-1",
  name: "Onboarding",
  description: "Guides new users",
  interaction_config: interactionConfig,
}

const conversations = {
  items: [
    {
      conversation_id: "conv-1",
      inputs: {},
      outputs: {},
      status: "succeeded",
      run_count: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
}

describe("public workflow API", () => {
  test("lists and deletes a public workflow conversation", async () => {
    const requests = capture()

    await listPublicWorkflowConversations("wf-1", "token-1")
    await deletePublicWorkflowConversation("wf-1", "conv-1", "token-1")

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["GET", "/api/v1/public/workflows/wf-1/conversations"],
      ["DELETE", "/api/v1/public/workflows/wf-1/conversations/conv-1"],
    ])
  })

  test("loads public workflow profiles and conversations", async () => {
    const urls: string[] = []
    withFetch((url) => {
      urls.push(url)
      return jsonResponse(url.endsWith("/profile") ? profile : conversations)
    })

    await expect(getPublicWorkflowProfile("wf-1", "token-1")).resolves.toEqual(
      profile
    )
    const initialized = await initializePublicWorkflow("wf-1", "token-1")

    expect(urls).toEqual([
      "/api/v1/public/workflows/wf-1/profile",
      "/api/v1/public/workflows/wf-1/profile",
      "/api/v1/public/workflows/wf-1/conversations",
    ])
    expect(initialized).toEqual({ profile, conversations })
  })

  test("lists runs and creates public workflow runs", async () => {
    const requests = capture()

    await listPublicWorkflowRuns("wf-1", "conv-1", "token-1")
    await listPublicWorkflowRuns("wf-1", "conv-1", "token-1", {
      limit: 20,
      offset: 5,
    })
    await createPublicWorkflowRun("wf-1", "token-1", "hello")
    await createPublicWorkflowRun("wf-1", "token-1", "continue", "conv-1", [
      "file-1",
    ])

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      [
        "GET",
        "/api/v1/public/workflows/wf-1/runs?limit=200&conversation_id=conv-1",
      ],
      [
        "GET",
        "/api/v1/public/workflows/wf-1/runs?limit=20&offset=5&conversation_id=conv-1",
      ],
      ["POST", "/api/v1/public/workflows/wf-1/runs"],
      ["POST", "/api/v1/public/workflows/wf-1/runs"],
    ])
    expect(requests[2]?.body).toEqual({ question: "hello" })
    expect(requests[3]?.body).toEqual({
      question: "continue",
      file_ids: ["file-1"],
      conversation_id: "conv-1",
    })
  })

  test("uploads, submits forms, regenerates, and rates public workflow runs", async () => {
    const requests = capture()

    await uploadPublicWorkflowFiles("wf-1", "token-1", [
      new File(["data"], "doc.pdf", { type: "application/pdf" }),
    ])
    await submitPublicWorkflowForm("wf-1", "token-1", "run-1", "node-1", {
      name: "Ada",
    })
    await regeneratePublicWorkflowRun("wf-1", "token-1", "run-1")
    await setPublicWorkflowRunFeedback("wf-1", "token-1", "run-1", "positive")
    await setPublicWorkflowRunFeedback("wf-1", "token-1", "run-1", null)

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["POST", "/api/v1/public/workflows/wf-1/uploads"],
      ["POST", "/api/v1/public/workflows/wf-1/runs/run-1/form"],
      ["POST", "/api/v1/public/workflows/wf-1/runs/run-1/regenerate"],
      ["POST", "/api/v1/public/workflows/wf-1/runs/run-1/feedback"],
      ["POST", "/api/v1/public/workflows/wf-1/runs/run-1/feedback"],
    ])
    expect(requests[0]?.body).toBeInstanceOf(FormData)
    expect((requests[0]?.body as FormData).getAll("files")).toHaveLength(1)
    expect(requests[1]?.body).toEqual({
      runtime_node_id: "node-1",
      form_data: { name: "Ada" },
    })
    expect(requests[3]?.body).toEqual({ value: "positive" })
    expect(requests[4]?.body).toEqual({ value: null })
  })

  test("observes public workflow run streams", async () => {
    const urls: string[] = []
    let authorization: string | null = null
    globalThis.setTimeout = ((callback: () => void) => {
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout
    withFetch((url, init) => {
      urls.push(url)
      authorization = new Headers(init?.headers).get("Authorization")
      return ndjsonResponse([
        {
          type: "answer_delta",
          live_sequence: "1700000000000-0",
          stream_epoch: "worker-1",
          node_id: "llm-1",
          delta: "partial",
        },
        { type: "complete", sequence: 2, run: { id: "run-1" } },
      ])
    })

    const eventTypes: string[] = []
    await observePublicWorkflowRun("wf-1", "token-1", "run-1", (event) =>
      eventTypes.push(event.type)
    )

    expect(eventTypes).toEqual(["answer_delta", "complete"])
    expect(urls[0]).toContain(
      "/public/workflows/wf-1/runs/run-1/stream?after=0&live_after=0-0"
    )
    expect(authorization as string | null).toBe("Bearer token-1")
  })

  test("fetches workflow API documentation with the API key", async () => {
    const documentation = {
      workflow_id: "wf-1",
      workflow_name: "Onboarding",
      base_path: "/api/v1/workflow-api/wf-1",
      interaction_config: interactionConfig,
    }
    let url = ""
    let authorization: string | null = null
    withFetch((requestUrl, init) => {
      url = requestUrl
      authorization = new Headers(init?.headers).get("Authorization")
      return jsonResponse(documentation)
    })

    const result = await getWorkflowApiDocumentation("wf-1", "nxf_key")

    expect(url).toBe("/api/v1/workflow-api/wf-1/documentation")
    expect(result).toEqual(documentation)
    expect(authorization as string | null).toBe("Bearer nxf_key")
  })

  test("surfaces non-2xx public workflow responses as API errors", async () => {
    withFetch(() => jsonResponse({ detail: "Workflow not found." }, 404))

    try {
      await getPublicWorkflowProfile("wf-1", "token-1")
      throw new Error("request should fail")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(404)
      expect((error as ApiError).message).toBe("Workflow not found.")
    }
  })
})

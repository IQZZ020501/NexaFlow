/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { ApiError } from "@/lib/api-client"
import {
  createWorkflowRun,
  getWorkflowDefinition,
  listWorkflowNodeExecutions,
  listWorkflowRuns,
  listWorkflowVersions,
  observeWorkflowRun,
  publishWorkflow,
  regenerateWorkflowRun,
  restoreWorkflowVersion,
  setWorkflowRunFeedback,
  submitWorkflowForm,
  updateWorkflowDefinition,
  uploadWorkflowFiles,
  validateWorkflowDefinition,
} from "@/lib/api/workflows"
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

const graph = {
  nodes: [],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
}

describe("workflow API extras", () => {
  test("fetches, validates, and publishes workflow definitions", async () => {
    const requests = capture()

    await getWorkflowDefinition("token-1", "ws-1", "wf-1")
    await updateWorkflowDefinition("token-1", "ws-1", "wf-1", 7, graph)
    await validateWorkflowDefinition("token-1", "ws-1", "wf-1", graph)
    await publishWorkflow("token-1", "ws-1", "wf-1")
    await listWorkflowVersions("token-1", "ws-1", "wf-1")
    await restoreWorkflowVersion("token-1", "ws-1", "wf-1", 3, 5)

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["GET", "/api/v1/workspaces/ws-1/workflows/wf-1/definition"],
      ["PUT", "/api/v1/workspaces/ws-1/workflows/wf-1/definition"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/validate"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/publish"],
      ["GET", "/api/v1/workspaces/ws-1/workflows/wf-1/versions"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/versions/3/restore"],
    ])
    expect(requests.every(({ authorization }) => authorization === "Bearer token-1")).toBe(true)
    expect(requests[1]?.body).toEqual({ expected_revision: 7, graph })
    expect(requests[2]?.body).toEqual({ graph })
    expect(requests[5]?.body).toEqual({ expected_revision: 5 })
  })

  test("parses a workflow definition response", async () => {
    const definition = {
      id: "definition-1",
      workspace_id: "ws-1",
      agent_id: "wf-1",
      revision: 3,
      graph,
      graph_hash: "hash",
      updated_by_user_id: "user-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    }
    withFetch(() => jsonResponse(definition))

    await expect(
      getWorkflowDefinition("token-1", "ws-1", "wf-1")
    ).resolves.toEqual(definition)
  })

  test("starts, submits, and regenerates workflow runs with rating feedback", async () => {
    const requests = capture()

    await createWorkflowRun("token-1", "ws-1", "wf-1", "hello")
    await createWorkflowRun(
      "token-1",
      "ws-1",
      "wf-1",
      "release",
      "published",
      3,
      ["file-1"]
    )
    await submitWorkflowForm("token-1", "ws-1", "wf-1", "run-1", "node-1", {
      name: "Ada",
    })
    await regenerateWorkflowRun("token-1", "ws-1", "wf-1", "run-1")
    await setWorkflowRunFeedback("token-1", "ws-1", "wf-1", "run-1", "positive")
    await setWorkflowRunFeedback("token-1", "ws-1", "wf-1", "run-1", "negative")
    await setWorkflowRunFeedback("token-1", "ws-1", "wf-1", "run-1", null)

    expect(requests.map(({ url, method }) => [method, url])).toEqual([
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/runs"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/runs"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/runs/run-1/form"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/runs/run-1/regenerate"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/runs/run-1/feedback"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/runs/run-1/feedback"],
      ["POST", "/api/v1/workspaces/ws-1/workflows/wf-1/runs/run-1/feedback"],
    ])
    expect(requests[0]?.body).toEqual({ question: "hello", source: "draft" })
    expect(requests[1]?.body).toEqual({
      question: "release",
      source: "published",
      version_number: 3,
      file_ids: ["file-1"],
    })
    expect(requests[2]?.body).toEqual({
      runtime_node_id: "node-1",
      form_data: { name: "Ada" },
    })
    expect(requests[4]?.body).toEqual({ value: "positive" })
    expect(requests[5]?.body).toEqual({ value: "negative" })
    expect(requests[6]?.body).toEqual({ value: null })
  })

  test("uploads workflow attachments as form data", async () => {
    const requests: Array<{ url: string; body: BodyInit | null | undefined }> = []
    withFetch((url, init) => {
      requests.push({ url, body: init?.body })
      return jsonResponse([
        {
          id: "upload-1",
          filename: "debug.txt",
          content_type: "text/plain",
          size_bytes: 5,
          category: "document",
        },
      ])
    })

    const files = [new File(["debug"], "debug.txt", { type: "text/plain" })]
    const uploaded = await uploadWorkflowFiles("token-1", "ws-1", "wf-1", files)

    expect(requests[0]?.url).toBe(
      "/api/v1/workspaces/ws-1/workflows/wf-1/uploads"
    )
    expect(requests[0]?.body).toBeInstanceOf(FormData)
    expect((requests[0]?.body as FormData).getAll("files")).toEqual(files)
    expect(uploaded).toEqual([
      {
        id: "upload-1",
        filename: "debug.txt",
        content_type: "text/plain",
        size_bytes: 5,
        category: "document",
      },
    ])
  })

  test("lists workflow runs with pagination and node executions", async () => {
    const requests = capture()

    await listWorkflowRuns("token-1", "ws-1", "wf-1")
    await listWorkflowRuns("token-1", "ws-1", "wf-1", { limit: 20 })
    await listWorkflowRuns("token-1", "ws-1", "wf-1", { limit: 20, offset: 5 })
    await listWorkflowNodeExecutions("token-1", "ws-1", "wf-1", "run-1")

    expect(requests.map(({ url }) => url)).toEqual([
      "/api/v1/workspaces/ws-1/workflows/wf-1/runs",
      "/api/v1/workspaces/ws-1/workflows/wf-1/runs?limit=20",
      "/api/v1/workspaces/ws-1/workflows/wf-1/runs?limit=20&offset=5",
      "/api/v1/workspaces/ws-1/workflows/wf-1/runs/run-1/nodes",
    ])
  })

  test("parses workflow run lists and node executions", async () => {
    const run = {
      id: "run-1",
      conversation_id: "conv-1",
      workspace_id: "ws-1",
      agent_id: "wf-1",
      requested_by_user_id: "user-1",
      status: "succeeded" as const,
      source: "draft" as const,
      definition_revision: 2,
      version_number: null,
      graph_hash: "hash",
      inputs: {},
      outputs: {},
      max_steps: 30,
      max_model_tokens: 4000,
      step_count: 3,
      token_usage: 100,
      last_error: null,
      trace_id: "trace-1",
      started_at: null,
      finished_at: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      pending_form: null,
    }
    const execution = {
      id: "exec-1",
      run_id: "run-1",
      node_id: "llm-1",
      node_type: "llm" as const,
      status: "succeeded" as const,
      sequence: 1,
      inputs: {},
      outputs: {},
      model_usage: {},
      error: null,
      started_at: null,
      finished_at: null,
      duration_ms: 120,
    }
    withFetch((url) =>
      jsonResponse(
        url.endsWith("/nodes")
          ? { items: [execution] }
          : [run]
      )
    )

    const runs = await listWorkflowRuns("token-1", "ws-1", "wf-1", { limit: 20 })
    const executions = await listWorkflowNodeExecutions(
      "token-1",
      "ws-1",
      "wf-1",
      "run-1"
    )

    expect(runs).toEqual([run])
    expect(executions).toEqual({ items: [execution] })
  })

  test("observes workflow run streams until completion", async () => {
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
        { type: "complete", sequence: 3, run: { id: "run-1" } },
      ])
    })

    const eventTypes: string[] = []
    await observeWorkflowRun(
      "token-1",
      "ws-1",
      "wf-1",
      "run-1",
      (event) => eventTypes.push(event.type)
    )

    expect(eventTypes).toEqual(["answer_delta", "complete"])
    expect(urls[0]).toContain("/workflows/wf-1/runs/run-1/stream?after=0")
    expect(urls[0]).toContain("live_after=0-0")
    expect(authorization as string | null).toBe("Bearer token-1")
  })

  test("surfaces non-2xx workflow responses as API errors", async () => {
    withFetch(() => jsonResponse({ detail: "Run not found." }, 404))

    try {
      await listWorkflowRuns("token-1", "ws-1", "wf-1")
      throw new Error("request should fail")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(404)
      expect((error as ApiError).message).toBe("Run not found.")
    }
  })
})

import { afterEach, describe, expect, test } from "bun:test"

import {
  createWorkflowRun,
  updateWorkflowDefinition,
} from "../lib/api/workflows"
import {
  createPublicWorkflowRun,
  getWorkflowApiDocumentation,
} from "../lib/api/public-workflows"
import {
  initialPublicWorkflowValues,
  parsePublicWorkflowValues,
} from "../components/workflows/public-workflow-chat"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

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
      { input: "release" },
      "published",
      3
    )

    expect(JSON.parse(body)).toEqual({
      inputs: { input: "release" },
      source: "published",
      version_number: 3,
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
      { query: "release" },
      "conversation-1"
    )
    await getWorkflowApiDocumentation("workflow-1", "nxf_key")

    expect(requests[0]?.url).toContain("/public/workflows/workflow-1/runs")
    expect(JSON.parse(requests[0]?.body ?? "{}")).toEqual({
      inputs: { query: "release" },
      conversation_id: "conversation-1",
    })
    expect(requests[1]?.url).toContain("/workflow-api/workflow-1/documentation")
    expect(requests[1]?.authorization).toBe("Bearer nxf_key")
  })

  test("parses published Start node inputs by declared type", () => {
    const fields = [
      { name: "query", type: "string" as const, required: true, default: "" },
      { name: "count", type: "number" as const, required: true, default: 2 },
      {
        name: "enabled",
        type: "boolean" as const,
        required: false,
        default: true,
      },
      {
        name: "filters",
        type: "object" as const,
        required: false,
        default: {},
      },
    ]
    const values = initialPublicWorkflowValues(fields)
    values.query = "release"

    expect(parsePublicWorkflowValues(fields, values)).toEqual({
      query: "release",
      count: 2,
      enabled: true,
      filters: {},
    })
    expect(() =>
      parsePublicWorkflowValues(fields, { ...values, filters: "[]" })
    ).toThrow()
  })
})

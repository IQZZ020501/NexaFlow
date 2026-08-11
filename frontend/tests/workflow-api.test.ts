import { afterEach, describe, expect, test } from "bun:test"

import {
  createWorkflowRun,
  updateWorkflowDefinition,
} from "../lib/api/workflows"

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
})

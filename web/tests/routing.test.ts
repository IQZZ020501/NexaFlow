import { describe, expect, test } from "bun:test"

import { pathForRoute, routeFromPath } from "../src/app/routing"

describe("app routing", () => {
  test("round trips knowledge base detail routes", () => {
    expect(routeFromPath("/knowledge/kb_123")).toEqual({
      page: "knowledge",
      systemTab: "workspaces",
      knowledgeBaseId: "kb_123",
    })
    expect(
      pathForRoute({
        page: "knowledge",
        systemTab: "workspaces",
        knowledgeBaseId: "kb_123",
      })
    ).toBe("/knowledge/kb_123")
  })

  test("keeps the knowledge list route separate from detail routes", () => {
    expect(routeFromPath("/knowledge")).toEqual({
      page: "knowledge",
      systemTab: "workspaces",
    })
    expect(pathForRoute({ page: "knowledge", systemTab: "workspaces" })).toBe(
      "/knowledge"
    )
  })
})

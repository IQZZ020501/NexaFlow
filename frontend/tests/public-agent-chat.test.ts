import { describe, expect, test } from "bun:test"

import {
  hasPublicToolDetails,
  publicToolName,
} from "../components/agents/public-agent-chat"
import type { ExternalAgentProgressEvent } from "../lib/api/public-agents"

function mcpProgressEvent(
  overrides: Partial<ExternalAgentProgressEvent> = {}
): ExternalAgentProgressEvent {
  return {
    id: "tool-1",
    type: "tool",
    status: "succeeded",
    stage: "succeeded",
    turn: 1,
    count: null,
    hits: [],
    tool_name: "web_search",
    tool_label: "Web search",
    tool_kind: "mcp",
    server_name: "Tavily",
    input: { query: "GitHub trending" },
    output: { results: [{ title: "NexaFlow" }] },
    ...overrides,
  }
}

describe("public MCP progress cards", () => {
  test("uses the MCP display label instead of a generic tool title", () => {
    expect(publicToolName(mcpProgressEvent())).toBe("Web search")
  })

  test("can expand when an MCP event has input or output", () => {
    expect(hasPublicToolDetails(mcpProgressEvent())).toBe(true)
    expect(
      hasPublicToolDetails(
        mcpProgressEvent({ input: {}, output: null })
      )
    ).toBe(false)
  })
})

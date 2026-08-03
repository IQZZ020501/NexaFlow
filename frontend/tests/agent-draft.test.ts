import { describe, expect, test } from "bun:test"

import {
  isAgentFormDirty,
  type AgentFormState,
} from "../components/agents/agents-page"
import type { Agent } from "../lib/api/agents"

const agent: Agent = {
  id: "agent-1",
  workspace_id: "workspace-1",
  name: "Research assistant",
  description: "Answers from workspace knowledge",
  instructions: "Cite the sources you use.",
  model_id: "model-1",
  knowledge_base_ids: ["knowledge-1", "knowledge-2"],
  mcp_tools: [{ server_id: "server-1", tool_name: "search" }],
  status: "active",
  created_by_user_id: "user-1",
  can_edit: true,
  created_at: "2026-08-03T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
}

const form: AgentFormState = {
  id: agent.id,
  name: agent.name,
  modelId: agent.model_id,
  instructions: agent.instructions,
  knowledgeBaseIds: [...agent.knowledge_base_ids],
  mcpTools: [...agent.mcp_tools],
  status: agent.status,
}

describe("Agent form state", () => {
  test("ignores binding ordering but detects actual edits", () => {
    expect(
      isAgentFormDirty(
        {
          ...form,
          knowledgeBaseIds: [...form.knowledgeBaseIds].reverse(),
        },
        agent
      )
    ).toBe(false)
    expect(isAgentFormDirty({ ...form, modelId: "model-2" }, agent)).toBe(true)
    expect(
      isAgentFormDirty({ ...form, instructions: "Answer briefly." }, agent)
    ).toBe(true)
  })
})

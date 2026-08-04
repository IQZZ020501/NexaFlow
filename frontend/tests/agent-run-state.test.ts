import { describe, expect, test } from "bun:test"

import { mergeAgentRunStreamEvent } from "../lib/agent-run-state"
import type { AgentRun, AgentRunEvent } from "../lib/api/agents"

const run: AgentRun = {
  id: "run-1",
  workspace_id: "workspace-1",
  agent_id: "agent-1",
  requested_by_user_id: "user-1",
  goal: "Prepare a report",
  model_id: "model-1",
  model_name: "Model",
  status: "running",
  plan: [],
  plan_revision: 0,
  events: [],
  pending_approval: null,
  budget: {},
  usage: {},
  result: "",
  last_error: null,
  stop_reason: null,
  resumable: false,
  planned_at: null,
  started_at: "2026-08-04T00:00:00Z",
  finished_at: null,
  created_at: "2026-08-04T00:00:00Z",
  updated_at: "2026-08-04T00:00:00Z",
  trace_id: "trace-1",
}

const processEvent: AgentRunEvent = {
  event_id: "run-1:running:call-1",
  sequence: 1,
  created_at: "2026-08-04T00:00:01Z",
  type: "tool",
  turn: 1,
  tool_name: "search",
  status: "running",
  summary: "agent.tool_running",
  call_id: "call-1",
  tool_label: "Search",
  tool_kind: "knowledge",
  server_name: "",
  input: {},
  output: null,
}

describe("Agent run stream state", () => {
  test("upserts snapshots and process events without duplicate runs", () => {
    const withSnapshot = mergeAgentRunStreamEvent(
      [run],
      { type: "run", run: { ...run, plan_revision: 1 } },
      null
    )
    expect(withSnapshot).toHaveLength(1)
    expect(withSnapshot[0]?.plan_revision).toBe(1)

    const withProcess = mergeAgentRunStreamEvent(
      withSnapshot,
      { type: "process", event: processEvent },
      run.id
    )
    const updated = mergeAgentRunStreamEvent(
      withProcess,
      {
        type: "process",
        event: {
          ...processEvent,
          event_id: "run-1:2",
          status: "succeeded",
        },
      },
      run.id
    )
    expect(updated[0]?.events).toHaveLength(1)
    expect(updated[0]?.events[0]?.status).toBe("succeeded")
  })

  test("appends answer deltas only to the active run", () => {
    const updated = mergeAgentRunStreamEvent(
      [run],
      { type: "answer_delta", delta: "Done" },
      run.id
    )
    expect(updated[0]?.result).toBe("Done")
  })
})

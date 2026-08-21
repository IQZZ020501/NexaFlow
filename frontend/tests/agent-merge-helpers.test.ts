/* @jsxImportSource react */
/**
 * Pure-helper coverage for the exported merge/state helpers in
 * components/agents/agents-page.tsx. Complements the UI-level suite with
 * exhaustive branch coverage of the reducer-style functions.
 */
import { describe, expect, test } from "bun:test"

import {
  isAgentFormDirty,
  isAgentListLoading,
  isCurrentAgentConversation,
  mergeAgentRunSnapshot,
  mergeAgentRunStreamEvent,
  mergeInitialAgentRun,
  type AgentFormState,
} from "@/components/agents/agents-page"
import type {
  Agent,
  AgentRun,
  AgentRunEvent,
  AgentRunStreamEvent,
} from "@/lib/api/agents"

import { mockNextNavigation, mockUseSession } from "./helpers/dom"

mockUseSession()
mockNextNavigation()

const WS = "ws-1"

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    workspace_id: WS,
    name: "Research Assistant",
    app_type: "agent",
    description: "Answers from workspace knowledge",
    interaction_config: {
      prologue: "",
      tts_type: "BROWSER",
      file_upload: false,
      file_upload_setting: { file_upload_type: ["document", "image"] },
      user_input_title: "",
    },
    instructions: "Cite the sources you use.",
    model_id: "model-1",
    knowledge_query_mode: "required",
    knowledge_base_ids: ["knowledge-1"],
    tools: [{ tool_id: "tool-1", version_id: "version-1" }],
    status: "active",
    published: false,
    has_unpublished_changes: false,
    published_by_user_id: null,
    published_at: null,
    created_by_user_id: "u-1",
    can_edit: true,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: "2026-08-03T00:00:00Z",
    ...overrides,
  }
}

function makeWorkflow(overrides: Partial<Agent> = {}): Agent {
  return makeAgent({
    id: "agent-2",
    name: "Weekly Digest",
    app_type: "workflow",
    model_id: "model-1",
    knowledge_base_ids: [],
    tools: [],
    published: true,
    ...overrides,
  })
}

function makeRun(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run-1",
    workspace_id: WS,
    agent_id: "agent-1",
    requested_by_user_id: "u-1",
    conversation_id: "conversation-1",
    goal: "Summarize the latest releases",
    model_id: "model-1",
    model_name: "DeepSeek Chat",
    knowledge_query_mode: "required",
    status: "succeeded",
    plan: [],
    events: [],
    result: "Here is the summary.",
    model_usage: { prompt_tokens: 10, completion_tokens: 20 },
    last_error: null,
    planned_at: null,
    started_at: "2026-08-04T00:00:00Z",
    finished_at: "2026-08-04T00:00:01Z",
    created_at: "2026-08-04T00:00:00Z",
    updated_at: "2026-08-04T00:00:01Z",
    trace_id: "trace-1",
    ...overrides,
  }
}

const thoughtEvent = (overrides: Record<string, unknown> = {}): AgentRunEvent =>
  ({
    type: "thought",
    turn: 1,
    tool_name: "",
    status: "running",
    summary: "agent.analyzing",
    call_id: "",
    tool_label: "",
    tool_kind: "unknown",
    server_name: "",
    input: {},
    output: null,
    duration_ms: 0,
    reasoning: "",
    ...overrides,
  }) as AgentRunEvent

function formFromAgentFixture(agent: Agent): AgentFormState {
  return {
    id: agent.id,
    appType: agent.app_type,
    name: agent.name,
    description: agent.description,
    interactionConfig: structuredClone(agent.interaction_config),
    modelId: agent.model_id,
    instructions: agent.instructions,
    knowledgeQueryMode: agent.knowledge_query_mode,
    knowledgeBaseIds: [...agent.knowledge_base_ids],
    tools: (agent.tools ?? []).map((tool) => ({ ...tool })),
    status: agent.status,
  }
}

describe("isCurrentAgentConversation", () => {
  test("matches equal ids including null", () => {
    expect(isCurrentAgentConversation(null, null)).toBe(true)
    expect(isCurrentAgentConversation("conversation-1", "conversation-1")).toBe(
      true
    )
  })

  test("rejects mismatched ids", () => {
    expect(isCurrentAgentConversation("conversation-1", null)).toBe(false)
    expect(isCurrentAgentConversation(null, "conversation-1")).toBe(false)
    expect(isCurrentAgentConversation("conversation-1", "conversation-2")).toBe(
      false
    )
  })
})

describe("isAgentListLoading", () => {
  test("requires a workspace and at least one loading flag", () => {
    expect(isAgentListLoading(null, true, false)).toBe(false)
    expect(isAgentListLoading("ws-1", false, false)).toBe(false)
    expect(isAgentListLoading("ws-1", true, false)).toBe(true)
    expect(isAgentListLoading("ws-1", false, true)).toBe(true)
    expect(isAgentListLoading("ws-1", true, true)).toBe(true)
  })
})

describe("mergeInitialAgentRun", () => {
  const pending = makeRun({
    id: "run-1",
    status: "running",
    result: "Pending answer",
    events: [thoughtEvent()],
    live_stream_epoch: "worker-1",
    live_stream_cursor: "1000-0",
  })

  test("keeps pending answer and live cursors for every in-flight status", () => {
    for (const status of ["queued", "running", "awaiting_approval"]) {
      const merged = mergeInitialAgentRun(
        pending,
        makeRun({ id: "run-1", status: status as AgentRun["status"], result: "" })
      )
      expect(merged.result).toBe("Pending answer")
      expect(merged.events).toEqual(pending.events)
      expect(merged.live_stream_epoch).toBe("worker-1")
      expect(merged.live_stream_cursor).toBe("1000-0")
    }
  })

  test("keeps live events and answer when the live run already has them", () => {
    const live = makeRun({
      id: "run-1",
      status: "running",
      result: "Live answer",
      events: [thoughtEvent({ turn: 2 })],
    })
    const merged = mergeInitialAgentRun(pending, live)
    expect(merged.events).toEqual(live.events)
    expect(merged.result).toBe("Live answer")
  })

  test("drops live cursors for terminal statuses", () => {
    for (const status of ["succeeded", "failed", "cancelled"]) {
      const merged = mergeInitialAgentRun(
        pending,
        makeRun({
          id: "run-1",
          status: status as AgentRun["status"],
          result: "Final",
          events: [thoughtEvent({ status: "succeeded" })],
        })
      )
      expect(merged.result).toBe("Final")
      expect(merged.events).toHaveLength(1)
      expect(merged.live_stream_epoch).toBeUndefined()
      expect(merged.live_stream_cursor).toBeUndefined()
    }
  })
})

describe("mergeAgentRunSnapshot", () => {
  test("replaces the placeholder run in place", () => {
    const placeholder = makeRun({
      id: "pending-1",
      status: "running",
      result: "draft",
    })
    const live = makeRun({ id: "run-1", status: "succeeded", result: "answer" })
    const replaced = mergeAgentRunSnapshot(
      [placeholder, makeRun({ id: "run-2", status: "succeeded" })],
      live,
      "pending-1"
    )
    expect(replaced.map((run) => run.id)).toEqual(["run-1", "run-2"])
    expect(replaced[0].result).toBe("answer")
  })

  test("replaces by id without a placeholder", () => {
    const original = makeRun({ id: "run-1", status: "running", result: "old" })
    const snapshot = makeRun({ id: "run-1", status: "succeeded", result: "new" })
    const replaced = mergeAgentRunSnapshot([original], snapshot)
    expect(replaced).toHaveLength(1)
    expect(replaced[0].result).toBe("new")
  })

  test("prepends unknown snapshots and leaves other runs untouched", () => {
    const existing = makeRun({ id: "run-2", status: "succeeded" })
    const snapshot = makeRun({ id: "run-1", status: "succeeded" })
    const replaced = mergeAgentRunSnapshot([existing], snapshot)
    expect(replaced.map((run) => run.id)).toEqual(["run-1", "run-2"])
    expect(replaced[1]).toBe(existing)
  })
})

describe("mergeAgentRunStreamEvent", () => {
  test("run events merge through the snapshot path", () => {
    const placeholder = makeRun({
      id: "pending-1",
      status: "running",
      result: "draft",
    })
    const snapshot = makeRun({ id: "run-1", status: "succeeded", result: "ok" })
    const merged = mergeAgentRunStreamEvent([placeholder], "run-1", {
      type: "run",
      sequence: 1,
      run: snapshot,
    } as AgentRunStreamEvent, "pending-1")
    expect(merged.map((run) => run.id)).toEqual(["run-1"])
    expect(merged[0].result).toBe("ok")
  })

  test("process events match by call id, by shape, or append", () => {
    const base = makeRun({
      status: "running",
      result: "",
      events: [
        thoughtEvent({ call_id: "call-x", tool_name: "search" }),
        thoughtEvent({ turn: 9, tool_name: "lookup" }),
      ],
    })

    const byCallId = mergeAgentRunStreamEvent([base], "run-1", {
      type: "process",
      sequence: 2,
      event: thoughtEvent({ call_id: "call-x", status: "succeeded" }),
    } as AgentRunStreamEvent)
    expect(byCallId[0].events[0].status).toBe("succeeded")
    expect(byCallId[0].events).toHaveLength(2)

    const byShape = mergeAgentRunStreamEvent([base], "run-1", {
      type: "process",
      sequence: 3,
      event: thoughtEvent({ turn: 9, tool_name: "lookup", status: "failed" }),
    } as AgentRunStreamEvent)
    expect(byShape[0].events[1].status).toBe("failed")
    expect(byShape[0].events).toHaveLength(2)

    const appended = mergeAgentRunStreamEvent([base], "run-1", {
      type: "process",
      sequence: 4,
      event: thoughtEvent({ turn: 3, tool_name: "other" }),
    } as AgentRunStreamEvent)
    expect(appended[0].events).toHaveLength(3)

    const untouched = mergeAgentRunStreamEvent([base], "run-9", {
      type: "process",
      sequence: 5,
      event: thoughtEvent({ turn: 3 }),
    } as AgentRunStreamEvent)
    expect(untouched).toEqual([base])
  })

  test("reasoning deltas append, skip stale cursors, and update live fields", () => {
    const run = makeRun({
      status: "running",
      result: "",
      events: [thoughtEvent({ reasoning: "" }), thoughtEvent({ turn: 2 })],
    })
    const streamed = mergeAgentRunStreamEvent([run], "run-1", {
      type: "reasoning_delta",
      sequence: 1,
      turn: 1,
      delta: "Thinking…",
    } as AgentRunStreamEvent)
    expect(streamed[0].events[0].reasoning).toBe("Thinking…")
    expect(streamed[0].events[1]).toEqual(run.events[1])
    expect(streamed[0].live_stream_cursor).toBeUndefined()

    const freshRun = makeRun({
      status: "running",
      result: "",
      events: [],
      live_stream_epoch: "w-1",
      live_stream_cursor: "1000-5",
    })
    const deduped = mergeAgentRunStreamEvent([freshRun], "run-1", {
      type: "reasoning_delta",
      sequence: 2,
      live_sequence: "1000-4",
      stream_epoch: "w-1",
      turn: 1,
      delta: "stale",
    } as AgentRunStreamEvent)
    expect(deduped[0]).toBe(freshRun)
  })

  test("answer deltas append and reset on a new epoch", () => {
    const run = makeRun({ status: "running", result: "Hello", events: [] })
    const streamed = mergeAgentRunStreamEvent([run], "run-1", {
      type: "answer_delta",
      sequence: 1,
      delta: " world",
    } as AgentRunStreamEvent)
    expect(streamed[0].result).toBe("Hello world")
    expect(streamed[0].live_stream_cursor).toBeUndefined()

    const reset = mergeAgentRunStreamEvent(streamed, "run-1", {
      type: "answer_reset",
      sequence: 2,
    } as AgentRunStreamEvent)
    expect(reset[0].result).toBe("")

    const takeover = mergeAgentRunStreamEvent(
      [
        makeRun({
          status: "running",
          result: "Partial",
          events: [],
          live_stream_epoch: "w-1",
          live_stream_cursor: "1000-2",
        }),
      ],
      "run-1",
      {
        type: "answer_delta",
        sequence: 2,
        live_sequence: "1000-3",
        stream_epoch: "w-2",
        delta: "fresh",
      } as AgentRunStreamEvent
    )
    expect(takeover[0].result).toBe("fresh")
    expect(takeover[0].live_stream_epoch).toBe("w-2")
    expect(takeover[0].live_stream_cursor).toBe("1000-3")

    const unchanged = mergeAgentRunStreamEvent([run], "run-9", {
      type: "answer_delta",
      sequence: 3,
      delta: "x",
    } as AgentRunStreamEvent)
    expect(unchanged).toEqual([run])
  })

  test("approval events update status and error", () => {
    const runs = [
      makeRun({ id: "run-1", status: "running", result: "", events: [] }),
      makeRun({ id: "run-2", status: "running", result: "", events: [] }),
    ]
    const required = mergeAgentRunStreamEvent(runs, "run-1", {
      type: "approval_required",
      sequence: 1,
      call_id: "call-1",
      reason: "needs confirmation",
    } as AgentRunStreamEvent)
    expect(required[0].status).toBe("awaiting_approval")
    expect(required[0].last_error).toBe("needs confirmation")
    expect(required[1].status).toBe("running")

    const resolved = mergeAgentRunStreamEvent(required, "run-1", {
      type: "approval_resolved",
      sequence: 2,
      call_id: "call-1",
      decision: "approved",
    } as AgentRunStreamEvent)
    expect(resolved[0].status).toBe("queued")
    expect(resolved[0].last_error).toBeNull()
  })

  test("terminal events replace the matching run only", () => {
    const runs = [
      makeRun({ id: "run-1", status: "running", result: "", events: [] }),
      makeRun({ id: "run-2", status: "running", result: "", events: [] }),
    ]
    const replaced = mergeAgentRunStreamEvent(runs, "run-1", {
      type: "complete",
      sequence: 9,
      run: makeRun({ id: "run-1", status: "succeeded", result: "done" }),
    } as AgentRunStreamEvent)
    expect(replaced[0].result).toBe("done")
    expect(replaced[1]).toBe(runs[1])
  })
})

describe("isAgentFormDirty", () => {
  const agent = makeAgent()

  test("clean form matches its agent", () => {
    expect(isAgentFormDirty(formFromAgentFixture(agent), agent)).toBe(false)
  })

  test("detects every mutable field", () => {
    const base = formFromAgentFixture(agent)
    expect(isAgentFormDirty({ ...base, name: "  Renamed  " }, agent)).toBe(true)
    expect(isAgentFormDirty({ ...base, description: "  " }, agent)).toBe(true)
    expect(
      isAgentFormDirty(
        { ...base, interactionConfig: { ...base.interactionConfig, prologue: "x" } },
        agent
      )
    ).toBe(true)
    expect(isAgentFormDirty({ ...base, modelId: "model-2" }, agent)).toBe(true)
    expect(isAgentFormDirty({ ...base, instructions: " " }, agent)).toBe(true)
    expect(
      isAgentFormDirty({ ...base, knowledgeQueryMode: "agentic" }, agent)
    ).toBe(true)
    expect(isAgentFormDirty({ ...base, status: "disabled" }, agent)).toBe(true)
    expect(
      isAgentFormDirty({ ...base, knowledgeBaseIds: ["knowledge-2"] }, agent)
    ).toBe(true)
    expect(isAgentFormDirty({ ...base, tools: [] }, agent)).toBe(true)
  })

  test("tool order does not count as dirty and extra versions do", () => {
    const base = formFromAgentFixture(agent)
    expect(
      isAgentFormDirty(
        {
          ...base,
          tools: [
            { tool_id: "tool-1", version_id: "version-1" },
            { tool_id: "tool-2", version_id: "version-2" },
          ],
        },
        makeAgent({
          tools: [
            { tool_id: "tool-2", version_id: "version-2" },
            { tool_id: "tool-1", version_id: "version-1" },
          ],
        })
      )
    ).toBe(false)
    expect(
      isAgentFormDirty(
        { ...base, tools: [{ tool_id: "tool-1", version_id: "version-2" }] },
        agent
      )
    ).toBe(true)
  })

  test("workflow app types ignore knowledge and tool changes", () => {
    const workflow = makeWorkflow()
    const workflowForm = formFromAgentFixture(workflow)
    expect(
      isAgentFormDirty(
        {
          ...workflowForm,
          knowledgeBaseIds: ["knowledge-9"],
          tools: [{ tool_id: "tool-9", version_id: "version-9" }],
        },
        workflow
      )
    ).toBe(false)
  })

  test("agents without tools are not dirty against empty tool forms", () => {
    const bare = makeAgent({ tools: undefined })
    expect(isAgentFormDirty(formFromAgentFixture(bare), bare)).toBe(false)
  })
})

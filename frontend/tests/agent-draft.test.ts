import { describe, expect, test } from "bun:test"

import {
  isAgentFormDirty,
  isCurrentAgentConversation,
  mergeAgentRunSnapshot,
  mergeAgentRunStreamEvent,
  mergeInitialAgentRun,
  type AgentFormState,
} from "../components/agents/agents-page"
import {
  collapsedProcessStatusKey,
  isNearScrollBottom,
  processTimeline,
  unrenderedAgentToolCalls,
} from "../components/agents/agent-detail-workspace"
import type { Agent, AgentRun, AgentToolCall } from "../lib/api/agents"

describe("Agent conversation async guards", () => {
  test("does not restore an aborted question after switching conversations", async () => {
    let activeConversationId: string | null = "conversation-1"
    const actionConversationId = activeConversationId
    let question = ""
    const completion = Promise.reject(new Error("aborted")).catch(() => {
      if (
        isCurrentAgentConversation(
          activeConversationId,
          actionConversationId
        )
      ) {
        question = "old question"
      }
    })

    activeConversationId = "conversation-2"
    await completion

    expect(question).toBe("")
  })

  test("does not merge a tool decision after switching conversations", async () => {
    let activeConversationId: string | null = "conversation-1"
    const actionConversationId = activeConversationId
    let runIds = ["new-conversation-run"]
    const completion = Promise.resolve("old-conversation-run").then((runId) => {
      if (
        isCurrentAgentConversation(
          activeConversationId,
          actionConversationId
        )
      ) {
        runIds = [runId, ...runIds]
      }
    })

    activeConversationId = "conversation-2"
    await completion

    expect(runIds).toEqual(["new-conversation-run"])
  })
})

const agent: Agent = {
  id: "agent-1",
  workspace_id: "workspace-1",
  name: "Research assistant",
  description: "Answers from workspace knowledge",
  instructions: "Cite the sources you use.",
  model_id: "model-1",
  knowledge_query_mode: "required",
  knowledge_base_ids: ["knowledge-1", "knowledge-2"],
  mcp_tools: [{ server_id: "server-1", tool_name: "search" }],
  status: "active",
  published: false,
  published_by_user_id: null,
  published_at: null,
  created_by_user_id: "user-1",
  can_edit: true,
  created_at: "2026-08-03T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
}

const form: AgentFormState = {
  id: agent.id,
  name: agent.name,
  description: agent.description,
  modelId: agent.model_id,
  instructions: agent.instructions,
  knowledgeQueryMode: agent.knowledge_query_mode,
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
    expect(
      isAgentFormDirty({ ...form, description: "New description" }, agent)
    ).toBe(true)
    expect(
      isAgentFormDirty(
        { ...form, description: ` ${agent.description} ` },
        agent
      )
    ).toBe(false)
  })
})

describe("Agent preview state", () => {
  test("follows content only while the viewport is near the bottom", () => {
    expect(
      isNearScrollBottom({
        scrollHeight: 1_000,
        scrollTop: 536,
        clientHeight: 400,
      })
    ).toBe(true)
    expect(
      isNearScrollBottom({
        scrollHeight: 1_000,
        scrollTop: 535,
        clientHeight: 400,
      })
    ).toBe(false)
  })

  test("keeps eager knowledge after the initial thought", () => {
    const thought = {
      type: "thought",
      turn: 1,
      summary: "agent.answer_ready",
    } as AgentRun["events"][number]
    const updatedThought = {
      ...thought,
      summary: "agent.tools_selected",
    }
    const knowledge = {
      type: "tool",
      turn: 0,
      tool_kind: "knowledge",
    } as AgentRun["events"][number]
    const mcp = {
      type: "tool",
      turn: 1,
      tool_kind: "mcp",
    } as AgentRun["events"][number]

    expect(
      processTimeline({
        events: [knowledge, thought, updatedThought, mcp],
      } as AgentRun).map(({ event }) => event)
    ).toEqual([updatedThought, knowledge, mcp])
  })

  test("keeps an approval inline until its tool event arrives", () => {
    const thought = {
      type: "thought",
      turn: 1,
      call_id: "",
    } as AgentRun["events"][number]
    const call = {
      call_id: "call-1",
      status: "awaiting_approval",
    } as AgentToolCall
    const timeline = processTimeline({ events: [thought] } as AgentRun)

    expect(unrenderedAgentToolCalls(timeline, [call])).toEqual([call])
    expect(
      unrenderedAgentToolCalls(timeline, [{ ...call, status: "approved" }])
    ).toHaveLength(1)

    const toolEvent = {
      type: "tool",
      turn: 1,
      call_id: call.call_id,
    } as AgentRun["events"][number]
    expect(
      unrenderedAgentToolCalls(
        processTimeline({ events: [thought, toolEvent] } as AgentRun),
        [call]
      )
    ).toEqual([])
  })

  test("keeps tool progress visible when the process panel is collapsed", () => {
    expect(collapsedProcessStatusKey("awaiting_approval", true, true)).toBeNull()
    expect(
      collapsedProcessStatusKey("awaiting_approval", true, false)
    ).toBe("等待工具调用确认")
    expect(collapsedProcessStatusKey("running", true, false)).toBe("执行过程")
  })

  test("keeps optimistic progress until the stream reports progress", () => {
    const pendingRun = {
      id: "pending-1",
      events: [{ summary: "agent.analyzing" }],
    } as AgentRun
    const liveRun = { ...pendingRun, id: "run-1", events: [] }
    const liveEvent = pendingRun.events[0]

    expect(mergeInitialAgentRun(pendingRun, liveRun).events).toEqual(
      pendingRun.events
    )
    expect(
      mergeInitialAgentRun(pendingRun, {
        ...liveRun,
        events: [liveEvent],
      } as AgentRun).events
    ).toEqual([liveEvent])
  })

  test("keeps live cursors on non-terminal snapshots with persisted text", () => {
    const pendingRun = {
      id: "run-1",
      status: "running",
      events: [],
      result: "partial",
      live_stream_epoch: "worker-1",
      live_stream_cursor: "1700000000000-1",
    } as unknown as AgentRun
    const merged = mergeInitialAgentRun(pendingRun, {
      ...pendingRun,
      result: "persisted partial",
      live_stream_epoch: undefined,
      live_stream_cursor: undefined,
    })

    expect(merged.result).toBe("persisted partial")
    expect(merged.live_stream_epoch).toBe("worker-1")
    expect(merged.live_stream_cursor).toBe("1700000000000-1")
  })

  test("keeps partial text across reconnects and resets it on worker takeover", () => {
    const running = {
      id: "run-1",
      status: "running",
      events: [],
      result: "Hello",
      live_stream_epoch: "worker-1",
    } as unknown as AgentRun
    const reconnected = mergeAgentRunStreamEvent(
      [running],
      running.id,
      { type: "run", sequence: 2, run: { ...running, result: "" } }
    )[0]
    expect(reconnected.result).toBe("Hello")

    const reasoningResumed = mergeAgentRunStreamEvent(
      [reconnected],
      running.id,
      {
        type: "reasoning_delta",
        live_sequence: "1700000000001-0",
        stream_epoch: "worker-2",
        turn: 1,
        delta: "Restarted reasoning",
      }
    )[0]
    expect(reasoningResumed.result).toBe("")

    const resumed = mergeAgentRunStreamEvent(
      [reasoningResumed],
      running.id,
      {
        type: "answer_delta",
        live_sequence: "1700000000002-0",
        stream_epoch: "worker-2",
        delta: "Restarted",
      }
    )[0]
    expect(resumed.result).toBe("Restarted")
  })

  test("keeps the process timeline when approval returns a queued snapshot", () => {
    const toolEvent = {
      type: "tool",
      turn: 1,
      tool_name: "execute_sql",
      status: "succeeded",
      call_id: "call-1",
    } as AgentRun["events"][number]
    const liveRun = {
      id: "run-1",
      status: "awaiting_approval",
      events: [toolEvent],
      result: "",
    } as unknown as AgentRun
    const approvalResponse = {
      ...liveRun,
      status: "queued",
      events: [],
    } as unknown as AgentRun

    const merged = mergeAgentRunSnapshot([liveRun], approvalResponse)[0]

    expect(merged.status).toBe("queued")
    expect(merged.events).toEqual([toolEvent])
  })
})

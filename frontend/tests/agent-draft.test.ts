import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"

import { AgentConfigFields } from "../src/components/agents/agent-config-fields"
import { AgentAttachmentList } from "../src/components/agents/agent-attachment-list"
import { InteractionConfigFields } from "../src/components/agents/interaction-config-fields"
import {
  isAgentFormDirty,
  isAgentListLoading,
  isCurrentAgentConversation,
  mergeAgentRunSnapshot,
  mergeAgentRunStreamEvent,
  mergeInitialAgentRun,
  type AgentFormState,
} from "../src/components/agents/agents-page"
import {
  agentPublicationAction,
  collapsedProcessStatusKey,
  isNearScrollBottom,
  processTimeline,
  unrenderedAgentToolCalls,
} from "../src/components/agents/agent-detail-workspace"
import type { Agent, AgentRun, AgentToolCall } from "../src/lib/api/agents"
import {
  acceptedUploadExtensions,
  normalizeInteractionConfigForAppType,
} from "../src/lib/interaction-config"

const agentsPageSource = readFileSync(
  join(import.meta.dir, "../src/components/agents/agents-page.tsx"),
  "utf8"
)

describe("Agent conversation async guards", () => {
  test("does not restore an aborted question after switching conversations", async () => {
    let activeConversationId: string | null = "conversation-1"
    const actionConversationId = activeConversationId
    let question = ""
    const completion = Promise.reject(new Error("aborted")).catch(() => {
      if (
        isCurrentAgentConversation(activeConversationId, actionConversationId)
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
        isCurrentAgentConversation(activeConversationId, actionConversationId)
      ) {
        runIds = [runId, ...runIds]
      }
    })

    activeConversationId = "conversation-2"
    await completion

    expect(runIds).toEqual(["new-conversation-run"])
  })
})

describe("Agent list loading state", () => {
  test("stops loading without a workspace and includes deep-link fetches", () => {
    expect(isAgentListLoading("workspace-1", true, false)).toBe(true)
    expect(isAgentListLoading(null, true, false)).toBe(false)
    expect(isAgentListLoading("workspace-1", false, true)).toBe(true)
    expect(isAgentListLoading("workspace-1", false, false)).toBe(false)
  })
})

describe("Application cards", () => {
  test("show the actual workflow publication state", () => {
    expect(agentsPageSource).toContain(
      't(agent.published ? "已发布" : "未发布")'
    )
    expect(agentsPageSource).not.toContain('t("即将推出")')
  })
})

describe("Agent deletion", () => {
  test("uses an in-app confirmation dialog before issuing the delete", () => {
    const handlerStart = agentsPageSource.indexOf(
      "async function handleDeleteAgent"
    )
    const handlerEnd = agentsPageSource.indexOf(
      "function closeAgentPermissions"
    )
    const dialogStart = agentsPageSource.indexOf(
      "function renderDeleteAgentDialog"
    )
    const dialogEnd = agentsPageSource.indexOf(
      "function renderTypeChooserDialog"
    )

    expect(handlerStart).toBeGreaterThan(-1)
    expect(handlerEnd).toBeGreaterThan(handlerStart)
    expect(dialogStart).toBeGreaterThan(-1)
    expect(dialogEnd).toBeGreaterThan(dialogStart)

    const deleteHandler = agentsPageSource.slice(handlerStart, handlerEnd)
    const deleteDialog = agentsPageSource.slice(dialogStart, dialogEnd)

    expect(deleteHandler).not.toContain("window.confirm")
    expect(deleteHandler).toContain("limit: CARD_BATCH_SIZE")
    expect(deleteHandler).toContain("offset: 0")
    expect(deleteHandler).toContain("setListedAgentsCount(listedAgents.length)")
    expect(deleteDialog).toContain("<Dialog")
    expect(deleteDialog).toContain("onClick={() => void handleDeleteAgent()}")
    expect(agentsPageSource).toContain(
      "onSelect={() => setDeleteAgentTarget(agent)}"
    )
  })
})

const agent: Agent = {
  id: "agent-1",
  workspace_id: "workspace-1",
  name: "Research assistant",
  app_type: "agent",
  description: "Answers from workspace knowledge",
  interaction_config: {
    prologue: "",
    tts_type: "BROWSER",
    file_upload: false,
    file_upload_setting: {
      file_upload_type: ["document", "image", "audio"],
    },
    user_input_title: "",
  },
  instructions: "Cite the sources you use.",
  model_id: "model-1",
  knowledge_query_mode: "required",
  knowledge_base_ids: ["knowledge-1", "knowledge-2"],
  tools: [{ tool_id: "tool-1", version_id: "version-1" }],
  status: "active",
  published: false,
  has_unpublished_changes: false,
  published_by_user_id: null,
  published_at: null,
  created_by_user_id: "user-1",
  can_edit: true,
  created_at: "2026-08-03T00:00:00Z",
  updated_at: "2026-08-03T00:00:00Z",
}

const form: AgentFormState = {
  id: agent.id,
  appType: agent.app_type,
  name: agent.name,
  description: agent.description,
  interactionConfig: structuredClone(agent.interaction_config),
  modelId: agent.model_id,
  instructions: agent.instructions,
  knowledgeQueryMode: agent.knowledge_query_mode,
  knowledgeBaseIds: [...agent.knowledge_base_ids],
  tools: [...(agent.tools ?? [])],
  status: agent.status,
}

describe("Agent form state", () => {
  test("accepts common source files as Agent attachments", () => {
    const accepted = acceptedUploadExtensions(["document"])
    expect(accepted).toContain(".py")
    expect(accepted).toContain(".java")
  })

  test("shows selected attachment names in the composer", () => {
    const markup = renderToStaticMarkup(
      createElement(AgentAttachmentList, {
        files: [
          {
            name: "release-plan.pdf",
            size: 42,
            lastModified: 1,
          } as File,
        ],
        onRemove: () => undefined,
        t: (key, values) =>
          key === "移除 {value}" ? `移除 ${values?.value}` : key,
      })
    )

    expect(markup).toContain("release-plan.pdf")
    expect(markup).toContain("移除 release-plan.pdf")
  })

  test("normalizes attachment types at the shared app-type boundary", () => {
    expect(
      normalizeInteractionConfigForAppType(
        {
          ...agent.interaction_config,
          file_upload_setting: {
            ...agent.interaction_config.file_upload_setting,
            file_upload_type: ["audio"],
          },
        },
        "agent"
      ).file_upload_setting.file_upload_type
    ).toEqual(["document", "image"])
    expect(
      normalizeInteractionConfigForAppType(agent.interaction_config, "workflow")
        .file_upload_setting.file_upload_type
    ).toEqual(["document", "image"])
  })
  test("publishes drafts, republishes changed releases, and unpublishes current releases", () => {
    expect(agentPublicationAction(agent)).toBe("publish")
    expect(
      agentPublicationAction({ published: true, has_unpublished_changes: true })
    ).toBe("republish")
    expect(
      agentPublicationAction({
        published: true,
        has_unpublished_changes: false,
      })
    ).toBe("unpublish")
  })

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

  test("shows advanced configuration only after creation", () => {
    const renderForm = (agentForm: AgentFormState) =>
      renderToStaticMarkup(
        createElement(AgentConfigFields, {
          form: agentForm,
          setForm: () => undefined,
          models: [],
          knowledgeBases: [],
          tools: [],
          token: "token",
          workspaceId: "workspace-1",
          readOnly: false,
          t: (key) => key,
        })
      )

    const creationMarkup = renderForm({ ...form, id: null })
    expect(creationMarkup).not.toContain("对话设置")
    expect(creationMarkup).not.toContain("系统提示词")
    expect(creationMarkup).not.toContain("关联知识库")
    expect(creationMarkup).not.toContain("工具")

    const editMarkup = renderForm(form)
    expect(editMarkup).not.toContain("对话设置")
    expect(editMarkup).toContain("系统提示词")
    expect(editMarkup).toContain("关联知识库")
    expect(editMarkup).toContain("工具")
  })

  test("moves workflow upload types behind settings without limits or audio", () => {
    const markup = renderToStaticMarkup(
      createElement(InteractionConfigFields, {
        appType: "workflow",
        value: { ...agent.interaction_config, file_upload: true },
        onChange: () => undefined,
        t: (key) => key,
        idPrefix: "workflow",
      })
    )

    expect(markup).not.toContain("最多文件数")
    expect(markup).not.toContain("单文件上限")
    expect(markup).toContain('title="文件上传设置"')
    expect(markup).not.toContain('type="checkbox"')
    expect(markup).not.toContain("音频")
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
    expect(
      collapsedProcessStatusKey("awaiting_approval", true, true)
    ).toBeNull()
    expect(collapsedProcessStatusKey("awaiting_approval", true, false)).toBe(
      "等待工具调用确认"
    )
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
    const reconnected = mergeAgentRunStreamEvent([running], running.id, {
      type: "run",
      sequence: 2,
      run: { ...running, result: "" },
    })[0]
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

    const resumed = mergeAgentRunStreamEvent([reasoningResumed], running.id, {
      type: "answer_delta",
      live_sequence: "1700000000002-0",
      stream_epoch: "worker-2",
      delta: "Restarted",
    })[0]
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

  test("terminal error events end the loading state even with a running snapshot", () => {
    const running = {
      id: "run-1",
      status: "running",
      events: [],
      result: "",
    } as unknown as AgentRun
    const merged = mergeAgentRunStreamEvent([running], "run-1", {
      type: "error",
      sequence: 3,
      run: {
        ...running,
        last_error: "Agent executor lost its lease; the run was interrupted.",
      },
    })[0]
    expect(merged.status).toBe("failed")
    expect(merged.last_error).toContain("lost its lease")
  })

  test("terminal complete events mark the run succeeded", () => {
    const running = {
      id: "run-1",
      status: "running",
      events: [],
      result: "",
    } as unknown as AgentRun
    const merged = mergeAgentRunStreamEvent([running], "run-1", {
      type: "complete",
      sequence: 3,
      run: running,
    })[0]
    expect(merged.status).toBe("succeeded")
  })
})

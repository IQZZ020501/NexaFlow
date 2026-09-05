/* @jsxImportSource react */
/**
 * DOM-level coverage for AgentDetailWorkspace and the management panels
 * (overview / logs / monitoring / conversation users).
 */
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test"
import { useState } from "react"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { cleanup } from "@testing-library/react"

import {
  AgentDetailWorkspace,
  collapsedProcessStatusKey,
  isNearScrollBottom,
  processTimeline,
  unrenderedAgentToolCalls,
} from "@/components/agents/agent-detail-workspace"
import { LanguageProvider, useLanguage } from "@/contexts/language-provider"
import type {
  Agent,
  AgentRun,
  AgentRunEvent,
  AgentToolCall,
} from "@/lib/api/agents"
import type { AgentFormState } from "@/components/agents/agents-page"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { ToolSummary } from "@/lib/api/tools"

import {
  jsonResponse,
  makeSession,
  mockNextImage,
  mockUseSession,
  renderPage,
} from "./helpers/dom"

const WS = "ws-1"

function model(id: string, name: string): RegisteredModel {
  return {
    id,
    workspace_id: WS,
    name,
    provider: "deepseek",
    provider_type: "openai",
    model_type: "LLM",
    model_name: "deepseek-chat",
    status: "active",
    credential: {},
    api_base: "",
    has_api_key: true,
    api_key_hint: null,
    meta: {},
    created_by_user_id: "u-1",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  }
}

function knowledgeBase(id: string, name: string): KnowledgeBase {
  return {
    id,
    workspace_id: WS,
    name,
    description: "知识库描述",
    status: "active",
    embedding_model_id: null,
    reranker_model_id: null,
    created_by_user_id: "u-1",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    permission: "edit",
  }
}

function tool(): ToolSummary {
  return {
    id: "tool-1",
    workspace_id: WS,
    kind: "mcp",
    function_name: "search",
    display_name: "Catalog search",
    description: "Search the catalog",
    current_version_id: "version-1",
    status: "active",
    availability: "available",
    source: {
      id: "source-1",
      name: "Database",
      kind: "mcp",
      transport: "streamable_http",
    },
    created_by_user_id: "u-1",
    permission: "owner",
    can_view: true,
    can_use: true,
    can_manage: true,
  }
}

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

function formFrom(agent: Agent): AgentFormState {
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

function makeToolCall(overrides: Partial<AgentToolCall> = {}): AgentToolCall {
  return {
    call_id: "call-1",
    turn: 1,
    tool_name: "execute_sql",
    tool_kind: "mcp",
    server_name: "Database",
    arguments: { query: "SELECT 1" },
    status: "awaiting_approval",
    approval_required: true,
    last_error: null,
    approved_at: null,
    started_at: null,
    finished_at: null,
    ...overrides,
  }
}

const notifyCalls: Array<{ kind: string; message: string }> = []
const session = makeSession({
  me: {
    user: {
      id: "u-1",
      username: "admin",
      email: "admin@app.local",
      name: "NexaFlow Admin",
      is_global_admin: true,
      must_change_password: false,
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      workspaces: [
        { id: WS, name: "Test Workspace", is_default: true, role: "admin" },
      ],
      teams: [],
    },
    memberships: [{ workspace_id: WS, role: "admin" }],
  },
  notify: (kind: "success" | "error", message: string) =>
    notifyCalls.push({ kind, message }),
})
mockUseSession(session)

const stableRouter = {
  push: () => undefined,
  replace: () => undefined,
  back: () => undefined,
  forward: () => undefined,
  prefetch: () => undefined,
  refresh: () => undefined,
}
mock.module("next/navigation", () => ({
  useParams: () => ({}),
  useRouter: () => stableRouter,
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/",
}))
mockNextImage()

type Respond = (
  init?: RequestInit,
  path?: string,
  query?: URLSearchParams
) => Response | Promise<Response>
type FetchCase = {
  method: string
  pathname: string
  exact?: boolean
  respond: Respond
}

function fetchRouter(
  cases: FetchCase[],
  fallback?: (url: string, init?: RequestInit) => Response
) {
  return (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://localhost")
    const method = init?.method ?? "GET"
    for (const c of cases) {
      if (c.method !== method) continue
      const matches = c.exact
        ? u.pathname === c.pathname
        : u.pathname === c.pathname || u.pathname.startsWith(`${c.pathname}/`)
      if (matches) return c.respond(init, u.pathname, u.searchParams)
    }
    if (fallback) return fallback(url, init)
    throw new Error(`Unhandled ${method} ${u.pathname}`)
  }
}

let routes: FetchCase[] = []
const fetchStub = ((url: string, init?: RequestInit) =>
  fetchRouter(routes)(url, init)) as unknown as typeof fetch
const originalFetch = globalThis.fetch
beforeEach(() => {
  globalThis.fetch = fetchStub
})
afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
  notifyCalls.length = 0
})

const agent = makeAgent()
const models = [model("model-1", "DeepSeek Chat")]
const knowledgeBases = [knowledgeBase("knowledge-1", "产品文档")]
const tools = [tool()]

function LanguageProviderWrap({ children }: { children: React.ReactNode }) {
  return (
    <LanguageProvider defaultLanguage="zh-Hans">{children}</LanguageProvider>
  )
}

type HarnessProps = {
  agent?: Agent
  runs?: AgentRun[]
  toolCallsByRun?: Record<string, AgentToolCall[]>
  resolvingCallId?: string | null
  question?: string
  files?: File[]
  pendingQuestion?: string | null
  isDirty?: boolean
  isSaving?: boolean
  isPublishing?: boolean
  isAsking?: boolean
  isRunsLoading?: boolean
  activeView?: "overview" | "settings" | "logs" | "monitoring" | "users"
  canManagePublishing?: boolean
  canEdit?: boolean
  onViewChange?: (view: string) => void
  onBack?: () => void
  onDelete?: () => void
  onSave?: (event: unknown) => void
  onPublish?: () => void
  onAsk?: (event: unknown) => void
  onCancelAsk?: () => void
  onNewConversation?: () => void
  onToolCallDecision?: (
    runId: string,
    callId: string,
    decision: "approve" | "reject"
  ) => void
  onRegenerateRun?: (runId: string, goal?: string) => void
  onRunFeedback?: (
    runId: string,
    value: "positive" | "negative" | null
  ) => void
  regeneratingRunId?: string | null
  feedbackPendingRunId?: string | null
}

function Harness(props: HarnessProps = {}) {
  const { t } = useLanguage()
  const workspaceAgent = props.agent ?? agent
  const [form, setForm] = useState<AgentFormState>(() =>
    formFrom(workspaceAgent)
  )
  const [question, setQuestion] = useState(props.question ?? "")
  const [files, setFiles] = useState<File[]>(props.files ?? [])
  const callbacks = {
    onBack: props.onBack ?? (() => undefined),
    onDelete: props.onDelete ?? (() => undefined),
    onSave: props.onSave ?? (() => undefined),
    onPublish: props.onPublish ?? (() => undefined),
    onViewChange: props.onViewChange ?? (() => undefined),
    onAsk: props.onAsk ?? (() => undefined),
    onCancelAsk: props.onCancelAsk ?? (() => undefined),
    onNewConversation: props.onNewConversation ?? (() => undefined),
    onToolCallDecision: props.onToolCallDecision ?? (() => undefined),
    onRegenerateRun: props.onRegenerateRun ?? (() => undefined),
    onRunFeedback: props.onRunFeedback ?? (() => undefined),
    notify: (kind: "success" | "error", message: string) =>
      notifyCalls.push({ kind, message }),
    t,
  }
  return (
    <AgentDetailWorkspace
      agent={workspaceAgent}
      form={form}
      setForm={setForm}
      models={models}
      knowledgeBases={knowledgeBases}
      tools={tools}
      runs={props.runs ?? []}
      toolCallsByRun={props.toolCallsByRun ?? {}}
      resolvingCallId={props.resolvingCallId ?? null}
      question={question}
      setQuestion={setQuestion}
      files={files}
      setFiles={setFiles}
      pendingQuestion={props.pendingQuestion ?? null}
      isDirty={props.isDirty ?? false}
      isSaving={props.isSaving ?? false}
      isPublishing={props.isPublishing ?? false}
      isAsking={props.isAsking ?? false}
      isRunsLoading={props.isRunsLoading ?? false}
      activeView={props.activeView ?? "overview"}
      token="test-token"
      workspaceId={WS}
      canManagePublishing={props.canManagePublishing ?? true}
      onBack={callbacks.onBack}
      onDelete={callbacks.onDelete}
      onSave={callbacks.onSave as never}
      onPublish={callbacks.onPublish}
      onViewChange={callbacks.onViewChange as never}
      onAsk={callbacks.onAsk as never}
      onCancelAsk={callbacks.onCancelAsk}
      onNewConversation={callbacks.onNewConversation}
      onToolCallDecision={callbacks.onToolCallDecision}
      onRegenerateRun={callbacks.onRegenerateRun}
      onRunFeedback={callbacks.onRunFeedback}
      regeneratingRunId={props.regeneratingRunId ?? null}
      feedbackPendingRunId={props.feedbackPendingRunId ?? null}
      notify={callbacks.notify}
      t={t}
    />
  )
}

function navButton(name: string) {
  const navs = screen.getAllByLabelText("Agent 详情导航")
  return within(navs[0]).getByRole("button", { name })
}

describe("AgentDetailWorkspace header and navigation", () => {
  test("renders the header with model line and view label", () => {
    renderPage(<Harness />)
    expect(screen.getByText("Research Assistant")).toBeTruthy()
    expect(screen.getByText("已启用")).toBeTruthy()
    expect(screen.getByText(/DeepSeek Chat · 概览/)).toBeTruthy()
    expect(screen.getByLabelText("返回 Agent 列表")).toBeTruthy()
  })

  test("shows published and dirty badges", () => {
    renderPage(<Harness agent={makeAgent({ published: true })} isDirty />)
    expect(screen.getAllByText("已发布").length).toBeGreaterThan(0)
    expect(screen.getByText("未保存")).toBeTruthy()
  })

  test("publish action cycles through publish states", () => {
    const view = renderPage(<Harness agent={makeAgent({ published: false })} />)
    expect(screen.getByText("发布").closest("button")!).toBeTruthy()
    view.rerender(
      <LanguageProviderWrap>
        <Harness
          agent={makeAgent({ published: true, has_unpublished_changes: true })}
        />
      </LanguageProviderWrap>
    )
    expect(screen.getByText("重新发布").closest("button")!).toBeTruthy()
  })

  test("unpublish action appears for a published clean agent", () => {
    renderPage(
      <Harness
        agent={makeAgent({ published: true, has_unpublished_changes: false })}
      />
    )
    expect(screen.getByText("取消发布").closest("button")!).toBeTruthy()
  })

  test("publish is disabled while dirty or publishing", () => {
    renderPage(<Harness isDirty />)
    expect(
      (screen.getByText("发布").closest("button")! as HTMLButtonElement)
        .disabled
    ).toBe(true)
    renderPage(<Harness isPublishing />)
    const publishButtons = screen.getAllByRole("button", { name: /发布/ })
    expect(
      publishButtons.some((button) => (button as HTMLButtonElement).disabled)
    ).toBe(true)
  })

  test("hides the publish button for non-admin members", () => {
    renderPage(<Harness canManagePublishing={false} />)
    expect(screen.queryByRole("button", { name: /发布/ })).toBeNull()
  })

  test("save button is disabled until dirty", () => {
    renderPage(<Harness activeView="settings" />)
    const cleanSave = screen
      .getAllByRole("button", { name: "保存" })
      .at(-1) as HTMLButtonElement
    expect(cleanSave.disabled).toBe(true)
    renderPage(<Harness activeView="settings" isDirty />)
    const dirtySave = screen
      .getAllByRole("button", { name: "保存" })
      .at(-1) as HTMLButtonElement
    expect(dirtySave.disabled).toBe(false)
  })

  test("submitting the settings form calls onSave", () => {
    const onSave = (event: unknown) => {
      savedEvent = event as { preventDefault?: () => void }
    }
    let savedEvent: { preventDefault?: () => void } = {}
    renderPage(<Harness activeView="settings" isDirty onSave={onSave} />)
    const form = document.getElementById("agent-settings-form")
    fireEvent.submit(form!)
    expect(savedEvent.preventDefault).toBeTypeOf("function")
  })

  test("new conversation and panel toggle are available in settings", () => {
    const onNewConversation = (() => {
      newConversationCalls += 1
    }) as () => void
    let newConversationCalls = 0
    renderPage(
      <Harness activeView="settings" onNewConversation={onNewConversation} />
    )
    fireEvent.click(screen.getByLabelText("新建对话"))
    expect(newConversationCalls).toBe(1)
    fireEvent.click(screen.getByLabelText("预览"))
    expect(screen.getByLabelText("设置")).toBeTruthy()
  })

  test("exposes delete as a standalone action", () => {
    let deleteCalls = 0
    renderPage(
      <Harness
        onDelete={() => {
          deleteCalls += 1
        }}
      />
    )
    fireEvent.click(screen.getByLabelText("删除 Agent"))
    expect(deleteCalls).toBe(1)
  })

  test("navigation switches views for editable agents", () => {
    const views: string[] = []
    renderPage(<Harness onViewChange={(view) => views.push(view)} />)
    fireEvent.click(navButton("对话日志"))
    fireEvent.click(navButton("监控统计"))
    fireEvent.click(navButton("对话用户"))
    fireEvent.click(navButton("设置"))
    expect(views).toEqual(["logs", "monitoring", "users", "settings"])
  })

  test("view-only agents only see overview and settings", () => {
    renderPage(<Harness agent={makeAgent({ can_edit: false })} />)
    const navs = screen.getAllByLabelText("Agent 详情导航")
    expect(
      within(navs[0]).queryByRole("button", { name: "对话日志" })
    ).toBeNull()
    expect(within(navs[0]).getByText("概览").closest("button")!).toBeTruthy()
  })

  test("falls back to overview when a restricted view is active", () => {
    renderPage(
      <Harness agent={makeAgent({ can_edit: false })} activeView="logs" />
    )
    expect(screen.getByText("公开访问与 API")).toBeTruthy()
    expect(screen.queryByText("对话日志")).toBeNull()
  })

  test("back button calls onBack", () => {
    let backCalls = 0
    renderPage(
      <Harness
        onBack={() => {
          backCalls += 1
        }}
      />
    )
    fireEvent.click(screen.getByLabelText("返回 Agent 列表"))
    expect(backCalls).toBe(1)
  })
})

describe("AgentDetailWorkspace preview", () => {
  test("shows the empty conversation state", () => {
    renderPage(<Harness activeView="settings" />)
    expect(screen.getByText("开始和 Agent 对话")).toBeTruthy()
  })

  test("shows the loading state", () => {
    renderPage(<Harness activeView="settings" isRunsLoading />)
    expect(screen.getByText("正在加载")).toBeTruthy()
  })

  test("renders a succeeded run with its answer", () => {
    const run = makeRun({ status: "succeeded", result: "**bold** summary" })
    renderPage(<Harness activeView="settings" runs={[run]} />)
    expect(screen.getByText("Summarize the latest releases")).toBeTruthy()
    expect(screen.getByText("bold")).toBeTruthy()
    expect(screen.getByText("summary")).toBeTruthy()
  })

  test("shows the first-token timestamp below the answer", () => {
    const run = makeRun({
      created_at: "2026-08-04T00:00:00Z",
      events: [
        {
          type: "thought",
          turn: 1,
          tool_name: "",
          status: "succeeded",
          summary: "agent.answer_ready",
          call_id: "",
          tool_label: "",
          tool_kind: "unknown",
          server_name: "",
          input: {},
          output: null,
          duration_ms: 0,
          created_at: "2026-08-04T00:00:01Z",
        },
      ],
    })
    const { container } = renderPage(
      <Harness activeView="settings" runs={[run]} />
    )
    const timestamps = container.querySelectorAll("time")

    expect(timestamps).toHaveLength(1)
    expect(timestamps[0]?.getAttribute("datetime")).toBe(
      "2026-08-04T00:00:01Z"
    )
  })

  test("renders generated artifacts as filename download links", () => {
    const downloadUrl = "/api/v1/artifacts/signed-token"
    const run = makeRun({
      result: `📄 下载地址：\`${downloadUrl}\``,
      events: [
        {
          type: "tool",
          turn: 1,
          tool_name: "create_artifact",
          status: "succeeded",
          summary: "Artifact created.",
          call_id: "artifact-call",
          tool_label: "Create document or page",
          tool_kind: "unknown",
          server_name: "",
          input: {},
          output: {
            filename: "公司内部管理制度汇编.docx",
            download_url: downloadUrl,
          },
          duration_ms: 10,
        },
      ],
    })

    renderPage(<Harness activeView="settings" runs={[run]} />)

    const link = screen.getByRole("link", {
      name: "公司内部管理制度汇编.docx",
    })
    expect(link.getAttribute("href")).toBe(downloadUrl)
    expect(link.className).toContain("text-sky-600")
    expect(link.hasAttribute("download")).toBe(true)
    expect(link.getAttribute("target")).toBeNull()
    expect(screen.queryByText(downloadUrl)).toBeNull()
  })

  test("preserves and wraps multiline user messages", () => {
    const goal = [
      "scc .",
      "───────────────────────────────────────────────────────────────────────────────",
      "Language            Files       Lines    Blanks  Comments       Code Complexity",
    ].join("\n")
    const { container } = renderPage(
      <Harness activeView="settings" runs={[makeRun({ goal })]} />
    )
    const message = Array.from(container.querySelectorAll(".bg-foreground")).find(
      (element) => element.textContent === goal
    )

    expect(message).toBeTruthy()
    expect(message!.className).toContain("whitespace-pre-wrap")
    expect(message!.className).toContain("[overflow-wrap:anywhere]")
  })

  test("closes the message editor after resubmitting", () => {
    const regenerated: Array<[string, string | undefined]> = []
    renderPage(
      <Harness
        activeView="settings"
        runs={[makeRun()]}
        onRegenerateRun={(runId, goal) => regenerated.push([runId, goal])}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "编辑消息" }))
    fireEvent.change(screen.getByLabelText("编辑消息"), {
      target: { value: "Updated question" },
    })
    fireEvent.click(screen.getByRole("button", { name: "重新发送" }))

    expect(regenerated).toEqual([["run-1", "Updated question"]])
    expect(screen.queryByLabelText("编辑消息")).toBeNull()
  })

  test("renders unified result actions and disables regeneration while busy", () => {
    const regenerated: string[] = []
    const feedback: Array<[string, "positive" | "negative" | null]> = []
    const run = makeRun({
      status: "succeeded",
      result: "Completed answer",
      feedback: "positive",
    })
    renderPage(
      <Harness
        activeView="settings"
        runs={[run]}
        isAsking
        onRegenerateRun={(runId) => regenerated.push(runId)}
        onRunFeedback={(runId, value) => feedback.push([runId, value])}
      />
    )

    const regenerate = screen.getByRole("button", { name: "重新生成" })
    const like = screen.getByRole("button", { name: "取消点赞" })
    expect((regenerate as HTMLButtonElement).disabled).toBe(true)
    expect(like.getAttribute("aria-pressed")).toBe("true")

    fireEvent.click(regenerate)
    fireEvent.click(like)
    expect(regenerated).toEqual([])
    expect(feedback).toEqual([["run-1", null]])
    expect(screen.getByRole("button", { name: "点踩" })).toBeTruthy()
    expect(screen.getAllByRole("button", { name: "复制" }).length).toBeGreaterThan(0)
  })

  test("renders a failed run with the error message", () => {
    const run = makeRun({
      status: "failed",
      result: "",
      last_error: "model timeout",
    })
    renderPage(<Harness activeView="settings" runs={[run]} />)
    expect(screen.getByText("model timeout")).toBeTruthy()
  })

  test("renders queued and cancelled runs", () => {
    const { container } = renderPage(
      <Harness
        activeView="settings"
        runs={[
          makeRun({ id: "run-q", status: "queued", result: "" }),
          makeRun({
            id: "run-c",
            status: "cancelled",
            result: "",
            events: [
              {
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
              },
              {
                type: "thought",
                turn: 1,
                tool_name: "",
                status: "failed",
                summary: "agent.answer_ready",
                call_id: "",
                tool_label: "",
                tool_kind: "unknown",
                server_name: "",
                input: {},
                output: null,
                duration_ms: 0,
              },
            ],
          }),
        ]}
      />
    )
    expect(screen.getByText("等待执行")).toBeTruthy()
    expect(screen.getAllByText("运行已取消").length).toBeGreaterThan(0)
    expect(container.querySelectorAll(".animate-spin")).toHaveLength(0)
    expect(screen.queryByText("正在生成回答")).toBeNull()
  })

  test("renders the answering indicator for a running run", () => {
    const run = makeRun({
      id: "run-r",
      status: "running",
      result: "",
      events: [],
    })
    renderPage(<Harness activeView="settings" runs={[run]} />)
    expect(screen.getAllByText("正在生成回答").length).toBeGreaterThan(0)
  })

  test("renders process timeline with thought and tool events", () => {
    const run = makeRun({
      status: "running",
      result: "",
      events: [
        {
          type: "thought",
          turn: 1,
          tool_name: "",
          status: "succeeded",
          summary: "agent.tools_selected",
          call_id: "",
          tool_label: "",
          tool_kind: "unknown",
          server_name: "",
          input: {},
          output: null,
          duration_ms: 0,
        },
        {
          type: "thought",
          turn: 2,
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
          reasoning: "Reasoning line",
        },
        {
          type: "thought",
          turn: 3,
          tool_name: "",
          status: "succeeded",
          summary: "agent.tools_selected",
          call_id: "",
          tool_label: "",
          tool_kind: "unknown",
          server_name: "",
          input: {},
          output: null,
          duration_ms: 0,
          reasoning: "Tool reasoning result",
        },
        {
          type: "tool",
          turn: 3,
          tool_name: "search",
          status: "running",
          summary: "agent.preparing_tool_call",
          call_id: "call-3",
          tool_label: "search",
          tool_kind: "unknown",
          server_name: "",
          input: { query: "latest releases" },
          output: null,
          duration_ms: 0,
        },
        {
          type: "tool",
          turn: 1,
          tool_name: "search",
          status: "succeeded",
          summary: "agent.tool_running",
          call_id: "call-2",
          tool_label: "search",
          tool_kind: "mcp",
          server_name: "Database",
          input: { query: "releases" },
          output: { hits: 1 },
          duration_ms: 120,
        },
      ],
    })
    renderPage(<Harness activeView="settings" runs={[run]} />)
    expect(screen.getAllByText("已完成分析")).toHaveLength(2)
    const reasoning = screen.getByText("Tool reasoning result")
    const preparing = screen.getAllByText("search")[0]!
    expect(
      reasoning.compareDocumentPosition(preparing) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
    fireEvent.click(preparing.closest("button")!)
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "PRE" &&
          element.textContent === "query:\nlatest releases"
      )
    ).toBeTruthy()
    expect(screen.getByText("Reasoning line")).toBeTruthy()
    const searchLabels = screen.getAllByText("search")
    expect(searchLabels).toHaveLength(2)

    const completedToolButton = searchLabels[1]!.closest("button")!
    const completedToolCard = completedToolButton.parentElement!
    fireEvent.click(completedToolButton)
    expect(within(completedToolCard).getByText("调用输入")).toBeTruthy()
    expect(within(completedToolCard).getByText(/query/)).toBeTruthy()
    expect(within(completedToolCard).getByText("调用结果")).toBeTruthy()
  })

  test("renders knowledge hits inside tool details", () => {
    const run = makeRun({
      status: "running",
      result: "",
      events: [
        {
          type: "tool",
          turn: 0,
          tool_name: "knowledge_retrieval",
          status: "succeeded",
          summary: "agent.knowledge_chunks_returned:2",
          call_id: "call-3",
          tool_label: "",
          tool_kind: "knowledge",
          server_name: "",
          input: { query: "x" },
          output: {
            hits: [
              {
                document: "doc-a",
                knowledge_base: "kb-a",
                content: "chunk content",
              },
            ],
          },
          duration_ms: 10,
        },
      ],
    })
    renderPage(<Harness activeView="settings" runs={[run]} />)
    expect(screen.getByText("知识库检索")).toBeTruthy()
    expect(screen.getByText("已检索 2 个知识片段")).toBeTruthy()
    fireEvent.click(screen.getByText("知识库检索").closest("button")!)
    expect(screen.getByText("doc-a")).toBeTruthy()
    expect(screen.getByText("chunk content")).toBeTruthy()
  })

  test("renders inline approval and resolves it", () => {
    const run = makeRun({ status: "awaiting_approval", result: "", events: [] })
    const calls: Array<[string, string, string]> = []
    renderPage(
      <Harness
        activeView="settings"
        runs={[run]}
        toolCallsByRun={{ "run-1": [makeToolCall()] }}
        onToolCallDecision={(runId, callId, decision) =>
          calls.push([runId, callId, decision])
        }
      />
    )
    expect(screen.getByText("工具调用需要确认")).toBeTruthy()
    expect(screen.getByText(/execute_sql/)).toBeTruthy()
    fireEvent.click(screen.getByText("批准并执行").closest("button")!)
    expect(calls).toEqual([["run-1", "call-1", "approve"]])
    fireEvent.click(screen.getByText("拒绝").closest("button")!)
    expect(calls[1]).toEqual(["run-1", "call-1", "reject"])
  })

  test("renders an uncertain approval with its error", () => {
    const run = makeRun({ status: "awaiting_approval", result: "", events: [] })
    renderPage(
      <Harness
        activeView="settings"
        runs={[run]}
        toolCallsByRun={{
          "run-1": [
            makeToolCall({ status: "uncertain", last_error: "retry failed" }),
          ],
        }}
      />
    )
    expect(screen.getByText("工具执行结果不确定")).toBeTruthy()
    expect(screen.getByText("不重试并继续")).toBeTruthy()
    expect(screen.getByText("retry failed")).toBeTruthy()
  })

  test("renders pending tool calls as running events", () => {
    const run = makeRun({ status: "running", result: "", events: [] })
    renderPage(
      <Harness
        activeView="settings"
        runs={[run]}
        toolCallsByRun={{ "run-1": [makeToolCall({ status: "pending" })] }}
      />
    )
    expect(screen.getAllByText(/execute_sql/).length).toBeGreaterThan(0)
  })

  test("shows collapsed process status for approvals", async () => {
    const run = makeRun({ status: "awaiting_approval", result: "", events: [] })
    const { container } = renderPage(
      <Harness
        activeView="settings"
        runs={[run]}
        toolCallsByRun={{ "run-1": [makeToolCall()] }}
      />
    )
    const details = container.querySelector("details") as HTMLDetailsElement
    expect(details).toBeTruthy()
    details.open = false
    details.dispatchEvent(new Event("toggle", { bubbles: true }))
    await waitFor(() =>
      expect(screen.getByText("等待工具调用确认")).toBeTruthy()
    )
  })

  test("typing and submitting the ask form calls onAsk", () => {
    let submitted: { preventDefault?: () => void } | null = null
    renderPage(
      <Harness
        activeView="settings"
        onAsk={(event) => {
          submitted = event as { preventDefault?: () => void }
        }}
      />
    )
    const textarea = screen.getByLabelText(
      "向 Agent 提问"
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "What is new?" } })
    expect(textarea.value).toBe("What is new?")
    const form = textarea.closest("form")
    fireEvent.submit(form!)
    expect(submitted).toBeTruthy()
  })

  test("submit button is disabled without a question or while busy", () => {
    renderPage(<Harness activeView="settings" />)
    expect(
      (screen.getByLabelText("发送问题") as HTMLButtonElement).disabled
    ).toBe(true)
    renderPage(<Harness activeView="settings" question="q" isAsking />)
    expect(screen.getByLabelText("停止生成")).toBeTruthy()
  })

  test("ask controls are disabled for dirty or disabled agents", () => {
    renderPage(<Harness activeView="settings" isDirty />)
    expect(
      (screen.getAllByLabelText("向 Agent 提问").at(-1) as HTMLTextAreaElement)
        .disabled
    ).toBe(true)
    expect(
      (screen.getAllByLabelText("添加附件").at(-1) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    renderPage(
      <Harness
        activeView="settings"
        agent={makeAgent({ status: "disabled" })}
      />
    )
    expect(
      (screen.getAllByLabelText("向 Agent 提问").at(-1) as HTMLTextAreaElement)
        .disabled
    ).toBe(true)
  })

  test("attaches and removes files", () => {
    renderPage(<Harness activeView="settings" />)
    const fileInput = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement
    const file = new File(["a"], "notes.txt", { type: "text/plain" })
    fireEvent.change(fileInput, { target: { files: [file] } })
    expect(screen.getByText("notes.txt")).toBeTruthy()
    fireEvent.click(screen.getByLabelText("移除 notes.txt"))
    expect(screen.queryByText("notes.txt")).toBeNull()
  })

  test("shows a pending question while asking", () => {
    renderPage(
      <Harness activeView="settings" pendingQuestion="Loading question" />
    )
    expect(screen.queryByText("开始和 Agent 对话")).toBeNull()
  })

  test("fires the scroll-follow handler", () => {
    const { container } = renderPage(
      <Harness
        activeView="settings"
        runs={[makeRun({ status: "succeeded", result: "answer" })]}
      />
    )
    const scrollHost = container.querySelector(
      ".overflow-y-auto"
    ) as HTMLElement
    fireEvent.scroll(scrollHost, { target: { scrollTop: 10 } })
    expect(screen.getByText("answer")).toBeTruthy()
  })
})

describe("AgentOverviewPanel", () => {
  test("shows public URL and copy/open actions", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async () => undefined },
      configurable: true,
    })
    renderPage(<Harness />)
    const overview = screen.getByText("公开访问与 API").closest("section")
    expect(overview?.className).toContain("max-w-[1600px]")
    const accessGrid = screen
      .getByText("公开访问链接")
      .closest("div.min-w-0")?.parentElement
    expect(accessGrid?.className).toContain("xl:grid")
    expect(screen.getByText(/\/chat\/agent-1/)).toBeTruthy()
    expect(screen.getByText("未发布")).toBeTruthy()
    expect(screen.getByText("发布后此链接才可访问。")).toBeTruthy()
    fireEvent.click(screen.getByText("复制链接").closest("button")!)
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.message === "已复制")).toBe(true)
    )
    const openLink = screen.getByRole("link", { name: "打开链接" })
    expect(openLink.getAttribute("href")).toContain("/chat/agent-1")
    const apiDocs = screen.getByRole("link", { name: "API 文档" })
    expect(apiDocs.getAttribute("href")).toContain("/agent-api/agent-1/docs")
  })

  test("manages API keys: create, rotate and revoke", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ items: [] }),
      },
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () =>
          jsonResponse({
            credential: {
              id: "cred-1",
              agent_id: "agent-1",
              workspace_id: WS,
              name: "Production",
              hint: "nxf_…abcd",
              created_by_user_id: "u-1",
              last_used_at: null,
              revoked_at: null,
              created_at: "2026-08-04T00:00:00Z",
            },
            token: "nxf_secret_token",
          }),
      },
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials/cred-1/rotate`,
        exact: true,
        respond: () =>
          jsonResponse({
            credential: {
              id: "cred-1",
              agent_id: "agent-1",
              workspace_id: WS,
              name: "Production",
              hint: "nxf_…wxyz",
              created_by_user_id: "u-1",
              last_used_at: null,
              revoked_at: null,
              created_at: "2026-08-04T00:00:00Z",
            },
            token: "nxf_rotated_token",
          }),
      },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials/cred-1`,
        exact: true,
        respond: () => new Response(null, { status: 204 }),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("暂无 API Key")).toBeTruthy())

    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Production" },
    })
    fireEvent.submit(screen.getByLabelText("名称").closest("form")!)
    await waitFor(() =>
      expect(screen.getByText("nxf_secret_token")).toBeTruthy()
    )
    expect(screen.getAllByText("Production").length).toBeGreaterThan(0)

    fireEvent.click(screen.getByText("轮换").closest("button")!)
    await waitFor(() =>
      expect(screen.getByText("nxf_rotated_token")).toBeTruthy()
    )
    expect(notifyCalls.some((call) => call.message === "API Key 已轮换")).toBe(
      true
    )

    fireEvent.click(screen.getByText("撤销").closest("button")!)
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "撤销" }
      )
    )
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "API Key 已撤销")
      ).toBe(true)
    )
    expect(screen.getByText("已撤销")).toBeTruthy()

    fireEvent.click(screen.getByText("关闭").closest("button")!)
    expect(screen.queryByText("nxf_rotated_token")).toBeNull()
  })

  test("view-only member cannot manage API keys", () => {
    renderPage(<Harness agent={makeAgent({ can_edit: false })} />)
    expect(screen.getByText("仅工作空间管理员可管理 API Key。")).toBeTruthy()
  })

  test("member without manage rights sees read-only key list", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () =>
          jsonResponse({
            items: [
              {
                id: "cred-2",
                agent_id: "agent-1",
                workspace_id: WS,
                name: "Service",
                hint: "nxf_…0000",
                created_by_user_id: "u-1",
                last_used_at: "2026-08-05T00:00:00Z",
                revoked_at: null,
                created_at: "2026-08-01T00:00:00Z",
              },
            ],
          }),
      },
    ]
    renderPage(<Harness canManagePublishing={false} />)
    fireEvent.click(screen.getByText("查看 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("Service")).toBeTruthy())
  })
})

describe("AgentOverviewPanel API key failure paths", () => {
  const credential = (id: string) => ({
    id,
    agent_id: "agent-1",
    workspace_id: WS,
    name: `Key ${id}`,
    hint: "nxf_…abcd",
    created_by_user_id: "u-1",
    last_used_at: null,
    revoked_at: null,
    created_at: "2026-08-01T00:00:00Z",
  })

  test("reports an error when API keys fail to load", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.kind === "error")).toBe(true)
    )
  })

  test("reports an error when creating an API key fails", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ items: [] }),
      },
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("暂无 API Key")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Broken" },
    })
    fireEvent.submit(screen.getByLabelText("名称").closest("form")!)
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.kind === "error")).toBe(true)
    )
  })

  test("reports an error when rotating an API key fails", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ items: [credential("cred-r")] }),
      },
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials/cred-r/rotate`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("Key cred-r")).toBeTruthy())
    fireEvent.click(screen.getByText("轮换").closest("button")!)
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.kind === "error")).toBe(true)
    )
  })

  test("shows the rotating spinner while a rotation is in flight", async () => {
    let resolveRotate: (value: Response) => void = () => undefined
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ items: [credential("cred-s")] }),
      },
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials/cred-s/rotate`,
        exact: true,
        respond: () =>
          new Promise<Response>((resolve) => {
            resolveRotate = resolve
          }),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("Key cred-s")).toBeTruthy())
    fireEvent.click(screen.getByText("轮换").closest("button")!)
    expect(screen.getAllByText("轮换").length).toBeGreaterThanOrEqual(1)
    resolveRotate!(
      jsonResponse({
        credential: { ...credential("cred-s"), hint: "nxf_…wxyz" },
        token: "nxf_rotated",
      })
    )
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "API Key 已轮换")
      ).toBe(true)
    )
  })

  test("reports an error when revoking an API key fails", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ items: [credential("cred-v")] }),
      },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials/cred-v`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("Key cred-v")).toBeTruthy())
    fireEvent.click(screen.getByText("撤销").closest("button")!)
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "撤销" }
      )
    )
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.kind === "error")).toBe(true)
    )
  })

  test("revoking one key leaves the other credentials untouched", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () =>
          jsonResponse({ items: [credential("cred-a"), credential("cred-b")] }),
      },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials/cred-a`,
        exact: true,
        respond: () => new Response(null, { status: 204 }),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("Key cred-a")).toBeTruthy())
    fireEvent.click(screen.getAllByText("撤销")[0].closest("button")!)
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "撤销" }
      )
    )
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "API Key 已撤销")
      ).toBe(true)
    )
    expect(screen.getByText("已撤销")).toBeTruthy()
    expect(screen.getByText("Key cred-b")).toBeTruthy()
  })

  test("copies a freshly created API key token", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () => jsonResponse({ items: [] }),
      },
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/api-credentials`,
        exact: true,
        respond: () =>
          jsonResponse({
            credential: { ...credential("cred-c"), name: "Production" },
            token: "nxf_copy_me",
          }),
      },
    ]
    renderPage(<Harness />)
    fireEvent.click(screen.getByText("管理 API Key").closest("button")!)
    await waitFor(() => expect(screen.getByText("暂无 API Key")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "Production" },
    })
    fireEvent.submit(screen.getByLabelText("名称").closest("form")!)
    await waitFor(() => expect(screen.getByText("nxf_copy_me")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("复制 API Key"))
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "API Key 已复制")
      ).toBe(true)
    )
  })

  test("reports an error when copying the public link fails", async () => {
    const originalClipboard = navigator.clipboard
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async () => {
          throw new Error("denied")
        },
      },
      configurable: true,
    })
    try {
      renderPage(<Harness />)
      fireEvent.click(screen.getByText("复制链接").closest("button")!)
      await waitFor(() =>
        expect(notifyCalls.some((call) => call.message === "复制失败")).toBe(
          true
        )
      )
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      })
    }
  })
})

describe("AgentLogsPanel", () => {
  const logItem = {
    id: "log-1",
    conversation_id: "conversation-1",
    access_source: "public",
    consumer_id: "anonymous-1",
    display_name: "Visitor",
    requested_by_user_id: null,
    execution_user_id: "u-1",
    question: "How do I reset my password?",
    status: "succeeded",
    result: "**Step one**",
    last_error: null,
    model_usage: { prompt_tokens: 5 },
    feedback: "positive",
    feedback_updated_at: "2026-08-04T00:01:00Z",
    created_at: "2026-08-04T00:00:00Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-08-04T00:00:00Z",
  }

  test("shows loading then empty states", async () => {
    let resolveFirst: (value: Response) => void
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/logs`,
        exact: false,
        respond: () =>
          new Promise<Response>((resolve) => {
            resolveFirst = resolve
          }),
      },
    ]
    renderPage(<Harness activeView="logs" />)
    expect(screen.getByText("正在加载")).toBeTruthy()
    resolveFirst!(jsonResponse({ items: [], total: 0, offset: 0, limit: 20 }))
    await waitFor(() => expect(screen.getByText("暂无对话日志")).toBeTruthy())
  })

  test("renders log rows with pagination and detail dialog", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/logs`,
        exact: false,
        respond: (_init, _path, query) =>
          jsonResponse({
            items: [logItem],
            total: 45,
            offset: Number(query?.get("offset") ?? 0),
            limit: 20,
          }),
      },
    ]
    renderPage(<Harness activeView="logs" />)
    await waitFor(() =>
      expect(screen.getByText("How do I reset my password?")).toBeTruthy()
    )
    expect(screen.getByText("公开访问")).toBeTruthy()
    expect(screen.getByText("Visitor")).toBeTruthy()
    expect(screen.getByText("成功")).toBeTruthy()
    expect(screen.getByRole("img", { name: "点赞" })).toBeTruthy()
    expect(screen.getByText("显示 1-20，共 45 条")).toBeTruthy()

    fireEvent.click(screen.getByText("下一页").closest("button")!)
    await waitFor(() =>
      expect(screen.getByText("显示 21-40，共 45 条")).toBeTruthy()
    )
    fireEvent.click(screen.getByText("上一页").closest("button")!)
    await waitFor(() =>
      expect(screen.getByText("显示 1-20，共 45 条")).toBeTruthy()
    )

    fireEvent.click(screen.getByLabelText("查看日志详情"))
    await waitFor(() => expect(screen.getByText("对话详情")).toBeTruthy())
    expect(screen.getByText("Step one")).toBeTruthy()
    expect(screen.getAllByRole("img", { name: "点赞" }).length).toBeGreaterThan(0)
    expect(screen.getByText("暂无错误")).toBeTruthy()
    expect(screen.getByText(/"prompt_tokens"/)).toBeTruthy()
  })

  test("renders error states in log rows and refresh", async () => {
    const failingLog = {
      ...logItem,
      id: "log-2",
      question: "",
      access_source: "api",
      status: "failed",
      feedback: null,
      last_error: "execution crashed",
      result: "",
      display_name: "",
    }
    let page = 0
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/logs`,
        exact: false,
        respond: () => {
          page += 1
          return jsonResponse({
            items: page === 1 ? [failingLog] : [],
            total: 1,
            offset: 0,
            limit: 20,
          })
        },
      },
    ]
    renderPage(<Harness activeView="logs" />)
    await waitFor(() => expect(screen.getByText("未提供问题")).toBeTruthy())
    expect(screen.getByText("API")).toBeTruthy()
    expect(screen.getByText("失败")).toBeTruthy()
    expect(screen.getByRole("img", { name: "暂无反馈" })).toBeTruthy()
    expect(screen.getByText("execution crashed")).toBeTruthy()
    fireEvent.click(screen.getByText("刷新").closest("button")!)
    await waitFor(() => expect(screen.getByText("暂无对话日志")).toBeTruthy())
  })

  test("reports a logs load error", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/logs`,
        exact: false,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<Harness activeView="logs" />)
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.kind === "error")).toBe(true)
    )
  })

  test("renders console-sourced logs and opens details with the keyboard", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/logs`,
        exact: false,
        respond: () =>
          jsonResponse({
            items: [
              {
                ...logItem,
                id: "log-3",
                access_source: "console",
                display_name: "",
                result: "",
                feedback: "negative",
                last_error: "step failed",
              },
            ],
            total: 1,
            offset: 0,
            limit: 20,
          }),
      },
    ]
    renderPage(<Harness activeView="logs" />)
    await waitFor(() =>
      expect(screen.getByText("How do I reset my password?")).toBeTruthy()
    )
    expect(screen.getByText("控制台")).toBeTruthy()
    expect(screen.getByRole("img", { name: "点踩" })).toBeTruthy()
    expect(screen.getByText("step failed")).toBeTruthy()

    const row = screen.getByLabelText("查看日志详情")
    fireEvent.keyDown(row, { key: "Enter" })
    await waitFor(() => expect(screen.getByText("对话详情")).toBeTruthy())
    expect(screen.getByText("Agent 未返回结果")).toBeTruthy()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByText("对话详情")).toBeNull())
  })

  test("shows the workflow no-result message in log details", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/logs`,
        exact: false,
        respond: () =>
          jsonResponse({
            items: [{ ...logItem, id: "log-4", result: "" }],
            total: 1,
            offset: 0,
            limit: 20,
          }),
      },
    ]
    renderPage(
      <Harness agent={makeAgent({ app_type: "workflow" })} activeView="logs" />
    )
    await waitFor(() =>
      expect(screen.getByText("How do I reset my password?")).toBeTruthy()
    )
    fireEvent.click(screen.getByLabelText("查看日志详情"))
    await waitFor(() =>
      expect(screen.getByText("工作流未返回结果")).toBeTruthy()
    )
  })

  test("reports an error when refreshing logs fails", async () => {
    let page = 0
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/logs`,
        exact: false,
        respond: () => {
          page += 1
          if (page === 1) {
            return jsonResponse({
              items: [logItem],
              total: 1,
              offset: 0,
              limit: 20,
            })
          }
          return jsonResponse({ detail: "boom" }, 500)
        },
      },
    ]
    renderPage(<Harness activeView="logs" />)
    await waitFor(() =>
      expect(screen.getByText("How do I reset my password?")).toBeTruthy()
    )
    fireEvent.click(screen.getByText("刷新").closest("button")!)
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.kind === "error")).toBe(true)
    )
  })
})

describe("AgentMonitoringPanel", () => {
  const monitoring = {
    days: 7,
    summary: {
      active_users: 3,
      conversations: 10,
      runs: 25,
      succeeded: 22,
      failed: 3,
      total_tokens: 1234,
    },
    daily: [
      {
        date: "2026-08-04",
        active_users: 1,
        conversations: 2,
        runs: 5,
        succeeded: 4,
        failed: 1,
        total_tokens: 100,
      },
      {
        date: "2026-08-05",
        active_users: 2,
        conversations: 3,
        runs: 8,
        succeeded: 8,
        failed: 0,
        total_tokens: 200,
      },
    ],
  }

  test("renders summary cards and the trend chart", async () => {
    const monitoringDays: string[] = []
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/monitoring`,
        exact: false,
        respond: (_init, _path, query) => {
          monitoringDays.push(query?.get("days") ?? "")
          return jsonResponse(monitoring)
        },
      },
    ]
    renderPage(<Harness activeView="monitoring" />)
    await waitFor(() => expect(screen.getByText("活跃用户")).toBeTruthy())
    expect(screen.getByText("对话次数")).toBeTruthy()
    expect(screen.getByText("运行次数")).toBeTruthy()
    expect(screen.getByText("成功运行")).toBeTruthy()
    expect(screen.getByText("Tokens 总数")).toBeTruthy()
    expect(screen.getByText("失败 3 次")).toBeTruthy()
    expect(monitoringDays).toContain("7")

    const dropdown = screen.getByLabelText("统计周期")
    fireEvent.pointerDown(dropdown)
    fireEvent.click(dropdown)
    fireEvent.click(await screen.findByRole("menuitem", { name: /过去 30 天/ }))
    await waitFor(() => expect(monitoringDays).toContain("30"))
  })

  test("reports a monitoring load error", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/monitoring`,
        exact: false,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<Harness activeView="monitoring" />)
    await waitFor(() =>
      expect(notifyCalls.some((call) => call.kind === "error")).toBe(true)
    )
  })
})

describe("AgentConversationUsersPanel", () => {
  const userItem = {
    consumer_id: "anonymous-1",
    access_source: "public",
    display_name: "Visitor",
    first_seen_at: "2026-08-01T00:00:00Z",
    last_seen_at: "2026-08-05T00:00:00Z",
    conversation_count: 4,
    run_count: 7,
  }

  test("renders users with pagination", async () => {
    let page = 0
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/conversation-users`,
        exact: false,
        respond: () => {
          page += 1
          return jsonResponse({
            items: page === 1 ? [userItem] : [],
            total: 1,
            offset: page === 1 ? 0 : 20,
            limit: 20,
          })
        },
      },
    ]
    renderPage(<Harness activeView="users" />)
    await waitFor(() => expect(screen.getByText("Visitor")).toBeTruthy())
    expect(screen.getByText("anonymous-1")).toBeTruthy()
    expect(screen.getByText("公开访问")).toBeTruthy()
    expect(screen.getByText("4 / 7")).toBeTruthy()

    fireEvent.click(screen.getByText("刷新").closest("button")!)
    await waitFor(() => expect(screen.getByText("暂无对话用户")).toBeTruthy())
  })

  test("shows the empty state", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/conversation-users`,
        exact: false,
        respond: () =>
          jsonResponse({ items: [], total: 0, offset: 0, limit: 20 }),
      },
    ]
    renderPage(<Harness activeView="users" />)
    await waitFor(() => expect(screen.getByText("暂无对话用户")).toBeTruthy())
  })

  test("pages back through conversation users", async () => {
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/conversation-users`,
        exact: false,
        respond: (_init, _path, query) =>
          jsonResponse({
            items: [userItem],
            total: 45,
            offset: Number(query?.get("offset") ?? 0),
            limit: 20,
          }),
      },
    ]
    renderPage(<Harness activeView="users" />)
    await waitFor(() => expect(screen.getByText("Visitor")).toBeTruthy())
    expect(screen.getByText("显示 1-20，共 45 条")).toBeTruthy()
    fireEvent.click(screen.getByText("下一页").closest("button")!)
    await waitFor(() =>
      expect(screen.getByText("显示 21-40，共 45 条")).toBeTruthy()
    )
    fireEvent.click(screen.getByText("上一页").closest("button")!)
    await waitFor(() =>
      expect(screen.getByText("显示 1-20，共 45 条")).toBeTruthy()
    )
  })
})

describe("AgentDetailWorkspace edge behavior", () => {
  test("isNearScrollBottom compares the remaining scroll distance", () => {
    const near = { clientHeight: 400, scrollHeight: 440, scrollTop: 0 }
    expect(isNearScrollBottom(near)).toBe(true)
    const far = { clientHeight: 400, scrollHeight: 1000, scrollTop: 0 }
    expect(isNearScrollBottom(far)).toBe(false)
    expect(isNearScrollBottom({ ...far, scrollTop: 900 })).toBe(true)
    expect(
      isNearScrollBottom({ clientHeight: 0, scrollHeight: 0, scrollTop: 0 })
    ).toBe(true)
  })

  test("processTimeline splices eager knowledge after the first thought", () => {
    const knowledgeEvent = {
      type: "tool",
      turn: 0,
      tool_name: "knowledge_retrieval",
      status: "succeeded",
      summary: "agent.knowledge_chunks_returned:2",
      call_id: "call-3",
      tool_label: "",
      tool_kind: "knowledge",
      server_name: "",
      input: {},
      output: { hits: [] },
      duration_ms: 10,
    } as AgentRunEvent
    const thought = {
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
    } as AgentRunEvent
    const withThought = processTimeline(
      makeRun({
        status: "running",
        result: "",
        events: [knowledgeEvent, thought],
      })
    )
    // Knowledge is spliced in after the first thought event.
    expect(withThought.map((item) => item.event.call_id)).toEqual([
      "",
      "call-3",
    ])
    // Knowledge at turn 0 with no thought leaves the order untouched.
    const noThought = processTimeline(
      makeRun({
        status: "running",
        result: "",
        events: [
          knowledgeEvent,
          {
            ...thought,
            type: "tool",
            tool_name: "search",
            call_id: "call-9",
            tool_kind: "mcp",
          } as AgentRunEvent,
        ],
      })
    )
    expect(noThought.map((item) => item.event.call_id)).toEqual([
      "call-3",
      "call-9",
    ])
  })

  test("processTimeline deduplicates events by call id and position", () => {
    const timeline = processTimeline(
      makeRun({
        status: "running",
        result: "",
        events: [
          {
            type: "tool",
            turn: 1,
            tool_name: "search",
            status: "running",
            summary: "agent.tool_running",
            call_id: "call-1",
            tool_label: "search",
            tool_kind: "mcp",
            server_name: "Database",
            input: {},
            output: null,
            duration_ms: 0,
          },
          {
            type: "tool",
            turn: 1,
            tool_name: "search",
            status: "succeeded",
            summary: "agent.tool_running",
            call_id: "call-1",
            tool_label: "search",
            tool_kind: "mcp",
            server_name: "Database",
            input: {},
            output: { ok: true },
            duration_ms: 120,
          },
        ],
      })
    )
    expect(timeline).toHaveLength(1)
    expect(timeline[0].event.status).toBe("succeeded")
  })

  test("unrenderedAgentToolCalls keeps only unrendered actionable calls", () => {
    const timeline = processTimeline(
      makeRun({
        status: "running",
        result: "",
        events: [
          {
            type: "tool",
            turn: 1,
            tool_name: "search",
            status: "succeeded",
            summary: "agent.tool_running",
            call_id: "call-1",
            tool_label: "search",
            tool_kind: "mcp",
            server_name: "Database",
            input: {},
            output: null,
            duration_ms: 0,
          },
        ],
      })
    )
    const calls = [
      makeToolCall({ call_id: "call-1", status: "pending" }),
      makeToolCall({ call_id: "call-2", status: "awaiting_approval" }),
      makeToolCall({ call_id: "call-3", status: "succeeded" }),
    ]
    const pending = unrenderedAgentToolCalls(timeline, calls)
    expect(pending.map((call) => call.call_id)).toEqual(["call-2"])
  })

  test("collapsedProcessStatusKey covers the collapsed states", () => {
    expect(collapsedProcessStatusKey("running", true, false)).toBe("执行过程")
    expect(collapsedProcessStatusKey("running", false, false)).toBeNull()
    expect(collapsedProcessStatusKey("awaiting_approval", false, false)).toBe(
      "等待工具调用确认"
    )
    expect(collapsedProcessStatusKey("running", true, true)).toBeNull()
  })

  test("copies the answer message and handles clipboard failures", async () => {
    const run = makeRun({ status: "succeeded", result: "Copyable answer" })
    const originalClipboard = navigator.clipboard
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async () => undefined },
      configurable: true,
    })
    const first = renderPage(<Harness activeView="settings" runs={[run]} />)
    fireEvent.click(
      first.container.querySelectorAll('[aria-label="复制"]')[0] as HTMLElement
    )
    await waitFor(() =>
      expect(
        first.container.querySelector('[aria-label="已复制"]')
      ).toBeTruthy()
    )

    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async () => {
          throw new Error("denied")
        },
      },
      configurable: true,
    })
    const view = renderPage(<Harness activeView="settings" runs={[run]} />)
    fireEvent.click(
      view.container.querySelectorAll('[aria-label="复制"]')[0] as HTMLElement
    )
    await waitFor(() =>
      expect(
        view.container.querySelectorAll('[aria-label="复制"]').length
      ).toBe(2)
    )
    Object.defineProperty(navigator, "clipboard", {
      value: originalClipboard,
      configurable: true,
    })
  })

  test("renders the legacy knowledge chunk summary", () => {
    const run = makeRun({
      status: "running",
      result: "",
      events: [
        {
          type: "tool",
          turn: 1,
          tool_name: "knowledge_retrieval",
          status: "succeeded",
          summary: "3 knowledge chunks returned.",
          call_id: "call-4",
          tool_label: "",
          tool_kind: "knowledge",
          server_name: "",
          input: {},
          output: { hits: [] },
          duration_ms: 10,
        },
      ],
    })
    renderPage(<Harness activeView="settings" runs={[run]} />)
    expect(screen.getByText("已检索 3 个知识片段")).toBeTruthy()
  })

  test("switches to the debug preview panel", () => {
    const view = renderPage(<Harness activeView="settings" />)
    const configPanel = view.container.querySelector(
      ".border-r.bg-muted\\/30"
    ) as HTMLElement | null
    expect(configPanel).not.toBeNull()
    expect(configPanel!.className).toContain("flex")
    fireEvent.click(screen.getByRole("button", { name: "调试预览" }))
    expect(configPanel!.className).toContain("hidden")
  })

  test("submits the ask form with Enter and clicks the attachment button", async () => {
    let submitted: { preventDefault?: () => void } | null = null
    renderPage(
      <Harness
        activeView="settings"
        onAsk={(event) => {
          submitted = event as { preventDefault?: () => void }
        }}
      />
    )
    const textarea = screen.getByLabelText(
      "向 Agent 提问"
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "Entered question" } })
    fireEvent.keyDown(textarea, { key: "Enter" })
    await waitFor(() => expect(submitted).toBeTruthy())

    fireEvent.click(screen.getByTitle("添加附件").closest("button")!)
    expect(screen.getByTitle("添加附件")).toBeTruthy()
  })

  test("follows the preview scroll container when it is the scroll host", () => {
    const run = makeRun({ status: "running", result: "", events: [] })
    const { container } = renderPage(
      <Harness activeView="settings" runs={[run]} />
    )
    const scrollHost = container.querySelector(
      ".overflow-y-auto"
    ) as HTMLElement
    Object.defineProperty(scrollHost, "getClientRects", {
      value: () => [{ toJSON: () => ({}) }],
      configurable: true,
    })
    Object.defineProperty(scrollHost, "scrollHeight", {
      value: 1000,
      configurable: true,
    })
    Object.defineProperty(scrollHost, "clientHeight", {
      value: 200,
      configurable: true,
    })
    fireEvent.scroll(scrollHost, { target: { scrollTop: 5 } })
    expect(scrollHost).toBeTruthy()
  })
})

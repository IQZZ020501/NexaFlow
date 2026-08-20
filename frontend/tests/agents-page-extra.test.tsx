/* @jsxImportSource react */
/**
 * Supplementary UI coverage for components/agents/agents-page.tsx: the edges
 * the main suite does not exercise (tool-catalog failure + retry, workflow
 * agent loading guards, publish guards and workflow publish labels, run
 * regeneration and feedback success/error paths, and stream-approval
 * tool-call loading failures).
 */
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { cleanup } from "@testing-library/react"

import { AgentsPage, type AgentFormState } from "@/components/agents/agents-page"
import { LanguageProvider } from "@/contexts/language-provider"
import type {
  Agent,
  AgentRun,
  AgentToolCall,
} from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import type { ToolDetail, ToolSummary } from "@/lib/api/tools"

import {
  jsonResponse,
  makeSession,
  mockNextImage,
  mockUseSession,
  renderPage,
} from "./helpers/dom"

/* ------------------------------------------------------------------ */
/* Fixtures                                                           */
/* ------------------------------------------------------------------ */

const WS = "ws-1"

function model(
  id: string,
  name: string,
  modelName: string,
  status = "active"
): RegisteredModel {
  return {
    id,
    workspace_id: WS,
    name,
    provider: "deepseek",
    provider_type: "openai",
    model_type: "LLM",
    model_name: modelName,
    status,
    credential: {},
    api_base: "",
    has_api_key: true,
    api_key_hint: "sk-…abc",
    meta: {},
    created_by_user_id: "u-1",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  }
}

function knowledgeBase(
  id: string,
  name: string,
  description: string,
  status = "active"
): KnowledgeBase {
  return {
    id,
    workspace_id: WS,
    name,
    description,
    status,
    embedding_model_id: null,
    reranker_model_id: null,
    created_by_user_id: "u-1",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    permission: "edit",
  }
}

function mcpServer(): McpServer {
  return {
    id: "server-1",
    workspace_id: WS,
    name: "Database",
    transport: "streamable_http",
    url: "https://mcp.example.com/mcp",
    stdio_command: null,
    tools: [
      {
        name: "search",
        description: "Search the catalog",
        input_schema: {},
        annotations: null,
        definition_hash: "h1",
        policy_mode: "read_only",
      },
    ],
    status: "active",
    has_bearer_token: false,
    bearer_token_hint: null,
    last_error: null,
    created_by_user_id: "u-1",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  }
}

function makeTool(overrides: Partial<ToolDetail> = {}): ToolDetail {
  return {
    id: "tool-1",
    workspace_id: WS,
    kind: "python",
    function_name: "lookup",
    display_name: "Lookup",
    description: "Lookup data",
    current_version_id: "version-1",
    status: "active",
    availability: "available",
    source: { id: "source-1", name: "Mine", kind: "python", transport: null },
    created_by_user_id: "u-1",
    permission: "owner",
    can_view: true,
    can_use: true,
    can_manage: true,
    version_id: "version-1",
    revision: 1,
    input_schema: { type: "object" },
    output_schema: { type: "object" },
    approval: "auto",
    effect: "pure",
    workflow_callable: true,
    parallel_safe: true,
    draft: null,
    ...overrides,
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

/* ------------------------------------------------------------------ */
/* Test harness helpers                                                */
/* ------------------------------------------------------------------ */

const adminMe = {
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
}

const notifyCalls: Array<{ kind: string; message: string }> = []
const session = makeSession({
  me: adminMe,
  notify: (kind: "success" | "error", message: string) =>
    notifyCalls.push({ kind, message }),
})
mockUseSession(session)

const navState: {
  params: Record<string, string>
  search: string
  pathname: string
  pushCalls: string[]
  replaceCalls: string[]
} = {
  params: {},
  search: "",
  pathname: "/app/apps",
  pushCalls: [],
  replaceCalls: [],
}

// A stable router object is required: AgentsPage's runs effect depends on
// `router`, so a fresh object per render would re-run it forever.
const stableRouter = {
  push: (href: string) => navState.pushCalls.push(href),
  replace: (href: string) => navState.replaceCalls.push(href),
  back: () => undefined,
  forward: () => undefined,
  prefetch: () => undefined,
  refresh: () => undefined,
}
mock.module("next/navigation", () => ({
  useParams: () => navState.params,
  useRouter: () => stableRouter,
  useSearchParams: () => new URLSearchParams(navState.search),
  usePathname: () => navState.pathname,
}))
mockNextImage()

// Stub the heavy dynamic workflow canvas runtime; the workflow branch of
// AgentsPage (tool catalog error + retry) is exercised through this stub.
mock.module("@/components/workflows/workflow-detail-workspace", () => ({
  WorkflowDetailWorkspace: (props: {
    agent: { id: string; name: string }
    form: AgentFormState
    setForm: (form: AgentFormState) => void
    onDelete: () => void
    onManagePermissions: () => void
    onSaveApp: (event: unknown) => void
    onViewChange: (view: string) => void
    onBack: () => void
    agents?: Agent[]
    tools?: ToolDetail[]
    toolsError?: string | null
    onRetryTools?: () => void
  }) => (
    <div data-testid="workflow-stub">
      WF-STUB:<span>{props.agent.name}</span>
      <span data-testid="workflow-agent-count">
        {props.agents?.length ?? 0}
      </span>
      <span data-testid="workflow-tool-count">{props.tools?.length ?? 0}</span>
      {props.toolsError ? <span>{props.toolsError}</span> : null}
      {props.onRetryTools ? (
        <button type="button" onClick={props.onRetryTools}>
          stub-retry-tools
        </button>
      ) : null}
      <button
        type="button"
        onClick={() =>
          props.setForm({ ...props.form, name: `${props.form.name} !` })
        }
      >
        stub-make-dirty
      </button>
    </div>
  ),
}))

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

function ndjson(events: unknown[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`))
      }
      controller.close()
    },
  })
  return new Response(body, { status: 200 })
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
  Object.keys(navState.params).forEach((key) => delete navState.params[key])
  navState.search = ""
  navState.pathname = "/app/apps"
  navState.pushCalls = []
  navState.replaceCalls = []
  notifyCalls.length = 0
  session.me = adminMe
  ;(session as { selectedWorkspaceId: string | null }).selectedWorkspaceId =
    "ws-1"
  ;(session as { token: string | null }).token = "test-token"
})

function baseRoutes(
  agents: Agent[] = [makeAgent()],
  tools: ToolSummary[] = []
) {
  return [
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/agents`,
      exact: true,
      respond: () => jsonResponse(agents),
    },
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/models`,
      exact: true,
      respond: () =>
        jsonResponse([model("model-1", "DeepSeek Chat", "deepseek-chat")]),
    },
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/knowledge-bases`,
      exact: true,
      respond: () =>
        jsonResponse([
          knowledgeBase("knowledge-1", "产品文档", "产品使用文档"),
        ]),
    },
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/mcp-servers`,
      exact: true,
      respond: () => jsonResponse([mcpServer()]),
    },
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/tools`,
      exact: true,
      respond: () => jsonResponse(tools),
    },
  ]
}

async function renderDetail(
  opts: {
    agent?: Agent
    initialView?: string
    agents?: Agent[]
    extraRoutes?: FetchCase[]
    initialConversationId?: string | null
  } = {}
) {
  const agent = opts.agent ?? makeAgent()
  navState.params.id = agent.id
  routes = [
    ...baseRoutes(opts.agents ?? [agent]),
    ...(opts.extraRoutes ?? []),
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/agents/${agent.id}`,
      exact: true,
      respond: () => jsonResponse(agent),
    },
  ]
  const viewProps = {
    ...(opts.initialView ? { initialView: opts.initialView as never } : {}),
    ...(opts.initialConversationId
      ? { initialConversationId: opts.initialConversationId }
      : {}),
  }
  const rendered = renderPage(<AgentsPage {...viewProps} />)
  await waitFor(() => expect(screen.getByText(agent.name)).toBeTruthy())
  return rendered
}

async function expectWorkflowStub(name = "Weekly Digest") {
  await waitFor(() =>
    expect(screen.getByTestId("workflow-stub").textContent).toContain(
      `WF-STUB:${name}`
    )
  )
}

/* ------------------------------------------------------------------ */
/* Tests                                                               */
/* ------------------------------------------------------------------ */

describe("AgentsPage tool catalog and workflow agent loading", () => {
  test("reports a tool catalog load failure in the workflow palette and recovers on retry", async () => {
    const workflow = makeWorkflow()
    let toolListCalls = 0
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/tools`,
        exact: true,
        respond: () => {
          toolListCalls += 1
          return toolListCalls === 1
            ? jsonResponse({ detail: "catalog boom" }, 500)
            : jsonResponse([makeTool()])
        },
      },
      ...baseRoutes([workflow]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/tools/tool-1`,
        exact: true,
        respond: () => jsonResponse(makeTool()),
      },
    ]
    navState.params.id = "agent-2"
    renderPage(<AgentsPage />)
    await expectWorkflowStub()

    await waitFor(() => expect(screen.getByText("catalog boom")).toBeTruthy())
    expect(screen.getByTestId("workflow-tool-count").textContent).toBe("0")

    fireEvent.click(screen.getByText("stub-retry-tools"))
    await waitFor(() =>
      expect(screen.getByTestId("workflow-tool-count").textContent).toBe("1")
    )
    expect(screen.queryByText("catalog boom")).toBeNull()
    expect(toolListCalls).toBeGreaterThanOrEqual(2)
  })

  test("clears workflow agents when the workspace becomes unavailable", async () => {
    const workflow = makeWorkflow()
    navState.params.id = "agent-2"
    routes = baseRoutes([workflow])
    const rendered = renderPage(<AgentsPage />)
    await expectWorkflowStub()

    ;(session as { selectedWorkspaceId: string | null }).selectedWorkspaceId =
      null
    rendered.rerender(
      <LanguageProvider defaultLanguage="zh-Hans">
        <AgentsPage />
      </LanguageProvider>
    )
    // The list view renders again after workspace data is cleared.
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
    expect(
      notifyCalls.some((call) => call.kind === "error")
    ).toBe(false)
  })

  test("reports an error when loading workflow agents fails", async () => {
    const workflow = makeWorkflow()
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: true,
        respond: (_init, _path, query) =>
          query?.get("limit") === "200"
            ? jsonResponse({ detail: "workflow agents boom" }, 500)
            : jsonResponse([workflow]),
      },
      ...baseRoutes([]),
    ]
    navState.params.id = "agent-2"
    renderPage(<AgentsPage />)
    await expectWorkflowStub()
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "workflow agents boom")
      ).toBe(true)
    )
  })
})

describe("AgentsPage list guards and publish edges", () => {
  test("skips loading more agents once the workspace is gone", async () => {
    const offsets: Array<string | null> = []
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: false,
        respond: (_init, _path, query) => {
          offsets.push(query?.get("offset") ?? null)
          return jsonResponse([makeAgent()])
        },
      },
      ...baseRoutes([]).slice(1),
    ]
    class FakeIntersectionObserver {
      static instances: FakeIntersectionObserver[] = []
      callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback
        FakeIntersectionObserver.instances.push(this)
      }
      observe() {}
      unobserve() {}
      disconnect() {}
      trigger() {
        this.callback(
          [{ isIntersecting: true } as IntersectionObserverEntry],
          this as unknown as IntersectionObserver
        )
      }
    }
    const OriginalIntersectionObserver = globalThis.IntersectionObserver
    ;(globalThis as { IntersectionObserver: unknown }).IntersectionObserver =
      FakeIntersectionObserver
    try {
      const rendered = renderPage(<AgentsPage />)
      await waitFor(() =>
        expect(screen.getByText("Research Assistant")).toBeTruthy()
      )
      ;(session as { selectedWorkspaceId: string | null }).selectedWorkspaceId =
        null
      rendered.rerender(
        <LanguageProvider defaultLanguage="zh-Hans">
          <AgentsPage />
        </LanguageProvider>
      )
      await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
      FakeIntersectionObserver.instances.forEach((instance) =>
        instance.trigger()
      )
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(offsets).toEqual(["0"])
      expect(
        notifyCalls.some((call) => call.kind === "error")
      ).toBe(false)
    } finally {
      globalThis.IntersectionObserver = OriginalIntersectionObserver
    }
  })

  test("ignores publish while the form is dirty", async () => {
    const agent = makeAgent()
    const patchBodies: string[] = []
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: (init) => {
            patchBodies.push(String(init?.body ?? ""))
            return jsonResponse({ ...agent, name: "Renamed" })
          },
        },
      ],
    })
    const settingsNavButton = screen
      .getAllByRole("button", { name: "设置" })
      .find((button) => Boolean(button.closest("nav")))
    expect(settingsNavButton).toBeTruthy()
    fireEvent.click(settingsNavButton!)
    await waitFor(() =>
      expect(screen.getByLabelText("向 Agent 提问")).toBeTruthy()
    )

    const nameInput = screen.getByLabelText("Agent 名称") as HTMLInputElement
    fireEvent.change(nameInput, { target: { value: "Renamed Assistant" } })
    await waitFor(() => expect(screen.getByText("未保存")).toBeTruthy())

    const publishButton = screen.getByText("发布").closest("button")!
    expect((publishButton as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(publishButton)
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(patchBodies).toEqual([])
    expect(notifyCalls.some((call) => call.message.includes("发布"))).toBe(
      false
    )
  })

  test("notifies with the workflow published label when the response is a workflow", async () => {
    const agent = makeAgent({ published: false })
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: () =>
            jsonResponse({
              ...agent,
              name: "Weekly Digest",
              app_type: "workflow",
              published: true,
            }),
        },
      ],
    })
    fireEvent.click(screen.getByText("发布"))
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "工作流已发布")
      ).toBe(true)
    )
  })

  test("notifies with the workflow unpublished label when the response is a workflow", async () => {
    const agent = makeAgent({ published: true, has_unpublished_changes: false })
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: () =>
            jsonResponse({
              ...agent,
              name: "Weekly Digest",
              app_type: "workflow",
              published: false,
            }),
        },
      ],
    })
    fireEvent.click(screen.getByText("取消发布"))
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "工作流已取消发布")
      ).toBe(true)
    )
  })
})

describe("AgentsPage run regeneration", () => {
  const conversationRoutes = (
    runs: AgentRun[],
    extra: FetchCase[] = []
  ) => [
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
      exact: true,
      respond: () => jsonResponse(runs),
    },
    ...extra,
  ]

  test("ignores regenerate requests while another feedback is pending", async () => {
    const agent = makeAgent()
    const first = makeRun({ id: "run-1", result: "First answer" })
    const second = makeRun({ id: "run-2", result: "Second answer" })
    let resolveFeedback: (value: Response) => void = () => undefined
    let regenerateCalls = 0
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        ...conversationRoutes([first, second]),
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/feedback`,
          exact: true,
          respond: () =>
            new Promise<Response>((resolve) => {
              resolveFeedback = resolve
            }),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-2/regenerate`,
          exact: true,
          respond: () => {
            regenerateCalls += 1
            return jsonResponse(
              makeRun({
                id: "run-2",
                status: "queued",
                result: "",
              })
            )
          },
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("First answer")).toBeTruthy())
    const firstArticle = screen.getByText("First answer").closest("article")!
    const secondArticle = screen.getByText("Second answer").closest("article")!

    fireEvent.click(
      within(firstArticle).getByRole("button", { name: "点赞" })
    )
    fireEvent.click(
      within(secondArticle).getByRole("button", { name: "重新生成" })
    )
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(regenerateCalls).toBe(0)

    resolveFeedback!(
      jsonResponse(makeRun({ id: "run-1", feedback: "positive" }))
    )
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点赞" })).toBeTruthy()
    )
  })

  test("regenerates a run and renders the streamed replacement", async () => {
    const agent = makeAgent()
    const original = makeRun({ result: "Original answer" })
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        ...conversationRoutes([original]),
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/regenerate`,
          exact: true,
          respond: () =>
            jsonResponse(
              makeRun({
                id: "run-2",
                regenerated_from_run_id: "run-1",
                status: "queued",
                result: "",
              })
            ),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-2/stream`,
          exact: false,
          respond: () =>
            ndjson([
              {
                type: "complete",
                sequence: 1,
                run: makeRun({
                  id: "run-2",
                  regenerated_from_run_id: "run-1",
                  status: "succeeded",
                  result: "Regenerated answer",
                }),
              },
            ]),
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )

    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "重新生成" })
    )
    await waitFor(() =>
      expect(screen.getByText("Regenerated answer")).toBeTruthy()
    )
    const regeneratedArticle = screen
      .getByText("Regenerated answer")
      .closest("article")!
    expect(
      (within(regeneratedArticle).getByRole("button", {
        name: "重新生成",
      }) as HTMLButtonElement).disabled
    ).toBe(false)
  })

  test("restores the previous answer when the regenerated run fails", async () => {
    const agent = makeAgent()
    const original = makeRun({ result: "Original answer" })
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        ...conversationRoutes([original]),
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/regenerate`,
          exact: true,
          respond: () =>
            jsonResponse(
              makeRun({
                id: "run-2",
                regenerated_from_run_id: "run-1",
                status: "queued",
                result: "",
              })
            ),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-2/stream`,
          exact: false,
          respond: () =>
            ndjson([
              {
                type: "error",
                sequence: 1,
                run: makeRun({
                  id: "run-2",
                  regenerated_from_run_id: "run-1",
                  status: "failed",
                  result: "",
                  last_error: "regeneration exploded",
                }),
              },
            ]),
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "重新生成" })
    )
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByText("regeneration exploded")).toBeNull()
    expect(
      notifyCalls.some((call) => call.kind === "error")
    ).toBe(false)
  })

  test("restores the previous answer and reports an error when observing regeneration fails", async () => {
    const agent = makeAgent()
    const original = makeRun({ result: "Original answer" })
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        ...conversationRoutes([original]),
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/regenerate`,
          exact: true,
          respond: () =>
            jsonResponse(
              makeRun({
                id: "run-2",
                regenerated_from_run_id: "run-1",
                status: "queued",
                result: "",
              })
            ),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-2/stream`,
          exact: false,
          respond: () => jsonResponse({ detail: "stream boom" }, 404),
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "重新生成" })
    )
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.kind === "error")
      ).toBe(true)
    )
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    expect(screen.queryByText(/stream boom/)).toBeNull()
  })

  test("drops a regenerate failure that arrives after switching conversations", async () => {
    const agent = makeAgent()
    const original = makeRun({ result: "Original answer" })
    let resolveRegenerate: (value: Response) => void = () => undefined
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        ...conversationRoutes([original]),
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/regenerate`,
          exact: true,
          respond: () =>
            new Promise<Response>((resolve) => {
              resolveRegenerate = resolve
            }),
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "重新生成" })
    )
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() =>
      expect(screen.getByText("开始和 Agent 对话")).toBeTruthy()
    )
    resolveRegenerate!(jsonResponse({ detail: "late regenerate boom" }, 500))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(notifyCalls.some((call) => call.kind === "error")).toBe(false)
  })

  test("reports an error when the regenerate request fails", async () => {
    const agent = makeAgent()
    const original = makeRun({ result: "Original answer" })
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        ...conversationRoutes([original]),
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/regenerate`,
          exact: true,
          respond: () => jsonResponse({ detail: "regenerate boom" }, 500),
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "重新生成" })
    )
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "regenerate boom")
      ).toBe(true)
    )
    expect(screen.getByText("Original answer")).toBeTruthy()
  })
})

describe("AgentsPage run feedback", () => {
  test("ignores feedback while another feedback request is pending", async () => {
    const agent = makeAgent()
    const first = makeRun({ id: "run-1", result: "First answer" })
    const second = makeRun({ id: "run-2", result: "Second answer" })
    let resolveFirst: (value: Response) => void = () => undefined
    let secondCalls = 0
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([first, second]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/feedback`,
          exact: true,
          respond: () =>
            new Promise<Response>((resolve) => {
              resolveFirst = resolve
            }),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-2/feedback`,
          exact: true,
          respond: () => {
            secondCalls += 1
            return jsonResponse(
              makeRun({ id: "run-2", feedback: "negative" })
            )
          },
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("First answer")).toBeTruthy())
    const firstArticle = screen.getByText("First answer").closest("article")!
    const secondArticle = screen.getByText("Second answer").closest("article")!

    fireEvent.click(
      within(firstArticle).getByRole("button", { name: "点赞" })
    )
    fireEvent.click(
      within(secondArticle).getByRole("button", { name: "点赞" })
    )
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(secondCalls).toBe(0)

    resolveFirst!(jsonResponse(makeRun({ id: "run-1", feedback: "positive" })))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点赞" })).toBeTruthy()
    )
  })

  test("applies the server feedback result", async () => {
    const agent = makeAgent()
    const succeeded = makeRun({ result: "Original answer" })
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([succeeded]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/feedback`,
          exact: true,
          respond: (init) => {
            expect(JSON.parse(String(init?.body ?? "{}"))).toEqual({
              feedback: "positive",
            })
            return jsonResponse(
              makeRun({ id: "run-1", feedback: "positive" })
            )
          },
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "点赞" })
    )
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消点赞" })).toBeTruthy()
    )
  })

  test("drops a feedback failure that arrives after switching conversations", async () => {
    const agent = makeAgent()
    const succeeded = makeRun({ result: "Original answer" })
    let resolveFeedback: (value: Response) => void = () => undefined
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([succeeded]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/feedback`,
          exact: true,
          respond: () =>
            new Promise<Response>((resolve) => {
              resolveFeedback = resolve
            }),
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "点赞" })
    )
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() =>
      expect(screen.getByText("开始和 Agent 对话")).toBeTruthy()
    )
    resolveFeedback!(jsonResponse({ detail: "late feedback boom" }, 500))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(notifyCalls.some((call) => call.kind === "error")).toBe(false)
  })

  test("reverts feedback and reports an error when the request fails", async () => {
    const agent = makeAgent()
    const succeeded = makeRun({ result: "Original answer" })
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([succeeded]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/feedback`,
          exact: true,
          respond: () => jsonResponse({ detail: "feedback boom" }, 500),
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("Original answer")).toBeTruthy()
    )
    const article = screen.getByText("Original answer").closest("article")!
    fireEvent.click(
      within(article).getByRole("button", { name: "点赞" })
    )
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "feedback boom")
      ).toBe(true)
    )
    await waitFor(() =>
      expect(
        within(article).getByRole("button", { name: "点赞" })
      ).toBeTruthy()
    )
  })
})

describe("AgentsPage stream approval tool-call loading", () => {
  test("reports an error when tool calls fail after the stream requests approval", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ status: "queued", result: "", events: [] })
    let streamCalls = 0
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([queuedRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls`,
          exact: true,
          respond: () => jsonResponse({ detail: "calls boom" }, 500),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () => {
            streamCalls += 1
            return streamCalls === 1
              ? ndjson([
                  {
                    type: "approval_required",
                    sequence: 1,
                    call_id: "call-1",
                    reason: "tool needs approval",
                  },
                ])
              : ndjson([
                  {
                    type: "complete",
                    sequence: 2,
                    run: makeRun({
                      status: "succeeded",
                      result: "done",
                    }),
                  },
                ])
          },
        },
      ],
    })
    await waitFor(() =>
      expect(
        notifyCalls.some((call) => call.message === "calls boom")
      ).toBe(true)
    )
  })

  test("drops the approval tool-call error after switching conversations", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ status: "queued", result: "", events: [] })
    let resolveCalls: (value: Response) => void = () => undefined
    let toolCallsStarted = false
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([queuedRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls`,
          exact: true,
          respond: () => {
            toolCallsStarted = true
            return new Promise<Response>((resolve) => {
              resolveCalls = resolve
            })
          },
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () =>
            ndjson([
              {
                type: "approval_required",
                sequence: 1,
                call_id: "call-1",
                reason: "tool needs approval",
              },
            ]),
        },
      ],
    })
    await waitFor(() => expect(toolCallsStarted).toBe(true))
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() =>
      expect(screen.getByText("开始和 Agent 对话")).toBeTruthy()
    )
    resolveCalls!(jsonResponse({ detail: "late boom" }, 500))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(
      notifyCalls.some((call) => call.kind === "error")
    ).toBe(false)
  })

  test("loads tool calls requested by the stream approval and renders the decision UI", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ status: "queued", result: "", events: [] })
    let streamCalls = 0
    await renderDetail({
      agent,
      initialView: "settings",
      initialConversationId: "conversation-1",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([queuedRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls`,
          exact: true,
          respond: () => jsonResponse([makeToolCall()]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () => {
            streamCalls += 1
            return streamCalls === 1
              ? ndjson([
                  {
                    type: "approval_required",
                    sequence: 1,
                    call_id: "call-1",
                    reason: "tool needs approval",
                  },
                ])
              : ndjson([
                  {
                    type: "complete",
                    sequence: 2,
                    run: makeRun({ status: "succeeded", result: "done" }),
                  },
                ])
          },
        },
      ],
    })
    await waitFor(() =>
      expect(screen.getByText("工具调用需要确认")).toBeTruthy()
    )
    expect(screen.getByText(/execute_sql/)).toBeTruthy()
  })
})

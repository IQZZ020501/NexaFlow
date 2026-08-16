/* @jsxImportSource react */
/**
 * DOM-level coverage for the Agent application management page
 * (components/agents/agents-page.tsx + lib/api/agents.ts through page flows).
 */
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { cleanup } from "@testing-library/react"

import {
  AgentsPage,
  isAgentFormDirty,
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
  AgentToolCall,
} from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import { getAgentRun } from "@/lib/api/agents"

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

function model(id: string, name: string, modelName: string, status = "active"): RegisteredModel {
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

function knowledgeBase(id: string, name: string, description: string, status = "active"): KnowledgeBase {
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
      { name: "search", description: "Search the catalog", input_schema: {}, annotations: null, definition_hash: "h1", policy_mode: "read_only" },
      { name: "execute_sql", description: "Run SQL", input_schema: {}, annotations: null, definition_hash: "h2", policy_mode: "approval_required" },
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

export function makeAgent(overrides: Partial<Agent> = {}): Agent {
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
    mcp_tools: [{ server_id: "server-1", tool_name: "search" }],
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
    mcp_tools: [],
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
    workspaces: [{ id: WS, name: "Test Workspace", is_default: true, role: "admin" }],
    teams: [],
  },
  memberships: [{ workspace_id: WS, role: "admin" }],
}

const memberMe = {
  ...adminMe,
  user: { ...adminMe.user, is_global_admin: false },
  memberships: [{ workspace_id: WS, role: "member" }],
}

const notifyCalls: Array<{ kind: string; message: string }> = []
const session = makeSession({
  me: adminMe,
  notify: (kind: "success" | "error", message: string) => notifyCalls.push({ kind, message }),
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

// NOTE: a stable router object is required — the shared mockNextNavigation
// helper returns a fresh object per call, which makes AgentsPage's runs
// effect re-run forever (its deps include `router`).
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

// The workflow detail workspace is loaded via next/dynamic and would pull in
// the heavy canvas runtime; stub it so the workflow branch of AgentsPage is
// still exercised (save/delete/permissions/back handlers included).
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
  }) => (
    <div data-testid="workflow-stub">
      WF-STUB:{props.agent.name}
      <button type="button" onClick={() => props.onDelete()}>
        stub-delete
      </button>
      <button type="button" onClick={() => props.onManagePermissions()}>
        stub-perms
      </button>
      <button type="button" onClick={() => props.onSaveApp({ preventDefault: () => undefined })}>
        stub-save
      </button>
      <button type="button" onClick={() => props.onBack()}>
        stub-back
      </button>
      <button type="button" onClick={() => props.onViewChange("settings")}>
        stub-view-settings
      </button>
      <button
        type="button"
        onClick={() => props.setForm({ ...props.form, name: `${props.form.name} !` })}
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

function fetchRouter(cases: FetchCase[], fallback?: (url: string, init?: RequestInit) => Response) {
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

// The shared `withFetch` helper restores the original fetch after the first
// test, so multi-test files must manage the stub themselves.
const fetchStub = ((url: string, init?: RequestInit) =>
  fetchRouter(routes)(url, init)) as unknown as typeof fetch
const originalFetch = globalThis.fetch
beforeEach(() => {
  globalThis.fetch = fetchStub
})
afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
})

function resetNav() {
  Object.keys(navState.params).forEach((key) => delete navState.params[key])
  navState.search = ""
  navState.pathname = "/app/apps"
  navState.pushCalls = []
  navState.replaceCalls = []
  notifyCalls.length = 0
  session.me = adminMe
}

function baseRoutes(agents: Agent[] = [makeAgent()]) {
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
      respond: () => jsonResponse([model("model-1", "DeepSeek Chat", "deepseek-chat")]),
    },
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/knowledge-bases`,
      exact: true,
      respond: () => jsonResponse([knowledgeBase("knowledge-1", "产品文档", "产品使用文档")]),
    },
    {
      method: "GET",
      pathname: `/api/v1/workspaces/${WS}/mcp-servers`,
      exact: true,
      respond: () => jsonResponse([mcpServer()]),
    },
  ]
}

function cardOf(name: string): HTMLElement {
  const heading = screen.getByText(name)
  const card = heading.closest("[role='button']")
  if (!card) throw new Error(`card not found for ${name}`)
  return card as HTMLElement
}

function openModelDropdown() {
  const trigger = screen.getByLabelText("选择模型")
  fireEvent.pointerDown(trigger)
  fireEvent.click(trigger)
}

async function renderDetail(opts: {
  agent?: Agent
  initialView?: string
  hasLegacyView?: boolean
  agents?: Agent[]
  extraRoutes?: FetchCase[]
} = {}) {
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
    ...(opts.hasLegacyView ? { hasLegacyView: true } : {}),
  }
  renderPage(<AgentsPage {...viewProps} />)
  await waitFor(() => expect(screen.getByText(agent.name)).toBeTruthy())
  return agent
}

/* ------------------------------------------------------------------ */
/* Tests                                                               */
/* ------------------------------------------------------------------ */

afterEach(() => {
  cleanup()
  resetNav()
})

describe("AgentsPage list view", () => {
  test("renders agent and workflow cards with badges and counts", async () => {
    routes = baseRoutes([makeAgent(), makeWorkflow(), makeWorkflow({ id: "agent-3", name: "Nightly Report", published: false })])
    renderPage(<AgentsPage />)

    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    expect(screen.getByText("Weekly Digest")).toBeTruthy()
    expect(screen.getByText("已发布")).toBeTruthy()
    expect(screen.getByText("未发布")).toBeTruthy()

    const agentCard = cardOf("Research Assistant")
    expect(within(agentCard).getByText("Agent")).toBeTruthy()
    expect(within(agentCard).getByText("已启用")).toBeTruthy()
    expect(within(agentCard).getByText("DeepSeek Chat")).toBeTruthy()
    expect(within(agentCard).getAllByText("1").length).toBe(2)
    expect(within(agentCard).getByText("MCP 工具")).toBeTruthy()

    const workflowCard = cardOf("Weekly Digest")
    expect(within(workflowCard).getByText("工作流")).toBeTruthy()
    expect(within(workflowCard).getAllByText("0").length).toBe(2)

    expect(screen.getByText("已加载全部")).toBeTruthy()
    expect(screen.getByText("应用")).toBeTruthy()
  })

  test("opens an agent by clicking its card", async () => {
    routes = baseRoutes([makeAgent()])
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())

    fireEvent.click(cardOf("Research Assistant"))
    expect(navState.pushCalls).toContain("/app/apps/agent-1")
  })

  test("opens an agent from the pencil edit button", async () => {
    routes = baseRoutes([makeAgent()])
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())

    fireEvent.click(within(cardOf("Research Assistant")).getByRole("button", { name: "编辑应用" }))
    expect(navState.pushCalls).toContain("/app/apps/agent-1")
  })

  test("filters cards by search across name and model", async () => {
    routes = baseRoutes([makeAgent(), makeWorkflow()])
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())

    const search = screen.getByPlaceholderText("搜索应用...")
    fireEvent.change(search, { target: { value: "digest" } })
    expect(screen.queryByText("Research Assistant")).toBeNull()
    expect(screen.getByText("Weekly Digest")).toBeTruthy()

    fireEvent.change(search, { target: { value: "deepseek" } })
    expect(screen.getByText("Research Assistant")).toBeTruthy()

    fireEvent.change(search, { target: { value: "zzz" } })
    expect(screen.getByText("没有匹配的 Agent")).toBeTruthy()
    expect(screen.queryByText("Research Assistant")).toBeNull()
  })

  test("shows the empty state with a create entry point", async () => {
    routes = baseRoutes([])
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
    expect(screen.getByText("创建应用后，可以编排对话、检索和工具调用流程。")).toBeTruthy()
    expect(screen.getAllByText("新建应用").length).toBeGreaterThanOrEqual(2)
  })

  test("shows the no-model empty state and disables creation", async () => {
    routes = [
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/agents`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() =>
      expect(screen.getByText("先接入一个已启用的大语言模型，再创建 Agent。")).toBeTruthy()
    )
    const createButtons = screen.getAllByRole("button", { name: "新建应用" })
    expect(createButtons.length).toBeGreaterThan(0)
    for (const button of createButtons) {
      expect((button as HTMLButtonElement).disabled).toBe(true)
    }
  })

  test("reports an error when workspace data fails to load", async () => {
    routes = [
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/agents`, exact: true, respond: () => jsonResponse([], 500) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([], 500) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
  })

  test("loads more agents when the list end is reached", async () => {
    const fifty = Array.from({ length: 50 }, (_, index) =>
      makeAgent({ id: `agent-${index}`, name: `Agent ${index}` })
    )
    const secondBatch = [makeAgent({ id: "agent-50", name: "Agent 50" })]
    const offsets: Array<string | null> = []
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: false,
        respond: (_init, _path, query) => {
          offsets.push(query?.get("offset") ?? null)
          return jsonResponse(query?.get("offset") === "50" ? secondBatch : fifty)
        },
      },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
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
    ;(globalThis as { IntersectionObserver: unknown }).IntersectionObserver = FakeIntersectionObserver
    try {
      renderPage(<AgentsPage />)
      await waitFor(() => expect(screen.getByText("Agent 0")).toBeTruthy())
      expect(screen.queryByText("Agent 50")).toBeNull()
      FakeIntersectionObserver.instances.forEach((instance) => instance.trigger())
      await waitFor(() => expect(screen.getByText("Agent 50")).toBeTruthy())
      expect(offsets).toContain("50")
    } finally {
      globalThis.IntersectionObserver = OriginalIntersectionObserver
    }
  })

  test("reports an error when loading more agents fails", async () => {
    let offset: string | null = null
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: false,
        respond: (_init, _path, query) => {
          offset = query?.get("offset") ?? null
          if (offset === "50") return jsonResponse([], 500)
          return jsonResponse(Array.from({ length: 50 }, (_, index) => makeAgent({ id: `agent-${index}`, name: `Agent ${index}` })))
        },
      },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
    ]
    class FakeIntersectionObserver2 {
      static instances: FakeIntersectionObserver2[] = []
      callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback
        FakeIntersectionObserver2.instances.push(this)
      }
      observe() {}
      unobserve() {}
      disconnect() {}
      trigger() {
        this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
      }
    }
    const OriginalIntersectionObserver = globalThis.IntersectionObserver
    ;(globalThis as { IntersectionObserver: unknown }).IntersectionObserver = FakeIntersectionObserver2
    try {
      renderPage(<AgentsPage />)
      await waitFor(() => expect(screen.getByText("Agent 0")).toBeTruthy())
      FakeIntersectionObserver2.instances.forEach((instance) => instance.trigger())
      await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
    } finally {
      globalThis.IntersectionObserver = OriginalIntersectionObserver
    }
  })

  test("hides edit affordances for view-only agents", async () => {
    routes = baseRoutes([makeAgent({ can_edit: false })])
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    const card = cardOf("Research Assistant")
    expect(within(card).queryByRole("button", { name: "编辑应用" })).toBeNull()
    expect(within(card).queryByTitle("更多")).toBeNull()
  })

  test("opens an agent with the keyboard", async () => {
    routes = baseRoutes([makeAgent()])
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    const card = cardOf("Research Assistant")
    fireEvent.keyDown(card, { key: "Enter" })
    expect(navState.pushCalls).toContain("/app/apps/agent-1")
    fireEvent.keyDown(card, { key: " " })
    expect(navState.pushCalls.filter((href) => href === "/app/apps/agent-1").length).toBe(2)
  })

  test("shows the loading indicator while fetching more agents", async () => {
    const fifty = Array.from({ length: 50 }, (_, index) =>
      makeAgent({ id: `agent-${index}`, name: `Agent ${index}` })
    )
    let resolveBatch: (value: Response) => void = () => undefined
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: false,
        respond: (_init, _path, query) =>
          query?.get("offset") === "50"
            ? new Promise<Response>((resolve) => {
                resolveBatch = resolve
              })
            : jsonResponse(fifty),
      },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
    ]
    class FakeIntersectionObserver3 {
      static instances: FakeIntersectionObserver3[] = []
      callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback
        FakeIntersectionObserver3.instances.push(this)
      }
      observe() {}
      unobserve() {}
      disconnect() {}
      trigger() {
        this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
      }
    }
    const OriginalIntersectionObserver = globalThis.IntersectionObserver
    ;(globalThis as { IntersectionObserver: unknown }).IntersectionObserver = FakeIntersectionObserver3
    try {
      renderPage(<AgentsPage />)
      await waitFor(() => expect(screen.getByText("Agent 0")).toBeTruthy())
      FakeIntersectionObserver3.instances.forEach((instance) => instance.trigger())
      await waitFor(() => expect(screen.getByText("正在加载")).toBeTruthy())
      resolveBatch!(jsonResponse([makeAgent({ id: "agent-50", name: "Agent 50" })]))
      await waitFor(() => expect(screen.getByText("Agent 50")).toBeTruthy())
    } finally {
      globalThis.IntersectionObserver = OriginalIntersectionObserver
    }
  })

  test("does not fetch more when the whole list is already loaded", async () => {
    const offsets: Array<string | null> = []
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: false,
        respond: (_init, _path, query) => {
          offsets.push(query?.get("offset") ?? null)
          return jsonResponse([makeAgent(), makeWorkflow()])
        },
      },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
    ]
    class FakeIntersectionObserver4 {
      static instances: FakeIntersectionObserver4[] = []
      callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback
        FakeIntersectionObserver4.instances.push(this)
      }
      observe() {}
      unobserve() {}
      disconnect() {}
      trigger() {
        this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
      }
    }
    const OriginalIntersectionObserver = globalThis.IntersectionObserver
    ;(globalThis as { IntersectionObserver: unknown }).IntersectionObserver = FakeIntersectionObserver4
    try {
      renderPage(<AgentsPage />)
      await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
      expect(screen.getByText("已加载全部")).toBeTruthy()
      FakeIntersectionObserver4.instances.forEach((instance) => instance.trigger())
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(offsets).toEqual(["0"])
    } finally {
      globalThis.IntersectionObserver = OriginalIntersectionObserver
    }
  })

  test("skips data loading without a selected workspace", async () => {
    const previousWorkspaceId = session.selectedWorkspaceId
    ;(session as { selectedWorkspaceId: string | null }).selectedWorkspaceId = null
    try {
      routes = [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents`,
          exact: true,
          respond: () => {
            throw new Error("should not fetch")
          },
        },
      ]
      renderPage(<AgentsPage />)
      await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
    } finally {
      ;(session as { selectedWorkspaceId: string | null }).selectedWorkspaceId = previousWorkspaceId
    }
  })
})

describe("AgentsPage create flow", () => {
  test("creates an agent from the type chooser dialog", async () => {
    let createdBody = ""
    let createdMethod = ""
    routes = [
      ...baseRoutes([]),
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: true,
        respond: (init) => {
          createdMethod = init?.method ?? ""
          createdBody = String(init?.body ?? "")
          return jsonResponse(makeAgent({ id: "agent-new" }), 201)
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())

    fireEvent.click(screen.getAllByRole("button", { name: "新建应用" })[0])
    expect(screen.getByText("选择要创建的应用类型")).toBeTruthy()

    fireEvent.click(screen.getByText("智能对话助手，自动规划并使用模型、知识和工具。"))
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getAllByText("新建应用").length).toBeGreaterThanOrEqual(2)

    fireEvent.change(within(dialog).getByLabelText("Agent 名称"), { target: { value: "Support Copilot" } })
    fireEvent.change(within(dialog).getByLabelText("描述"), { target: { value: "Answers support questions" } })

    openModelDropdown()
    fireEvent.click(await screen.findByRole("menuitem", { name: /DeepSeek Chat/ }))

    const form = within(dialog).getByLabelText("Agent 名称").closest("form")
    fireEvent.submit(form!)
    await waitFor(() => expect(navState.pushCalls).toContain("/app/apps/agent-new"))
    expect(createdMethod).toBe("POST")
    const payload = JSON.parse(createdBody)
    expect(payload.name).toBe("Support Copilot")
    expect(payload.app_type).toBe("agent")
    expect(payload.model_id).toBe("model-1")
    expect(payload.knowledge_base_ids).toEqual([])
    expect(payload.mcp_tools).toEqual([])
    expect(notifyCalls.some((call) => call.message === "Agent 已创建")).toBe(true)
  })

  test("creates a workflow with workflow payload normalization", async () => {
    let createdBody = ""
    routes = [
      ...baseRoutes([]),
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: true,
        respond: (init) => {
          createdBody = String(init?.body ?? "")
          return jsonResponse(makeWorkflow({ id: "wf-new" }), 201)
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())

    fireEvent.click(screen.getAllByRole("button", { name: "新建应用" })[0])
    fireEvent.click(screen.getByText("按预设步骤编排固定流程，适合确定性的处理任务。"))

    const dialog = screen.getByRole("dialog")
    fireEvent.change(within(dialog).getByLabelText("工作流名称"), { target: { value: "Release Flow" } })
    openModelDropdown()
    fireEvent.click(await screen.findByRole("menuitem", { name: /DeepSeek Chat/ }))

    const form = within(dialog).getByLabelText("工作流名称").closest("form")
    fireEvent.submit(form!)
    await waitFor(() => expect(navState.pushCalls).toContain("/app/apps/wf-new"))
    const payload = JSON.parse(createdBody)
    expect(payload.app_type).toBe("workflow")
    expect(payload.mcp_tools).toEqual([])
    expect(payload.knowledge_base_ids).toEqual([])
    expect(notifyCalls.some((call) => call.message === "工作流已创建")).toBe(true)
  })

  test("keeps the create dialog open when the submit fails", async () => {
    routes = [
      ...baseRoutes([]),
      {
        method: "POST",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "新建应用" })[0])
    fireEvent.click(screen.getByText("智能对话助手，自动规划并使用模型、知识和工具。"))
    const dialog = screen.getByRole("dialog")
    fireEvent.change(within(dialog).getByLabelText("Agent 名称"), { target: { value: "Broken" } })
    openModelDropdown()
    fireEvent.click(await screen.findByRole("menuitem", { name: /DeepSeek Chat/ }))
    const form = within(dialog).getByLabelText("Agent 名称").closest("form")
    fireEvent.submit(form!)
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
    expect(screen.getByRole("dialog")).toBeTruthy()
  })

  test("cancels the create dialog", async () => {
    routes = baseRoutes([])
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
    fireEvent.click(screen.getAllByRole("button", { name: "新建应用" })[0])
    fireEvent.click(screen.getByText("智能对话助手，自动规划并使用模型、知识和工具。"))
    const dialog = screen.getByRole("dialog")
    fireEvent.click(within(dialog).getByText("取消").closest("button")!)
    expect(screen.queryByRole("dialog")).toBeNull()
  })
})

describe("AgentsPage detail view", () => {
  test("loads a deep-linked agent missing from the list", async () => {
    const agent = makeAgent({ id: "agent-9", name: "Deep Linked" })
    routes = [
      ...baseRoutes([]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-9`,
        exact: true,
        respond: () => jsonResponse(agent),
      },
    ]
    navState.params.id = "agent-9"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Deep Linked")).toBeTruthy())
    expect(screen.getByText("公开访问与 API")).toBeTruthy()
  })

  test("redirects to /app/apps when the deep-linked agent cannot be resolved", async () => {
    routes = [
      ...baseRoutes([]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/ghost`,
        exact: true,
        respond: () => jsonResponse({ detail: "not found" }, 404),
      },
    ]
    navState.params.id = "ghost"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(navState.replaceCalls).toContain("/app/apps"))
  })

  test("edits and saves the agent via PATCH", async () => {
    const agent = makeAgent()
    let patchBody = ""
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: (init) => {
            patchBody = String(init?.body ?? "")
            return jsonResponse({ ...agent, name: "Renamed Assistant", description: "Updated description" })
          },
        },
      ],
    })
    const settingsNavButton = screen
      .getAllByRole("button", { name: "设置" })
      .find((button) => Boolean(button.closest("nav")))
    expect(settingsNavButton).toBeTruthy()
    fireEvent.click(settingsNavButton!)
    await waitFor(() => expect(screen.getByLabelText("向 Agent 提问")).toBeTruthy())
    expect(navState.replaceCalls).toContain("/app/apps/agent-1/settings")

    const nameInput = screen.getByLabelText("Agent 名称") as HTMLInputElement
    fireEvent.change(nameInput, { target: { value: "Renamed Assistant" } })
    await waitFor(() => expect(screen.getByText("未保存")).toBeTruthy())

    fireEvent.click(document.querySelector('button[form="agent-settings-form"]') as HTMLButtonElement)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "Agent 已更新")).toBe(true))
    const payload = JSON.parse(patchBody)
    expect(payload.name).toBe("Renamed Assistant")
    expect(payload.app_type).toBe("agent")
  })

  test("publishes an unpublished agent", async () => {
    const agent = makeAgent({ published: false })
    let patchBody = ""
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: (init) => {
            patchBody = String(init?.body ?? "")
            return jsonResponse({ ...agent, published: true })
          },
        },
      ],
    })
    expect(screen.getByText("发布")).toBeTruthy()
    fireEvent.click(screen.getByText("发布"))
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "Agent 已发布")).toBe(true))
    expect(JSON.parse(patchBody)).toEqual({ published: true })
  })

  test("republishes an agent with unpublished changes", async () => {
    const agent = makeAgent({ published: true, has_unpublished_changes: true })
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: (init) => jsonResponse({ ...agent, ...JSON.parse(String(init?.body ?? "{}")) }),
        },
      ],
    })
    fireEvent.click(screen.getByText("重新发布"))
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "Agent 已发布")).toBe(true))
  })

  test("unpublishes a published agent", async () => {
    const agent = makeAgent({ published: true, has_unpublished_changes: false })
    let patchBody = ""
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: (init) => {
            patchBody = String(init?.body ?? "")
            return jsonResponse({ ...agent, published: false })
          },
        },
      ],
    })
    fireEvent.click(screen.getByText("取消发布"))
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "Agent 已取消发布")).toBe(true))
    expect(JSON.parse(patchBody)).toEqual({ published: false })
  })

  test("hides publish for non-admin members", async () => {
    session.me = memberMe
    const agent = makeAgent()
    routes = baseRoutes([agent])
    navState.params.id = "agent-1"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    expect(screen.queryByText("发布")).toBeNull()
  })

  test("redirects non-workflow apps in canvas mode", async () => {
    const agent = makeAgent()
    routes = baseRoutes([agent])
    navState.params.id = "agent-1"
    renderPage(<AgentsPage workflowCanvasMode />)
    await waitFor(() =>
      expect(navState.replaceCalls).toContain("/app/apps/agent-1")
    )
  })

  test("canonicalizes legacy application view links", async () => {
    await renderDetail({ initialView: "logs", hasLegacyView: true })

    await waitFor(() =>
      expect(navState.replaceCalls).toContain("/app/apps/agent-1/logs")
    )
  })

  test("renders the workflow detail branch", async () => {
    const workflow = makeWorkflow()
    routes = baseRoutes([workflow])
    navState.params.id = "agent-2"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("WF-STUB:Weekly Digest")).toBeTruthy())
    expect(screen.queryByText("应用")).toBeNull()
  })

  test("saves workflow changes and deletes from the workflow workspace", async () => {
    const workflow = makeWorkflow()
    let patchBody = ""
    let deleteCount = 0
    routes = [
      ...baseRoutes([workflow]),
      {
        method: "PATCH",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-2`,
        exact: true,
        respond: (init) => {
          patchBody = String(init?.body ?? "")
          return jsonResponse({ ...workflow, description: "Updated" })
        },
      },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-2`,
        exact: true,
        respond: () => {
          deleteCount += 1
          return new Response(null, { status: 204 })
        },
      },
    ]
    navState.params.id = "agent-2"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("WF-STUB:Weekly Digest")).toBeTruthy())

    fireEvent.click(screen.getByText("stub-save").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "工作流已更新")).toBe(true))
    const payload = JSON.parse(patchBody)
    expect(payload.app_type).toBe("workflow")
    expect(payload.mcp_tools).toEqual([])

    fireEvent.click(screen.getByText("stub-delete").closest("button")!)
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("删除工作流")).toBeTruthy()
    fireEvent.click(within(dialog).getByText("删除").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "工作流已删除")).toBe(true))
    expect(deleteCount).toBe(1)
  })

  test("opens permissions from the workflow workspace", async () => {
    const workflow = makeWorkflow()
    routes = [
      ...baseRoutes([workflow]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/members`,
        exact: false,
        respond: () => jsonResponse([]),
      },
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-2/permissions`,
        exact: true,
        respond: () => jsonResponse([]),
      },
    ]
    navState.params.id = "agent-2"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("WF-STUB:Weekly Digest")).toBeTruthy())
    fireEvent.click(screen.getByText("stub-perms").closest("button")!)
    await waitFor(() => expect(screen.getByText("资源授权")).toBeTruthy())
  })

  test("redirects workflow settings views to the canvas when not in canvas mode", async () => {
    const workflow = makeWorkflow()
    routes = baseRoutes([workflow])
    navState.params.id = "agent-2"
    renderPage(<AgentsPage initialView="settings" />)
    await waitFor(() => expect(navState.replaceCalls).toContain("/workflow/agent-2"))
  })

  test("deletes the agent from the detail menu", async () => {
    const agent = makeAgent()
    let deleteCount = 0
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "DELETE",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: () => {
            deleteCount += 1
            return new Response(null, { status: 204 })
          },
        },
      ],
    })
    fireEvent.pointerDown(screen.getByLabelText("设置"))
    fireEvent.click(screen.getByLabelText("设置"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /删除 Agent/ }))

    expect(screen.getByText("删除 Agent")).toBeTruthy()
    fireEvent.click(screen.getByText("删除").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "Agent 已删除")).toBe(true))
    expect(deleteCount).toBe(1)
    await waitFor(() => expect(navState.pushCalls).toContain("/app/apps"))
  })

  test("reports an error when publishing fails", async () => {
    const agent = makeAgent({ published: false })
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: () => jsonResponse({ detail: "boom" }, 500),
        },
      ],
    })
    fireEvent.click(screen.getByText("发布"))
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
  })

  test("confirms discarding dirty changes before leaving", async () => {
    const agent = makeAgent()
    await renderDetail({
      agent,
      extraRoutes: [
        {
          method: "PATCH",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
          exact: true,
          respond: (init) => jsonResponse({ ...agent, ...JSON.parse(String(init?.body ?? "{}")) }),
        },
      ],
    })
    const settingsNavButton = screen
      .getAllByRole("button", { name: "设置" })
      .find((button) => Boolean(button.closest("nav")))
    fireEvent.click(settingsNavButton!)
    await waitFor(() => expect(screen.getByLabelText("向 Agent 提问")).toBeTruthy())
    const nameInput = screen.getByLabelText("Agent 名称") as HTMLInputElement
    fireEvent.change(nameInput, { target: { value: "Renamed" } })
    await waitFor(() => expect(screen.getByText("未保存")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("返回 Agent 列表"))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "放弃更改" },
      ),
    )
    await waitFor(() => expect(navState.pushCalls).toContain("/app/apps"))
    await waitFor(() => expect(nameInput.value).toBe(agent.name))
    expect(screen.queryByText("未保存")).toBeNull()
  })

  test("stays on the page when discarding changes is declined", async () => {
    const agent = makeAgent()
    await renderDetail({ agent })
    const settingsNavButton = screen
      .getAllByRole("button", { name: "设置" })
      .find((button) => Boolean(button.closest("nav")))
    fireEvent.click(settingsNavButton!)
    await waitFor(() => expect(screen.getByLabelText("向 Agent 提问")).toBeTruthy())
    const nameInput = screen.getByLabelText("Agent 名称") as HTMLInputElement
    fireEvent.change(nameInput, { target: { value: "Renamed" } })
    await waitFor(() => expect(screen.getByText("未保存")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("返回 Agent 列表"))
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "确认操作" })).getByRole(
        "button",
        { name: "取消" },
      ),
    )
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull(),
    )
    expect(navState.pushCalls).not.toContain("/app/apps")
  })

  test("opens permissions from the detail workspace menu", async () => {
    const agent = makeAgent()
    routes = [
      ...baseRoutes([agent]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/members`,
        exact: false,
        respond: () => jsonResponse([]),
      },
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions`,
        exact: true,
        respond: () => jsonResponse([]),
      },
    ]
    navState.params.id = "agent-1"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(screen.getByLabelText("设置"))
    fireEvent.click(screen.getByLabelText("设置"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /资源授权/ }))
    await waitFor(() => expect(screen.getByText("选择用户")).toBeTruthy())
  })

  test("backs to the workflow overview in canvas mode", async () => {
    const workflow = makeWorkflow()
    routes = baseRoutes([workflow])
    navState.params.id = "agent-2"
    renderPage(<AgentsPage workflowCanvasMode />)
    await waitFor(() => expect(screen.getByText("WF-STUB:Weekly Digest")).toBeTruthy())
    fireEvent.click(screen.getByText("stub-back").closest("button")!)
    expect(navState.replaceCalls).toContain("/app/apps/agent-2")
  })

  test("routes workflow settings changes to the canvas", async () => {
    const workflow = makeWorkflow()
    routes = baseRoutes([workflow])
    navState.params.id = "agent-2"
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("WF-STUB:Weekly Digest")).toBeTruthy())
    fireEvent.click(screen.getByText("stub-view-settings").closest("button")!)
    await waitFor(() => expect(navState.pushCalls).toContain("/workflow/agent-2"))
  })
})

describe("AgentsPage card menu: permissions and delete", () => {
  test("opens the permissions dialog and grants a permission", async () => {
    const agent = makeAgent()
    let putBody = ""
    routes = [
      ...baseRoutes([agent]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/members`,
        exact: false,
        respond: () =>
          jsonResponse([
            {
              user: { id: "u-2", username: "alice", name: "Alice", email: "a@x.co", is_global_admin: false, must_change_password: false, is_active: true, created_at: "", workspaces: [], teams: [] },
              role: "member",
            },
          ]),
      },
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions`,
        exact: true,
        respond: () => jsonResponse([]),
      },
      {
        method: "PUT",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions/u-2`,
        exact: true,
        respond: (init) => {
          putBody = String(init?.body ?? "")
          return jsonResponse({
            user: { id: "u-2", username: "alice", name: "Alice", email: "a@x.co", is_global_admin: false, must_change_password: false, is_active: true, created_at: "", workspaces: [], teams: [] },
            permission: "view",
          })
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /资源授权/ }))

    await waitFor(() => expect(screen.getByText("Alice / alice")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("用户"))
    fireEvent.click(screen.getByText("保存授权").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "授权已保存")).toBe(true))
    expect(JSON.parse(putBody)).toEqual({ permission: "view" })
  })

  test("revokes an existing permission", async () => {
    const agent = makeAgent()
    let revoked = false
    routes = [
      ...baseRoutes([agent]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/members`,
        exact: false,
        respond: () => jsonResponse([]),
      },
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions`,
        exact: true,
        respond: () =>
          jsonResponse([
            {
              user: { id: "u-3", username: "bob", name: "Bob", email: "b@x.co", is_global_admin: false, must_change_password: false, is_active: true, created_at: "", workspaces: [], teams: [] },
              permission: "view",
            },
          ]),
      },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions/u-3`,
        exact: true,
        respond: () => {
          revoked = true
          return new Response(null, { status: 204 })
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /资源授权/ }))

    await waitFor(() => expect(screen.getByText("Bob")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("撤销授权"))
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "授权已撤销")).toBe(true))
    expect(revoked).toBe(true)
  })

  test("reports an error and closes the permissions dialog on load failure", async () => {
    const agent = makeAgent()
    routes = [
      ...baseRoutes([agent]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/members`,
        exact: false,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions`,
        exact: true,
        respond: () => jsonResponse([], 500),
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /资源授权/ }))
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
    expect(screen.queryByText("保存授权")).toBeNull()
  })

  test("deletes an agent from the card menu with confirmation", async () => {
    const agent = makeAgent()
    let deleteCount = 0
    let relistCount = 0
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: false,
        respond: () => {
          relistCount += 1
          return jsonResponse(relistCount > 1 ? [] : [agent])
        },
      },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([model("model-1", "DeepSeek Chat", "deepseek-chat")]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
        exact: true,
        respond: () => {
          deleteCount += 1
          return new Response(null, { status: 204 })
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /删除/ }))

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("确定删除 Agent“Research Assistant”吗？")).toBeTruthy()
    fireEvent.click(within(dialog).getByText("删除").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "Agent 已删除")).toBe(true))
    expect(deleteCount).toBe(1)
    expect(relistCount).toBe(2)
    await waitFor(() => expect(screen.getByText("还没有应用")).toBeTruthy())
  })

  test("cancels the delete dialog without deleting", async () => {
    const agent = makeAgent()
    let deleteCount = 0
    routes = [
      ...baseRoutes([agent]),
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
        exact: true,
        respond: () => {
          deleteCount += 1
          return new Response(null, { status: 204 })
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /删除/ }))
    fireEvent.click(screen.getByText("取消").closest("button")!)
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(deleteCount).toBe(0)
  })

  test("closes the delete dialog with Escape without deleting", async () => {
    const agent = makeAgent()
    let deleteCount = 0
    routes = [
      ...baseRoutes([agent]),
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
        exact: true,
        respond: () => {
          deleteCount += 1
          return new Response(null, { status: 204 })
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /删除/ }))
    expect(screen.getByRole("dialog")).toBeTruthy()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(deleteCount).toBe(0)
  })

  test("reports an error when the delete request fails", async () => {
    const agent = makeAgent()
    routes = [
      ...baseRoutes([agent]),
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /删除/ }))
    fireEvent.click(within(screen.getByRole("dialog")).getByText("删除").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
    // The dialog stays open so the user can retry or cancel.
    expect(screen.getByRole("dialog")).toBeTruthy()
  })

  test("reports an error when relisting agents after a delete fails", async () => {
    const agent = makeAgent()
    let deleteCount = 0
    let relistCount = 0
    routes = [
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents`,
        exact: false,
        respond: () => {
          relistCount += 1
          return jsonResponse(relistCount > 1 ? { detail: "boom" } : [agent], relistCount > 1 ? 500 : 200)
        },
      },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/models`, exact: true, respond: () => jsonResponse([model("model-1", "DeepSeek Chat", "deepseek-chat")]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/knowledge-bases`, exact: true, respond: () => jsonResponse([]) },
      { method: "GET", pathname: `/api/v1/workspaces/${WS}/mcp-servers`, exact: true, respond: () => jsonResponse([]) },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1`,
        exact: true,
        respond: () => {
          deleteCount += 1
          return new Response(null, { status: 204 })
        },
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /删除/ }))
    fireEvent.click(within(screen.getByRole("dialog")).getByText("删除").closest("button")!)
    await waitFor(() => expect(deleteCount).toBe(1))
    await waitFor(() => expect(notifyCalls.filter((call) => call.kind === "error").length).toBe(1))
    // The deleted agent is still removed from the local list.
    expect(screen.queryByText("Research Assistant")).toBeNull()
  })

  test("reports an error when granting a permission fails", async () => {
    const agent = makeAgent()
    routes = [
      ...baseRoutes([agent]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/members`,
        exact: false,
        respond: () =>
          jsonResponse([
            {
              user: { id: "u-2", username: "alice", name: "Alice", email: "a@x.co", is_global_admin: false, must_change_password: false, is_active: true, created_at: "", workspaces: [], teams: [] },
              role: "member",
            },
          ]),
      },
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions`,
        exact: true,
        respond: () => jsonResponse([]),
      },
      {
        method: "PUT",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions/u-2`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /资源授权/ }))
    await waitFor(() => expect(screen.getByText("Alice / alice")).toBeTruthy())
    const trigger = screen.getByLabelText("用户")
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: /alice/ }))
    fireEvent.click(screen.getByText("保存授权").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
  })

  test("reports an error when revoking a permission fails", async () => {
    const agent = makeAgent()
    routes = [
      ...baseRoutes([agent]),
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/members`,
        exact: false,
        respond: () => jsonResponse([]),
      },
      {
        method: "GET",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions`,
        exact: true,
        respond: () =>
          jsonResponse([
            {
              user: { id: "u-3", username: "bob", name: "Bob", email: "b@x.co", is_global_admin: false, must_change_password: false, is_active: true, created_at: "", workspaces: [], teams: [] },
              permission: "view",
            },
          ]),
      },
      {
        method: "DELETE",
        pathname: `/api/v1/workspaces/${WS}/agents/agent-1/permissions/u-3`,
        exact: true,
        respond: () => jsonResponse({ detail: "boom" }, 500),
      },
    ]
    renderPage(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("Research Assistant")).toBeTruthy())
    fireEvent.pointerDown(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(within(cardOf("Research Assistant")).getByTitle("更多"))
    fireEvent.click(await screen.findByRole("menuitem", { name: /资源授权/ }))
    await waitFor(() => expect(screen.getByText("Bob")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("撤销授权"))
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
  })
})

describe("AgentsPage run flows", () => {
  test("asks a question and renders the streamed answer", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ id: "run-1", status: "queued", result: "" })
    const answerReadyEvent = {
      type: "thought" as const,
      turn: 1,
      tool_name: "",
      status: "succeeded" as const,
      summary: "agent.answer_ready",
      call_id: "",
      tool_label: "",
      tool_kind: "unknown" as const,
      server_name: "",
      input: {},
      output: null,
      duration_ms: 0,
    }
    const finishedRun = makeRun({
      id: "run-1",
      status: "succeeded",
      result: "Hello from the stream",
      events: [answerReadyEvent],
    })
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse(queuedRun, 201),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () =>
            ndjson([
              { type: "process", sequence: 1, event: { type: "thought", turn: 1, tool_name: "", status: "succeeded", summary: "agent.answer_ready", call_id: "", tool_label: "", tool_kind: "unknown", server_name: "", input: {}, output: null, duration_ms: 0 } },
              { type: "answer_delta", sequence: 2, delta: "Hello from the stream" },
              { type: "complete", sequence: 3, run: finishedRun },
            ]),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())

    const textarea = screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "Summarize the latest releases" } })
    fireEvent.click(screen.getByLabelText("发送问题"))

    await waitFor(() => expect(screen.getByText("Hello from the stream")).toBeTruthy())
    expect(screen.getByText("Summarize the latest releases")).toBeTruthy()
    expect(screen.getByText("回答已生成")).toBeTruthy()
  })

  test("uploads attachments and streams reasoning deltas", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ id: "run-1", status: "queued", result: "" })
    const finishedRun = makeRun({ id: "run-1", status: "succeeded", result: "Final answer" })
    let runBody = ""
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/uploads`,
          exact: true,
          respond: () =>
            jsonResponse([
              { id: "up-1", filename: "report.pdf", content_type: "application/pdf", size_bytes: 10, category: "document" },
            ]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: (init) => {
            runBody = String(init?.body ?? "")
            return jsonResponse(queuedRun, 201)
          },
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () =>
            ndjson([
              { type: "reasoning_delta", sequence: 1, live_sequence: "1000-0", stream_epoch: "worker-1", turn: 1, delta: "Thinking…" },
              { type: "answer_delta", sequence: 2, live_sequence: "1000-1", stream_epoch: "worker-1", delta: "Final answer" },
              { type: "complete", sequence: 3, run: finishedRun },
            ]),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(["pdf"], "report.pdf", { type: "application/pdf" })
    fireEvent.change(fileInput, { target: { files: [file] } })
    await waitFor(() => expect(screen.getByText("report.pdf")).toBeTruthy())

    const textarea = screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "Analyze this report" } })
    fireEvent.click(screen.getByLabelText("发送问题"))

    await waitFor(() => expect(screen.getByText("Final answer")).toBeTruthy())
    await waitFor(() => expect(JSON.parse(runBody).file_ids).toEqual(["up-1"]))
  })

  test("cancels an in-flight ask and restores the question", async () => {
    const agent = makeAgent()
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: (init) =>
            new Promise<Response>((_resolve, reject) => {
              const signal = init?.signal
              if (signal?.aborted) reject(signal.reason)
              else signal?.addEventListener("abort", () => reject(signal.reason), { once: true })
            }),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())

    const textarea = screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "Will this hang?" } })
    fireEvent.click(screen.getByLabelText("发送问题"))
    await waitFor(() => expect(screen.getByLabelText("停止生成")).toBeTruthy())

    fireEvent.click(screen.getByLabelText("停止生成"))
    await waitFor(() => expect(screen.getByLabelText("发送问题")).toBeTruthy())
    expect((screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement).value).toBe("Will this hang?")
  })

  test("reports an error when the run submission fails", async () => {
    const agent = makeAgent()
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse({ detail: "boom" }, 500),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())

    const textarea = screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "This will fail" } })
    fireEvent.click(screen.getByLabelText("发送问题"))

    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
    expect((screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement).value).toBe("This will fail")
  })

  test("loads existing runs with an awaiting approval and resolves it", async () => {
    const agent = makeAgent()
    const pendingRun = makeRun({
      id: "run-1",
      status: "awaiting_approval",
      result: "",
      events: [
        { type: "thought", turn: 1, tool_name: "", status: "running", summary: "agent.analyzing", call_id: "", tool_label: "", tool_kind: "unknown", server_name: "", input: {}, output: null, duration_ms: 0, reasoning: "" },
      ],
    })
    const resolvedRun = makeRun({ id: "run-1", status: "succeeded", result: "Query executed" })
    let toolCallStatus = "awaiting_approval"
    let approveBody: string | null = null
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([pendingRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls`,
          exact: true,
          respond: () => jsonResponse([makeToolCall({ status: toolCallStatus as AgentToolCall["status"] })]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () => ndjson([{ type: "complete", sequence: 5, run: resolvedRun }]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls/call-1/approve`,
          exact: true,
          respond: (init) => {
            approveBody = String(init?.body ?? "")
            toolCallStatus = "approved"
            return jsonResponse(makeRun({ id: "run-1", status: "queued", result: "" }))
          },
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("工具调用需要确认")).toBeTruthy())
    expect(screen.getByText(/execute_sql/)).toBeTruthy()

    fireEvent.click(screen.getByText("批准并执行").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "工具调用已批准")).toBe(true))
    expect(approveBody ?? "").toBe("")
  })

  test("rejects a tool call decision", async () => {
    const agent = makeAgent()
    const pendingRun = makeRun({
      id: "run-1",
      status: "awaiting_approval",
      result: "",
      events: [
        { type: "thought", turn: 1, tool_name: "", status: "running", summary: "agent.analyzing", call_id: "", tool_label: "", tool_kind: "unknown", server_name: "", input: {}, output: null, duration_ms: 0, reasoning: "" },
      ],
    })
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([pendingRun]),
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
          respond: () => ndjson([{ type: "complete", sequence: 5, run: makeRun({ status: "failed", last_error: "rejected", result: "" }) }]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls/call-1/reject`,
          exact: true,
          respond: () => jsonResponse(makeRun({ id: "run-1", status: "queued", result: "" })),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("工具调用需要确认")).toBeTruthy())
    fireEvent.click(screen.getByText("拒绝").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "工具调用已拒绝")).toBe(true))
  })

  test("starts a new conversation and resets the preview", async () => {
    const agent = makeAgent()
    const succeededRun = makeRun({ status: "succeeded", result: "Old answer" })
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([succeededRun]),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("Old answer")).toBeTruthy())

    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    expect(navState.pushCalls.some((href) => href.startsWith("/app/apps/agent-1/settings?conversation_id="))).toBe(true)
  })

  test("ignores empty ask submissions", async () => {
    const agent = makeAgent()
    let runPosts = 0
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => {
            runPosts += 1
            return jsonResponse(makeRun({ status: "queued", result: "" }), 201)
          },
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    const textarea = screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement
    const form = textarea.closest("form")
    fireEvent.submit(form!)
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(runPosts).toBe(0)
  })

  test("notifies when the run stream reports an error", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ id: "run-1", status: "queued", result: "" })
    const failedRun = makeRun({ id: "run-1", status: "failed", result: "", last_error: "execution failed" })
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse(queuedRun, 201),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () =>
            ndjson([
              { type: "run", sequence: 1, run: queuedRun },
              { type: "error", sequence: 2, run: failedRun },
            ]),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    const textarea = screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "This will error" } })
    fireEvent.click(screen.getByLabelText("发送问题"))
    await waitFor(() => expect(notifyCalls.some((call) => call.message === "Agent 回答失败")).toBe(true))
    await waitFor(() => expect(screen.getByText("execution failed")).toBeTruthy())
  })

  test("drops stream events that arrive after a new conversation", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ id: "run-1", status: "queued", result: "" })
    const finishedRun = makeRun({ id: "run-1", status: "succeeded", result: "Late answer" })
    let emitStream: (() => void) | null = null
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse(queuedRun, 201),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () =>
            new Promise<Response>((resolve) => {
              emitStream = () =>
                resolve(
                  ndjson([
                    { type: "run", sequence: 1, run: queuedRun },
                    { type: "complete", sequence: 2, run: finishedRun },
                  ])
                )
            }),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    const textarea = screen.getByLabelText("向 Agent 提问") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "Race me" } })
    fireEvent.click(screen.getByLabelText("发送问题"))
    await waitFor(() => expect(screen.getByLabelText("停止生成")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    emitStream!()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByText("Late answer")).toBeNull()
  })

  test("reports an error when a tool call decision fails", async () => {
    const agent = makeAgent()
    const pendingRun = makeRun({
      id: "run-1",
      status: "awaiting_approval",
      result: "",
      events: [thoughtEvent()],
    })
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([pendingRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls`,
          exact: true,
          respond: () => jsonResponse([makeToolCall()]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls/call-1/approve`,
          exact: true,
          respond: () => jsonResponse({ detail: "boom" }, 500),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("工具调用需要确认")).toBeTruthy())
    fireEvent.click(screen.getByText("批准并执行").closest("button")!)
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
  })

  test("ignores a stale tool call resolution after switching conversations", async () => {
    const agent = makeAgent()
    const pendingRun = makeRun({
      id: "run-1",
      status: "awaiting_approval",
      result: "",
      events: [thoughtEvent()],
    })
    let resolveApprove: (value: Response) => void = () => undefined
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([pendingRun]),
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
          respond: () => ndjson([{ type: "complete", sequence: 1, run: makeRun({ status: "succeeded", result: "" }) }]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls/call-1/approve`,
          exact: true,
          respond: () =>
            new Promise<Response>((resolve) => {
              resolveApprove = resolve
            }),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("工具调用需要确认")).toBeTruthy())
    fireEvent.click(screen.getByText("批准并执行").closest("button")!)
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    resolveApprove!(jsonResponse(makeRun({ id: "run-1", status: "queued", result: "" })))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(notifyCalls.some((call) => call.message === "工具调用已批准")).toBe(false)
  })

  test("ignores a stale tool-call list after switching conversations", async () => {
    const agent = makeAgent()
    const pendingRun = makeRun({
      id: "run-1",
      status: "awaiting_approval",
      result: "",
      events: [thoughtEvent()],
    })
    let toolCallsRequests = 0
    let callsRequested = false
    let resolveCalls: (value: Response) => void = () => undefined
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([pendingRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls`,
          exact: true,
          respond: () => {
            toolCallsRequests += 1
            if (toolCallsRequests === 1) return jsonResponse([makeToolCall()])
            callsRequested = true
            return new Promise<Response>((resolve) => {
              resolveCalls = resolve
            })
          },
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () => ndjson([{ type: "complete", sequence: 1, run: makeRun({ status: "succeeded", result: "" }) }]),
        },
        {
          method: "POST",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls/call-1/approve`,
          exact: true,
          respond: () => jsonResponse(makeRun({ id: "run-1", status: "queued", result: "" })),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("工具调用需要确认")).toBeTruthy(), {
      timeout: 3000,
    })
    fireEvent.click(screen.getByText("批准并执行").closest("button")!)
    await waitFor(() => expect(callsRequested).toBe(true))
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    resolveCalls!(jsonResponse([makeToolCall({ status: "approved" })]))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(notifyCalls.some((call) => call.message === "工具调用已批准")).toBe(false)
  })

  test("discards run lists that resolve after a conversation switch", async () => {
    const agent = makeAgent()
    let resolveRuns: (value: Response) => void = () => undefined
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () =>
            new Promise<Response>((resolve) => {
              resolveRuns = resolve
            }),
        },
      ],
    })
    await waitFor(() => expect(screen.getByText("正在加载")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    resolveRuns!(jsonResponse([makeRun({ status: "succeeded", result: "Old answer" })]))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByText("Old answer")).toBeNull()
  })

  test("reports an error when loading tool calls for an awaiting run fails", async () => {
    const agent = makeAgent()
    const pendingRun = makeRun({
      id: "run-1",
      status: "awaiting_approval",
      result: "",
      events: [thoughtEvent()],
    })
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([pendingRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/tool-calls`,
          exact: true,
          respond: () => jsonResponse({ detail: "boom" }, 500),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () => ndjson([{ type: "complete", sequence: 1, run: makeRun({ status: "succeeded", result: "" }) }]),
        },
      ],
    })
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
  })

  test("drops observed stream events that arrive after a new conversation", async () => {
    const agent = makeAgent()
    const runningRun = makeRun({ id: "run-1", status: "running", result: "", events: [] })
    let emitObserved: (() => void) | null = null
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([runningRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () =>
            new Promise<Response>((resolve) => {
              emitObserved = () =>
                resolve(
                  ndjson([
                    {
                      type: "process",
                      sequence: 1,
                      event: {
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
                    },
                  ])
                )
            }),
        },
      ],
    })
    await waitFor(() => expect(emitObserved).toBeTruthy())
    fireEvent.click(screen.getByLabelText("新建对话"))
    await waitFor(() => expect(screen.getByText("开始和 Agent 对话")).toBeTruthy())
    emitObserved!()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByText("正在分析问题")).toBeNull()
  })

  test("loads tool calls when the stream requests approval", async () => {
    const agent = makeAgent()
    const queuedRun = makeRun({ id: "run-1", status: "queued", result: "", events: [] })
    await renderDetail({
      agent,
      initialView: "settings",
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
    await waitFor(() => expect(screen.getByText("工具调用需要确认")).toBeTruthy())
    expect(screen.getByText(/execute_sql/)).toBeTruthy()
  })

  test("reports an error when observing a live run fails", async () => {
    const agent = makeAgent()
    const runningRun = makeRun({ id: "run-1", status: "running", result: "", events: [] })
    await renderDetail({
      agent,
      initialView: "settings",
      extraRoutes: [
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs`,
          exact: true,
          respond: () => jsonResponse([runningRun]),
        },
        {
          method: "GET",
          pathname: `/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1/stream`,
          exact: false,
          respond: () => jsonResponse({ detail: "boom" }, 404),
        },
      ],
    })
    await waitFor(() => expect(notifyCalls.some((call) => call.kind === "error")).toBe(true))
  })
})

describe("lib/api/agents direct calls", () => {
  test("getAgentRun requests the single run endpoint", async () => {
    let requestedUrl = ""
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      requestedUrl = String(input)
      return jsonResponse(makeRun())
    }) as unknown as typeof fetch
    const run = await getAgentRun("token", WS, "agent-1", "run-1")
    expect(run.id).toBe("run-1")
    expect(requestedUrl).toBe(`/api/v1/workspaces/${WS}/agents/agent-1/runs/run-1`)
  })
})

/* ------------------------------------------------------------------ */
/* Stream merge pure functions                                         */
/* ------------------------------------------------------------------ */

const thoughtEvent = (
  overrides: Record<string, unknown> = {}
): AgentRunEvent =>
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
  } as AgentRunEvent)

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
    mcpTools: agent.mcp_tools.map((tool) => ({ ...tool })),
    status: agent.status,
  }
}

describe("run stream merge pure functions", () => {
  test("mergeInitialAgentRun keeps live fields for in-flight runs", () => {
    const pending = makeRun({
      id: "run-1",
      status: "running",
      result: "Pending answer",
      events: [thoughtEvent()],
      live_stream_epoch: "worker-1",
      live_stream_cursor: "1000-0",
    })
    const live = makeRun({
      id: "run-1",
      status: "running",
      result: "",
      events: [],
    })
    const merged = mergeInitialAgentRun(pending, live)
    expect(merged.events).toEqual(pending.events)
    expect(merged.result).toBe("Pending answer")
    expect(merged.live_stream_epoch).toBe("worker-1")
    expect(merged.live_stream_cursor).toBe("1000-0")

    const settled = mergeInitialAgentRun(
      pending,
      makeRun({ id: "run-1", status: "succeeded", result: "Final" })
    )
    expect(settled.result).toBe("Final")
    expect(settled.live_stream_epoch).toBeUndefined()
  })

  test("mergeAgentRunSnapshot replaces the placeholder and prepends unknowns", () => {
    const placeholder = makeRun({ id: "pending-1", status: "running", result: "draft" })
    const live = makeRun({ id: "run-1", status: "succeeded", result: "answer" })
    const replaced = mergeAgentRunSnapshot(
      [placeholder, makeRun({ id: "run-2", status: "succeeded", result: "other" })],
      live,
      "pending-1"
    )
    expect(replaced.map((run) => run.id)).toEqual(["run-1", "run-2"])
    expect(replaced[0].result).toBe("answer")

    const fresh = mergeAgentRunSnapshot([makeRun({ id: "run-2" })], live)
    expect(fresh.map((run) => run.id)).toEqual(["run-1", "run-2"])
  })

  test("process events append when nothing matches and replace by call id", () => {
    const run = makeRun({ status: "running", result: "", events: [thoughtEvent()] })
    const appended = mergeAgentRunStreamEvent([run], "run-1", {
      type: "process",
      sequence: 2,
      event: thoughtEvent({ turn: 2 }),
    } as AgentRunStreamEvent)
    expect(appended[0].events).toHaveLength(2)
    expect(appended[0].events[1].turn).toBe(2)

    // A process event whose call id matches an existing event replaces it.
    const runWithCall = makeRun({
      status: "running",
      result: "",
      events: [thoughtEvent({ call_id: "call-x" })],
    })
    const replaced = mergeAgentRunStreamEvent([runWithCall], "run-1", {
      type: "process",
      sequence: 3,
      event: {
        ...thoughtEvent({ status: "succeeded" }),
        call_id: "call-x",
      },
    } as AgentRunStreamEvent)
    expect(replaced[0].events).toHaveLength(1)
    expect(replaced[0].events[0].status).toBe("succeeded")
  })

  test("reasoning deltas append, dedupe by live cursor, and skip other runs", () => {
    const run = makeRun({
      status: "running",
      result: "",
      events: [
        thoughtEvent({ reasoning: "" }),
        thoughtEvent({ turn: 2 }),
      ],
    })
    const streamed = mergeAgentRunStreamEvent([run], "run-1", {
      type: "reasoning_delta",
      sequence: 1,
      turn: 1,
      delta: "Thinking…",
    } as AgentRunStreamEvent)
    expect(streamed[0].events[0].reasoning).toBe("Thinking…")
    // A non-thought event at the same turn passes through untouched.
    expect(streamed[0].events[1]).toEqual(run.events[1])

    const deduped = mergeAgentRunStreamEvent(
      [makeRun({ status: "running", result: "", events: [], live_stream_epoch: "w-1", live_stream_cursor: "1000-5" })],
      "run-1",
      {
        type: "reasoning_delta",
        sequence: 2,
        live_sequence: "1000-4",
        stream_epoch: "w-1",
        turn: 1,
        delta: "old",
      } as AgentRunStreamEvent
    )
    expect(deduped[0].events).toEqual([])

    const unchanged = mergeAgentRunStreamEvent([run], "run-9", {
      type: "reasoning_delta",
      sequence: 3,
      turn: 1,
      delta: "x",
    } as AgentRunStreamEvent)
    expect(unchanged).toEqual([run])
  })

  test("answer deltas append, dedupe by live cursor, and skip other runs", () => {
    const run = makeRun({ status: "running", result: "Hello", events: [] })
    const streamed = mergeAgentRunStreamEvent([run], "run-1", {
      type: "answer_delta",
      sequence: 1,
      delta: " world",
    } as AgentRunStreamEvent)
    expect(streamed[0].result).toBe("Hello world")

    const deduped = mergeAgentRunStreamEvent(
      [makeRun({ status: "running", result: "x", events: [], live_stream_epoch: "w-1", live_stream_cursor: "1000-5" })],
      "run-1",
      {
        type: "answer_delta",
        sequence: 2,
        live_sequence: "1000-4",
        stream_epoch: "w-1",
        delta: "stale",
      } as AgentRunStreamEvent
    )
    expect(deduped[0].result).toBe("x")

    const unchanged = mergeAgentRunStreamEvent([run], "run-9", {
      type: "answer_delta",
      sequence: 3,
      delta: "y",
    } as AgentRunStreamEvent)
    expect(unchanged).toEqual([run])
  })

  test("a new stream epoch resets the partial answer", () => {
    const run = makeRun({
      status: "running",
      result: "Partial",
      events: [thoughtEvent({ reasoning: "old" })],
      live_stream_epoch: "w-1",
    })
    const streamed = mergeAgentRunStreamEvent([run], "run-1", {
      type: "reasoning_delta",
      sequence: 1,
      stream_epoch: "w-2",
      turn: 1,
      delta: "fresh",
    } as AgentRunStreamEvent)
    expect(streamed[0].result).toBe("")
    expect(streamed[0].events[0].reasoning).toBe("fresh")
    expect(streamed[0].live_stream_epoch).toBe("w-2")
  })

  test("approval_required and approval_resolved update the run status", () => {
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
    expect(resolved[1].status).toBe("running")
  })

  test("run events replace matching runs", () => {
    const runs = [makeRun({ id: "run-1", status: "running", result: "", events: [] })]
    const finished = makeRun({ id: "run-1", status: "succeeded", result: "done" })
    const replaced = mergeAgentRunStreamEvent(runs, "run-1", {
      type: "complete",
      sequence: 9,
      run: finished,
    } as AgentRunStreamEvent)
    expect(replaced[0].result).toBe("done")
  })

  test("isAgentFormDirty detects per-field changes", () => {
    const agent = makeAgent()
    expect(isAgentFormDirty(formFromAgentFixture(agent), agent)).toBe(false)
    expect(
      isAgentFormDirty(
        { ...formFromAgentFixture(agent), name: "  " },
        agent
      )
    ).toBe(true)
    expect(
      isAgentFormDirty(
        { ...formFromAgentFixture(agent), modelId: "model-2" },
        agent
      )
    ).toBe(true)
    expect(
      isAgentFormDirty(
        { ...formFromAgentFixture(agent), status: "disabled" },
        agent
      )
    ).toBe(true)
    expect(
      isAgentFormDirty(
        { ...formFromAgentFixture(agent), knowledgeBaseIds: [] },
        agent
      )
    ).toBe(true)
    expect(
      isAgentFormDirty(
        { ...formFromAgentFixture(agent), mcpTools: [] },
        agent
      )
    ).toBe(true)
    // Workflow app types ignore knowledge and MCP bindings.
    const workflow = makeWorkflow()
    const workflowForm: AgentFormState = {
      ...formFromAgentFixture(workflow),
      knowledgeBaseIds: ["knowledge-9"],
      mcpTools: [{ server_id: "server-9", tool_name: "tool" }],
    }
    expect(isAgentFormDirty(workflowForm, workflow)).toBe(false)
  })
})

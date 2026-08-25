/* @jsxImportSource react */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
} from "bun:test"
import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react"

import {
  PublicAgentChat,
  cancelPublicAgentStream,
  hasPublicToolDetails,
  mergePublicRunEvent,
  publicToolName,
} from "@/components/agents/public-agent-chat"
import { PublicWorkflowChat } from "@/components/workflows/public-workflow-chat"
import { ApiError } from "@/lib/api-client"
import { copyText } from "@/lib/clipboard"
import {
  displayTeamName,
  displayWorkspaceName,
  formatDateTime,
  getMembershipRole,
  hasWorkspaceMembership,
  initials,
  modelLabel,
} from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import type { TFunction } from "@/i18n"
import type { MeResponse } from "@/lib/api/auth"
import type { RegisteredModel } from "@/lib/api/llm"
import {
  getPublicAgentRun,
  listPublicAgentRuns,
  listPublicAgentRunToolCalls,
  observePublicAgentRun,
  resolvePublicAgentRunToolCall,
  streamPublicAgentRun,
  uploadPublicAgentFiles,
  type ExternalAgentProgressEvent,
  type ExternalAgentRun,
  type PublicAgentConversation,
  type PublicAgentProfile,
} from "@/lib/api/public-agents"
import {
  createPublicWorkflowRun,
  getPublicWorkflowProfile,
  getWorkflowApiDocumentation,
  initializePublicWorkflow,
  listPublicWorkflowRuns,
  observePublicWorkflowRun,
  submitPublicWorkflowForm,
  uploadPublicWorkflowFiles,
} from "@/lib/api/public-workflows"

import {
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  type FetchHandler,
} from "./helpers/dom"

const t = ((key: string) => key) as TFunction

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PROFILE: PublicAgentProfile = {
  id: "agent-1",
  name: "公开助手",
  description: "这是一个公开助手。",
  interaction_config: {
    prologue: "",
    tts_type: "BROWSER",
    file_upload: true,
    file_upload_setting: { file_upload_type: ["document", "image"] },
    user_input_title: "",
  },
}

function conversation(
  id: string,
  question: string
): PublicAgentConversation {
  return {
    conversation_id: id,
    question,
    status: "completed",
    result: "",
    run_count: 1,
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
  }
}

function run(overrides: Partial<ExternalAgentRun> = {}): ExternalAgentRun {
  return {
    id: "run-1",
    conversation_id: "conv-1",
    question: "你好",
    status: "succeeded",
    result: "回答内容",
    error: null,
    progress: [],
    created_at: "2026-08-10T00:00:00Z",
    started_at: "2026-08-10T00:00:00Z",
    finished_at: "2026-08-10T00:00:01Z",
    updated_at: "2026-08-10T00:00:01Z",
    ...overrides,
  }
}

function knowledgeEvent(
  id: string,
  status: ExternalAgentProgressEvent["status"],
  overrides: Partial<ExternalAgentProgressEvent> = {}
): ExternalAgentProgressEvent {
  return {
    id,
    type: "knowledge",
    status,
    stage: status,
    turn: 1,
    count: null,
    hits: [],
    ...overrides,
  }
}

function toolEvent(
  id: string,
  status: ExternalAgentProgressEvent["status"],
  overrides: Partial<ExternalAgentProgressEvent> = {}
): ExternalAgentProgressEvent {
  return {
    id,
    type: "tool",
    status,
    stage: status,
    turn: 1,
    count: null,
    tool_name: "",
    tool_label: "",
    tool_kind: "unknown",
    server_name: "",
    input: {},
    output: null,
    hits: [],
    ...overrides,
  }
}

/** A rich execution timeline exercising every PublicExecutionProcess branch. */
const FULL_PROGRESS: ExternalAgentProgressEvent[] = [
  {
    id: "reasoning-1",
    type: "analysis",
    status: "running",
    stage: "analyzing",
    turn: 1,
    count: null,
    reasoning: "让我想想\n继续想",
    hits: [],
  },
  {
    id: "rev-1",
    type: "analysis",
    status: "succeeded",
    stage: "reviewing",
    turn: 2,
    count: null,
    hits: [],
  },
  {
    id: "done-1",
    type: "analysis",
    status: "succeeded",
    stage: "completed",
    turn: 3,
    count: null,
    hits: [],
  },
  {
    id: "preparing-1",
    type: "analysis",
    status: "running",
    stage: "running",
    turn: 4,
    count: null,
    hits: [],
  },
  knowledgeEvent("k1", "running"),
  knowledgeEvent("k2", "succeeded", {
    count: 2,
    hits: [
      {
        knowledge_base: "kb-1",
        document: "doc-1",
        content: "片段内容",
      },
    ],
  }),
  knowledgeEvent("k3", "succeeded", { count: 0 }),
  toolEvent("t1", "running", {
    tool_name: "search",
    tool_label: "Search",
    tool_kind: "mcp",
    server_name: "Tavily",
    input: { q: "x" },
  }),
  toolEvent("t2", "succeeded", {
    tool_name: "web_search",
    tool_label: "Web search",
    tool_kind: "mcp",
    server_name: "Tavily",
    input: { query: "NexaFlow" },
    output: { results: ["r1"] },
    input_truncated: true,
  }),
  toolEvent("f1", "failed", {
    tool_name: "db_query",
    tool_label: "DB Query",
    tool_kind: "unknown",
  }),
  toolEvent("g1", "succeeded"),
  {
    id: "a1",
    type: "answer",
    status: "running",
    stage: "analyzing",
    turn: 1,
    count: null,
    hits: [],
  },
  {
    id: "a2",
    type: "answer",
    status: "succeeded",
    stage: "succeeded",
    turn: 1,
    count: null,
    hits: [],
  },
]

function ndjsonResponse(events: unknown[]): Response {
  const body = events
    .map((event) => `${JSON.stringify(event)}\n`)
    .join("")
  return new Response(body, { status: 200 })
}

function workflowProfile() {
  return {
    id: "wf-1",
    name: "公开流程",
    description: "流程描述",
    interaction_config: {
      prologue: "",
      tts_type: "BROWSER",
      file_upload: true,
      file_upload_setting: { file_upload_type: ["document"] },
      user_input_title: "",
    },
  }
}

function workflowRun(overrides: Record<string, unknown> = {}) {
  return {
    id: "wf-run-1",
    conversation_id: "conv-1",
    inputs: {},
    outputs: {},
    status: "succeeded",
    error: null,
    progress: [],
    created_at: "2026-08-10T00:00:00Z",
    started_at: "2026-08-10T00:00:00Z",
    finished_at: "2026-08-10T00:00:01Z",
    updated_at: "2026-08-10T00:00:01Z",
    pending_form: null,
    ...overrides,
  }
}

function meResponse(
  overrides: Partial<MeResponse> = {}
): MeResponse {
  return {
    user: {
      id: "u-1",
      username: "u",
      email: "u@x.co",
      name: "U",
      is_global_admin: false,
      must_change_password: false,
      is_active: true,
      created_at: "2026-08-10T00:00:00Z",
      workspaces: [],
      teams: [],
    },
    memberships: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Test harness: session + router + fetch stub
// ---------------------------------------------------------------------------

const session = makeSession()
mockUseSession(session)
const replaced: string[] = []
mockNextNavigation({ replace: (href: string) => replaced.push(href) })

let fetchHandler: FetchHandler = () => jsonResponse({})
const originalFetch = globalThis.fetch

const originalClipboard = navigator.clipboard
const originalSetTimeout = globalThis.setTimeout

afterEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    value: originalClipboard,
    configurable: true,
  })
  globalThis.setTimeout = originalSetTimeout
  globalThis.fetch = originalFetch
  cleanup()
})
beforeEach(() => {
  Object.assign(session, { token: "test-token", isSessionRestored: true })
  replaced.length = 0
  // Re-install the fetch stub after the previous test restored it. Requests
  // are dispatched through `fetchHandler`, which every test replaces.
  globalThis.fetch = ((
    input: RequestInfo | URL,
    init?: RequestInit
  ) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    return Promise.resolve(fetchHandler(url, init))
  }) as typeof fetch
})

type AgentFetchRoutes = {
  profile?: unknown
  conversations?: { items: PublicAgentConversation[] }
  history?:
    | { items: ExternalAgentRun[] }
    | (() => Response | Promise<Response>)
  createRun?: (
    body: Record<string, unknown>
  ) => Response | Promise<Response>
  streamResponses?: Array<() => Response | Promise<Response>>
  toolCalls?: () => Response | Promise<Response>
  resolveRun?: () => Response | Promise<Response>
  uploads?: unknown
}

function agentFetchHandler(
  routes: AgentFetchRoutes,
  requests: string[] = []
) {
  let streamCalls = 0
  return (url: string, init?: RequestInit): Response | Promise<Response> => {
    const method = init?.method ?? "GET"
    requests.push(`${method} ${url}`)
    if (url.endsWith("/profile")) {
      return jsonResponse(routes.profile ?? PROFILE)
    }
    if (url.includes("/conversations")) {
      return jsonResponse(routes.conversations ?? { items: [] })
    }
    if (url.includes("/uploads")) {
      return jsonResponse(routes.uploads ?? [])
    }
    if (url.includes("/stream")) {
      const responses = routes.streamResponses ?? []
      const response = responses[streamCalls]
      streamCalls += 1
      return response
        ? response()
        : ndjsonResponse([
            {
              type: "complete",
              sequence: 1,
              run: run({ status: "succeeded", result: "完成" }),
            },
          ])
    }
    const decision = url.match(/\/tool-calls\/([^/]+)\/(approve|reject)$/)
    if (decision) {
      const respond =
        routes.resolveRun ??
        (() => jsonResponse(run({ status: "running", result: "" })))
      return respond()
    }
    if (url.includes("/tool-calls")) {
      const respond = routes.toolCalls ?? (() => jsonResponse([]))
      return respond()
    }
    if (method === "POST" && url.includes("/runs")) {
      const create =
        routes.createRun ??
        ((body: Record<string, unknown>) =>
          jsonResponse(
            run({ status: "running", question: String(body.goal), result: "" }),
            201
          ))
      return create(JSON.parse(String(init?.body ?? "{}")))
    }
    if (url.includes("/runs")) {
      const history = routes.history
      return typeof history === "function"
        ? history()
        : jsonResponse(
            history ?? { items: [], total: 0, offset: 0, limit: 200 }
          )
    }
    return jsonResponse({})
  }
}

const TOOL_CALL = {
  call_id: "call-1",
  turn: 1,
  tool_name: "web_search",
  tool_kind: "mcp",
  server_name: "Tavily",
  arguments: { query: "NexaFlow" },
  status: "awaiting_approval",
  approval_required: true,
  last_error: null,
  approved_at: null,
  started_at: null,
  finished_at: null,
}

function sendMessage(text: string) {
  const textarea = screen.getByLabelText("请输入问题")
  fireEvent.change(textarea, { target: { value: text } })
  // Enter (without Shift or composition) submits the form directly.
  fireEvent.keyDown(textarea, { key: "Enter" })
}

// ---------------------------------------------------------------------------
// Pure helpers: display / clipboard / errors
// ---------------------------------------------------------------------------

describe("display helpers", () => {
  test("formats model labels and initials", () => {
    expect(
      modelLabel({ name: "deepseek-chat" } as RegisteredModel)
    ).toBe("deepseek-chat")
    expect(initials("NexaFlow Admin")).toBe("NE")
    expect(initials("  ")).toBe("NE")
    expect(initials("ab")).toBe("AB")
  })

  test("formats datetimes for a locale", () => {
    expect(formatDateTime("2026-08-10T00:00:00Z", "zh-CN")).toContain("2026")
  })

  test("translates the default workspace and team names", () => {
    expect(
      displayWorkspaceName({ name: "Default Workspace", is_default: true }, t)
    ).toBe("默认工作空间")
    expect(
      displayWorkspaceName({ name: "研发空间", is_default: true }, t)
    ).toBe("研发空间")
    expect(
      displayTeamName({ name: "Default Team", is_default: true }, t)
    ).toBe("默认团队")
    expect(displayTeamName({ name: "数据组", is_default: false }, t)).toBe(
      "数据组"
    )
  })

  test("detects workspace membership", () => {
    expect(hasWorkspaceMembership(null, "ws-1")).toBe(false)
    expect(
      hasWorkspaceMembership(meResponse(), "ws-1")
    ).toBe(false)
    expect(
      hasWorkspaceMembership(
        meResponse({ user: { ...meResponse().user, is_global_admin: true } }),
        "ws-1"
      )
    ).toBe(true)
    expect(
      hasWorkspaceMembership(
        meResponse({ memberships: [{ workspace_id: "ws-1", role: "editor" }] }),
        "ws-1"
      )
    ).toBe(true)
  })

  test("resolves membership roles", () => {
    expect(getMembershipRole(null, "ws-1")).toBeNull()
    expect(getMembershipRole(meResponse(), null)).toBeNull()
    expect(
      getMembershipRole(
        meResponse({ user: { ...meResponse().user, is_global_admin: true } }),
        "ws-1"
      )
    ).toBe("admin")
    expect(
      getMembershipRole(
        meResponse({ memberships: [{ workspace_id: "ws-1", role: "editor" }] }),
        "ws-1"
      )
    ).toBe("editor")
    expect(getMembershipRole(meResponse(), "ws-9")).toBeNull()
  })
})

describe("clipboard", () => {
  test("copies through the clipboard API when available", async () => {
    const written: string[] = []
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async (value: string) => {
          written.push(value)
        },
      },
      configurable: true,
    })

    await copyText("hello")

    expect(written).toEqual(["hello"])
  })

  test("falls back to execCommand when the clipboard API is missing", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    })
    const execCalls: string[] = []
    document.execCommand = ((command: string) => {
      execCalls.push(command)
      return true
    }) as typeof document.execCommand

    await copyText("fallback")

    expect(execCalls).toEqual(["copy"])
    expect(document.body.querySelector("textarea")).toBeNull()
  })

  test("rejects when the execCommand fallback fails", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    })
    document.execCommand = (() => false) as typeof document.execCommand

    try {
      await copyText("nope")
      throw new Error("copyText should reject")
    } catch (error) {
      expect((error as Error).message).toBe("Copy failed")
    }
  })
})

describe("getErrorMessage", () => {
  test("maps ApiError, plain errors, and unknown values", () => {
    expect(getErrorMessage(new ApiError(401, "expired"), t)).toBe("请重新登录")
    expect(
      getErrorMessage(new ApiError(401, "Invalid credentials."), t)
    ).toBe("用户名或密码错误")
    expect(getErrorMessage(new ApiError(403, "forbidden"), t)).toBe(
      "资源不存在或无权访问"
    )
    expect(getErrorMessage(new ApiError(404, "找不到"), t)).toBe(
      "资源不存在或无权访问"
    )
    expect(getErrorMessage(new ApiError(503, "离线"), t)).toBe("离线")
    expect(getErrorMessage(new TypeError("Failed to fetch"), t)).toBe(
      "网络连接失败，请稍后重试"
    )
    expect(getErrorMessage(new Error("崩溃"), t)).toBe("崩溃")
    expect(getErrorMessage("意外值", t)).toBe("请求失败")
    expect(getErrorMessage(null, t)).toBe("请求失败")
  })
})

// ---------------------------------------------------------------------------
// Public agent API
// ---------------------------------------------------------------------------

describe("public agent API", () => {
  test("lists runs with limit, offset and conversation filter", async () => {
    const requests: string[] = []
    fetchHandler = (url, init) => {
      requests.push(`${init?.method ?? "GET"} ${url}`)
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 50 })
    }

    await listPublicAgentRuns("agent-1", "conv-9", "token", {
      limit: 50,
      offset: 10,
    })

    expect(requests[0]).toContain(
      "/runs?limit=50&offset=10&conversation_id=conv-9"
    )
  })

  test("uploads files as a multipart form", async () => {
    const requests: Array<{ url: string; body: unknown }> = []
    fetchHandler = (url, init) => {
      requests.push({ url, body: init?.body })
      return jsonResponse(
        [
          {
            id: "f1",
            filename: "a.txt",
            content_type: "text/plain",
            size_bytes: 1,
            category: "document",
          },
        ],
        201
      )
    }
    const file = new File(["x"], "a.txt", { type: "text/plain" })

    const uploaded = await uploadPublicAgentFiles("agent-1", "token", [file])

    expect(requests[0]?.url).toContain("/uploads")
    expect(requests[0]?.body).toBeInstanceOf(FormData)
    expect((requests[0]?.body as FormData).getAll("files")).toHaveLength(1)
    expect(uploaded[0]?.id).toBe("f1")
  })

  test("fetches a single public run", async () => {
    const requests: string[] = []
    fetchHandler = (url) => {
      requests.push(url)
      return jsonResponse(run())
    }

    await getPublicAgentRun("agent-1", "token", "run-1")

    expect(requests[0]).toContain("/runs/run-1")
  })

  test("lists tool calls for a run", async () => {
    const requests: string[] = []
    fetchHandler = (url) => {
      requests.push(url)
      return jsonResponse([])
    }

    await listPublicAgentRunToolCalls("agent-1", "token", "run-1")

    expect(requests[0]).toContain("/runs/run-1/tool-calls")
  })

  test("resolves tool calls with approve or reject", async () => {
    const calls: string[] = []
    fetchHandler = (url, init) => {
      calls.push(`${init?.method ?? "GET"} ${url}`)
      return jsonResponse(run())
    }

    await resolvePublicAgentRunToolCall(
      "agent-1",
      "token",
      "run-1",
      "call-1",
      "approve"
    )
    await resolvePublicAgentRunToolCall(
      "agent-1",
      "token",
      "run-1",
      "call-1",
      "reject"
    )

    expect(calls[0]).toContain("/tool-calls/call-1/approve")
    expect(calls[1]).toContain("/tool-calls/call-1/reject")
    expect(calls.every((call) => call.startsWith("POST"))).toBe(true)
  })

  test("reconnects a public stream using the durable cursor", async () => {
    const urls: string[] = []
    let streamCalls = 0
    fetchHandler = (url) => {
      urls.push(url)
      streamCalls += 1
      if (streamCalls === 1) {
        return new Response(
          `${JSON.stringify({ type: "answer_delta", sequence: 9, delta: "part" })}\n`
        )
      }
      return new Response(
        `${JSON.stringify({
          type: "complete",
          sequence: 10,
          run: run({ status: "succeeded", result: "done" }),
        })}\n`
      )
    }

    const events: string[] = []
    await observePublicAgentRun("agent-1", "token", "run-1", (event) =>
      events.push(event.type)
    )

    expect(events).toEqual(["answer_delta", "complete"])
    expect(urls[1]).toContain("after=9")
  })

  test("normalizes an immediately failed public run into an error event", async () => {
    fetchHandler = () =>
      jsonResponse(
        run({ status: "failed", result: "", error: "早失败" }),
        201
      )

    const events: string[] = []
    await streamPublicAgentRun("agent-1", "token", "q", (event) =>
      events.push(event.type)
    )

    expect(events).toEqual(["run", "error"])
  })
})

// ---------------------------------------------------------------------------
// Public workflow API
// ---------------------------------------------------------------------------

describe("public workflow API", () => {
  test("loads a workflow profile", async () => {
    let requestedUrl = ""
    fetchHandler = (url) => {
      requestedUrl = url
      return jsonResponse(workflowProfile())
    }

    const profile = await getPublicWorkflowProfile("wf-1", "token")

    expect(requestedUrl).toContain("/workflows/wf-1/profile")
    expect(profile.name).toBe("公开流程")
  })

  test("initializes profile and conversations together", async () => {
    const requests: string[] = []
    fetchHandler = (url) => {
      requests.push(url)
      return url.includes("/conversations")
        ? jsonResponse({ items: [] })
        : jsonResponse(workflowProfile())
    }

    const result = await initializePublicWorkflow("wf-1", "token")

    expect(requests.map((url) => (url.includes("/conversations") ? "conv" : "profile"))).toEqual(
      ["profile", "conv"]
    )
    expect(result.conversations.items).toEqual([])
  })

  test("lists workflow runs with a conversation filter", async () => {
    const requests: string[] = []
    fetchHandler = (url) => {
      requests.push(url)
      return jsonResponse({ items: [workflowRun()] })
    }

    const result = await listPublicWorkflowRuns("wf-1", "conv-1", "token")

    expect(requests[0]).toContain(
      "/runs?limit=200&conversation_id=conv-1"
    )
    expect(result.items[0]?.id).toBe("wf-run-1")
  })

  test("creates a workflow run with question, files and conversation", async () => {
    let body = ""
    fetchHandler = (url, init) => {
      body = String(init?.body ?? "")
      return jsonResponse(workflowRun(), 201)
    }

    await createPublicWorkflowRun("wf-1", "token", "问题", "conv-1", ["f1"])

    expect(JSON.parse(body)).toEqual({
      question: "问题",
      file_ids: ["f1"],
      conversation_id: "conv-1",
    })
  })

  test("uploads workflow files as multipart form data", async () => {
    const requests: Array<{ url: string; body: unknown }> = []
    fetchHandler = (url, init) => {
      requests.push({ url, body: init?.body })
      return jsonResponse(
        [
          {
            id: "wf-f1",
            filename: "b.pdf",
            content_type: "application/pdf",
            size_bytes: 2,
            category: "document",
          },
        ],
        201
      )
    }
    const file = new File(["y"], "b.pdf", { type: "application/pdf" })

    const uploaded = await uploadPublicWorkflowFiles("wf-1", "token", [file])

    expect(requests[0]?.url).toContain("/uploads")
    expect((requests[0]?.body as FormData).getAll("files")).toHaveLength(1)
    expect(uploaded[0]?.id).toBe("wf-f1")
  })

  test("submits a pending workflow form", async () => {
    let body = ""
    fetchHandler = (url, init) => {
      body = String(init?.body ?? "")
      return jsonResponse(workflowRun())
    }

    await submitPublicWorkflowForm("wf-1", "token", "run-1", "node-2", {
      answer: "42",
    })

    expect(JSON.parse(body)).toEqual({
      runtime_node_id: "node-2",
      form_data: { answer: "42" },
    })
  })

  test("observes a workflow run stream with authorization", async () => {
    const requests: Array<{ url: string; auth: string | null }> = []
    fetchHandler = (url, init) => {
      requests.push({
        url,
        auth: new Headers(init?.headers).get("Authorization"),
      })
      return new Response(
        `${JSON.stringify({
          type: "complete",
          sequence: 1,
          run: workflowRun(),
        })}\n`
      )
    }

    const events: string[] = []
    await observePublicWorkflowRun("wf-1", "token", "wf-run-1", (event) =>
      events.push(event.type)
    )

    expect(events).toEqual(["complete"])
    expect(requests[0]?.url).toContain("/runs/wf-run-1/stream?after=0")
    expect(requests[0]?.auth).toBe("Bearer token")
  })

  test("fetches workflow API documentation with an API key", async () => {
    let auth = ""
    fetchHandler = (url, init) => {
      auth = new Headers(init?.headers).get("Authorization") ?? ""
      return jsonResponse({
        workflow_id: "wf-1",
        workflow_name: "公开流程",
        base_path: "/api/v1/workflow-api/wf-1",
        interaction_config: workflowProfile().interaction_config,
      })
    }

    await getWorkflowApiDocumentation("wf-1", "nxf_key")

    expect(auth).toBe("Bearer nxf_key")
  })
})

// ---------------------------------------------------------------------------
// run-stream edge cases
// ---------------------------------------------------------------------------

describe("observeNdjsonStream edge cases", () => {
  test("backs off retryable failures and completes", async () => {
    const delays: number[] = []
    globalThis.setTimeout = ((callback: () => void, delay?: number) => {
      delays.push(delay ?? 0)
      queueMicrotask(callback)
      return 1
    }) as typeof setTimeout
    let streamCalls = 0
    fetchHandler = (url) => {
      if (!url.includes("/stream")) return jsonResponse({})
      streamCalls += 1
      if (streamCalls < 3) return new Response("", { status: 503 })
      return new Response(
        `${JSON.stringify({ type: "complete", sequence: 1, run: workflowRun() })}\n`
      )
    }

    await observePublicWorkflowRun("wf-1", "token", "wf-run-1", () => {})

    expect(delays).toEqual([250, 500])
  })

  test("rejects on non-retryable stream responses", async () => {
    fetchHandler = () => new Response("", { status: 403 })

    try {
      await observePublicAgentRun("agent-1", "token", "run-1", () => {})
      throw new Error("observePublicAgentRun should reject")
    } catch (error) {
      expect((error as Error).message).toContain("status 403")
    }
  })

  test("rejects immediately when the signal aborts during a retry wait", async () => {
    const controller = new AbortController()
    let callCount = 0
    fetchHandler = () => {
      callCount += 1
      if (callCount === 1) {
        setTimeout(() => controller.abort(), 5)
      }
      return new Response("", { status: 503 })
    }

    await expect(
      observePublicAgentRun("agent-1", "token", "run-1", () => {}, controller.signal)
    ).rejects.toThrow(/abort/i)
  })

  test("rejects when the signal is already aborted on retry", async () => {
    const controller = new AbortController()
    fetchHandler = () => {
      controller.abort()
      return new Response("", { status: 503 })
    }

    await expect(
      observePublicAgentRun("agent-1", "token", "run-1", () => {}, controller.signal)
    ).rejects.toThrow(/abort/i)
  })

  test("rejects when the stream response has no body", async () => {
    const controller = new AbortController()
    fetchHandler = () => {
      controller.abort()
      return new Response(null, { status: 200 })
    }

    await expect(
      observePublicWorkflowRun("wf-1", "token", "wf-run-1", () => {}, controller.signal)
    ).rejects.toThrow(/abort/i)
  })

  test("rejects on an invalid JSON line", async () => {
    const controller = new AbortController()
    fetchHandler = () => {
      controller.abort()
      return new Response("not-json\n", { status: 200 })
    }

    await expect(
      observePublicAgentRun("agent-1", "token", "run-1", () => {}, controller.signal)
    ).rejects.toThrow(/abort/i)
  })

  test("tolerates a truncated final NDJSON line", async () => {
    const urls: string[] = []
    const events: string[] = []
    let streamCalls = 0
    fetchHandler = (url) => {
      urls.push(url)
      streamCalls += 1
      if (streamCalls === 1) {
        return new Response(
          `${JSON.stringify({
            type: "answer_delta",
            sequence: 3,
            live_sequence: "1700000000000-0",
            node_id: "n1",
            delta: "部分",
          })}\n{`
        )
      }
      return new Response(
        `${JSON.stringify({ type: "complete", sequence: 4, run: workflowRun() })}\n`
      )
    }

    await observePublicWorkflowRun("wf-1", "token", "wf-run-1", (event) =>
      events.push(event.type)
    )

    expect(events).toEqual(["answer_delta", "complete"])
    expect(urls[1]).toContain("after=3")
    expect(urls[1]).toContain("live_after=1700000000000-0")
  })
})

// ---------------------------------------------------------------------------
// public-agent-chat pure helpers
// ---------------------------------------------------------------------------

describe("public-agent-chat helpers", () => {
  test("derives tool names and expandability", () => {
    expect(
      publicToolName({
        id: "t1",
        type: "tool",
        status: "succeeded",
        stage: "succeeded",
        turn: 1,
        count: null,
        tool_label: "Web search",
        tool_name: "web_search",
        hits: [],
      })
    ).toBe("Web search")
    expect(
      publicToolName({
        id: "t2",
        type: "tool",
        status: "succeeded",
        stage: "succeeded",
        turn: 1,
        count: null,
        tool_name: "web_search",
        hits: [],
      })
    ).toBe("web_search")
    expect(
      publicToolName(
        {
          id: "t3",
          type: "tool",
          status: "succeeded",
          stage: "succeeded",
          turn: 1,
          count: null,
          tool_label: "Create document or page",
          tool_name: "create_artifact",
          hits: [],
        },
        t
      )
    ).toBe("创建文件")
    expect(
      hasPublicToolDetails({
        id: "k1",
        type: "knowledge",
        status: "succeeded",
        stage: "succeeded",
        turn: 1,
        count: null,
        hits: [],
      })
    ).toBe(true)
    expect(
      hasPublicToolDetails({
        id: "k2",
        type: "knowledge",
        status: "running",
        stage: "running",
        turn: 1,
        count: null,
        hits: [],
      })
    ).toBe(false)
    expect(
      hasPublicToolDetails({
        id: "t3",
        type: "tool",
        status: "succeeded",
        stage: "succeeded",
        turn: 1,
        count: null,
        input: {},
        output: null,
        hits: [],
      })
    ).toBe(false)
  })

  test("merges a run snapshot over the placeholder", () => {
    const placeholder = run({
      id: "pending-1",
      status: "running",
      result: "",
      progress: [knowledgeEvent("k1", "running")],
    })
    const merged = mergePublicRunEvent(
      [placeholder],
      "run-1",
      {
        type: "run",
        sequence: 0,
        run: run({ id: "run-1", status: "running", result: "开场", progress: [] }),
      },
      "pending-1"
    )[0]

    expect(merged.id).toBe("run-1")
    expect(merged.result).toBe("开场")
    // Progress is kept from the placeholder until the snapshot supplies one.
    expect(merged.progress).toHaveLength(1)
    expect(merged.live_stream_epoch).toBeUndefined()
  })

  test("keeps only the matching run on approval_required", () => {
    const other = run({ id: "run-2", status: "running" })
    const target = run({ id: "run-1", status: "running" })
    const merged = mergePublicRunEvent(
      [other, target],
      "run-1",
      { type: "approval_required", call_id: "call-1", reason: "确认" },
      "pending-1"
    )

    expect(merged[0]?.status).toBe("running")
    expect(merged[1]?.status).toBe("awaiting_approval")
  })

  test("leaves unrelated runs untouched for terminal events", () => {
    const merged = mergePublicRunEvent(
      [run({ id: "run-1", status: "running" })],
      "run-1",
      {
        type: "complete",
        sequence: 1,
        run: run({ id: "run-9", status: "succeeded" }),
      },
      "pending-1"
    )[0]

    expect(merged.id).toBe("run-1")
    expect(merged.status).toBe("running")
  })

  test("keeps non-matching runs when a run snapshot arrives", () => {
    const placeholder = run({ id: "pending-1", status: "running", result: "" })
    const other = run({ id: "run-2", status: "running" })
    const merged = mergePublicRunEvent(
      [placeholder, other],
      "run-1",
      {
        type: "run",
        sequence: 0,
        run: run({ id: "run-1", status: "running", result: "开场" }),
      },
      "pending-1"
    )

    expect(merged[0]?.id).toBe("run-1")
    expect(merged[1]?.id).toBe("run-2")
    expect(merged[1]?.status).toBe("running")
  })

  test("moves answer reasoning off the analysis progress", () => {
    const base = run({
      id: "run-1",
      status: "running",
      result: "",
      progress: [
        {
          id: "analysis-1",
          type: "analysis",
          status: "running",
          stage: "analyzing",
          turn: 1,
          count: null,
          reasoning: "思考中",
          hits: [],
        },
      ],
    })
    const merged = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "progress",
        sequence: 1,
        event: {
          id: "answer-1",
          type: "answer",
          status: "succeeded",
          stage: "succeeded",
          turn: 1,
          count: null,
          reasoning: "思考中",
          hits: [],
        },
      },
      "pending-1"
    )[0]

    expect(merged.progress).toHaveLength(2)
    expect(merged.progress[0]).toMatchObject({
      type: "analysis",
      reasoning: "",
    })
    expect(merged.progress[1]).toMatchObject({
      type: "answer",
      reasoning: "思考中",
    })
  })

  test("ignores stale reasoning deltas and unrelated answer deltas", () => {
    const base = run({
      id: "run-1",
      status: "running",
      result: "Hello",
      live_stream_epoch: "worker-1",
      live_stream_cursor: "1700000000000-1",
    })
    const other = run({ id: "run-2", status: "running", result: "Keep" })

    const staleReasoning = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "reasoning_delta",
        stream_epoch: "worker-1",
        live_sequence: "1700000000000-1",
        turn: 1,
        delta: " old",
      },
      "pending-1"
    )[0]
    expect(staleReasoning.result).toBe("Hello")
    expect(staleReasoning.progress).toEqual([])

    const merged = mergePublicRunEvent(
      [base, other],
      "run-1",
      {
        type: "answer_delta",
        stream_epoch: "worker-1",
        live_sequence: "1700000000000-1",
        delta: " dup",
      },
      "pending-1"
    )
    expect(merged[0]?.result).toBe("Hello")
    expect(merged[1]?.result).toBe("Keep")
  })

  test("ignores stale answer deltas and resets text on worker takeover", () => {
    const base = run({
      id: "run-1",
      status: "running",
      result: "Hello",
      live_stream_epoch: "worker-1",
      live_stream_cursor: "1700000000000-1",
    })
    const stale = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "answer_delta",
        stream_epoch: "worker-1",
        live_sequence: "1700000000000-1",
        delta: " dup",
      },
      "pending-1"
    )[0]
    expect(stale.result).toBe("Hello")

    const takenOver = mergePublicRunEvent(
      [base],
      "run-1",
      {
        type: "answer_delta",
        stream_epoch: "worker-2",
        live_sequence: "1700000000001-0",
        delta: "New",
      },
      "pending-1"
    )[0]
    expect(takenOver.result).toBe("New")
    expect(takenOver.live_stream_epoch).toBe("worker-2")
    expect(takenOver.live_stream_cursor).toBe("1700000000001-0")

    const reset = mergePublicRunEvent(
      [takenOver],
      "run-1",
      {
        type: "answer_reset",
        stream_epoch: "worker-2",
        live_sequence: "1700000000002-0",
      },
      "pending-1"
    )[0]
    expect(reset.result).toBe("")
    expect(reset.live_stream_cursor).toBe("1700000000002-0")
  })

  test("cancels the active public stream", () => {
    const controller = new AbortController()
    const ref = { current: controller }

    cancelPublicAgentStream(ref)

    expect(ref.current).toBeNull()
    expect(controller.signal.aborted).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// PublicAgentChat DOM
// ---------------------------------------------------------------------------

describe("PublicWorkflowChat", () => {
  test("switches conversations without remounting the public chat page", async () => {
    const testWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void }
    }
    testWindow.happyDOM.setURL("https://nexaflow.example/chat/wf-1")
    const workflowConversation = (conversationId: string, question: string) => ({
      conversation_id: conversationId,
      inputs: { question },
      outputs: {},
      status: "succeeded",
      run_count: 1,
      created_at: "2026-08-10T00:00:00Z",
      updated_at: "2026-08-10T00:00:01Z",
    })
    fetchHandler = (url) => {
      if (url.endsWith("/profile")) return jsonResponse(workflowProfile())
      if (url.includes("/conversations")) {
        return jsonResponse({
          items: [
            workflowConversation("conv-1", "第一个流程"),
            workflowConversation("conv-2", "第二个流程"),
          ],
        })
      }
      if (url.includes("/runs?")) return jsonResponse({ items: [] })
      return jsonResponse({})
    }

    renderPage(<PublicWorkflowChat workflowId="wf-1" />)
    expect(await screen.findByRole("heading", { name: "公开流程" })).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: /第二个流程/ }))

    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: /第二个流程/ })
          .getAttribute("aria-current")
      ).toBe("page")
    )
    expect(new URLSearchParams(window.location.search).get("conversation_id")).toBe(
      "conv-2"
    )
    expect(replaced).toEqual([])
  })
})

describe("PublicAgentChat", () => {
  test("shows the loading state while the profile loads", () => {
    fetchHandler = () => new Promise<Response>(() => {})

    renderPage(<PublicAgentChat agentId="agent-1" />)

    expect(screen.getByText("正在加载")).toBeTruthy()
  })

  test("shows a fatal error when the agent is unavailable", async () => {
    fetchHandler = (url) =>
      url.includes("/profile")
        ? jsonResponse({ detail: "not found" }, 404)
        : jsonResponse({})

    renderPage(<PublicAgentChat agentId="agent-1" />)

    expect(await screen.findByText("无法打开公开对话")).toBeTruthy()
    expect(screen.getByText("此 Agent 未发布或不可访问。")).toBeTruthy()
  })

  test("redirects to login when no session is restored", () => {
    Object.assign(session, { token: null, isSessionRestored: true })

    renderPage(<PublicAgentChat agentId="agent-1" />)

    expect(replaced).toEqual(["/login?next=%2Fchat%2Fagent-1"])
    expect(screen.getByText("正在加载")).toBeTruthy()
  })

  test("renders the empty conversation state", async () => {
    fetchHandler = agentFetchHandler({ conversations: { items: [] } })

    renderPage(<PublicAgentChat agentId="agent-1" />)

    expect(await screen.findByText("开始新对话")).toBeTruthy()
    expect(screen.getByRole("heading", { name: "公开助手" })).toBeTruthy()
    expect(screen.getAllByText("这是一个公开助手。").length).toBeGreaterThan(0)
    expect(screen.getByText("暂无历史记录")).toBeTruthy()
    expect(
      (screen.getByLabelText("发送问题") as HTMLButtonElement).disabled
    ).toBe(true)
    expect(replaced).toEqual([])
  })

  test("renders generated artifacts as filename download links", async () => {
    const downloadUrl = "/api/v1/artifacts/signed-token"
    const testWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void }
    }
    testWindow.happyDOM.setURL("https://nexaflow.example/chat/agent-1")
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "生成制度文件")] },
      history: {
        items: [
          run({
            result: `📄 下载地址：\`${downloadUrl}\``,
            progress: [
              toolEvent("artifact-1", "succeeded", {
                tool_name: "create_artifact",
                output: {
                  filename: "公司内部管理制度汇编.docx",
                  download_url: downloadUrl,
                },
              }),
            ],
          }),
        ],
        total: 1,
        offset: 0,
        limit: 200,
      },
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)

    const link = await screen.findByRole("link", {
      name: "公司内部管理制度汇编.docx",
    })
    expect(link.getAttribute("href")).toBe(downloadUrl)
    expect(link.className).toContain("text-sky-600")
    expect(link.hasAttribute("download")).toBe(true)
    expect(link.getAttribute("target")).toBeNull()
    expect(screen.queryByText(downloadUrl)).toBeNull()
  })

  test("renders history runs, selects conversations, and starts fresh", async () => {
    const testWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void }
    }
    testWindow.happyDOM.setURL("https://nexaflow.example/chat/agent-1")
    const historyByConversation: Record<string, ExternalAgentRun[]> = {
      "conv-1": [
        run({
          id: "r-md",
          question: "第一个问题",
          result: "## 历史回答\n列表",
        }),
        run({
          id: "r-fail",
          question: "失败问题",
          status: "failed",
          result: "",
          error: "历史失败",
        }),
        run({
          id: "r-cancel",
          question: "取消问题",
          status: "cancelled",
          result: "",
        }),
        run({
          id: "r-queued",
          question: "排队问题",
          status: "queued",
          result: "",
        }),
        run({
          id: "r-running",
          question: "进行中问题",
          status: "running",
          result: "",
        }),
        run({
          id: "r-ans",
          question: "回答阶段",
          result: "",
          status: "succeeded",
          progress: [
            {
              id: "ans-1",
              type: "answer",
              status: "succeeded",
              stage: "succeeded",
              turn: 1,
              count: null,
              hits: [],
            },
            knowledgeEvent("k-h", "succeeded", { count: 1 }),
          ],
        }),
      ],
      "conv-2": [
        run({
          id: "r2",
          question: "第二个会话的问题",
          result: "第二回答",
        }),
      ],
    }
    fetchHandler = (url, init) => {
      if (url.endsWith("/profile")) return jsonResponse(PROFILE)
      if (url.includes("/conversations")) {
        return jsonResponse({
          items: [conversation("conv-1", "第一个会话"), conversation("conv-2", "第二个会话")],
        })
      }
      if (url.includes("/runs") && (init?.method ?? "GET") === "GET") {
        const conversationId = new URL(url, "http://localhost").searchParams.get(
          "conversation_id"
        )
        return jsonResponse({
          items: historyByConversation[conversationId ?? ""] ?? [],
          total: 0,
          offset: 0,
          limit: 200,
        })
      }
      return jsonResponse({})
    }

    renderPage(<PublicAgentChat agentId="agent-1" />)

    expect(await screen.findByRole("heading", { name: "历史回答" })).toBeTruthy()
    expect(screen.getByText("列表")).toBeTruthy()
    expect(screen.getByText("历史失败")).toBeTruthy()
    expect(screen.getByText("运行已取消")).toBeTruthy()
    expect(screen.getByText("等待执行")).toBeTruthy()
    // Every run without progress shows the generating hint (queued excepted).
    expect(screen.getAllByText("正在生成回答").length).toBeGreaterThanOrEqual(1)
    // An answer-only timeline synthesizes an analysis step before it.
    expect(screen.getByText("已完成分析")).toBeTruthy()
    expect(screen.getByText("回答已生成")).toBeTruthy()
    expect(new URLSearchParams(window.location.search).get("conversation_id")).toBe(
      "conv-1"
    )
    const currentConversationButton = screen
      .getByText("第一个会话")
      .closest("button")!
    expect(currentConversationButton.getAttribute("aria-current")).toBe("page")

    // Selecting the current conversation keeps its already-loaded messages.
    fireEvent.click(currentConversationButton)
    expect(Boolean(screen.queryByText("正在加载"))).toBe(false)
    expect(screen.getByText("第一个问题")).toBeTruthy()

    // Switch to the second conversation.
    fireEvent.click(screen.getByRole("button", { name: /第二个会话/ }))
    expect(await screen.findByText("第二个会话的问题")).toBeTruthy()
    expect(screen.queryByText("第一个问题")).toBeNull()
    expect(new URLSearchParams(window.location.search).get("conversation_id")).toBe(
      "conv-2"
    )

    // Start a brand-new conversation.
    fireEvent.click(screen.getByTitle("新建对话"))
    expect(await screen.findByText("开始新对话")).toBeTruthy()
    expect(window.location.pathname).toBe("/chat/agent-1")
    expect(window.location.search).toBe("")
  })

  test("streams a full run and renders the execution timeline", async () => {
    const requests: string[] = []
    const createBodies: Array<Record<string, unknown>> = []
    fetchHandler = agentFetchHandler(
      {
        conversations: { items: [conversation("conv-1", "第一个会话")] },
        history: { items: [], total: 0, offset: 0, limit: 200 },
        createRun: (body) => {
          createBodies.push(body)
          return jsonResponse(
            run({
              status: "running",
              question: String(body.goal),
              result: "",
            }),
            201
          )
        },
        streamResponses: [
          () =>
            ndjsonResponse([
              { type: "run", sequence: 0, run: run({ status: "running", question: "什么是 NexaFlow？", result: "" }) },
              {
                type: "reasoning_delta",
                turn: 1,
                delta: "让我想想",
                stream_epoch: "w1",
                live_sequence: "1-0",
              },
              {
                type: "reasoning_delta",
                turn: 1,
                delta: "\n继续想",
                stream_epoch: "w1",
                live_sequence: "2-0",
              },
              { type: "progress", sequence: 1, event: knowledgeEvent("k1", "running") },
              { type: "progress", sequence: 2, event: knowledgeEvent("k2", "succeeded", { count: 2, hits: [{ knowledge_base: "kb-1", document: "doc-1", content: "片段内容" }] }) },
              { type: "progress", sequence: 3, event: knowledgeEvent("k3", "succeeded", { count: 0 }) },
              { type: "progress", sequence: 4, event: toolEvent("t1", "running", { tool_name: "search", tool_label: "Search", tool_kind: "mcp", server_name: "Tavily", input: { q: "x" } }) },
              { type: "progress", sequence: 5, event: toolEvent("t2", "succeeded", { tool_name: "web_search", tool_label: "Web search", tool_kind: "mcp", server_name: "Tavily", input: { query: "NexaFlow" }, output: { results: ["r1"] }, input_truncated: true }) },
              { type: "progress", sequence: 6, event: toolEvent("f1", "failed", { tool_name: "db_query", tool_label: "DB Query" }) },
              { type: "progress", sequence: 7, event: toolEvent("g1", "succeeded") },
              { type: "progress", sequence: 8, event: { id: "a1", type: "answer", status: "running", stage: "analyzing", turn: 1, count: null, hits: [] } },
              { type: "progress", sequence: 9, event: { id: "a2", type: "answer", status: "succeeded", stage: "succeeded", turn: 1, count: null, hits: [] } },
              { type: "answer_delta", delta: "## 回答标题\n**加粗**内容", stream_epoch: "w1", live_sequence: "3-0" },
              {
                type: "complete",
                sequence: 10,
                run: run({
                  status: "succeeded",
                  question: "什么是 NexaFlow？",
                  result: "## 回答标题\n**加粗**内容",
                  progress: FULL_PROGRESS,
                }),
              },
            ]),
        ],
      },
      requests
    )

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    sendMessage("什么是 NexaFlow？")

    expect(await screen.findByRole("heading", { name: "回答标题" })).toBeTruthy()
    expect(screen.getByText("加粗")).toBeTruthy()
    expect(screen.getByText(/让我想想/)).toBeTruthy()
    expect(screen.getByText("正在分析问题")).toBeTruthy()
    expect(screen.getByText("正在整理工具结果")).toBeTruthy()
    expect(screen.getByText("已完成分析")).toBeTruthy()
    expect(screen.getByText("正在准备工具调用")).toBeTruthy()
    expect(screen.getByText("正在调用 知识库检索")).toBeTruthy()
    expect(screen.getByText("已检索 2 个知识片段")).toBeTruthy()
    expect(screen.getByText("已检索 0 个知识片段")).toBeTruthy()
    expect(screen.getByText("Search")).toBeTruthy()
    expect(screen.getByText("正在调用 Search")).toBeTruthy()
    expect(screen.getByText("Web search")).toBeTruthy()
    expect(screen.getAllByText("完成").length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText("调用失败")).toBeTruthy()
    expect(screen.getByText("DB Query")).toBeTruthy()
    expect(screen.getByText("工具")).toBeTruthy()
    expect(screen.getByText("正在生成回答")).toBeTruthy()
    expect(screen.getByText("回答已生成")).toBeTruthy()
    expect(screen.getByText("什么是 NexaFlow？")).toBeTruthy()
    expect(
      (screen.getByLabelText("请输入问题") as HTMLTextAreaElement).value
    ).toBe("")
    expect(screen.getAllByTitle("复制").length).toBe(2)

    // Expand the successful knowledge row to reveal its hits.
    fireEvent.click(
      screen.getByRole("button", { name: /已检索 2 个知识片段/ })
    )
    expect(screen.getByText("doc-1")).toBeTruthy()
    expect(screen.getByText("kb-1")).toBeTruthy()
    expect(screen.getByText("片段内容")).toBeTruthy()

    // Expand the empty knowledge row.
    fireEvent.click(
      screen.getByRole("button", { name: /已检索 0 个知识片段/ })
    )
    expect(screen.getByText("未检索到相关知识片段")).toBeTruthy()

    // Expand the succeeded tool row to reveal input and output.
    fireEvent.click(screen.getByRole("button", { name: /Web search/ }))
    expect(screen.getByText("调用输入")).toBeTruthy()
    expect(screen.getByText(/内容过长已截断/)).toBeTruthy()
    expect(screen.getByText(/query/)).toBeTruthy()
    expect(screen.getByText(/r1/)).toBeTruthy()

    // A tool row without input or output is not expandable.
    expect(screen.queryByRole("button", { name: /^工具$/ })).toBeNull()

    // Reasoning box follows its own scroll.
    fireEvent.scroll(screen.getByText(/让我想想/), {
      target: { scrollTop: 200 },
    })

    // The execution process can be collapsed.
    fireEvent.click(screen.getByText("执行过程"))
    expect(
      (screen.getByText("执行过程").closest("details") as HTMLDetailsElement)
        .open
    ).toBe(false)

    // The create request carried the goal and conversation.
    expect(createBodies[0]).toEqual({
      goal: "什么是 NexaFlow？",
      conversation_id: "conv-1",
    })
    expect(
      requests.some((request) => request.startsWith("POST") && request.includes("/runs"))
    ).toBe(true)
    expect(requests.some((request) => request.includes("/stream?after=0&live_after=0-0"))).toBe(true)
  })

  test("starts a conversation from the empty state and records the new id", async () => {
    const testWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void }
    }
    testWindow.happyDOM.setURL("https://nexaflow.example/chat/agent-1")
    const createBodies: Array<Record<string, unknown>> = []
    fetchHandler = agentFetchHandler({
      conversations: { items: [] },
      history: () =>
        jsonResponse({
          items: [
            run({
              id: "run-new",
              conversation_id: "conv-new",
              question: "开始吧",
              status: "succeeded",
              result: "新会话回答",
            }),
          ],
          total: 1,
          offset: 0,
          limit: 200,
        }),
      createRun: (body) => {
        createBodies.push(body)
        return jsonResponse(
          run({
            id: "run-new",
            conversation_id: "conv-new",
            status: "running",
            question: String(body.goal),
            result: "",
          }),
          201
        )
      },
      streamResponses: [
        () =>
          ndjsonResponse([
            {
              type: "run",
              sequence: 0,
              run: run({
                id: "run-new",
                conversation_id: "conv-new",
                status: "running",
                result: "",
              }),
            },
            {
              type: "complete",
              sequence: 1,
              run: run({
                id: "run-new",
                conversation_id: "conv-new",
                status: "succeeded",
                result: "新会话回答",
              }),
            },
          ]),
      ],
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    sendMessage("开始吧")

    expect(await screen.findByText("新会话回答")).toBeTruthy()
    expect(createBodies[0]).toEqual({ goal: "开始吧" })
    expect(new URLSearchParams(window.location.search).get("conversation_id")).toBe(
      "conv-new"
    )
  })

  test("surfaces stream errors in the alert and the run bubble", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      streamResponses: [
        () =>
          ndjsonResponse([
            { type: "run", sequence: 0, run: run({ status: "running", result: "" }) },
            { type: "error", sequence: 1, run: run({ status: "failed", result: "", error: "模型超时" }) },
          ]),
      ],
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    sendMessage("会失败的请求")

    await waitFor(() =>
      expect(screen.getAllByText("模型超时").length).toBeGreaterThanOrEqual(2)
    )
    expect(screen.getByRole("alert")).toBeTruthy()
  })

  test("shows an error and a failed bubble when creating the run fails", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [run({ result: "历史内容" })],
        total: 1,
        offset: 0,
        limit: 200,
      },
      createRun: () => jsonResponse({ detail: "创建失败" }, 500),
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("历史内容")

    sendMessage("无法创建")

    await waitFor(() =>
      expect(screen.getAllByText("创建失败").length).toBeGreaterThanOrEqual(2)
    )
    expect(screen.getByRole("alert")).toBeTruthy()
    // Earlier history is untouched by the failed send.
    expect(screen.getByText("历史内容")).toBeTruthy()
    // The send button returns to its idle state after the failure.
    expect(screen.queryByLabelText("停止生成")).toBeNull()
  })

  test("cancels a running generation", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [] },
      createRun: () => jsonResponse(run({ status: "running", result: "" }), 201),
      streamResponses: [() => new Promise<Response>(() => {})],
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    sendMessage("慢慢来")

    expect(await screen.findByLabelText("停止生成")).toBeTruthy()
    fireEvent.click(screen.getByLabelText("停止生成"))

    await waitFor(() =>
      expect(screen.getByLabelText("发送问题")).toBeTruthy()
    )
    expect(
      (screen.getByLabelText("请输入问题") as HTMLTextAreaElement).disabled
    ).toBe(false)
  })

  test("approves a tool call and resumes observing the run", async () => {
    const requests: string[] = []
    let approved = false
    fetchHandler = agentFetchHandler(
      {
        conversations: { items: [] },
        // After the stream ends, the conversation is refreshed from history,
        // which still shows the run awaiting approval.
        history: () =>
          jsonResponse({
            items: [
              run({ id: "run-1", status: "awaiting_approval", result: "" }),
              run({ id: "run-2", status: "succeeded", result: "并行回答" }),
            ],
            total: 2,
            offset: 0,
            limit: 200,
          }),
        createRun: (body) =>
          jsonResponse(
            run({ status: "running", question: String(body.goal), result: "" }),
            201
          ),
        streamResponses: [
          () =>
            ndjsonResponse([
              { type: "run", sequence: 0, run: run({ status: "running", result: "" }) },
              { type: "approval_required", call_id: "call-1", reason: "需要确认" },
              { type: "complete", sequence: 1, run: run({ status: "awaiting_approval", result: "" }) },
            ]),
          () =>
            ndjsonResponse([
              {
                type: "approval_required",
                call_id: "call-1",
                reason: "再次确认",
              },
              {
                type: "answer_delta",
                delta: "批准后的回答",
                stream_epoch: "w1",
                live_sequence: "1-0",
              },
              {
                type: "complete",
                sequence: 2,
                run: run({ status: "succeeded", result: "批准后的回答" }),
              },
            ]),
        ],
        toolCalls: () => jsonResponse(approved ? [] : [TOOL_CALL]),
        resolveRun: () => {
          approved = true
          const { promise, resolve } = Promise.withResolvers<Response>()
          setTimeout(
            () => resolve(jsonResponse(run({ status: "running", result: "" }))),
            30
          )
          return promise
        },
      },
      requests
    )

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    sendMessage("需要审批的任务")

    expect(await screen.findByText("工具调用需要确认")).toBeTruthy()
    expect(screen.getByText(/web_search/)).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "批准并执行" }))

    // While resolving, the decision buttons are disabled.
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "批准并执行" }) as HTMLButtonElement)
          .disabled
      ).toBe(true)
    )

    expect(await screen.findByText("批准后的回答")).toBeTruthy()
    await waitFor(() =>
      expect(screen.queryByText("工具调用需要确认")).toBeNull()
    )
    expect(
      requests.some((request) => request.includes("/tool-calls/call-1/approve"))
    ).toBe(true)
  })

  test("rejects a tool call and reports resolve failures", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [] },
      history: () =>
        jsonResponse({
          items: [run({ id: "run-1", status: "awaiting_approval", result: "" })],
          total: 1,
          offset: 0,
          limit: 200,
        }),
      streamResponses: [
        () =>
          ndjsonResponse([
            { type: "run", sequence: 0, run: run({ status: "running", result: "" }) },
            { type: "approval_required", call_id: "call-1", reason: "需要确认" },
            { type: "complete", sequence: 1, run: run({ status: "awaiting_approval", result: "" }) },
          ]),
      ],
      toolCalls: () => jsonResponse([TOOL_CALL]),
      resolveRun: () => jsonResponse({ detail: "拒绝失败" }, 500),
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    sendMessage("拒绝这个工具")

    expect(await screen.findByText("工具调用需要确认")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }))

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("拒绝失败")
    )
  })

  test("reports failures while observing a resumed run", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({ id: "run-paused", status: "awaiting_approval", result: "" }),
        ],
        total: 1,
        offset: 0,
        limit: 200,
      },
      toolCalls: () => jsonResponse([TOOL_CALL]),
      resolveRun: () => jsonResponse(run({ status: "running", result: "" })),
      streamResponses: [() => new Response("", { status: 403 })],
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    expect(await screen.findByText("工具调用需要确认")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "批准并执行" }))

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("status 403")
    )
  })

  test("surfaces stream errors emitted while observing a resumed run", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({ id: "run-paused", status: "awaiting_approval", result: "" }),
        ],
        total: 1,
        offset: 0,
        limit: 200,
      },
      toolCalls: () => jsonResponse([TOOL_CALL]),
      resolveRun: () =>
        jsonResponse(run({ id: "run-paused", status: "running", result: "" })),
      streamResponses: [
        () =>
          ndjsonResponse([
            {
              type: "run",
              sequence: 0,
              run: run({ id: "run-paused", status: "running", result: "" }),
            },
            {
              type: "error",
              sequence: 1,
              run: run({
                id: "run-paused",
                status: "failed",
                result: "",
                error: "观察到的错误",
              }),
            },
          ]),
      ],
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    expect(await screen.findByText("工具调用需要确认")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "批准并执行" }))

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("观察到的错误")
    )
  })

  test("falls back to a generic message for error events without details", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({ id: "run-paused", status: "awaiting_approval", result: "" }),
        ],
        total: 1,
        offset: 0,
        limit: 200,
      },
      toolCalls: () => jsonResponse([TOOL_CALL]),
      resolveRun: () =>
        jsonResponse(run({ id: "run-paused", status: "running", result: "" })),
      streamResponses: [
        () =>
          ndjsonResponse([
            {
              type: "run",
              sequence: 0,
              run: run({ id: "run-paused", status: "running", result: "" }),
            },
            {
              type: "error",
              sequence: 1,
              run: run({ id: "run-paused", status: "failed", result: "" }),
            },
          ]),
      ],
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    expect(await screen.findByText("工具调用需要确认")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "批准并执行" }))

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "回答失败，请稍后重试。"
      )
    )
  })

  test("reports attachment upload failures without creating a run", async () => {
    const requests: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      requests.push(`${method} ${url}`)
      if (url.endsWith("/profile")) return jsonResponse(PROFILE)
      if (url.includes("/conversations")) {
        return jsonResponse({
          items: [conversation("conv-1", "第一个会话")],
        })
      }
      if (url.includes("/uploads")) {
        return jsonResponse({ detail: "文件上传失败" }, 500)
      }
      if (url.includes("/runs") && method === "GET") {
        return jsonResponse({
          items: [
            run({
              id: "run-1",
              conversation_id: "conv-1",
              status: "succeeded",
              result: "历史回答",
            }),
          ],
          total: 1,
          offset: 0,
          limit: 200,
        })
      }
      return jsonResponse({})
    }

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("历史回答")

    const fileInput = document.querySelector('input[type="file"]')
    fireEvent.change(fileInput as HTMLInputElement, {
      target: { files: [new File(["x"], "broken.txt", { type: "text/plain" })] },
    })
    sendMessage("带附件发送")

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("文件上传失败")
    )
    // The failed upload aborts the send before any run is created.
    expect(
      requests.some(
        (request) => request.startsWith("POST") && request.includes("/runs")
      )
    ).toBe(false)
    expect(screen.queryByLabelText("停止生成")).toBeNull()
  })

  test("shows an error when loading history fails", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: () => jsonResponse({ detail: "历史加载失败" }, 500),
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("历史加载失败")
    )
    expect(screen.getByText("开始新对话")).toBeTruthy()
  })

  test("loads tool calls for paused runs from history and ignores failures", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [
          run({
            id: "run-paused",
            status: "awaiting_approval",
            result: "",
            progress: [],
          }),
        ],
        total: 1,
        offset: 0,
        limit: 200,
      },
      toolCalls: () => jsonResponse({ detail: "boom" }, 500),
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)

    // A failed tool-call fetch is silent: no approval card, no error banner.
    expect(await screen.findByText("你好")).toBeTruthy()
    expect(screen.queryByText("工具调用需要确认")).toBeNull()
    expect(screen.queryByRole("alert")).toBeNull()
  })

  test("uploads attachments and sends their file ids", async () => {
    const requests: string[] = []
    const createBodies: Array<Record<string, unknown>> = []
    fetchHandler = agentFetchHandler(
      {
        conversations: { items: [] },
        history: () =>
          jsonResponse({
            items: [
              run({
                id: "run-1",
                conversation_id: "conv-1",
                status: "succeeded",
                result: "已处理附件",
              }),
            ],
            total: 1,
            offset: 0,
            limit: 200,
          }),
        createRun: (body) => {
          createBodies.push(body)
          return jsonResponse(
            run({ status: "running", question: String(body.goal), result: "" }),
            201
          )
        },
        streamResponses: [
          () =>
            ndjsonResponse([
              { type: "run", sequence: 0, run: run({ status: "running", result: "" }) },
              { type: "complete", sequence: 1, run: run({ status: "succeeded", result: "已处理附件" }) },
            ]),
        ],
        uploads: [
          {
            id: "f1",
            filename: "notes.md",
            content_type: "text/markdown",
            size_bytes: 9,
            category: "document",
          },
        ],
      },
      requests
    )

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    const fileInput = document.querySelector('input[type="file"]')
    const file = new File(["# 标题"], "notes.md", { type: "text/markdown" })
    fireEvent.click(screen.getByLabelText("添加附件"))
    fireEvent.change(fileInput as HTMLInputElement, {
      target: { files: [file] },
    })
    expect(screen.getByText("notes.md")).toBeTruthy()

    sendMessage("带上附件")

    expect(await screen.findByText("已处理附件")).toBeTruthy()
    await waitFor(() => expect(screen.queryByText("notes.md")).toBeNull())
    expect(requests.some((request) => request.startsWith("POST") && request.includes("/uploads"))).toBe(true)
    expect(createBodies[0]?.file_ids).toEqual(["f1"])
  })

  test("removes an attachment before sending", async () => {
    const requests: string[] = []
    fetchHandler = agentFetchHandler(
      {
        conversations: { items: [] },
        history: () =>
          jsonResponse({
            items: [
              run({
                id: "run-1",
                conversation_id: "conv-1",
                status: "succeeded",
                result: "无附件",
              }),
            ],
            total: 1,
            offset: 0,
            limit: 200,
          }),
        streamResponses: [
          () =>
            ndjsonResponse([
              { type: "run", sequence: 0, run: run({ status: "running", result: "" }) },
              { type: "complete", sequence: 1, run: run({ status: "succeeded", result: "无附件" }) },
            ]),
        ],
      },
      requests
    )

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("开始新对话")

    const fileInput = document.querySelector('input[type="file"]')
    fireEvent.change(fileInput as HTMLInputElement, {
      target: {
        files: [new File(["x"], "draft.txt", { type: "text/plain" })],
      },
    })
    fireEvent.click(screen.getByLabelText("移除 draft.txt"))
    expect(screen.queryByText("draft.txt")).toBeNull()

    sendMessage("发送纯文本")

    expect(await screen.findByText("无附件")).toBeTruthy()
    expect(
      requests.some((request) => request.includes("/uploads"))
    ).toBe(false)
  })

  test("copies messages and reflects success or failure", async () => {
    fetchHandler = agentFetchHandler({
      conversations: { items: [conversation("conv-1", "第一个会话")] },
      history: {
        items: [run({ result: "可复制的回答" })],
        total: 1,
        offset: 0,
        limit: 200,
      },
    })

    const written: string[] = []
    let shouldReject = true
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async (value: string) => {
          if (shouldReject) throw new Error("denied")
          written.push(value)
        },
      },
      configurable: true,
    })

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("可复制的回答")

    // Failure keeps the copy label.
    const questionCopy = screen.getAllByTitle("复制")[0]
    fireEvent.click(questionCopy)
    await waitFor(() => expect(written).toEqual([]))
    expect(screen.getAllByTitle("复制").length).toBe(2)

    // Success flips the label to 已复制.
    shouldReject = false
    const resultCopy = screen.getAllByTitle("复制")[1]
    fireEvent.click(resultCopy)
    await waitFor(() => expect(written).toEqual(["可复制的回答"]))
    expect(screen.getByTitle("已复制")).toBeTruthy()
  })

  test("opens the mobile history dialog and selects a conversation", async () => {
    const testWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void }
    }
    testWindow.happyDOM.setURL("https://nexaflow.example/chat/agent-1")
    const historyByConversation: Record<string, ExternalAgentRun[]> = {
      "conv-1": [run({ result: "来自对话的记录" })],
      "conv-2": [run({ id: "run-2", question: "第二个问题", result: "第二个会话的记录" })],
    }
    fetchHandler = (url, init) => {
      if (url.endsWith("/profile")) return jsonResponse(PROFILE)
      if (url.includes("/conversations")) {
        return jsonResponse({
          items: [conversation("conv-1", "第一个会话"), conversation("conv-2", "第二个会话")],
        })
      }
      if (url.includes("/runs") && (init?.method ?? "GET") === "GET") {
        const conversationId = new URL(url, "http://localhost").searchParams.get(
          "conversation_id"
        )
        return jsonResponse({
          items: historyByConversation[conversationId ?? ""] ?? [],
          total: 0,
          offset: 0,
          limit: 200,
        })
      }
      return jsonResponse({})
    }

    renderPage(<PublicAgentChat agentId="agent-1" />)
    await screen.findByText("来自对话的记录")

    fireEvent.click(screen.getByLabelText("打开历史记录"))

    // The dialog renders in a portal; the rest of the page is aria-hidden.
    expect(await screen.findByText("选择或新建对话")).toBeTruthy()
    const dialogContent = document.querySelector(
      '[data-slot="dialog-content"]'
    ) as HTMLElement
    expect(dialogContent).toBeTruthy()

    fireEvent.click(
      within(dialogContent).getByRole("button", { name: /第二个会话/ })
    )

    expect(await screen.findByText("第二个会话的记录")).toBeTruthy()
    await waitFor(() =>
      expect(document.querySelector('[data-slot="dialog-content"]')).toBeNull()
    )
    expect(new URLSearchParams(window.location.search).get("conversation_id")).toBe(
      "conv-2"
    )
  })
})

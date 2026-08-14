/* @jsxImportSource react */
/**
 * DOM-level coverage for AgentConfigFields, InteractionConfigFields and
 * AgentPermissionsDialog.
 */
import { afterEach, describe, expect, mock, test } from "bun:test"
import { useState } from "react"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { cleanup } from "@testing-library/react"

import { AgentConfigFields } from "@/components/agents/agent-config-fields"
import { InteractionConfigFields } from "@/components/agents/interaction-config-fields"
import { AgentPermissionsDialog } from "@/components/agents/agent-permissions-dialog"
import { LanguageProvider, useLanguage } from "@/contexts/language-provider"
import type { AgentFormState } from "@/components/agents/agents-page"
import type { AgentInteractionConfig } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"

import {
  makeSession,
  mockNextImage,
  mockUseSession,
  renderPage,
} from "./helpers/dom"

const WS = "ws-1"

function model(id: string, name: string, status = "active"): RegisteredModel {
  return {
    id,
    workspace_id: WS,
    name,
    provider: "deepseek",
    provider_type: "openai",
    model_type: "LLM",
    model_name: "deepseek-chat",
    status,
    credential: {},
    api_base: "",
    has_api_key: true,
    api_key_hint: null,
    meta: {},
    created_by_user_id: "u-1",
    created_at: "",
    updated_at: "",
  }
}

function knowledgeBase(id: string, name: string, description = "知识库描述", status = "active"): KnowledgeBase {
  return {
    id,
    workspace_id: WS,
    name,
    description,
    status,
    embedding_model_id: null,
    reranker_model_id: null,
    created_by_user_id: "u-1",
    created_at: "",
    updated_at: "",
    permission: "edit",
  }
}

function mcpServer(overrides: Partial<McpServer> = {}): McpServer {
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
    created_at: "",
    updated_at: "",
    ...overrides,
  }
}

const notifyCalls: Array<{ kind: string; message: string }> = []
mockUseSession(
  makeSession({
    me: {
      user: {
        id: "u-1",
        username: "admin",
        email: "a@b.c",
        name: "Admin",
        is_global_admin: true,
        must_change_password: false,
        is_active: true,
        created_at: "",
        workspaces: [{ id: WS, name: "W", is_default: true, role: "admin" }],
        teams: [],
      },
      memberships: [{ workspace_id: WS, role: "admin" }],
    },
    notify: (kind: "success" | "error", message: string) => notifyCalls.push({ kind, message }),
  })
)
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

const models = [model("model-1", "DeepSeek Chat"), model("model-2", "Legacy Model", "disabled")]
const knowledgeBases = [
  knowledgeBase("knowledge-1", "产品文档"),
  knowledgeBase("knowledge-2", "研发纪要"),
  knowledgeBase("knowledge-3", "旧知识库", "", "disabled"),
]
const mcpServers = [mcpServer()]

function initialForm(overrides: Partial<AgentFormState> = {}): AgentFormState {
  return {
    id: "agent-1",
    appType: "agent",
    name: "Research Assistant",
    description: "Answers from knowledge",
    interactionConfig: {
      prologue: "",
      tts_type: "BROWSER",
      file_upload: false,
      file_upload_setting: { file_upload_type: ["document", "image"] },
      user_input_title: "",
    },
    modelId: "model-1",
    instructions: "Be concise.",
    knowledgeQueryMode: "required",
    knowledgeBaseIds: ["knowledge-1"],
    mcpTools: [{ server_id: "server-1", tool_name: "search" }],
    status: "active",
    ...overrides,
  }
}

function FieldsHarness({
  form: initial,
  readOnly = false,
}: {
  form: AgentFormState
  readOnly?: boolean
}) {
  const { t } = useLanguage()
  const [form, setForm] = useState(initial)
  return (
    <AgentConfigFields
      form={form}
      setForm={setForm}
      models={models}
      knowledgeBases={knowledgeBases}
      mcpServers={mcpServers}
      readOnly={readOnly}
      t={t}
    />
  )
}

function openModelMenu() {
  const trigger = screen.getByLabelText("选择模型")
  fireEvent.pointerDown(trigger)
  fireEvent.click(trigger)
}

afterEach(() => {
  cleanup()
  notifyCalls.length = 0
})

describe("AgentConfigFields", () => {
  test("edits basic fields in create mode without advanced sections", async () => {
    renderPage(<FieldsHarness form={initialForm({ id: null, name: "", modelId: "" })} />)
    const name = screen.getByLabelText("Agent 名称") as HTMLInputElement
    fireEvent.change(name, { target: { value: "New Agent" } })
    expect(name.value).toBe("New Agent")

    const description = screen.getByLabelText("描述") as HTMLTextAreaElement
    fireEvent.change(description, { target: { value: "Fresh description" } })
    expect(description.value).toBe("Fresh description")

    expect(screen.queryByText("系统提示词")).toBeNull()
    expect(screen.queryByText("关联知识库")).toBeNull()
    expect(screen.queryByText("MCP 工具")).toBeNull()
    expect(screen.queryByText("状态")).toBeNull()

    openModelMenu()
    fireEvent.click(await screen.findByRole("menuitem", { name: /DeepSeek Chat/ }))
    expect(screen.getByText("DeepSeek Chat")).toBeTruthy()
  })

  test("edits instructions and expands knowledge and MCP sections", () => {
    renderPage(<FieldsHarness form={initialForm()} />)
    const instructions = screen.getByLabelText("系统提示词") as HTMLTextAreaElement
    fireEvent.change(instructions, { target: { value: "New instructions" } })
    expect(instructions.value).toBe("New instructions")

    fireEvent.click(screen.getByText("关联知识库").closest("button")!)
    expect(screen.getByText("每次先检索（推荐）")).toBeTruthy()
    expect(screen.getByText("产品文档")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Agent 按需检索" }))
    expect(screen.getByRole("button", { name: "Agent 按需检索" }).getAttribute("aria-pressed")).toBe("true")

    fireEvent.click(screen.getByText("MCP 工具").closest("button")!)
    expect(screen.getByText("Database / search")).toBeTruthy()
  })

  test("selects and removes knowledge bases from the picker", async () => {
    renderPage(<FieldsHarness form={initialForm({ knowledgeBaseIds: ["knowledge-1"] })} />)
    fireEvent.click(screen.getByText("关联知识库"))
    fireEvent.click(screen.getByLabelText("关联知识库"))

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("按需选择知识库，最多 4 个。")).toBeTruthy()
    expect(within(dialog).getByText("研发纪要")).toBeTruthy()

    fireEvent.click(within(dialog).getByText("研发纪要").closest("label")!)
    await waitFor(() =>
      expect(screen.getAllByText("2 个知识库").length).toBeGreaterThan(0)
    )

    const search = within(dialog).getByPlaceholderText("搜索知识库...")
    fireEvent.change(search, { target: { value: "zzz" } })
    expect(within(dialog).getByText("没有匹配的知识库")).toBeTruthy()
    fireEvent.change(search, { target: { value: "" } })

    fireEvent.click(within(dialog).getByText("产品文档").closest("label")!)
    fireEvent.click(within(dialog).getByText("研发纪要").closest("label")!)
    await waitFor(() => expect(screen.getByText("关联的知识库展示在这里")).toBeTruthy())
    fireEvent.click(within(dialog).getByRole("button", { name: "完成" }))
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("disables the fifth knowledge base selection", () => {
    renderPage(
      <FieldsHarness form={initialForm({ knowledgeBaseIds: ["k1", "k2", "k3", "k4"] })} />
    )
    fireEvent.click(screen.getByLabelText("关联知识库"))
    const dialog = screen.getByRole("dialog")
    const checkbox = within(dialog)
      .getByText("产品文档")
      .closest("label")!
      .querySelector('input[type="checkbox"]') as HTMLInputElement
    expect(checkbox.disabled).toBe(true)
  })

  test("selects and removes MCP tools from the picker", async () => {
    renderPage(<FieldsHarness form={initialForm({ mcpTools: [{ server_id: "server-1", tool_name: "search" }] })} />)
    fireEvent.click(screen.getByText("MCP 工具"))
    fireEvent.click(screen.getByLabelText("MCP 工具"))

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("Database")).toBeTruthy()
    expect(within(dialog).getByText("execute_sql")).toBeTruthy()

    fireEvent.click(within(dialog).getByText("execute_sql").closest("label")!)
    await waitFor(() =>
      expect(screen.getAllByText("2 个 MCP 工具").length).toBeGreaterThan(0)
    )

    fireEvent.click(within(dialog).getByText("search").closest("label")!)
    fireEvent.click(within(dialog).getByText("execute_sql").closest("label")!)
    await waitFor(() => expect(screen.getByText("选择的 MCP 工具展示在这里")).toBeTruthy())
    fireEvent.click(within(dialog).getByRole("button", { name: "完成" }))
  })

  test("changes the agent status through the dropdown", () => {
    renderPage(<FieldsHarness form={initialForm()} />)
    const statusTrigger = screen.getByLabelText("状态")
    fireEvent.pointerDown(statusTrigger)
    fireEvent.click(statusTrigger)
    fireEvent.click(screen.getByRole("menuitem", { name: "已停用" }))
    expect(screen.getByText("已停用")).toBeTruthy()
  })

  test("readOnly disables the editable fields", () => {
    renderPage(<FieldsHarness form={initialForm()} readOnly />)
    expect((screen.getByLabelText("Agent 名称") as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText("描述") as HTMLTextAreaElement).disabled).toBe(true)
    expect((screen.getByLabelText("系统提示词") as HTMLTextAreaElement).disabled).toBe(true)
    expect((screen.getByLabelText("选择模型") as HTMLButtonElement).disabled).toBe(true)
  })

  test("workflow app type hides knowledge and MCP sections", () => {
    renderPage(
      <FieldsHarness
        form={initialForm({ appType: "workflow", id: "wf-1", knowledgeBaseIds: [], mcpTools: [] })}
      />
    )
    expect(screen.queryByText("关联知识库")).toBeNull()
    expect(screen.queryByText("MCP 工具")).toBeNull()
  })
})

describe("AgentConfigFields empty resource states", () => {
  function EmptyHarness({ form }: { form: AgentFormState }) {
    const { t } = useLanguage()
    const [state, setState] = useState(form)
    return (
      <AgentConfigFields
        form={state}
        setForm={setState}
        models={[]}
        knowledgeBases={[]}
        mcpServers={[]}
        readOnly={false}
        t={t}
      />
    )
  }

  test("knowledge picker reports no available bases", () => {
    renderPage(<EmptyHarness form={initialForm()} />)
    fireEvent.click(screen.getByLabelText("关联知识库"))
    expect(screen.getByText("暂无可用知识库")).toBeTruthy()
  })

  test("MCP picker reports no available tools", () => {
    renderPage(<EmptyHarness form={initialForm()} />)
    fireEvent.click(screen.getByLabelText("MCP 工具"))
    expect(screen.getByText("暂无可用 MCP 工具")).toBeTruthy()
  })

  test("closes the knowledge picker with Escape", async () => {
    renderPage(<FieldsHarness form={initialForm()} />)
    fireEvent.click(screen.getByLabelText("关联知识库"))
    expect(screen.getByRole("dialog")).toBeTruthy()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })
})

describe("InteractionConfigFields", () => {
  function InteractionHarness({
    appType = "agent",
    initial = defaultConfig(),
    readOnly = false,
    compact = false,
    idPrefix = "icf",
  }: {
    appType?: "agent" | "workflow"
    initial?: AgentInteractionConfig
    readOnly?: boolean
    compact?: boolean
    idPrefix?: string
  }) {
    const { t } = useLanguage()
    const [value, setValue] = useState(initial)
    return (
      <InteractionConfigFields
        appType={appType}
        value={value}
        onChange={setValue}
        t={t}
        idPrefix={idPrefix}
        readOnly={readOnly}
        compact={compact}
      />
    )
  }

  function defaultConfig(): AgentInteractionConfig {
    return {
      prologue: "",
      tts_type: "BROWSER",
      file_upload: false,
      file_upload_setting: { file_upload_type: ["document", "image"] },
      user_input_title: "",
    }
  }

  test("edits prologue and input title and toggles tts and upload", () => {
    renderPage(<InteractionHarness />)
    const prologue = screen.getByLabelText("开场白") as HTMLTextAreaElement
    fireEvent.change(prologue, { target: { value: "Hello there" } })
    expect(prologue.value).toBe("Hello there")

    const title = screen.getByLabelText("用户输入标题") as HTMLInputElement
    fireEvent.change(title, { target: { value: "Your question" } })
    expect(title.value).toBe("Your question")

    fireEvent.click(screen.getByLabelText("文字转语音"))
    expect(screen.getByLabelText("文字转语音").getAttribute("aria-checked")).toBe("false")

    fireEvent.click(screen.getByLabelText("文件上传"))
    expect(screen.getByLabelText("文件上传").getAttribute("aria-checked")).toBe("true")
  })

  test("opens upload settings and toggles file types", () => {
    renderPage(<InteractionHarness />)
    fireEvent.click(screen.getByTitle("文件上传设置"))
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("文档")).toBeTruthy()
    expect(within(dialog).getByText("图片")).toBeTruthy()

    const documentCheckbox = within(dialog)
      .getByText("文档")
      .closest("label")!
      .querySelector('input[type="checkbox"]') as HTMLInputElement
    fireEvent.click(documentCheckbox)
    expect(documentCheckbox.checked).toBe(false)
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("workflow upload types have no audio and compact layout works", () => {
    renderPage(<InteractionHarness appType="workflow" compact />)
    fireEvent.click(screen.getByTitle("文件上传设置"))
    expect(screen.queryByText("音频")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "关闭" }))
  })

  test("readOnly disables the fields", () => {
    renderPage(<InteractionHarness readOnly />)
    expect((screen.getByLabelText("开场白") as HTMLTextAreaElement).disabled).toBe(true)
    expect((screen.getByLabelText("用户输入标题") as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText("文字转语音") as HTMLButtonElement).disabled).toBe(true)
  })
})

describe("AgentPermissionsDialog", () => {
  const member = (id: string, name: string, username: string) => ({
    user: {
      id,
      username,
      name,
      email: `${username}@x.co`,
      is_global_admin: false,
      must_change_password: false,
      is_active: true,
      created_at: "",
      workspaces: [],
      teams: [],
    },
    role: "member" as const,
  })

  test("renders loading state and then the grant form", async () => {
    const grant: Array<{ userId: string }> = []
    renderPage(
      <AgentPermissionsDialog
        agent={{ id: "agent-1", name: "Research Assistant", created_by_user_id: "owner-1" } as never}
        members={[member("u-2", "Alice", "alice"), member("owner-1", "Owner", "owner")]}
        permissions={[]}
        isLoading={false}
        isSaving={false}
        onClose={() => undefined}
        onGrant={(userId) => {
          grant.push({ userId })
        }}
        onRevoke={() => undefined}
      />
    )
    expect(screen.getByText("Alice / alice")).toBeTruthy()

    const trigger = screen.getByLabelText("用户")
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: /alice/ }))
    fireEvent.click(screen.getByText("保存授权").closest("button")!)
    expect(grant).toEqual([{ userId: "u-2" }])
  })

  test("renders a loading spinner while fetching", () => {
    renderPage(
      <AgentPermissionsDialog
        agent={null}
        members={[]}
        permissions={[]}
        isLoading
        isSaving={false}
        onClose={() => undefined}
        onGrant={() => undefined}
        onRevoke={() => undefined}
      />
    )
    expect(screen.queryByText("正在加载")).toBeNull()
  })

  test("shows existing grants and revokes them", () => {
    const revoked: string[] = []
    renderPage(
      <AgentPermissionsDialog
        agent={{ id: "agent-1", name: "Agent", created_by_user_id: "owner-1" } as never}
        members={[]}
        permissions={[{ user: member("u-3", "Bob", "bob").user, permission: "view" }]}
        isLoading={false}
        isSaving={false}
        onClose={() => undefined}
        onGrant={() => undefined}
        onRevoke={(userId) => {
          revoked.push(userId)
        }}
      />
    )
    expect(screen.getByText("Bob")).toBeTruthy()
    fireEvent.click(screen.getByLabelText("撤销授权"))
    expect(revoked).toEqual(["u-3"])
  })

  test("shows the empty grant list and disabled submit without targets", () => {
    renderPage(
      <AgentPermissionsDialog
        agent={{ id: "agent-1", name: "Agent", created_by_user_id: "owner-1" } as never}
        members={[]}
        permissions={[]}
        isLoading={false}
        isSaving={false}
        onClose={() => undefined}
        onGrant={() => undefined}
        onRevoke={() => undefined}
      />
    )
    expect(screen.getByText("暂无授权")).toBeTruthy()
    expect(screen.getByText("选择用户")).toBeTruthy()
    expect((screen.getByText("保存授权").closest("button") as HTMLButtonElement).disabled).toBe(true)
  })

  test("closes via the dialog close event", () => {
    let closeCalls = 0
    const view = renderPage(
      <AgentPermissionsDialog
        agent={{ id: "agent-1", name: "Agent", created_by_user_id: "owner-1" } as never}
        members={[]}
        permissions={[]}
        isLoading={false}
        isSaving={false}
        onClose={() => {
          closeCalls += 1
        }}
        onGrant={() => undefined}
        onRevoke={() => undefined}
      />
    )
    view.rerender(
      <LanguageProvider defaultLanguage="zh-Hans">
        <AgentPermissionsDialog
          agent={null}
          members={[]}
          permissions={[]}
          isLoading={false}
          isSaving={false}
          onClose={() => {
            closeCalls += 1
          }}
          onGrant={() => undefined}
          onRevoke={() => undefined}
        />
      </LanguageProvider>
    )
    expect(closeCalls).toBe(0)
  })
})

/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"

import { KnowledgeBaseDialogs } from "@/components/knowledge/knowledge-base-dialogs"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
import {
  PermissionBadge,
  StatusBadge,
} from "@/components/knowledge/status-badges"
import {
  documentStatusDotClassName,
  documentStatusLabel,
  formatBytes,
  taskStatusDotClassName,
  taskStatusLabel,
  taskTypeLabel,
} from "@/components/knowledge/status-labels"
import * as knowledgeApi from "@/lib/api/knowledge"
import * as llmApi from "@/lib/api/llm"
import type {
  KnowledgeBaseEditForm,
  KnowledgeBaseForm,
  KnowledgeBasePermissionForm,
  ResourcePermission,
} from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { WorkspaceMember } from "@/lib/api/system"
import { translate } from "@/i18n"
import { mockNextNavigation, mockUseSession, renderPage } from "./helpers/dom"

mockUseSession()
mockNextNavigation()

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const embeddingModel: RegisteredModel = {
  id: "model-emb",
  workspace_id: "ws-1",
  name: "text-embedding-pro",
  provider: "openai",
  provider_type: "openai",
  model_type: "EMBEDDING",
  model_name: "text-embedding-3-small",
  status: "active",
  credential: {},
  api_base: "",
  has_api_key: true,
  api_key_hint: null,
  meta: {},
  created_by_user_id: "u-admin",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

const rerankerModel: RegisteredModel = {
  ...embeddingModel,
  id: "model-rerank",
  name: "rerank-pro",
  model_type: "RERANKER",
  model_name: "bge-reranker-v2-m3",
}

const inactiveModel: RegisteredModel = {
  ...embeddingModel,
  id: "model-inactive",
  name: "embedding-disabled",
  status: "disabled",
}

const otherMember: WorkspaceMember = {
  user: {
    id: "u-other",
    username: "other",
    email: "other@app.local",
    name: "Other User",
    is_global_admin: false,
    must_change_password: false,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    workspaces: [],
    teams: [],
  },
  role: "member",
}

const grant: ResourcePermission = {
  user: otherMember.user,
  permission: "view",
}

function t(key: string, values?: Record<string, string | number>) {
  return translate("zh-Hans", key as never, values)
}

const emptyForm: KnowledgeBaseForm = {
  name: "",
  description: "",
  embedding_model_id: null,
  reranker_model_id: null,
}

const editForm: KnowledgeBaseEditForm = {
  id: "kb-1",
  name: "KB Alpha",
  description: "Alpha docs",
  embedding_model_id: "model-emb",
  reranker_model_id: "model-rerank",
}

const permissionForm: KnowledgeBasePermissionForm = {
  knowledgeBase: {
    id: "kb-1",
    workspace_id: "ws-1",
    name: "KB Alpha",
    description: "",
    status: "active",
    embedding_model_id: null,
    reranker_model_id: null,
    created_by_user_id: "u-admin",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    permission: "edit",
  },
  userId: "u-other",
  permission: "view",
}

function DialogsHarness({
  initial,
  shareTargets = [],
  permissions = [],
  registeredModels = [],
  onCreate = () => undefined,
  onUpdate = () => undefined,
  onGrant = () => undefined,
  onRevoke = () => undefined,
}: {
  initial?: Partial<{
    form: KnowledgeBaseForm
    editForm: KnowledgeBaseEditForm | null
    permissionForm: KnowledgeBasePermissionForm | null
    isDialogOpen: boolean
    isSaving: boolean
  }>
  shareTargets?: WorkspaceMember[]
  permissions?: ResourcePermission[]
  registeredModels?: RegisteredModel[]
  onCreate?: () => void
  onUpdate?: () => void
  onGrant?: () => void
  onRevoke?: (userId: string) => void
}) {
  const [form, setForm] = useState<KnowledgeBaseForm>(initial?.form ?? emptyForm)
  const [editFormState, setEditFormState] = useState<KnowledgeBaseEditForm | null>(
    initial?.editForm ?? null,
  )
  const [permissionFormState, setPermissionFormState] =
    useState<KnowledgeBasePermissionForm | null>(initial?.permissionForm ?? null)
  const [isDialogOpen, setIsDialogOpen] = useState(initial?.isDialogOpen ?? false)
  const isSaving = initial?.isSaving ?? false

  return (
    <KnowledgeBaseDialogs
      form={form}
      setForm={setForm}
      editForm={editFormState}
      setEditForm={setEditFormState}
      permissionForm={permissionFormState}
      setPermissionForm={setPermissionFormState}
      shareTargets={shareTargets}
      permissions={permissions}
      registeredModels={registeredModels}
      isDialogOpen={isDialogOpen}
      setIsDialogOpen={setIsDialogOpen}
      isSaving={isSaving}
      handleCreate={(event) => {
        event.preventDefault()
        onCreate()
      }}
      handleUpdate={(event) => {
        event.preventDefault()
        onUpdate()
      }}
      handleGrantPermission={(event) => {
        event.preventDefault()
        onGrant()
      }}
      handleRevokePermission={(userId) => onRevoke(userId)}
    />
  )
}

afterEach(() => {
  cleanup()
})

// ---------------------------------------------------------------------------
// KnowledgeBaseDialogs
// ---------------------------------------------------------------------------

describe("KnowledgeBaseDialogs", () => {
  test("renders the create dialog with model selects and submits", async () => {
    let created = 0
    renderPage(
      <DialogsHarness
        initial={{ isDialogOpen: true }}
        registeredModels={[embeddingModel, rerankerModel, inactiveModel]}
        onCreate={() => {
          created += 1
        }}
      />,
    )

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("配置知识库名称、描述和默认数据源。")).toBeTruthy()

    fireEvent.change(within(dialog).getByLabelText("知识库名称"), {
      target: { value: "New KB" },
    })
    fireEvent.change(within(dialog).getByLabelText("描述"), {
      target: { value: "Fresh docs" },
    })

    // Embedding model select only offers active EMBEDDING models.
    const embeddingTrigger = within(dialog).getByRole("button", {
      name: "选择 Embedding 模型",
    })
    fireEvent.pointerDown(embeddingTrigger)
    fireEvent.click(await screen.findByText("text-embedding-pro"))
    expect(screen.queryByText("embedding-disabled")).toBeNull()

    // Reranker select is optional and offers 不使用.
    const rerankerTrigger = within(dialog).getByRole("button", {
      name: "不使用 Rerank 模型",
    })
    fireEvent.pointerDown(rerankerTrigger)
    fireEvent.click(await screen.findByText("rerank-pro"))
    expect(within(dialog).getByText("rerank-pro")).toBeTruthy()

    fireEvent.click(within(dialog).getByRole("button", { name: "新建知识库" }))
    expect(created).toBe(1)
  })

  test("disables the create submit while saving", () => {
    renderPage(
      <DialogsHarness initial={{ isDialogOpen: true, isSaving: true }} />,
    )
    const submit = screen.getByRole("button", {
      name: "新建知识库",
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
  })

  test("closes the create dialog with the cancel button", () => {
    renderPage(<DialogsHarness initial={{ isDialogOpen: true }} />)
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("renders the edit dialog prefilled and submits updates", async () => {
    let updated = 0
    renderPage(
      <DialogsHarness
        initial={{ editForm }}
        registeredModels={[embeddingModel, rerankerModel]}
        onUpdate={() => {
          updated += 1
        }}
      />,
    )

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("更新知识库名称和描述。")).toBeTruthy()
    const nameInput = within(dialog).getByLabelText("知识库名称") as HTMLInputElement
    const descriptionInput = within(dialog).getByLabelText(
      "描述",
    ) as HTMLTextAreaElement
    expect(nameInput.value).toBe("KB Alpha")
    expect(descriptionInput.value).toBe("Alpha docs")
    expect(within(dialog).getByText("text-embedding-pro")).toBeTruthy()
    expect(within(dialog).getByText("rerank-pro")).toBeTruthy()

    fireEvent.change(nameInput, { target: { value: "KB Renamed" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
    expect(updated).toBe(1)
  })

  test("renders the permission dialog with grants and revoke actions", async () => {
    let granted = 0
    const revoked: string[] = []
    renderPage(
      <DialogsHarness
        initial={{ permissionForm }}
        shareTargets={[otherMember]}
        permissions={[grant]}
        onGrant={() => {
          granted += 1
        }}
        onRevoke={(userId) => {
          revoked.push(userId)
        }}
      />,
    )

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("资源授权")).toBeTruthy()
    expect(within(dialog).getByText("KB Alpha")).toBeTruthy() // dialog description
    expect(within(dialog).getByText("Other User")).toBeTruthy()
    expect(within(dialog).getByText("Other User / other")).toBeTruthy()
    expect(within(dialog).getByText("other")).toBeTruthy()

    // Grant list row with badge and revoke button.
    expect(within(dialog).getAllByText("可查看").length).toBeGreaterThanOrEqual(1)
    fireEvent.click(within(dialog).getByRole("button", { name: "撤销授权" }))
    expect(revoked).toEqual(["u-other"])

    // Save the grant form.
    fireEvent.click(within(dialog).getByRole("button", { name: "保存授权" }))
    expect(granted).toBe(1)
  })

  test("switches the permission level in the permission dialog", async () => {
    renderPage(
      <DialogsHarness
        initial={{ permissionForm }}
        shareTargets={[otherMember]}
        permissions={[]}
      />,
    )

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("暂无授权")).toBeTruthy()

    fireEvent.pointerDown(within(dialog).getByRole("button", { name: "权限" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "可编辑" }))
    // The trigger is label-associated 权限; check its visible content.
    expect(within(dialog).getByRole("button", { name: "权限" }).textContent).toContain(
      "可编辑",
    )
  })

  test("disables permission controls without share targets", () => {
    renderPage(
      <DialogsHarness
        initial={{ permissionForm }}
        shareTargets={[]}
        permissions={[]}
      />,
    )
    const userSelect = screen.getByRole("button", {
      name: "用户",
    }) as HTMLButtonElement
    expect(userSelect.disabled).toBe(true)
    const save = screen.getByRole("button", {
      name: "保存授权",
    }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  test("disables the embedding select when no models are registered", () => {
    renderPage(<DialogsHarness initial={{ isDialogOpen: true }} />)
    const embeddingTrigger = screen.getByRole("button", {
      name: "选择 Embedding 模型",
    }) as HTMLButtonElement
    expect(embeddingTrigger.disabled).toBe(true)
    // Optional reranker stays enabled with the 不使用 placeholder.
    const rerankerTrigger = screen.getByRole("button", {
      name: "不使用 Rerank 模型",
    }) as HTMLButtonElement
    expect(rerankerTrigger.disabled).toBe(false)
  })

  test("edits the description and models in the edit dialog", async () => {
    renderPage(
      <DialogsHarness
        initial={{ editForm }}
        registeredModels={[embeddingModel, rerankerModel]}
      />,
    )

    const dialog = screen.getByRole("dialog")
    const descriptionInput = within(dialog).getByLabelText(
      "描述",
    ) as HTMLTextAreaElement
    fireEvent.change(descriptionInput, { target: { value: "Updated docs" } })
    expect(descriptionInput.value).toBe("Updated docs")

    // Re-select the embedding model (already selected → still fires onChange).
    fireEvent.pointerDown(
      within(dialog).getByText("text-embedding-pro").closest("button")!,
    )
    const embeddingItem = (await screen.findAllByText("text-embedding-pro")).find(
      (element) => element.closest('[role="menuitem"]'),
    )!
    fireEvent.click(embeddingItem)
    expect(within(dialog).getByText("text-embedding-pro")).toBeTruthy()

    // Switch the reranker back to 不使用.
    fireEvent.pointerDown(within(dialog).getByText("rerank-pro").closest("button")!)
    fireEvent.click(await screen.findByRole("menuitem", { name: "不使用" }))
    expect(within(dialog).getByText("不使用 Rerank 模型")).toBeTruthy()
  })

  test("closes the edit dialog with the cancel button", () => {
    renderPage(<DialogsHarness initial={{ editForm }} />)
    expect(screen.getByRole("dialog")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  test("selects a permission target from the user dropdown", async () => {
    renderPage(
      <DialogsHarness
        initial={{ permissionForm }}
        shareTargets={[otherMember]}
        permissions={[]}
      />,
    )

    const dialog = screen.getByRole("dialog")
    fireEvent.pointerDown(within(dialog).getByRole("button", { name: "用户" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "Other User / other" }))
    expect(within(dialog).getByText("Other User / other")).toBeTruthy()
  })

  test("shows the saving spinner in the permission dialog", () => {
    renderPage(
      <DialogsHarness
        initial={{ permissionForm, isSaving: true }}
        shareTargets={[otherMember]}
        permissions={[]}
      />,
    )
    const save = screen.getByRole("button", {
      name: "保存授权",
    }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    expect(document.querySelector(".lucide-loader-circle")).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// MarkdownContent
// ---------------------------------------------------------------------------

describe("MarkdownContent", () => {
  test("renders a placeholder for empty content", () => {
    renderPage(<MarkdownContent content="   " />)
    expect(screen.getByText("暂无内容")).toBeTruthy()
  })

  test("renders headings, paragraphs, links, lists, blockquote, code and pre", () => {
    renderPage(
      <MarkdownContent
        content={[
          "# Title One",
          "## Title Two",
          "### Title Three",
          "Some **bold** and `inline code` text.",
          "[OpenAI](https://openai.com)",
          "- item a",
          "- item b",
          "1. first",
          "2. second",
          "> quoted text",
          "",
          "```",
          "const x = 1",
          "```",
          "",
          "---",
        ].join("\n")}
      />,
    )

    expect(screen.getByRole("heading", { level: 1, name: "Title One" })).toBeTruthy()
    expect(screen.getByRole("heading", { level: 2, name: "Title Two" })).toBeTruthy()
    expect(screen.getByRole("heading", { level: 3, name: "Title Three" })).toBeTruthy()
    // RTL text matching only sees direct text nodes, so match by fragments.
    expect(screen.getByText((content: string) => content.includes("Some"))).toBeTruthy()
    expect(screen.getByText("bold")).toBeTruthy()
    expect(screen.getByText("inline code")).toBeTruthy()
    const link = screen.getByRole("link", { name: "OpenAI" }) as HTMLAnchorElement
    expect(link.href).toBe("https://openai.com/")
    expect(link.target).toBe("_blank")
    expect(screen.getByText("item a")).toBeTruthy()
    expect(screen.getByText("item b")).toBeTruthy()
    expect(screen.getByText("first")).toBeTruthy()
    expect(screen.getByText("second")).toBeTruthy()
    expect(screen.getByText("quoted text")).toBeTruthy()
    expect(screen.getByText("const x = 1")).toBeTruthy()
  })

  test("renders GFM tables", () => {
    renderPage(
      <MarkdownContent
        content={[
          "| Name | Value |",
          "| ---- | ----- |",
          "| a    | 1     |",
          "| b    | 2     |",
        ].join("\n")}
      />,
    )
    const table = screen.getByRole("table")
    expect(table).toBeTruthy()
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeTruthy()
    expect(screen.getByRole("columnheader", { name: "Value" })).toBeTruthy()
    expect(screen.getByRole("cell", { name: "a" })).toBeTruthy()
    expect(screen.getByRole("cell", { name: "2" })).toBeTruthy()
  })

  test("renders emphasis next to CJK text", () => {
    renderPage(
      <MarkdownContent content="试用期按 **80%**发放，正式员工按 *标准*执行。" />,
    )

    expect(screen.getByText("80%").tagName).toBe("STRONG")
    expect(screen.getByText("标准").tagName).toBe("EM")
  })

  test("highlights and copies fenced code without copying controls", async () => {
    const originalClipboard = navigator.clipboard
    const written: string[] = []
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async (value: string) => void written.push(value),
      },
      configurable: true,
    })
    try {
      renderPage(
        <MarkdownContent
          content={[
            "```python",
            "def greet(name):",
            '    return f"Hello {name}"',
            "```",
          ].join("\n")}
        />,
      )

      await waitFor(() => expect(document.querySelector(".shiki")).toBeTruthy())
      fireEvent.click(screen.getByRole("button", { name: "复制代码" }))
      await waitFor(() =>
        expect(written).toEqual([
          'def greet(name):\n    return f"Hello {name}"',
        ]),
      )
      expect(screen.getByText("已复制")).toBeTruthy()
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      })
    }
  })

  test("falls back to source and reports clipboard failures", async () => {
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
      renderPage(
        <MarkdownContent
          content={["```made-up-language", "plain <code>", "```"].join(
            "\n",
          )}
        />,
      )

      expect(screen.getByText("plain <code>")).toBeTruthy()
      fireEvent.click(screen.getByRole("button", { name: "复制代码" }))
      await screen.findByText("复制失败")
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      })
    }
  })

  test("renders Mermaid, switches to source, and copies both forms", async () => {
    const originalClipboard = navigator.clipboard
    const originalClipboardItem = globalThis.ClipboardItem
    const writtenText: string[] = []
    const writtenItems: ClipboardItems[] = []
    class TestClipboardItem {
      constructor(readonly data: Record<string, Blob>) {}
    }
    Object.defineProperty(globalThis, "ClipboardItem", {
      value: TestClipboardItem,
      configurable: true,
    })
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async (value: string) => void writtenText.push(value),
        write: async (items: ClipboardItems[]) => void writtenItems.push(...items),
      },
      configurable: true,
    })
    try {
      const source = "graph TD\n  A[Start] --> B[Done]"
      renderPage(
        <MarkdownContent
          content={["```mermaid", source, "```"].join("\n")}
        />,
      )

      const diagram = (await screen.findByRole("img", {
        name: "Mermaid 图表",
      })) as HTMLImageElement
      const lightDiagram = diagram.src
      act(() => document.documentElement.classList.add("dark"))
      await waitFor(() =>
        expect(
          (screen.getByRole("img", {
            name: "Mermaid 图表",
          }) as HTMLImageElement).src,
        ).not.toBe(lightDiagram),
      )
      fireEvent.click(screen.getByRole("button", { name: "复制图表" }))
      await waitFor(() => expect(writtenItems.length).toBe(1))
      fireEvent.click(screen.getByRole("button", { name: "显示源码" }))
      expect(screen.getByText((text) => text.includes("A[Start]"))).toBeTruthy()
      fireEvent.click(screen.getByRole("button", { name: "复制源码" }))
      await waitFor(() => expect(writtenText).toEqual([source]))
    } finally {
      act(() => document.documentElement.classList.remove("dark"))
      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      })
      Object.defineProperty(globalThis, "ClipboardItem", {
        value: originalClipboardItem,
        configurable: true,
      })
    }
  })

  test("keeps invalid Mermaid source visible and reports copy failures", async () => {
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
      renderPage(
        <MarkdownContent
          content={["```mermaid", "this is not a diagram", "```"].join("\n")}
        />,
      )

      expect((await screen.findByRole("alert")).textContent).toContain(
        "图表渲染失败",
      )
      expect(screen.getByText("this is not a diagram")).toBeTruthy()
      fireEvent.click(screen.getByRole("button", { name: "复制源码" }))
      await screen.findByText("复制失败")
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      })
    }
  })

  test("renders external images and placeholders for embedded or missing ones", () => {
    renderPage(
      <MarkdownContent
        content={[
          "![external](https://example.com/x.png)",
          "![embedded](data:image/png;base64,AAAA)",
          "![missing]()",
        ].join("\n")}
      />,
    )
    const external = screen.getByRole("img", { name: "external" }) as HTMLImageElement
    expect(external.src).toContain("example.com/x.png")
    expect(screen.getAllByText("图片").length).toBe(2)
  })
})

// ---------------------------------------------------------------------------
// status-labels + status-badges
// ---------------------------------------------------------------------------

describe("knowledge status helpers", () => {
  test("maps every document status to a translated label", () => {
    const cases: Record<string, string> = {
      uploaded: "待解析",
      parse_queued: "解析排队中",
      parsing: "解析中",
      parsed: "待向量化",
      index_queued: "向量化排队中",
      indexing: "向量化中",
      preview: "预览",
      indexed: "已向量化",
      parse_failed: "解析失败",
      index_failed: "向量化失败",
    }
    for (const [status, label] of Object.entries(cases)) {
      expect(documentStatusLabel(status, t)).toBe(label)
    }
    expect(documentStatusLabel("mystery", t)).toBe("mystery")
  })

  test("classifies document status dot colors", () => {
    expect(documentStatusDotClassName("parse_failed")).toBe("bg-destructive")
    expect(documentStatusDotClassName("index_failed")).toBe("bg-destructive")
    expect(documentStatusDotClassName("parsed")).toBe("bg-emerald-500")
    expect(documentStatusDotClassName("indexed")).toBe("bg-emerald-500")
    expect(documentStatusDotClassName("parse_queued")).toBe("bg-sky-500")
    expect(documentStatusDotClassName("index_queued")).toBe("bg-sky-500")
    expect(documentStatusDotClassName("parsing")).toBe("bg-sky-500")
    expect(documentStatusDotClassName("indexing")).toBe("bg-sky-500")
    expect(documentStatusDotClassName("uploaded")).toBe("bg-muted-foreground")
    expect(documentStatusDotClassName("")).toBe("bg-muted-foreground")
  })

  test("maps task types and statuses", () => {
    expect(taskTypeLabel("parse", t)).toBe("解析")
    expect(taskTypeLabel("index", t)).toBe("向量化")
    expect(taskTypeLabel("rebuild_index", t)).toBe("重建索引")
    expect(taskTypeLabel("other", t)).toBe("other")

    expect(taskStatusLabel("queued", t)).toBe("排队中")
    expect(taskStatusLabel("running", t)).toBe("运行中")
    expect(taskStatusLabel("succeeded", t)).toBe("成功")
    expect(taskStatusLabel("failed", t)).toBe("失败")
    expect(taskStatusLabel("unknown", t)).toBe("unknown")

    expect(taskStatusDotClassName("failed")).toBe("bg-destructive")
    expect(taskStatusDotClassName("succeeded")).toBe("bg-emerald-500")
    expect(taskStatusDotClassName("queued")).toBe("bg-sky-500")
    expect(taskStatusDotClassName("running")).toBe("bg-sky-500")
    expect(taskStatusDotClassName("paused")).toBe("bg-muted-foreground")
  })

  test("formats byte sizes", () => {
    expect(formatBytes(0)).toBe("0 B")
    expect(formatBytes(1023)).toBe("1023 B")
    expect(formatBytes(1024)).toBe("1.0 KB")
    expect(formatBytes(2048)).toBe("2.0 KB")
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB")
  })

  test("renders status badges for known and unknown statuses", () => {
    renderPage(
      <>
        <StatusBadge status="active" />
        <StatusBadge status="archived" />
        <StatusBadge status="disabled" />
        <StatusBadge status="weird" />
      </>,
    )
    expect(screen.getByText("已启用")).toBeTruthy()
    expect(screen.getByText("已归档")).toBeTruthy()
    expect(screen.getByText("已停用")).toBeTruthy()
    expect(screen.getByText("weird")).toBeTruthy()
  })

  test("renders permission badges for edit and view", () => {
    renderPage(
      <>
        <PermissionBadge permission="edit" />
        <PermissionBadge permission="view" />
      </>,
    )
    expect(screen.getByText("可编辑")).toBeTruthy()
    expect(screen.getByText("可查看")).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// lib/api/knowledge.ts
// ---------------------------------------------------------------------------

const originalFetch = globalThis.fetch

function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    return Promise.resolve(handler(url, init))
  }) as typeof fetch
}

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe("lib/api/knowledge", () => {
  test("lists knowledge bases with optional query parameters", async () => {
    const calls: Array<{ url: string; method: string; auth: string | null }> = []
    stubFetch((url, init) => {
      const headers = new Headers(init?.headers)
      calls.push({
        url,
        method: init?.method ?? "GET",
        auth: headers.get("Authorization"),
      })
      return new Response("[]", { status: 200 })
    })

    await knowledgeApi.listKnowledgeBases("tok", "ws-1")
    await knowledgeApi.listKnowledgeBases("tok", "ws-1", { limit: 50, offset: 25 })

    expect(calls[0].url).toBe("/api/v1/workspaces/ws-1/knowledge-bases")
    expect(calls[1].url).toBe(
      "/api/v1/workspaces/ws-1/knowledge-bases?limit=50&offset=25",
    )
    expect(calls.every((call) => call.auth === "Bearer tok")).toBe(true)
  })

  test("creates and updates knowledge bases with JSON bodies", async () => {
    const calls: Array<{ method: string; body: string }> = []
    stubFetch((_url, init) => {
      calls.push({
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      })
      return new Response("{}", { status: 200 })
    })

    await knowledgeApi.createKnowledgeBase("tok", "ws-1", {
      name: "KB",
      description: "desc",
      embedding_model_id: "m1",
      reranker_model_id: null,
    })
    await knowledgeApi.updateKnowledgeBase("tok", "ws-1", "kb-1", {
      status: "archived",
    })

    expect(calls[0].method).toBe("POST")
    expect(JSON.parse(calls[0].body)).toEqual({
      name: "KB",
      description: "desc",
      embedding_model_id: "m1",
      reranker_model_id: null,
    })
    expect(calls[1].method).toBe("PATCH")
    expect(JSON.parse(calls[1].body)).toEqual({ status: "archived" })
  })

  test("deletes knowledge bases and documents", async () => {
    const methods: string[] = []
    stubFetch((_url, init) => {
      methods.push(init?.method ?? "GET")
      return new Response(null, { status: 204 })
    })

    await knowledgeApi.deleteKnowledgeBase("tok", "ws-1", "kb-1")
    await knowledgeApi.deleteKnowledgeDocument("tok", "ws-1", "kb-1", "doc-1")
    await knowledgeApi.deleteKnowledgeAttachment("tok", "ws-1", "kb-1", "att-1")
    expect(methods).toEqual(["DELETE", "DELETE", "DELETE"])
  })

  test("lists documents with and without include_staged", async () => {
    const urls: string[] = []
    stubFetch((url) => {
      urls.push(url)
      return new Response("[]", { status: 200 })
    })

    await knowledgeApi.listKnowledgeDocuments("tok", "ws-1", "kb-1")
    await knowledgeApi.listKnowledgeDocuments("tok", "ws-1", "kb-1", {
      includeStaged: true,
    })
    expect(urls[0]).toBe(
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/documents",
    )
    expect(urls[1]).toBe(
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/documents?include_staged=true",
    )
  })

  test("uploads attachments as FormData without a JSON content type", async () => {
    let body: unknown = null
    stubFetch((_url, init) => {
      body = init?.body
      return new Response("{}", { status: 200 })
    })

    await knowledgeApi.uploadKnowledgeAttachment("tok", "ws-1", "kb-1", new File(["x"], "a.txt"))
    expect(body instanceof FormData).toBe(true)
  })

  test("creates documents from attachment ids", async () => {
    const calls: Array<{ body: string }> = []
    stubFetch((_url, init) => {
      calls.push({ body: String(init?.body ?? "") })
      return new Response("[]", { status: 200 })
    })

    await knowledgeApi.createKnowledgeDocuments("tok", "ws-1", "kb-1", ["att-1"], true)
    await knowledgeApi.createKnowledgeDocuments("tok", "ws-1", "kb-1", ["att-2"], false)
    await knowledgeApi.createKnowledgeDocuments("tok", "ws-1", "kb-1", ["att-3"], true, "qa")
    expect(JSON.parse(calls[0].body)).toEqual({
      attachment_ids: ["att-1"],
      staged: true,
    })
    expect(JSON.parse(calls[1].body)).toEqual({
      attachment_ids: ["att-2"],
      staged: false,
    })
    expect(JSON.parse(calls[2].body)).toEqual({
      attachment_ids: ["att-3"],
      staged: true,
      import_mode: "qa",
    })
  })

  test("parses documents with and without explicit options", async () => {
    const calls: Array<{ body: string | undefined }> = []
    stubFetch((_url, init) => {
      calls.push({ body: init?.body === undefined ? undefined : String(init?.body) })
      return new Response("{}", { status: 200 })
    })

    await knowledgeApi.parseKnowledgeDocument("tok", "ws-1", "kb-1", "doc-1")
    await knowledgeApi.parseKnowledgeDocument("tok", "ws-1", "kb-1", "doc-1", {
      strategy: "flat",
      chunk_size: 800,
      chunk_overlap: 64,
      split_separator: "。",
      cleaning_rules: ["trim_lines"],
      auto_index: false,
    })
    expect(calls[0].body).toBeUndefined()
    expect(JSON.parse(calls[1].body!)).toEqual({
      strategy: "flat",
      chunk_size: 800,
      chunk_overlap: 64,
      split_separator: "。",
      cleaning_rules: ["trim_lines"],
      auto_index: false,
    })
  })

  test("indexes and toggles document active state", async () => {
    const calls: Array<{ method: string; body: string }> = []
    stubFetch((_url, init) => {
      calls.push({
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      })
      return new Response("{}", { status: 200 })
    })

    await knowledgeApi.indexKnowledgeDocument("tok", "ws-1", "kb-1", "doc-1")
    await knowledgeApi.setKnowledgeDocumentActive("tok", "ws-1", "kb-1", "doc-1", false)
    expect(calls[0].method).toBe("POST")
    expect(calls[1].method).toBe("PATCH")
    expect(JSON.parse(calls[1].body)).toEqual({ is_active: false })
  })

  test("downloads documents with the auth header and a blob", async () => {
    const calls: Array<{ url: string; auth: string | null }> = []
    const anchorPrototype = HTMLAnchorElement.prototype
    const originalClick = anchorPrototype.click
    const clicked: string[] = []
    anchorPrototype.click = function () {
      clicked.push(this.href)
    }
    try {
      stubFetch((url, init) => {
        const headers = new Headers(init?.headers)
        calls.push({ url, auth: headers.get("Authorization") })
        return new Response(new Blob(["content"]), { status: 200 })
      })

      await knowledgeApi.downloadKnowledgeDocument("tok", "ws-1", "kb-1", "doc-1", "a.txt")
      expect(calls[0].url).toBe(
        "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/documents/doc-1/download",
      )
      expect(calls[0].auth).toBe("Bearer tok")
      expect(clicked).toHaveLength(1)
      expect(clicked[0]).toMatch(/^blob:/)
    } finally {
      anchorPrototype.click = originalClick
    }
  })

  test("rejects downloads with a non-ok response", async () => {
    stubFetch(() => new Response("nope", { status: 500, statusText: "Server Error" }))
    await expect(
      knowledgeApi.downloadKnowledgeDocument("tok", "ws-1", "kb-1", "doc-1", "a.txt"),
    ).rejects.toThrow("Server Error")
  })

  test("loads document chunks across pages", async () => {
    const urls: string[] = []
    stubFetch((url) => {
      urls.push(url)
      if (url.includes("offset=0")) {
        return new Response(JSON.stringify(Array.from({ length: 200 }, () => ({}))), {
          status: 200,
        })
      }
      return new Response(JSON.stringify([{}, {}, {}]), { status: 200 })
    })

    const chunks = await knowledgeApi.listKnowledgeDocumentChunks("tok", "ws-1", "kb-1", "doc-1")
    expect(chunks).toHaveLength(203)
    expect(urls).toEqual([
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/documents/doc-1/chunks?limit=200&offset=0",
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/documents/doc-1/chunks?limit=200&offset=200",
    ])
  })

  test("loads knowledge assets as blobs", async () => {
    let calledUrl = ""
    stubFetch((url) => {
      calledUrl = url
      return new Response(new Blob(["img"]), { status: 200 })
    })
    const blob = await knowledgeApi.loadKnowledgeAsset("tok", "ws-1", "kb-1", "doc-1", "asset-1")
    expect(calledUrl).toBe(
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/documents/doc-1/assets/asset-1",
    )
    expect(await blob.text()).toBe("img")
  })

  test("lists tasks for a knowledge base or a document", async () => {
    const urls: string[] = []
    stubFetch((url) => {
      urls.push(url)
      return new Response("[]", { status: 200 })
    })
    await knowledgeApi.listKnowledgeTasks("tok", "ws-1", "kb-1")
    await knowledgeApi.listKnowledgeTasks("tok", "ws-1", "kb-1", "doc-1")
    expect(urls).toEqual([
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/tasks",
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/documents/doc-1/tasks",
    ])
  })

  test("retries tasks and rebuilds the index", async () => {
    const calls: Array<{ url: string; method: string }> = []
    stubFetch((url, init) => {
      calls.push({ url, method: init?.method ?? "GET" })
      return new Response("{}", { status: 200 })
    })
    await knowledgeApi.retryKnowledgeTask("tok", "ws-1", "kb-1", "task-1")
    await knowledgeApi.rebuildKnowledgeIndex("tok", "ws-1", "kb-1")
    expect(calls[0]).toEqual({
      url: "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/tasks/task-1/retry",
      method: "POST",
    })
    expect(calls[1]).toEqual({
      url: "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/rebuild-index",
      method: "POST",
    })
  })

  test("queries the knowledge base with the given limit", async () => {
    const calls: Array<{ url: string; body: string }> = []
    stubFetch((url, init) => {
      calls.push({ url, body: String(init?.body ?? "") })
      return new Response("[]", { status: 200 })
    })
    await knowledgeApi.queryKnowledgeBase("tok", "ws-1", "kb-1", {
      query: "hello",
      limit: 3,
    })
    expect(calls[0].url).toBe("/api/v1/workspaces/ws-1/knowledge-bases/kb-1/query")
    expect(JSON.parse(calls[0].body)).toEqual({ query: "hello", limit: 3 })
  })

  test("inspects retrieval with production query controls", async () => {
    const calls: Array<{ url: string; body: string }> = []
    stubFetch((url, init) => {
      calls.push({ url, body: String(init?.body ?? "") })
      return new Response('{"hits":[],"trace":{}}', { status: 200 })
    })
    await knowledgeApi.inspectKnowledgeBase("tok", "ws-1", "kb-1", {
      query: "hello",
      limit: 7,
      search_mode: "keywords",
      similarity: 0.4,
      include_references: true,
    })
    expect(calls[0].url).toBe(
      "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/query/inspect",
    )
    expect(JSON.parse(calls[0].body)).toEqual({
      query: "hello",
      limit: 7,
      search_mode: "keywords",
      similarity: 0.4,
      include_references: true,
    })
  })

  test("tests knowledge base models", async () => {
    let body = ""
    stubFetch((_url, init) => {
      body = String(init?.body ?? "")
      return new Response("{}", { status: 200 })
    })
    await knowledgeApi.testKnowledgeBaseModels("tok", "ws-1", "kb-1")
    expect(JSON.parse(body)).toEqual({ query: "Hello", documents: ["Hello"] })
  })

  test("manages knowledge base permissions", async () => {
    const calls: Array<{ url: string; method: string; body: string }> = []
    stubFetch((url, init) => {
      calls.push({
        url,
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      })
      return new Response("{}", { status: 200 })
    })

    await knowledgeApi.listKnowledgeBasePermissions("tok", "ws-1", "kb-1")
    await knowledgeApi.upsertKnowledgeBasePermission("tok", "ws-1", "kb-1", "u-1", "edit")
    await knowledgeApi.revokeKnowledgeBasePermission("tok", "ws-1", "kb-1", "u-1")

    expect(calls[0]).toMatchObject({
      url: "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/permissions",
      method: "GET",
    })
    expect(calls[1]).toMatchObject({
      url: "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/permissions/u-1",
      method: "PUT",
    })
    expect(JSON.parse(calls[1].body)).toEqual({ permission: "edit" })
    expect(calls[2]).toMatchObject({
      url: "/api/v1/workspaces/ws-1/knowledge-bases/kb-1/permissions/u-1",
      method: "DELETE",
    })
  })

  test("throws ApiError with the detail message from error responses", async () => {
    stubFetch(() =>
      new Response(JSON.stringify({ detail: "denied" }), { status: 403 }),
    )
    await expect(
      knowledgeApi.listKnowledgeBases("tok", "ws-1"),
    ).rejects.toMatchObject({ status: 403, message: "denied" })
  })

  test("propagates a parse error for non-JSON success bodies", async () => {
    stubFetch(() => new Response("<html>oops</html>", { status: 200 }))
    await expect(
      knowledgeApi.listKnowledgeBases("tok", "ws-1"),
    ).rejects.toThrow(SyntaxError)
  })
})

// ---------------------------------------------------------------------------
// lib/api/llm.ts
// ---------------------------------------------------------------------------

describe("lib/api/llm", () => {
  test("lists the model provider catalog with and without a model type", async () => {
    const urls: string[] = []
    stubFetch((url) => {
      urls.push(url)
      return new Response("[]", { status: 200 })
    })
    await llmApi.listModelProviderCatalog("tok")
    await llmApi.listModelProviderCatalog("tok", "EMBEDDING")
    expect(urls[0]).toBe("/api/v1/model-providers")
    expect(urls[1]).toBe("/api/v1/model-providers?model_type=EMBEDDING")
  })

  test("lists provider model types and base models", async () => {
    const urls: string[] = []
    stubFetch((url) => {
      urls.push(url)
      return new Response("[]", { status: 200 })
    })
    await llmApi.listModelProviderModelTypes("tok", "openai")
    await llmApi.listModelProviderBaseModels("tok", "openai", "EMBEDDING")
    expect(urls[0]).toBe(
      "/api/v1/model-providers/model-types?provider=openai",
    )
    expect(urls[1]).toBe(
      "/api/v1/model-providers/base-models?provider=openai&model_type=EMBEDDING",
    )
  })

  test("fetches the credential form for a provider", async () => {
    let url = ""
    stubFetch((requestUrl) => {
      url = requestUrl
      return new Response("[]", { status: 200 })
    })
    await llmApi.getModelProviderForm("tok", "openai")
    expect(url).toBe("/api/v1/model-providers/credential-form?provider=openai")
  })

  test("lists registered models with query parameters", async () => {
    const urls: string[] = []
    stubFetch((url) => {
      urls.push(url)
      return new Response("[]", { status: 200 })
    })
    await llmApi.listRegisteredModels("tok", "ws-1")
    await llmApi.listRegisteredModels("tok", "ws-1", { limit: 10, offset: 20 })
    expect(urls[0]).toBe("/api/v1/workspaces/ws-1/models")
    expect(urls[1]).toBe("/api/v1/workspaces/ws-1/models?limit=10&offset=20")
  })

  test("creates, updates and deletes registered models", async () => {
    const calls: Array<{ url: string; method: string; body: string }> = []
    stubFetch((url, init) => {
      calls.push({
        url,
        method: init?.method ?? "GET",
        body: String(init?.body ?? ""),
      })
      return new Response("{}", { status: 200 })
    })

    const payload = {
      name: "m",
      provider: "openai",
      provider_type: "openai",
      model_type: "EMBEDDING",
      model_name: "text-embedding-3",
      credential: { api_key: "k" },
    }
    await llmApi.createRegisteredModel("tok", "ws-1", payload)
    await llmApi.updateRegisteredModel("tok", "ws-1", "model-1", { name: "m2" })
    await llmApi.deleteRegisteredModel("tok", "ws-1", "model-1")

    expect(calls[0]).toMatchObject({
      url: "/api/v1/workspaces/ws-1/models",
      method: "POST",
    })
    expect(JSON.parse(calls[0].body)).toEqual(payload)
    expect(calls[1]).toMatchObject({
      url: "/api/v1/workspaces/ws-1/models/model-1",
      method: "PATCH",
    })
    expect(JSON.parse(calls[1].body)).toEqual({ name: "m2" })
    expect(calls[2]).toMatchObject({
      url: "/api/v1/workspaces/ws-1/models/model-1",
      method: "DELETE",
    })
  })
})

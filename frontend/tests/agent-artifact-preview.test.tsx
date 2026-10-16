/* @jsxImportSource react */
import { afterEach, beforeEach, expect, spyOn, test } from "bun:test"
import { act, useState, type ReactElement, type ReactNode } from "react"

import {
  AgentArtifactPreviewPanel,
  AgentArtifactPreviews,
} from "@/components/agents/artifacts/agent-artifact-previews"
import {
  AgentArtifactPreviewContext,
  useAgentArtifactPreview,
} from "@/components/agents/artifacts/agent-artifact-preview-context"
import { AgentAnswer } from "@/components/agents/agent-source-references"
import { useLanguage } from "@/contexts/language-provider"
import {
  previewArtifactsForEvents,
  htmlPreviewDocument,
  MAX_PREVIEW_BYTES,
  PREVIEW_MIME_TYPES,
  type ArtifactEvent,
} from "@/lib/agent-artifacts"
import {
  cleanup,
  fireEvent,
  renderPage as renderWithLanguage,
  screen,
  waitFor,
  withFetch,
  within,
} from "./helpers/dom"
import {
  filePreviewDocument,
  validateOfficeArchive,
} from "@/components/agents/artifacts/preview-protocol"
import { openSpreadsheet } from "@/components/agents/artifacts/preview-runtime/spreadsheet"
import ExcelJS from "exceljs"

function PreviewWorkspace({
  children,
  scope = "conversation-1",
}: {
  children: ReactNode
  scope?: string
}) {
  const preview = useAgentArtifactPreview(scope)
  return (
    <AgentArtifactPreviewContext value={preview}>
      <section>{children}</section>
      <AgentArtifactPreviewPanel />
    </AgentArtifactPreviewContext>
  )
}

function renderPage(ui: ReactElement) {
  return renderWithLanguage(<PreviewWorkspace>{ui}</PreviewWorkspace>)
}

const originalFetch = globalThis.fetch
beforeEach(() => {
  const testWindow = window as unknown as {
    happyDOM: {
      setURL: (url: string) => void
      settings: { handleDisabledFileLoadingAsSuccess: boolean }
    }
  }
  testWindow.happyDOM.setURL("https://nexaflow.example/")
  testWindow.happyDOM.settings.handleDisabledFileLoadingAsSuccess = true
})
afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
})

test.each([
  ["pdf", "pdf_skill"],
  ["docx", "documents_skill"],
  ["xlsx", "spreadsheets_skill"],
  ["pptx", "pptx_skill"],
] as const)(
  "opens %s in the right panel only on request, with a scoped byte transfer",
  async (format, tool) => {
    let loads = 0
    withFetch(() => {
      loads++
      return new Response("fixture", {
        headers: { "Content-Type": PREVIEW_MIME_TYPES[format] },
      })
    })
    renderPage(
      <AgentArtifactPreviews
        events={[
          {
            tool_name: tool,
            status: "succeeded",
            output: {
              filename: `report.${format}`,
              download_url: "/api/v1/artifacts/file-token",
            },
          },
        ]}
      />
    )
    expect(loads).toBe(0)
    fireEvent.click(
      screen.getByRole("button", { name: `预览文件：report.${format}` })
    )
    const frame = (await screen.findByTitle(
      `文件预览：report.${format}`
    )) as HTMLIFrameElement
    expect(
      screen
        .getByRole("complementary", {
          name: `文件预览：report.${format}`,
        })
        .contains(frame)
    ).toBe(true)
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts")
    expect(frame.srcdoc).not.toContain("file-token")
    await act(async () => {})
    const channel = /data-channel="([^"]+)"/.exec(frame.srcdoc)![1]
    const send = spyOn(frame.contentWindow!, "postMessage").mockImplementation(
      () => {}
    )
    const receive = (
      type: string,
      overrides: Record<string, unknown> = {},
      source: Window | null = frame.contentWindow
    ) => {
      act(() => {
        window.dispatchEvent(
          new window.MessageEvent("message", {
            source,
            origin: "null",
            data: { channel, type, ...overrides },
          })
        )
      })
    }
    receive("ready", { channel: "wrong-channel" })
    receive("ready", {}, window)
    expect(send).not.toHaveBeenCalled()
    receive("ready")
    receive("ready")
    expect(send).toHaveBeenCalledTimes(1)
    const message = send.mock.calls[0][0] as {
      bytes: ArrayBuffer
      format: string
    }
    expect(message.format).toBe(format)
    expect(new TextDecoder().decode(message.bytes)).toBe("fixture")
    expect(JSON.stringify(message)).not.toContain("file-token")
    receive("rendered", {
      metadata: {
        pageCount: 2,
        sheets: ["Summary", "Detail"],
        truncated: true,
      },
    })
    await screen.findByText("1 / 2")
    fireEvent.click(screen.getByRole("button", { name: "下一页" }))
    expect(screen.getByText("2 / 2")).toBeTruthy()
    fireEvent.change(screen.getByLabelText("选择工作表"), {
      target: { value: "1" },
    })
    fireEvent.click(screen.getByRole("button", { name: "放大" }))
    expect(send.mock.calls.at(-1)?.[0]).toMatchObject({
      type: "position",
      position: { page: 2, sheet: 1, zoom: 1.25 },
    })
    fireEvent.click(screen.getByRole("button", { name: "关闭" }))
    expect(document.querySelector("iframe")).toBeNull()
    expect(loads).toBe(1)
    send.mockRestore()
  }
)

test("viewer CSP allows only its bundled assets and rejects invalid channels", () => {
  const doc = filePreviewDocument("https://app.example", "channel-123")
  expect(doc).toContain("connect-src https://app.example/file-preview/ blob:")
  expect(doc).toContain("default-src 'none'")
  expect(doc).toContain("frame-src 'none'")
  expect(doc).not.toContain("'unsafe-eval'")
  expect(doc).not.toContain("allow-same-origin")
  expect(() =>
    filePreviewDocument("https://app.example", '"><script>')
  ).toThrow()
})

test("Office archive guard rejects excessive expansion, encryption and malformed packages", async () => {
  const workbook = new ExcelJS.Workbook()
  workbook.addWorksheet("Sheet1").addRow(["Test"])
  const bytes = new Uint8Array(await workbook.xlsx.writeBuffer()).buffer
  expect(() => validateOfficeArchive(bytes)).not.toThrow()
  expect(() => validateOfficeArchive(new ArrayBuffer(2))).toThrow()
  const oversized = bytes.slice(0)
  const view = new DataView(oversized)
  const directory = view.getUint32(oversized.byteLength - 6, true)
  view.setUint32(directory + 24, 64 * 1024 * 1024, true)
  expect(() => validateOfficeArchive(oversized)).toThrow()
  const encrypted = bytes.slice(0)
  new DataView(encrypted).setUint16(directory + 8, 1, true)
  expect(() => validateOfficeArchive(encrypted)).toThrow()
})

test("renders worksheet values as text, uses cached formulas, switches sheets and bounds the table", async () => {
  const workbook = new ExcelJS.Workbook()
  const first = workbook.addWorksheet("Summary")
  first.addRow([
    "<script>window.injected=1</script>",
    { formula: "1+2", result: 3 },
  ])
  first.getCell("A501").value = "Beyond preview"
  workbook.addWorksheet("Detail").addRow(["Second sheet"])
  workbook.addWorksheet("Private", { state: "hidden" }).addRow(["Hidden"])
  const container = document.createElement("div")
  const viewer = await openSpreadsheet(
    container,
    new Uint8Array(await workbook.xlsx.writeBuffer()).buffer,
    "Empty"
  )
  viewer.render({ page: 1, sheet: 0, zoom: 1 })
  expect(viewer.metadata.sheets).toEqual(["Summary", "Detail"])
  expect(container.querySelector("script")).toBeNull()
  expect(container.textContent).toContain("<script>")
  expect(
    container.querySelector("tbody tr td:nth-of-type(2)")?.textContent
  ).toBe("3")
  expect(container.querySelectorAll("tbody tr")).toHaveLength(500)
  expect(viewer.metadata.truncated).toBe(true)
  viewer.render({ page: 1, sheet: 1, zoom: 1.25 })
  expect(container.textContent).toContain("Second sheet")
  expect(viewer.metadata.truncated).toBe(false)
  viewer.destroy()
  expect(container.childElementCount).toBe(0)
})

const file = {
  filename: "page.html",
  download_url: "/api/v1/artifacts/signed-token",
}
const event: ArtifactEvent = {
  tool_name: "create_artifact",
  status: "succeeded",
  output: file,
}
const html =
  "<!doctype html><html><head><style>body { color: red }</style></head><body><button onclick=\"this.textContent='done'\">Try</button></body></html>"
const htmlResponse = () =>
  new Response(html, {
    headers: { "Content-Type": "text/html; charset=utf-8" },
  })

test("selects only platform HTML files from successful file tools, including bundles", () => {
  const results = previewArtifactsForEvents([
    event,
    {
      ...event,
      tool_name: "bash",
      output: {
        artifacts: [
          file,
          { filename: "demo.HTM", download_url: "/api/v1/artifacts/other" },
          null,
        ],
      },
    },
    {
      ...event,
      tool_name: "run_skill_script",
      output: {
        artifacts: [{ ...file, download_url: "/api/v1/artifacts/rewrite" }],
      },
    },
    {
      ...event,
      output: {
        filename: "readme.txt",
        download_url: "/api/v1/artifacts/text",
      },
    },
    { ...event, status: "running" },
    { ...event, status: "failed" },
    {
      ...event,
      tool_name: "remote_mcp",
      output: { ...file, filename: "remote.html" },
    },
    { ...event, output: null },
    { ...event, output: "page.html" },
  ])
  expect(results).toEqual([
    {
      filename: "page.html",
      downloadUrl: "/api/v1/artifacts/rewrite",
      format: "html",
    },
    {
      filename: "demo.HTM",
      downloadUrl: "/api/v1/artifacts/other",
      format: "html",
    },
  ])
})

test("rejects external, ambiguous, or non-download URLs even when labeled HTML", () => {
  for (const url of [
    "https://evil.test/api/v1/artifacts/token",
    "//evil.test/page.html",
    "javascript:alert(1)",
    "/api/v1/artifacts/token/preview",
    "/api/v1/artifacts/../users",
    "/api/v1/artifacts/token?redirect=evil",
    "/api/v1/artifacts/",
    "/api/v1/artifacts/token#fragment",
  ]) {
    expect(
      previewArtifactsForEvents([
        { ...event, output: { ...file, download_url: url } },
      ])
    ).toEqual([])
  }
  expect(
    previewArtifactsForEvents([
      event,
      { ...event, output: { ...file, filename: "alias.html" } },
    ])
  ).toHaveLength(1)
})

test("places the restrictive CSP before all generated markup and anchors locally", () => {
  const doc = htmlPreviewDocument(
    '<script>window.x=1</script><meta http-equiv="Content-Security-Policy" content="default-src *">'
  )
  expect(doc.indexOf("default-src 'none'")).toBeLessThan(
    doc.indexOf("<script>")
  )
  for (const rule of [
    "connect-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "worker-src 'none'",
    "form-action 'none'",
    "script-src 'unsafe-inline'",
  ])
    expect(doc).toContain(rule)
  expect(doc).toContain('<base href="about:srcdoc">')
  expect(doc).toContain('name="referrer" content="no-referrer"')
  expect(doc).not.toContain("unsafe-eval")
})

test("loads signed HTML without cookies and renders only in an opaque sandbox", async () => {
  let loads = 0
  withFetch((url, init) => {
    expect(url).toBe("/api/v1/artifacts/download")
    expect(init?.method).toBe("POST")
    expect(init?.credentials).toBe("omit")
    expect(JSON.parse(String(init?.body))).toEqual({ token: "signed-token" })
    loads++
    return htmlResponse()
  })
  renderPage(<AgentArtifactPreviews events={[event]} />)
  expect(document.querySelector("iframe")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  const frame = await screen.findByTitle("文件预览：page.html")
  expect(frame.tagName).toBe("IFRAME")
  expect(frame.getAttribute("sandbox")).toBe("allow-scripts")
  expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer")
  expect(frame.getAttribute("srcdoc")).toContain(html)
  expect(frame.getAttribute("srcdoc")).not.toContain("signed-token")
  expect(document.querySelector("button[onclick]")).toBeNull()
  expect(
    within(screen.getByRole("complementary"))
      .getByRole("link", { name: "下载原文" })
      .getAttribute("download")
  ).toBe("")

  expect(
    screen.getByRole("complementary", { name: "文件预览：page.html" })
  ).toBeTruthy()
  expect(screen.queryByRole("dialog")).toBeNull()
  expect(document.querySelector("[data-slot='dialog-overlay']")).toBeNull()
  for (const iframe of screen.getAllByTitle("文件预览：page.html"))
    expect(iframe.getAttribute("sandbox")).toBe("allow-scripts")
  fireEvent.click(screen.getByRole("button", { name: "关闭" }))
  await waitFor(() => expect(screen.queryByRole("complementary")).toBeNull())
  expect(document.querySelector("iframe")).toBeNull()
  expect(loads).toBe(1)
})

test("shows an expired page without mounting content, and keeps its download link", async () => {
  withFetch(() => new Response("not found", { status: 404 }))
  renderPage(<AgentArtifactPreviews events={[event]} />)
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  expect(
    await screen.findByText("文件已过期或不可用，请重新生成。")
  ).toBeTruthy()
  expect(document.querySelector("iframe")).toBeNull()
  expect(
    within(screen.getByRole("complementary")).getByRole("link", {
      name: "下载原文",
    })
  ).toBeTruthy()
  expect(screen.queryByRole("button", { name: "重试" })).toBeNull()
})

test("allows retry after a transient preview load failure", async () => {
  let loads = 0
  withFetch(() =>
    ++loads === 1
      ? new Response("unavailable", { status: 503 })
      : htmlResponse()
  )
  renderPage(<AgentArtifactPreviews events={[event]} />)
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  expect(
    await screen.findByText("文件预览失败，可重试或下载原文件查看。")
  ).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "重试" }))
  expect(await screen.findByTitle("文件预览：page.html")).toBeTruthy()
  expect(loads).toBe(2)
})

test("rejects mislabeled and oversized files before executing a preview", async () => {
  for (const response of [
    new Response(html, { headers: { "Content-Type": "text/plain" } }),
    new Response("x".repeat(MAX_PREVIEW_BYTES + 1), {
      headers: { "Content-Type": "text/html" },
    }),
  ]) {
    withFetch(() => response)
    renderPage(<AgentArtifactPreviews events={[event]} />)
    fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
    expect(
      await screen.findByText("文件预览失败，可重试或下载原文件查看。")
    ).toBeTruthy()
    expect(document.querySelector("iframe")).toBeNull()
    cleanup()
  }
})

test("keeps the loaded frame stable while answer text streams and does not execute code fences", async () => {
  let loads = 0
  withFetch(() => {
    loads++
    return htmlResponse()
  })
  function StreamingAnswer() {
    const { t } = useLanguage()
    const [content, setContent] = useState("First")
    return (
      <>
        <button onClick={() => setContent("First second")}>append</button>
        <AgentAnswer content={content} events={[event]} t={t} />
      </>
    )
  }
  renderPage(<StreamingAnswer />)
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  const frame = await screen.findByTitle("文件预览：page.html")
  fireEvent.click(screen.getByText("append"))
  expect(screen.getByTitle("文件预览：page.html")).toBe(frame)
  expect(loads).toBe(1)
  cleanup()
  function CodeAnswer() {
    const { t } = useLanguage()
    return (
      <AgentAnswer content={"```html\n<script>alert(1)</script>\n```"} t={t} />
    )
  }
  renderPage(<CodeAnswer />)
  expect(document.querySelector("iframe")).toBeNull()
})

test("aborts an obsolete file request and ignores its late result after a rewrite", async () => {
  let finish: ((response: Response) => void) | undefined
  let signal: AbortSignal | undefined
  withFetch((_url, init) => {
    if (String(init?.body).includes("signed-token")) {
      signal = init?.signal ?? undefined
      return new Promise<Response>((resolve) => {
        finish = resolve
      })
    }
    return new Response("<h1>Updated</h1>", {
      headers: { "Content-Type": "text/html" },
    })
  })
  function RewritingPage() {
    const [rewritten, setRewritten] = useState(false)
    return (
      <>
        <button onClick={() => setRewritten(true)}>rewrite</button>
        <AgentArtifactPreviews
          events={[
            {
              ...event,
              output: rewritten
                ? { ...file, download_url: "/api/v1/artifacts/rewritten" }
                : file,
            },
          ]}
        />
      </>
    )
  }
  renderPage(<RewritingPage />)
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  fireEvent.click(screen.getByText("rewrite"))
  await waitFor(() => expect(signal?.aborted).toBe(true))
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  const frame = await screen.findByTitle("文件预览：page.html")
  finish?.(htmlResponse())
  await waitFor(() => expect(frame.getAttribute("srcdoc")).toContain("Updated"))
})

test("shares a single non-modal preview across answers and leaves the composer usable", async () => {
  withFetch(() => htmlResponse())
  let sent = ""
  function Chat() {
    const [draft, setDraft] = useState("")
    return (
      <>
        <AgentArtifactPreviews events={[event]} />
        <AgentArtifactPreviews
          events={[
            {
              ...event,
              output: {
                filename: "other.html",
                download_url: "/api/v1/artifacts/other",
              },
            },
          ]}
        />
        <form
          onSubmit={(e) => {
            e.preventDefault()
            sent = draft
          }}
        >
          <textarea
            aria-label="Question"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit">Send</button>
        </form>
      </>
    )
  }
  renderPage(<Chat />)
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  const firstFrame = await screen.findByTitle("文件预览：page.html")
  const input = screen.getByRole("textbox", { name: "Question" })
  input.focus()
  expect(document.activeElement).toBe(input)
  expect(input.closest("[aria-hidden='true'], [inert]")).toBeNull()
  fireEvent.change(input, { target: { value: "Make the heading bigger" } })
  fireEvent.click(screen.getByRole("button", { name: "Send" }))
  expect(sent).toBe("Make the heading bigger")
  expect(screen.getByTitle("文件预览：page.html")).toBe(firstFrame)
  const second = screen.getByRole("button", { name: "预览文件：other.html" })
  fireEvent.click(second)
  await screen.findByTitle("文件预览：other.html")
  expect(document.querySelectorAll("iframe")).toHaveLength(1)
  expect(screen.getAllByRole("complementary")).toHaveLength(1)
  expect(screen.queryByTitle("文件预览：page.html")).toBeNull()
  fireEvent.keyDown(screen.getByRole("heading", { name: "other.html" }), {
    key: "Escape",
  })
  await waitFor(() => expect(document.activeElement).toBe(second))
  expect(screen.queryByRole("complementary")).toBeNull()
  expect((input as HTMLTextAreaElement).value).toBe("Make the heading bigger")
})

test("keeps a loaded preview when a follow-up moves its card into a previous answer", async () => {
  let loads = 0
  withFetch(() => {
    loads++
    return htmlResponse()
  })
  function Handoff() {
    const [handedOff, setHandedOff] = useState(false)
    return (
      <>
        <button onClick={() => setHandedOff(true)}>Follow up</button>
        {handedOff ? (
          <article>
            <AgentArtifactPreviews events={[event]} />
          </article>
        ) : null}
        <AgentArtifactPreviews events={handedOff ? [] : [event]} />
      </>
    )
  }
  renderPage(<Handoff />)
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  const frame = await screen.findByTitle("文件预览：page.html")
  fireEvent.click(screen.getByRole("button", { name: "Follow up" }))
  await act(async () => {})
  expect(screen.getByTitle("文件预览：page.html")).toBe(frame)
  expect(loads).toBe(1)
  const newCard = screen.getByRole("button", { name: "预览文件：page.html" })
  expect(newCard.getAttribute("aria-expanded")).toBe("true")
  fireEvent.click(screen.getByRole("button", { name: "关闭" }))
  await waitFor(() => expect(document.activeElement).toBe(newCard))
})

test("discards previews and cancels loading on a conversation change without restoring stale state", async () => {
  let signal: AbortSignal | null | undefined
  withFetch((_url, init) => {
    signal = init?.signal
    return new Promise<Response>(() => {})
  })
  function Conversations() {
    const [scope, setScope] = useState("one")
    return (
      <PreviewWorkspace scope={scope}>
        <button
          onClick={() => setScope((value) => (value === "one" ? "two" : "one"))}
        >
          Switch
        </button>
        <AgentArtifactPreviews events={[event]} />
      </PreviewWorkspace>
    )
  }
  renderWithLanguage(<Conversations />)
  fireEvent.click(screen.getByRole("button", { name: "预览文件：page.html" }))
  expect(screen.getByText("正在加载文件预览")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Switch" }))
  expect(signal?.aborted).toBe(true)
  expect(screen.queryByRole("complementary")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Switch" }))
  expect(screen.queryByRole("complementary")).toBeNull()
})

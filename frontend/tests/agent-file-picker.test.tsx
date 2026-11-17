/* @jsxImportSource react */
import { afterEach, expect, spyOn, test } from "bun:test"
import { act, renderHook } from "@testing-library/react"
import type { DragEvent } from "react"
import { AgentFilePicker } from "@/components/agents/agent-file-picker"
import { useAgentFileDrop } from "@/components/agents/use-agent-file-drop"
import {
  agentUploadPath,
  agentUploadForm,
  droppedAgentFiles,
} from "@/lib/agent-upload"
import {
  appendAttachmentFiles,
  RunAttachmentCards,
} from "@/components/agents/agent-attachment-list"
import type { TFunction } from "@/i18n"
import { cleanup, fireEvent, renderPage, screen, waitFor } from "./helpers/dom"

const t: TFunction = (key) => key
function nested(name: string, path: string) {
  const file = new File(["contents"], name, { type: "text/plain" })
  Object.defineProperty(file, "webkitRelativePath", { value: path })
  return file
}

afterEach(cleanup)

test("labels large standalone attachments as text excerpts", () => {
  renderPage(
    <RunAttachmentCards
      t={t}
      attachments={[
        {
          filename: "large.txt",
          size_bytes: 6 * 1024 * 1024,
          category: "document",
        },
        { filename: "folder/readme.md", size_bytes: 20, category: "document" },
      ]}
    />
  )
  expect(screen.getByText("仅文本摘录（原文件超过 5 MiB）")).toBeTruthy()
  expect(screen.getByText("文档")).toBeTruthy()
})

test("uploads selected folders with paths, excluding caches and Git data", () => {
  let files: File[] = []
  renderPage(
    <AgentFilePicker
      disabled={false}
      t={t}
      onFiles={(added) => {
        files = added
      }}
    />
  )
  const folder = screen.getByLabelText("上传文件夹")
  expect(folder.hasAttribute("webkitdirectory")).toBe(true)
  fireEvent.change(folder, {
    target: {
      files: [
        nested("index.ts", "app/src/index.ts"),
        nested("package.json", "app/package.json"),
        nested("config", "app/.git/config"),
        nested("index.js", "app/node_modules/index.js"),
      ],
    },
  })
  expect(files.map(agentUploadPath)).toEqual([
    "app/src/index.ts",
    "app/package.json",
  ])
  expect(
    (agentUploadForm(files).getAll("files") as File[]).map((file) => file.name)
  ).toEqual(["app/src/index.ts", "app/package.json"])
  expect(appendAttachmentFiles([], files)).toHaveLength(2)
})

test("attachment menu opens the folder picker and disables while running", async () => {
  renderPage(<AgentFilePicker disabled={false} t={t} onFiles={() => {}} />)
  const folder = screen.getByLabelText("上传文件夹") as HTMLInputElement
  const click = spyOn(folder, "click").mockImplementation(() => {})
  fireEvent.keyDown(screen.getByRole("button", { name: "添加附件" }), {
    key: "ArrowDown",
  })
  await waitFor(() =>
    expect(screen.getByRole("menuitem", { name: "上传文件夹" })).toBeTruthy()
  )
  fireEvent.click(screen.getByRole("menuitem", { name: "上传文件夹" }))
  expect(click).toHaveBeenCalledTimes(1)
  click.mockRestore()
  cleanup()
  renderPage(<AgentFilePicker disabled t={t} onFiles={() => {}} />)
  expect(
    (screen.getByRole("button", { name: "添加附件" }) as HTMLButtonElement)
      .disabled
  ).toBe(true)
})

test("dropped directories preserve nested paths across reader batches", async () => {
  const file = new File(["export {}"], "main.ts")
  const entry = {
    name: "main.ts",
    isFile: true,
    file: (done: (file: File) => void) => done(file),
  }
  let calls = 0
  const directory = {
    name: "app",
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (done: (entries: unknown[]) => void) =>
        done(calls++ ? [] : [entry]),
    }),
  }
  const files = await droppedAgentFiles({
    items: [{ kind: "file", webkitGetAsEntry: () => directory }],
    files: [],
  } as unknown as DataTransfer)
  expect(files.map(agentUploadPath)).toEqual(["app/main.ts"])
})

test("drops plain files from items when the browser omits its file list", async () => {
  const file = new File(["contents"], "notes.txt")
  expect(
    await droppedAgentFiles({
      items: [{ kind: "file", getAsFile: () => file }],
      files: [],
    } as unknown as DataTransfer)
  ).toEqual([file])
})

test("does not append a directory after switching conversations", async () => {
  let added: File[] = []
  let complete!: (file: File) => void
  const { result, rerender } = renderHook(
    ({ scope }) =>
      useAgentFileDrop(
        scope,
        false,
        (files) => {
          added = files
        },
        () => {}
      ),
    { initialProps: { scope: "first" } }
  )
  let reading!: Promise<void>
  act(() => {
    reading = result.current.onDrop({
      preventDefault() {},
      dataTransfer: {
        files: [],
        items: [
          {
            kind: "file",
            webkitGetAsEntry: () => ({
              name: "notes.txt",
              isFile: true,
              file: (done: (file: File) => void) => {
                complete = done
              },
            }),
          },
        ],
      },
    } as unknown as DragEvent)
  })
  expect(result.current.isReadingFiles).toBe(true)
  rerender({ scope: "second" })
  rerender({ scope: "first" })
  expect(result.current.isReadingFiles).toBe(false)
  await act(async () => {
    complete(new File(["contents"], "notes.txt"))
    await reading
  })
  expect(added).toHaveLength(0)
})

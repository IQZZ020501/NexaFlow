/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"

import { ResourceFolderTree } from "@/components/resource-folders/resource-folder-tree"
import type { ResourceFolder } from "@/lib/api/resource-folders"
import { LanguageProvider } from "@/contexts/language-provider"
import {
  cleanup,
  fireEvent,
  renderPage,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

const folder = (
  id: string,
  name: string,
  parentId: string | null
): ResourceFolder => ({
  id,
  workspace_id: "ws-1",
  resource_type: "knowledge",
  parent_id: parentId,
  name,
  created_by_user_id: "u-1",
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
})

const folders = [
  folder("root-2", "人事制度", "root-1"),
  folder("root-1", "规章制度", null),
  folder("root-3", "员工手册", "root-1"),
]

function Harness({
  canManage = true,
  onCreate = async () => undefined,
  onRename = async () => undefined,
  onDelete = async () => null,
  onFolderDeleted = () => undefined,
}: {
  canManage?: boolean
  onCreate?: (name: string, parentId: string | null) => Promise<void>
  onRename?: (folderId: string, name: string) => Promise<void>
  onDelete?: (folderId: string) => Promise<string | null | undefined>
  onFolderDeleted?: (folderId: string, parentId: string | null) => void
}) {
  return (
    <LanguageProvider defaultLanguage="zh-Hans">
      <ResourceFolderTree
        folders={folders}
        selectedFolderId={null}
        canManage={canManage}
        onSelect={() => undefined}
        onCreate={onCreate}
        onRename={onRename}
        onDelete={onDelete}
        onFolderDeleted={onFolderDeleted}
      />
    </LanguageProvider>
  )
}

afterEach(() => {
  cleanup()
})

test("renders the sorted hierarchy and hides management without permission", () => {
  const view = renderPage(<Harness />)
  expect(screen.getByText("规章制度")).toBeTruthy()
  expect(screen.getByText("人事制度")).toBeTruthy()
  expect(screen.getByText("员工手册")).toBeTruthy()
  // Children are sorted by name.
  const children = Array.from(view.container.querySelectorAll("span.truncate"))
    .map((node) => node.textContent)
    .filter((name) => ["人事制度", "员工手册"].includes(name ?? ""))
  expect(children).toEqual(["人事制度", "员工手册"])

  cleanup()
  renderPage(<Harness canManage={false} />)
  expect(screen.queryByLabelText("管理文件夹 规章制度")).toBeNull()
  expect(screen.queryByLabelText("新建子文件夹")).toBeNull()
})

test("creates and renames folders through the dialog", async () => {
  const created: Array<[string, string | null]> = []
  const renamed: Array<[string, string]> = []
  renderPage(
    <Harness
      onCreate={async (name, parentId) => {
        created.push([name, parentId])
      }}
      onRename={async (folderId, name) => {
        renamed.push([folderId, name])
      }}
    />
  )

  fireEvent.click(screen.getByLabelText("新建子文件夹"))
  const input = screen.getByPlaceholderText("文件夹名称")
  fireEvent.change(input, { target: { value: "新目录" } })
  fireEvent.submit(input.closest("form")!)
  await waitFor(() => expect(created).toEqual([["新目录", null]]))

  const manageRules = screen.getByLabelText("管理文件夹 规章制度")
  fireEvent.pointerDown(manageRules)
  fireEvent.click(manageRules)
  fireEvent.click(await screen.findByRole("menuitem", { name: "新建子文件夹" }))
  fireEvent.change(screen.getByPlaceholderText("文件夹名称"), {
    target: { value: "子目录" },
  })
  fireEvent.submit(screen.getByPlaceholderText("文件夹名称").closest("form")!)
  await waitFor(() =>
    expect(created).toContainEqual(["子目录", "root-1"])
  )

  const manageHr = screen.getByLabelText("管理文件夹 人事制度")
  fireEvent.pointerDown(manageHr)
  fireEvent.click(manageHr)
  fireEvent.click(await screen.findByRole("menuitem", { name: "重命名" }))
  fireEvent.change(screen.getByPlaceholderText("文件夹名称"), {
    target: { value: "新人事制度" },
  })
  fireEvent.submit(screen.getByPlaceholderText("文件夹名称").closest("form")!)
  await waitFor(() => expect(renamed).toEqual([["root-2", "新人事制度"]]))
})

test("surfaces create errors inside the dialog", async () => {
  renderPage(
    <Harness
      onCreate={async () => {
        throw new Error("boom")
      }}
    />
  )
  fireEvent.click(screen.getByLabelText("新建子文件夹"))
  fireEvent.change(screen.getByPlaceholderText("文件夹名称"), {
    target: { value: "失败" },
  })
  fireEvent.submit(screen.getByPlaceholderText("文件夹名称").closest("form")!)
  expect(await screen.findByText("boom")).toBeTruthy()
})

test("deletes after confirmation and reports the parent", async () => {
  const deleted: Array<[string, string | null]> = []
  renderPage(
    <Harness
      onDelete={async (folderId) => {
        deleted.push([folderId, "root-1"])
        return "root-1"
      }}
      onFolderDeleted={(folderId, parentId) => {
        deleted.push([folderId, parentId])
      }}
    />
  )
  const manageBooklet = screen.getByLabelText("管理文件夹 员工手册")
  fireEvent.pointerDown(manageBooklet)
  fireEvent.click(manageBooklet)
  fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }))
  const confirmDialog = await screen.findByRole("dialog")
  expect(
    within(confirmDialog).getByText(
      "删除文件夹“员工手册”？其中的内容会移动到上一级。"
    )
  ).toBeTruthy()
  fireEvent.click(within(confirmDialog).getByRole("button", { name: "删除" }))
  await waitFor(() =>
    expect(deleted).toEqual([
      ["root-3", "root-1"],
      ["root-3", "root-1"],
    ])
  )
})

test("declined confirmation skips deletion", async () => {
  const deleted: Array<[string, string | null]> = []
  renderPage(
    <Harness
      onDelete={async (folderId) => {
        deleted.push([folderId, "root-1"])
        return "root-1"
      }}
    />
  )
  const manageBooklet = screen.getByLabelText("管理文件夹 员工手册")
  fireEvent.pointerDown(manageBooklet)
  fireEvent.click(manageBooklet)
  fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }))
  fireEvent.click(await screen.findByRole("button", { name: "取消" }))
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(deleted).toEqual([])
})

/* @jsxImportSource react */
import { expect, test } from "bun:test"

import { ResourceFolderTree } from "@/components/resource-folders/resource-folder-tree"
import { fireEvent, renderPage, screen } from "./helpers/dom"

test("renders a full-height nested resource folder tree", () => {
  let selected: string | null = null
  const { container } = renderPage(
    <ResourceFolderTree
      folders={[
        {
          id: "rules",
          workspace_id: "ws-1",
          resource_type: "knowledge",
          parent_id: null,
          name: "规章制度",
          created_by_user_id: "u-1",
          created_at: "2026-08-25T00:00:00Z",
          updated_at: "2026-08-25T00:00:00Z",
        },
        {
          id: "hr",
          workspace_id: "ws-1",
          resource_type: "knowledge",
          parent_id: "rules",
          name: "人事制度",
          created_by_user_id: "u-1",
          created_at: "2026-08-25T00:00:00Z",
          updated_at: "2026-08-25T00:00:00Z",
        },
      ]}
      selectedFolderId={selected}
      canManage={false}
      onSelect={(folderId) => {
        selected = folderId
      }}
      onCreate={async () => undefined}
      onRename={async () => undefined}
      onDelete={async () => null}
    />
  )

  expect(screen.getByText("根目录")).toBeTruthy()
  expect(screen.getByText("规章制度")).toBeTruthy()
  fireEvent.click(screen.getByLabelText("收起"))
  expect(screen.queryByText("人事制度")).toBeNull()
  fireEvent.click(screen.getByLabelText("展开"))
  fireEvent.click(screen.getByText("人事制度"))
  expect(selected as string | null).toBe("hr")
  expect(container.querySelector("aside")?.className).toContain(
    "lg:min-h-[calc(100svh-11rem)]"
  )
})

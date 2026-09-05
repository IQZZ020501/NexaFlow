/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"
import * as React from "react"

import { ResourceBulkMoveBar } from "@/components/resource-folders/resource-bulk-move-bar"
import { cleanup, fireEvent, renderPage, screen } from "./helpers/dom"

afterEach(cleanup)

test("selects the current resource list before enabling a batch move", () => {
  let moves = 0

  function Harness() {
    const [selectedIds, setSelectedIds] = React.useState<string[]>([])
    const [isManaging, setIsManaging] = React.useState(false)
    return (
      <ResourceBulkMoveBar
        resourceIds={["resource-1", "resource-2"]}
        selectedIds={selectedIds}
        isManaging={isManaging}
        onSelectedIdsChange={setSelectedIds}
        onManagingChange={setIsManaging}
        onMove={() => {
          moves += 1
        }}
      />
    )
  }

  renderPage(<Harness />)
  expect(screen.queryByRole("checkbox", { name: "全选" })).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "批量管理" }))
  const move = screen.getByRole("button", { name: "移动到文件夹" })
  expect(move.hasAttribute("disabled")).toBe(true)

  fireEvent.click(screen.getByRole("checkbox", { name: "全选" }))
  expect(screen.getByText("已选择 2 项")).toBeTruthy()
  expect(move.hasAttribute("disabled")).toBe(false)

  fireEvent.click(move)
  expect(moves).toBe(1)

  fireEvent.click(screen.getByRole("button", { name: "取消" }))
  expect(screen.getByRole("button", { name: "批量管理" })).toBeTruthy()
  expect(screen.queryByRole("checkbox", { name: "全选" })).toBeNull()
})

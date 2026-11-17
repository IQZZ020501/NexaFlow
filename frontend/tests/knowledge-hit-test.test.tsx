/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"
import userEvent from "@testing-library/user-event"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { KnowledgeHitTest } from "@/components/knowledge/knowledge-hit-test"
import { jsonResponse, renderPage, resetFetch, withFetch } from "./helpers/dom"

afterEach(() => {
  cleanup()
  resetFetch()
})

test("keeps out-of-range values visible, explains them, and submits corrected numbers", async () => {
  const bodies: unknown[] = []
  withFetch((_url, init) => {
    bodies.push(JSON.parse(String(init?.body)))
    return jsonResponse({ hits: [], trace: null })
  })
  renderPage(
    <KnowledgeHitTest
      token="token"
      workspaceId="ws"
      knowledgeBaseId="kb"
      reportError={() => {}}
      onTested={() => {}}
    />
  )
  const user = userEvent.setup()
  const similarity = screen.getByLabelText("相似度") as HTMLInputElement
  const limit = screen.getByLabelText("返回数量") as HTMLInputElement
  fireEvent.change(screen.getByLabelText("查询内容"), {
    target: { value: "test" },
  })
  await user.clear(similarity)
  await user.type(similarity, "5")
  expect(similarity.value).toBe("5")
  expect(screen.getByText("相似度必须是 0 到 1 之间的数字")).toBeTruthy()
  await user.clear(limit)
  await user.type(limit, "-1")
  expect(limit.value).toBe("-1")
  expect(screen.getByText("返回数量必须是 1 到 20 之间的整数")).toBeTruthy()
  expect(
    (screen.getByRole("button", { name: "测试召回" }) as HTMLButtonElement)
      .disabled
  ).toBe(true)
  expect(bodies).toHaveLength(0)
  fireEvent.change(similarity, { target: { value: "0.63" } })
  fireEvent.change(limit, { target: { value: "3" } })
  fireEvent.click(screen.getByRole("button", { name: "测试召回" }))
  await waitFor(() =>
    expect(bodies).toEqual([
      { query: "test", limit: 3, search_mode: "blend", similarity: 0.63 },
    ])
  )
})

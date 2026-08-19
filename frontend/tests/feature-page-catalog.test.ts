import { describe, expect, test } from "bun:test"

import { pages } from "../src/lib/pages"

const workspacePageKeys = ["apps", "knowledge", "models", "tools"] as const

describe("feature page layout catalog", () => {
  test("defines refreshed workspace layouts for every top-level page", () => {
    expect(pages.map((page) => page.key)).toEqual([...workspacePageKeys])

    for (const page of pages) {
      expect(page.description.length).toBeGreaterThan(12)
      expect(`搜索${page.label}`).toContain("搜索")
      expect(page.emptyTitle).toMatch(/^还没有/)
      expect(page.emptyDescription.length).toBeGreaterThan(20)
      expect(page.dialogFields).toHaveLength(3)
    }

    const apps = pages.find((page) => page.key === "apps")
    const knowledge = pages.find((page) => page.key === "knowledge")
    const models = pages.find((page) => page.key === "models")
    const tools = pages.find((page) => page.key === "tools")

    expect(apps?.actionLabel).toBe("新建应用")
    expect(knowledge?.emptyTitle).toBe("还没有知识库")
    expect(knowledge?.description).toContain("文档")
    expect(models?.label).toContain("模型")
    expect(tools?.secondaryActionLabel.length).toBeGreaterThan(0)
  })
})

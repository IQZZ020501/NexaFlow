/* @jsxImportSource react */
import { expect, test } from "bun:test"

import { SkillsPage } from "@/components/tools/skills-page"
import { renderPage, screen } from "./helpers/dom"

test("SkillsPage explains Skill-owned execution and Agent selection", () => {
  renderPage(<SkillsPage />)

  expect(screen.getByRole("heading", { name: "Skills" })).toBeTruthy()
  expect(screen.getByText("DOCX")).toBeTruthy()
  expect(screen.getByText("PDF")).toBeTruthy()
  expect(screen.getByText("PPTX")).toBeTruthy()
  expect(screen.getByText("Excel")).toBeTruthy()
  expect(screen.getByText("PPTX · python-pptx")).toBeTruthy()
  expect(screen.getByText("手动安装")).toBeTruthy()
  expect(screen.getByText("运行方式")).toBeTruthy()
  expect(screen.getByText("绑定到 Agent")).toBeTruthy()
  expect(screen.getByText("Skill 自带执行")).toBeTruthy()
  expect(screen.queryByText("创建文件")).toBeNull()
  expect(screen.queryByText("Python 工具")).toBeNull()
  expect(
    screen.getByRole("link", { name: "返回工具" }).getAttribute("href")
  ).toBe("/app/tools")
})

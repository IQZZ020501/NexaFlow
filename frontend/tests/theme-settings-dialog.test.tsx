/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"

import { ThemeSettingsDialog } from "@/components/app/theme-settings-dialog"
import { ThemeProvider } from "@/contexts/theme-provider"
import { cleanup, fireEvent, render, screen } from "./helpers/dom"
import { LanguageProvider } from "@/contexts/language-provider"

afterEach(() => {
  cleanup()
  localStorage.clear()
  document.documentElement.className = ""
  document.documentElement.removeAttribute("style")
  for (const attribute of [
    "palette",
    "font",
    "radius",
    "density",
    "sidebar",
    "layout",
    "content-width",
  ]) {
    document.documentElement.removeAttribute(`data-${attribute}`)
  }
})

test("renders the complete appearance panel and applies selections", () => {
  render(
    <LanguageProvider defaultLanguage="zh-Hans">
      <ThemeProvider defaultTheme="dark">
        <ThemeSettingsDialog open onOpenChange={() => undefined} />
      </ThemeProvider>
    </LanguageProvider>
  )

  expect(screen.getByRole("heading", { name: "主题设置" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "颜色预设" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "字体" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "圆角" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "密度" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "侧边栏" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "布局" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "内容宽度" })).toBeTruthy()

  fireEvent.click(screen.getByRole("button", { name: "Anthropic" }))
  fireEvent.click(screen.getByRole("button", { name: "衬线" }))
  fireEvent.click(screen.getByRole("button", { name: "0.5" }))
  fireEvent.click(screen.getByRole("button", { name: "宽松" }))
  fireEvent.click(screen.getByRole("button", { name: "浮动" }))
  fireEvent.click(screen.getByRole("button", { name: "全屏布局" }))
  fireEvent.click(screen.getByRole("button", { name: "居中" }))

  const root = document.documentElement
  expect(root.dataset.palette).toBe("anthropic")
  expect(root.dataset.font).toBe("serif")
  expect(root.dataset.radius).toBe("0.5")
  expect(root.dataset.density).toBe("relaxed")
  expect(root.dataset.sidebar).toBe("floating")
  expect(root.dataset.layout).toBe("full")
  expect(root.dataset.contentWidth).toBe("centered")
})

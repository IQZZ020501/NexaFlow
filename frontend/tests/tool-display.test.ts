/* @jsxImportSource react */
import { describe, expect, test } from "bun:test"

import type { TFunction } from "../src/i18n"
import {
  toolDisplayDescription,
  toolDisplayName,
  toolSourceDisplayName,
} from "../src/lib/tool-display"

const t = ((key: string) => key) as TFunction

describe("tool display helpers", () => {
  test("localizes built-in tool display names", () => {
    expect(
      toolDisplayName(
        {
          function_name: "inline_python",
          display_name: "Python",
          description: "Runs code",
        },
        t
      )
    ).toBe("Python 代码")
    expect(
      toolDisplayName(
        {
          function_name: "current_time",
          display_name: "Time",
          description: "UTC time",
        },
        t
      )
    ).toBe("当前时间")
  })

  test("falls back to the configured display name for custom tools", () => {
    expect(
      toolDisplayName(
        {
          function_name: "search_web",
          display_name: "Web Search",
          description: "Searches the web",
        },
        t
      )
    ).toBe("Web Search")
  })

  test("localizes built-in tool display descriptions", () => {
    expect(
      toolDisplayDescription(
        {
          function_name: "inline_python",
          display_name: "Python",
          description: "Runs code",
        },
        t
      )
    ).toBe("在工作流沙箱中运行 Python 代码。")
    expect(
      toolDisplayDescription(
        {
          function_name: "current_time",
          display_name: "Time",
          description: "UTC time",
        },
        t
      )
    ).toBe("返回当前 UTC 时间。")
  })

  test("falls back to the configured description for custom tools", () => {
    expect(
      toolDisplayDescription(
        {
          function_name: "search_web",
          display_name: "Web Search",
          description: "Searches the web",
        },
        t
      )
    ).toBe("Searches the web")
  })

  test("localizes built-in tool sources", () => {
    expect(
      toolSourceDisplayName({ kind: "builtin", name: "Builtin" }, t)
    ).toBe("内置")
  })

  test("falls back to the source name for external sources", () => {
    expect(
      toolSourceDisplayName({ kind: "mcp", name: "Search MCP" }, t)
    ).toBe("Search MCP")
  })
})

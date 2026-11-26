import { describe, expect, test } from "bun:test"
import * as React from "react"
import { renderToStaticMarkup } from "react-dom/server"

import { ChartStyle } from "@/components/ui/chart"
import {
  escapeCsvCell,
  isSafeHttpUrl,
  isSafeNavigationUrl,
} from "@/lib/safe-url"

describe("safe-url helpers", () => {
  test("isSafeHttpUrl allows http/https and rejects javascript/data/relative", () => {
    expect(isSafeHttpUrl("https://accounts.example.com/authorize")).toBe(true)
    expect(isSafeHttpUrl("http://127.0.0.1:8000/callback")).toBe(true)
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false)
    expect(isSafeHttpUrl("data:text/html,<script>alert(1)</script>")).toBe(
      false
    )
    expect(isSafeHttpUrl("/relative/path")).toBe(false)
  })

  test("isSafeNavigationUrl allows safe relative paths and rejects protocol-relative", () => {
    expect(isSafeNavigationUrl("/api/v1/auth/enterprise/1/start")).toBe(true)
    expect(isSafeNavigationUrl("https://sso.example.com/start")).toBe(true)
    expect(isSafeNavigationUrl("//evil.example.com")).toBe(false)
    expect(isSafeNavigationUrl("javascript:alert(1)")).toBe(false)
  })

  test("escapeCsvCell neutralizes spreadsheet formula prefixes and escapes quotes", () => {
    expect(escapeCsvCell('=CMD("calc")')).toBe('"\'=CMD(""calc"")"')
    expect(escapeCsvCell("+1+1")).toBe('"\'+1+1"')
    expect(escapeCsvCell("-1")).toBe('"\'-1"')
    expect(escapeCsvCell("@SUM(A1)")).toBe('"\'@SUM(A1)"')
    expect(escapeCsvCell("\t123")).toBe('"\'\t123"')
    expect(escapeCsvCell('normal "text"')).toBe('"normal ""text"""')
  })

  test("ChartStyle drops unsafe identifiers and CSS values", () => {
    const clean = renderToStaticMarkup(
      React.createElement(ChartStyle, {
        id: "chart-safe",
        config: {
          runs: { color: "var(--primary)" },
          "evil}body{": { color: "red" },
          injected: { color: "red; } body { display:none }" },
          urlProp: { color: "url(https://evil.example/a)" },
        },
      })
    )
    expect(clean).toContain("--color-runs: var(--primary);")
    expect(clean).not.toContain("evil")
    expect(clean).not.toContain("injected")
    expect(clean).not.toContain("url(")

    const badId = renderToStaticMarkup(
      React.createElement(ChartStyle, {
        id: "bad] { display:none",
        config: { runs: { color: "red" } },
      })
    )
    expect(badId).toBe("")
  })
})

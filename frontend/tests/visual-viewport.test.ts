import { describe, expect, test } from "bun:test"

import { visualViewportShellStyle } from "@/lib/visual-viewport"

describe("visualViewportShellStyle", () => {
  test("pins the shell to a scrolled visual viewport when the keyboard opens", () => {
    expect(visualViewportShellStyle({ height: 420, offsetTop: 312 })).toEqual({
      position: "fixed",
      top: 312,
      left: 0,
      right: 0,
      width: "100%",
      height: 420,
      maxHeight: 420,
    })
  })

  test("keeps the shell at the top of an unshifted visual viewport", () => {
    const style = visualViewportShellStyle({ height: 800, offsetTop: 0 })
    expect(style?.position).toBe("fixed")
    expect(style?.top).toBe(0)
    expect(style?.height).toBe(800)
  })

  test("returns no overlay style without metrics", () => {
    expect(visualViewportShellStyle(null)).toBeUndefined()
  })
})

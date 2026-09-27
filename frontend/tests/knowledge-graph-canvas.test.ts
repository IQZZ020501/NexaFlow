import { describe, expect, test } from "bun:test"
import { Color } from "pixi.js"

import { cssColorToPixiColor } from "@/components/knowledge/knowledge-graph-canvas"

describe("knowledge graph canvas colors", () => {
  test("rasterizes CSS Color 4 values before passing them to Pixi", () => {
    const context = {
      clearRect: () => undefined,
      fillRect: () => undefined,
      fillStyle: "#000000",
      getImageData: () => ({
        data: new Uint8ClampedArray([250, 250, 250, 255]),
      }),
    } as unknown as CanvasRenderingContext2D

    const color = cssColorToPixiColor("lab(98.26 0 0)", 0x18181b, context)

    expect(color).toBe(0xfafafa)
    expect(new Color(color).toNumber()).toBe(0xfafafa)
  })

  test("uses a safe Pixi color when Canvas 2D is unavailable", () => {
    expect(cssColorToPixiColor("lab(98.26 0 0)", 0x18181b, null)).toBe(0x18181b)
  })
})

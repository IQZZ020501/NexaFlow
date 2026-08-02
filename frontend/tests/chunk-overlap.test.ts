import { describe, expect, test } from "bun:test"

import { findChunkOverlapLength } from "../src/features/knowledge/chunk-overlap"

describe("chunk overlap", () => {
  test("finds text repeated at the segment boundary", () => {
    const overlap = "这是上一分段结尾复用到下一分段开头的文本"

    expect(
      findChunkOverlapLength(
        `上一分段正文。${overlap}`,
        `${overlap}下一分段正文。`,
      ),
    ).toBe(overlap.length)
  })

  test("ignores short coincidental matches", () => {
    expect(findChunkOverlapLength("上一分段。", "。下一分段")).toBe(0)
  })

  test("returns zero when segment boundaries do not overlap", () => {
    expect(findChunkOverlapLength("上一分段正文", "下一分段正文")).toBe(0)
  })
})

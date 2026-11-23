import { describe, expect, test } from "bun:test"
import {
  DOCUMENT_PAGE_SIZES,
  documentPageCount,
} from "../src/components/knowledge/knowledge-base-page"

describe("knowledge document pagination", () => {
  test("defaults to 10 items per page and offers 10/20/50/100", () => {
    expect(DOCUMENT_PAGE_SIZES).toEqual([10, 20, 50, 100])
  })

  test("computes page counts with a minimum of one page", () => {
    expect(documentPageCount(0, 10)).toBe(1)
    expect(documentPageCount(10, 10)).toBe(1)
    expect(documentPageCount(11, 10)).toBe(2)
    expect(documentPageCount(100, 50)).toBe(2)
    expect(documentPageCount(101, 50)).toBe(3)
    expect(documentPageCount(25, 20)).toBe(2)
    expect(documentPageCount(10827, 10)).toBe(1083)
    expect(documentPageCount(21655, 100)).toBe(217)
  })
})

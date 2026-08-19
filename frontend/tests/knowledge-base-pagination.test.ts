import { describe, expect, test } from "bun:test"
import {
  DOCUMENT_PAGE_SIZES,
  documentPageCount,
  paginateDocuments,
} from "../src/components/knowledge/knowledge-base-page"

describe("knowledge document pagination", () => {
  test("defaults to 10 items per page and offers 10/20/50/100", () => {
    expect(DOCUMENT_PAGE_SIZES).toEqual([10, 20, 50, 100])
  })

  test("slices documents by page and page size", () => {
    const items = Array.from({ length: 25 }, (_, index) => index)
    expect(paginateDocuments(items, 1, 10)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
    ])
    expect(paginateDocuments(items, 2, 10)).toEqual([
      10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
    ])
    expect(paginateDocuments(items, 3, 10)).toEqual([20, 21, 22, 23, 24])
    expect(paginateDocuments(items, 1, 20)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
    ])
    expect(paginateDocuments(items, 2, 20)).toEqual([20, 21, 22, 23, 24])
    expect(paginateDocuments(items, 1, 50)).toEqual(items)
  })

  test("handles empty lists and out-of-range pages", () => {
    expect(paginateDocuments([], 1, 10)).toEqual([])
    expect(paginateDocuments([1, 2, 3], 2, 10)).toEqual([])
  })

  test("computes page counts with a minimum of one page", () => {
    expect(documentPageCount(0, 10)).toBe(1)
    expect(documentPageCount(10, 10)).toBe(1)
    expect(documentPageCount(11, 10)).toBe(2)
    expect(documentPageCount(100, 50)).toBe(2)
    expect(documentPageCount(101, 50)).toBe(3)
    expect(documentPageCount(25, 20)).toBe(2)
  })
})

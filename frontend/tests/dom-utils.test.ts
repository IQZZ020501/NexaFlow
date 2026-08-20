/* @jsxImportSource react */
import { describe, expect, test } from "bun:test"

import { isEventFromDropdownMenu } from "../src/lib/dom"

const dropdownTarget = {
  closest: (selector: string) =>
    selector.includes("dropdown-menu-content") ? { tag: "content" } : null,
}
const plainTarget = {
  closest: () => null,
}

describe("isEventFromDropdownMenu", () => {
  test("returns true when the event target is dropdown content", () => {
    expect(
      isEventFromDropdownMenu({ target: dropdownTarget, composedPath: () => [] })
    ).toBe(true)
  })

  test("returns false when the target is not dropdown content and no composed path is given", () => {
    expect(isEventFromDropdownMenu({ target: plainTarget })).toBe(false)
    expect(isEventFromDropdownMenu({ target: null })).toBe(false)
    expect(isEventFromDropdownMenu({ target: {} })).toBe(false)
    expect(isEventFromDropdownMenu({ target: "text node" })).toBe(false)
    expect(
      isEventFromDropdownMenu({ target: undefined, composedPath: undefined })
    ).toBe(false)
  })

  test("returns true when a composed path item is dropdown content", () => {
    expect(
      isEventFromDropdownMenu({
        target: plainTarget,
        composedPath: () => [dropdownTarget],
      })
    ).toBe(true)
    expect(
      isEventFromDropdownMenu({
        target: plainTarget,
        composedPath: () => [plainTarget, dropdownTarget],
      })
    ).toBe(true)
  })

  test("returns false when no composed path item is dropdown content", () => {
    expect(
      isEventFromDropdownMenu({
        target: plainTarget,
        composedPath: () => [plainTarget],
      })
    ).toBe(false)
    expect(
      isEventFromDropdownMenu({
        target: plainTarget,
        composedPath: () => [],
      })
    ).toBe(false)
  })

  test("ignores non-closest-capable composed path items", () => {
    expect(
      isEventFromDropdownMenu({
        target: plainTarget,
        composedPath: () => [42, "svg", { closest: null }],
      })
    ).toBe(false)
  })
})

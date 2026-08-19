import { describe, expect, test } from "bun:test"

import { isEventFromDropdownMenu } from "../src/lib/dom"

type ClosestCapable = {
  closest: (selector: string) => ClosestCapable | null
}

function elementWithClosest(matches: boolean): ClosestCapable {
  return {
    closest: (selector) =>
      matches && selector === "[data-slot='dropdown-menu-content']" ? elementWithClosest(true) : null,
  }
}

describe("dialog dropdown interaction guard", () => {
  test("recognizes dropdown menu clicks from the composed event path", () => {
    const dropdownContent = elementWithClosest(true)
    const menuItem = elementWithClosest(false)

    const event = {
      target: elementWithClosest(false),
      composedPath: () => [menuItem, dropdownContent],
    }

    expect(isEventFromDropdownMenu(event)).toBe(true)
  })
})

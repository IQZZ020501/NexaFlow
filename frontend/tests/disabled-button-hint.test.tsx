/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"

import { Button } from "@/components/ui/button"
import { DisabledButtonHint } from "@/components/ui/disabled-button-hint"

import { renderPage } from "./helpers/dom"

afterEach(() => cleanup())

describe("DisabledButtonHint", () => {
  test("explains a disabled action on keyboard focus without enabling it", async () => {
    let saves = 0
    renderPage(
      <DisabledButtonHint reason="No changes to save">
        <Button disabled onClick={() => saves++}>
          Save
        </Button>
      </DisabledButtonHint>
    )
    const button = screen.getByRole("button", {
      name: "Save",
    }) as HTMLButtonElement
    const wrapper = button.parentElement!

    expect(wrapper.tabIndex).toBe(0)
    fireEvent.focus(wrapper)
    await waitFor(() =>
      expect(screen.getByRole("tooltip").textContent).toBe("No changes to save")
    )
    fireEvent.click(button)

    expect(button.disabled).toBe(true)
    expect(saves).toBe(0)
  })

  test("does not add a keyboard stop to an enabled action", () => {
    renderPage(
      <DisabledButtonHint>
        <Button>Save</Button>
      </DisabledButtonHint>
    )

    expect(
      screen.getByRole("button", { name: "Save" }).parentElement?.tabIndex
    ).toBe(-1)
  })
})

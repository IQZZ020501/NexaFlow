/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { act, cleanup, fireEvent, screen } from "@testing-library/react"

import { StopGenerationButton } from "@/components/agents/stop-generation-button"
import type { TFunction } from "@/i18n"

import { renderPage } from "./helpers/dom"

const t = ((key: string) => key) as TFunction

afterEach(() => cleanup())

describe("StopGenerationButton", () => {
  test("prevents repeated cancellation until the request finishes", async () => {
    let finish!: () => void
    let requests = 0
    const pending = new Promise<void>((resolve) => {
      finish = resolve
    })
    renderPage(
      <StopGenerationButton
        onStop={() => {
          requests++
          return pending
        }}
        t={t}
      />
    )
    const button = screen.getByRole("button", {
      name: "停止生成",
    }) as HTMLButtonElement

    fireEvent.click(button)
    fireEvent.click(button)

    expect(requests).toBe(1)
    expect(button.disabled).toBe(true)
    expect(button.getAttribute("aria-busy")).toBe("true")
    expect(button.textContent).toBe("停止中")

    await act(async () => finish())

    expect(button.disabled).toBe(false)
    expect(button.getAttribute("aria-busy")).toBe("false")
    expect(button.textContent).toBe("停止")
  })
})

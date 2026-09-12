/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"

import {
  feedbackConfirmationLabel,
  RunActionBar,
} from "@/components/app/run-action-bar"
import type { TFunction } from "@/i18n"

import { renderPage } from "./helpers/dom"

const t = ((key: string) => key) as TFunction

afterEach(() => cleanup())

describe("RunActionBar", () => {
  test("localizes saved feedback confirmations", () => {
    expect(feedbackConfirmationLabel("positive", t)).toBe("已点赞")
    expect(feedbackConfirmationLabel("negative", t)).toBe("已点踩")
    expect(feedbackConfirmationLabel(null, t)).toBe("已取消反馈")
  })

  test("keeps copy available while a feedback write is pending", () => {
    renderPage(
      <RunActionBar
        result="Answer"
        feedbackPending
        onRegenerate={() => undefined}
        onFeedback={() => undefined}
        t={t}
      />
    )

    expect(
      (screen.getByRole("button", { name: "重新生成" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(
      (screen.getByRole("button", { name: "点赞" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(
      (screen.getByRole("button", { name: "点踩" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(
      (screen.getByRole("button", { name: "复制" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  })

  test("orders actions consistently and exposes feedback selection", async () => {
    const feedback: Array<"positive" | "negative" | null> = []
    const originalClipboard = navigator.clipboard
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async () => undefined },
      configurable: true,
    })
    const view = renderPage(
      <RunActionBar
        result="Answer"
        feedback="negative"
        onRegenerate={() => undefined}
        onFeedback={(value) => feedback.push(value)}
        t={t}
      />
    )

    expect(
      Array.from(view.container.querySelectorAll("button")).map((button) =>
        button.getAttribute("aria-label")
      )
    ).toEqual(["重新生成", "点赞", "取消点踩", "复制"])
    expect(
      screen
        .getByRole("button", { name: "取消点踩" })
        .getAttribute("aria-pressed")
    ).toBe("true")
    const selectedButton = screen.getByRole("button", { name: "取消点踩" })
    expect(selectedButton.className).toContain("bg-primary/10")
    expect(selectedButton.className).toContain("text-primary")
    expect(
      selectedButton.querySelector("svg")?.getAttribute("class")
    ).toContain("fill-current")

    fireEvent.click(screen.getByRole("button", { name: "取消点踩" }))
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    expect(feedback).toEqual([null])
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy()
    )

    Object.defineProperty(navigator, "clipboard", {
      value: originalClipboard,
      configurable: true,
    })
  })

  test("shows an accessible feedback tooltip", async () => {
    renderPage(
      <RunActionBar
        result="Answer"
        onRegenerate={() => undefined}
        onFeedback={() => undefined}
        t={t}
      />
    )

    fireEvent.focus(screen.getByRole("button", { name: "点赞" }))

    await waitFor(() =>
      expect(screen.getByRole("tooltip").textContent).toContain("点赞")
    )
  })
})

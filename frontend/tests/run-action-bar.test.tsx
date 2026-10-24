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
const originalClipboard = navigator.clipboard

afterEach(() => {
  cleanup()
  Object.defineProperty(navigator, "clipboard", {
    value: originalClipboard,
    configurable: true,
  })
})

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
  })

  test("restores the copy action after showing a confirmation", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async () => undefined },
      configurable: true,
    })
    renderPage(
      <RunActionBar
        result="Answer"
        onRegenerate={() => undefined}
        onFeedback={() => undefined}
        t={t}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy()
    )
    await waitFor(
      () => expect(screen.getByRole("button", { name: "复制" })).toBeTruthy(),
      { timeout: 2500 }
    )
    expect(screen.getByRole("status").textContent).toBe("")
  })

  test("shows a failed copy and allows retrying", async () => {
    let attempts = 0
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async () => {
          attempts++
          if (attempts === 1) throw new Error("Clipboard denied")
        },
      },
      configurable: true,
    })
    renderPage(
      <RunActionBar
        result="Answer"
        onRegenerate={() => undefined}
        onFeedback={() => undefined}
        t={t}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("复制失败")
    )
    fireEvent.click(screen.getByRole("button", { name: "复制失败" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy()
    )
    expect(attempts).toBe(2)
  })

  test("does not keep a confirmation when the result changes", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async () => undefined },
      configurable: true,
    })
    const props = {
      onRegenerate: () => undefined,
      onFeedback: () => undefined,
      t,
    }
    const view = renderPage(<RunActionBar {...props} result="First answer" />)

    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy()
    )
    view.rerender(<RunActionBar {...props} result="Next answer" />)

    expect(screen.getByRole("button", { name: "复制" })).toBeTruthy()
    expect(screen.getByRole("status").textContent).toBe("")
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

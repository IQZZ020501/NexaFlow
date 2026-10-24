/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react"

import { CopyButton } from "@/components/ui/copy-button"
import { translate, type TFunction } from "@/i18n"

import { renderPage } from "./helpers/dom"

const t: TFunction = (key, values) => translate("zh-Hans", key, values)
const originalClipboard = navigator.clipboard

afterEach(() => {
  cleanup()
  Object.defineProperty(navigator, "clipboard", {
    value: originalClipboard,
    configurable: true,
  })
})

describe("CopyButton", () => {
  test("shows a failed copy and restores a custom label after a successful retry", async () => {
    let attempts = 0
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async (value: string) => {
          expect(value).toBe("Example code")
          if (++attempts === 1) throw new Error("Clipboard denied")
        },
      },
      configurable: true,
    })
    renderPage(
      <CopyButton value="Example code" label="复制代码" showLabel t={t} />
    )

    fireEvent.click(screen.getByRole("button", { name: "复制代码" }))
    const retry = await screen.findByRole("button", { name: "复制失败" })
    expect(retry.textContent).toBe("复制失败")
    expect(screen.getByRole("status").textContent).toBe("复制失败")
    fireEvent.click(retry)
    await screen.findByRole("button", { name: "已复制" })
    await waitFor(
      () =>
        expect(screen.getByRole("button", { name: "复制代码" })).toBeTruthy(),
      { timeout: 2500 }
    )
    expect(attempts).toBe(2)
  })

  test("ignores a late clipboard result when a newer copy has completed", async () => {
    let failFirst!: (error: Error) => void
    let attempts = 0
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: () =>
          ++attempts === 1
            ? new Promise<void>((_, reject) => {
                failFirst = reject
              })
            : Promise.resolve(),
      },
      configurable: true,
    })
    renderPage(<CopyButton value="Answer" t={t} />)
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    await screen.findByRole("button", { name: "已复制" })

    await act(async () => failFirst(new Error("Late failure")))

    expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "复制失败" })).toBeNull()
  })
})

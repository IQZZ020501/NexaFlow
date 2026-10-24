/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"

import { ChangePasswordDialog } from "@/components/auth/change-password-dialog"

import { jsonResponse, renderPage } from "./helpers/dom"

const originalFetch = globalThis.fetch

afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
})

describe("ChangePasswordDialog", () => {
  test("shows pending feedback until the password request finishes", async () => {
    let finish!: (response: Response) => void
    let changed = false
    globalThis.fetch = (() =>
      new Promise<Response>((resolve) => {
        finish = resolve
      })) as unknown as typeof fetch
    renderPage(
      <ChangePasswordDialog
        open
        token="test-token"
        onNotify={() => undefined}
        onChanged={() => {
          changed = true
        }}
      />
    )
    fireEvent.change(screen.getByLabelText("新密码"), {
      target: { value: "Password1" },
    })
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "Password1" },
    })
    fireEvent.submit(
      screen.getByRole("button", { name: "保存" }).closest("form")!
    )

    const pending = screen.getByRole("button", {
      name: "保存中",
    }) as HTMLButtonElement
    expect(pending.disabled).toBe(true)
    expect(pending.getAttribute("aria-busy")).toBe("true")
    expect(pending.querySelector(".animate-spin")).toBeTruthy()

    finish(jsonResponse({}))
    await waitFor(() => expect(changed).toBe(true))
    expect(
      (screen.getByRole("button", { name: "保存" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  })
})

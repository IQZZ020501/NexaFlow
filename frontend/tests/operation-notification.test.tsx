/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"
import { cleanup, fireEvent, screen } from "@testing-library/react"
import { OperationNotification } from "@/components/app/operation-notification"
import { renderPage } from "./helpers/dom"

afterEach(cleanup)
test("shows full multiline error details and a localized heading with a close action", () => {
  const message = "Very long provider diagnostics ".repeat(20) + "\n第二条原因"
  let dismissed = false
  renderPage(
    <OperationNotification
      notification={{ id: 1, kind: "error", message }}
      onDismiss={() => {
        dismissed = true
      }}
    />
  )
  expect(screen.getByText("操作失败")).toBeTruthy()
  const alert = screen.getByRole("alert")
  expect(alert.textContent).toContain(message)
  expect(Boolean(alert.querySelector(".truncate"))).toBe(false)
  fireEvent.click(screen.getByRole("button", { name: "关闭提示" }))
  expect(dismissed).toBe(true)
})

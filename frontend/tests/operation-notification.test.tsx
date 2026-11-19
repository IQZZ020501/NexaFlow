/* @jsxImportSource react */
import { afterEach, expect, mock, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { useState } from "react"
import { OperationNotification } from "@/components/app/operation-notification"
import { LanguageProvider } from "@/contexts/language-provider"
import type { AppNotification } from "@/lib/notifications"
import { renderPage } from "./helpers/dom"

afterEach(cleanup)

test.each(["success", "error", "info"] as const)(
  "%s notifications disappear after 2.5 seconds",
  async (kind) => {
    function NotificationExample() {
      const [notification, setNotification] = useState<AppNotification | null>({
        id: 1,
        kind,
        message: "A notification",
      })
      return (
        <OperationNotification
          notification={notification}
          onDismiss={() => setNotification(null)}
        />
      )
    }

    renderPage(<NotificationExample />)
    expect(screen.getByText("A notification")).toBeTruthy()
    await new Promise((resolve) => setTimeout(resolve, 1200))
    expect(screen.getByText("A notification")).toBeTruthy()
    await waitFor(
      () => expect(Boolean(screen.queryByText("A notification"))).toBe(false),
      { timeout: 1800 }
    )
  }
)

test("a repeated notification gets a fresh timer even with the same id and message", async () => {
  const notification: AppNotification = {
    id: 1,
    kind: "error",
    message: "Repeated notification",
  }
  const onDismiss = mock(() => undefined)
  const { rerender } = renderPage(
    <OperationNotification notification={notification} onDismiss={onDismiss} />
  )
  await new Promise((resolve) => setTimeout(resolve, 1400))
  rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      <OperationNotification
        notification={{ ...notification }}
        onDismiss={onDismiss}
      />
    </LanguageProvider>
  )
  await new Promise((resolve) => setTimeout(resolve, 1300))
  expect(onDismiss).not.toHaveBeenCalled()
  await waitFor(() => expect(onDismiss).toHaveBeenCalledTimes(1), {
    timeout: 1800,
  })
})

test("an unrelated rerender uses the latest close callback without extending the timer", async () => {
  const notification: AppNotification = {
    id: 1,
    kind: "success",
    message: "A notification",
  }
  const previousDismiss = mock(() => undefined)
  const currentDismiss = mock(() => undefined)
  const { rerender } = renderPage(
    <OperationNotification
      notification={notification}
      onDismiss={previousDismiss}
    />
  )
  await new Promise((resolve) => setTimeout(resolve, 1400))
  rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      <OperationNotification
        notification={notification}
        onDismiss={currentDismiss}
      />
    </LanguageProvider>
  )
  await waitFor(() => expect(currentDismiss).toHaveBeenCalledTimes(1), {
    timeout: 1600,
  })
  expect(previousDismiss).not.toHaveBeenCalled()
})

test("unmounting cancels automatic dismissal", async () => {
  const onDismiss = mock(() => undefined)
  const { unmount } = renderPage(
    <OperationNotification
      notification={{ id: 1, kind: "info", message: "A notification" }}
      onDismiss={onDismiss}
    />
  )
  unmount()
  await new Promise((resolve) => setTimeout(resolve, 2700))
  expect(onDismiss).not.toHaveBeenCalled()
})

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

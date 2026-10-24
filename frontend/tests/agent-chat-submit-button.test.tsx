/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"

import { AgentChatSubmitButton } from "@/components/agents/agent-chat-submit-button"
import type { TFunction } from "@/i18n"

const t = ((key: string) => key) as TFunction

afterEach(() => cleanup())

describe("AgentChatSubmitButton", () => {
  test("submits a running draft without cancelling the run", () => {
    let submissions = 0
    let cancellations = 0
    render(
      <form
        onSubmit={(event) => {
          event.preventDefault()
          submissions++
        }}
      >
        <AgentChatSubmitButton
          isRunning
          hasInput
          onStop={() => {
            cancellations++
          }}
          t={t}
        />
      </form>
    )

    expect(screen.getAllByRole("button")).toHaveLength(1)
    fireEvent.click(screen.getByRole("button", { name: "追加后续任务" }))

    expect(submissions).toBe(1)
    expect(cancellations).toBe(0)
  })

  test("prevents repeated cancellation across draft changes until the request finishes", async () => {
    let finish!: () => void
    let requests = 0
    const pending = new Promise<void>((resolve) => {
      finish = resolve
    })
    const props = {
      isRunning: true,
      onStop: () => {
        requests++
        return pending
      },
      t,
    }
    const { rerender } = render(
      <AgentChatSubmitButton {...props} hasInput={false} />
    )
    const button = screen.getByRole("button", {
      name: "停止生成",
    }) as HTMLButtonElement

    fireEvent.click(button)
    fireEvent.click(button)

    expect(requests).toBe(1)
    expect(button.disabled).toBe(true)
    expect(button.getAttribute("aria-busy")).toBe("true")
    expect(button.title).toBe("停止中")

    rerender(<AgentChatSubmitButton {...props} hasInput />)
    expect(
      screen.getByRole("button", { name: "追加后续任务" }) === button
    ).toBe(true)
    expect(button.disabled).toBe(true)
    rerender(<AgentChatSubmitButton {...props} hasInput={false} />)
    fireEvent.click(screen.getByRole("button", { name: "停止生成" }))
    expect(requests).toBe(1)
    expect(button.disabled).toBe(true)

    await act(async () => finish())

    expect(button.disabled).toBe(false)
    expect(button.getAttribute("aria-busy")).toBe("false")
    expect(button.title).toBe("停止生成")
  })
})

/* @jsxImportSource react */
import { expect, test } from "bun:test"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"

function Counter() {
  const [count, setCount] = useState(0)
  return (
    <button type="button" onClick={() => setCount((n) => n + 1)}>
      count: {count}
    </button>
  )
}

test("happy-dom + RTL render and interact", async () => {
  render(<Counter />)
  expect(screen.getByText("count: 0")).toBeTruthy()
  fireEvent.click(screen.getByRole("button"))
  expect(screen.getByText("count: 1")).toBeTruthy()
  cleanup()
})

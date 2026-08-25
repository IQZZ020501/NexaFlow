/* @jsxImportSource react */
import { afterEach, expect, mock, test } from "bun:test"
import { act } from "@testing-library/react"
import { useState } from "react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import {
  cleanup,
  fireEvent,
  renderPage,
  screen,
  waitFor,
} from "./helpers/dom"

type PendingHighlight = {
  code: string
  resolve: (html: string) => void
}

const pendingHighlights: PendingHighlight[] = []

mock.module("shiki/bundle/web", () => ({
  codeToHtml: (code: string) =>
    new Promise<string>((resolve) => {
      pendingHighlights.push({ code, resolve })
    }),
}))

afterEach(() => {
  cleanup()
  pendingHighlights.length = 0
})

function StreamingCode() {
  const [lines, setLines] = useState(["print('first')"])
  const content = ["```python", ...lines, "```"].join("\n")

  return (
    <>
      <button
        type="button"
        onClick={() => setLines((value) => [...value, "print('second')"])}
      >
        append
      </button>
      <MarkdownContent content={content} />
    </>
  )
}

function highlightedHtml(code: string) {
  return `<pre class="shiki"><code>${code}</code></pre>`
}

test("keeps highlighted code mounted while streamed content updates", async () => {
  renderPage(<StreamingCode />)

  await waitFor(() =>
    expect(pendingHighlights.map(({ code }) => code)).toEqual([
      "print('first')",
    ])
  )
  await act(async () => {
    pendingHighlights[0].resolve(highlightedHtml(pendingHighlights[0].code))
  })

  const highlighted = await waitFor(() => {
    const element = document.querySelector(".markdown-shiki")
    expect(element).toBeTruthy()
    return element
  })

  fireEvent.click(screen.getByRole("button", { name: "append" }))

  await waitFor(() =>
    expect(pendingHighlights.map(({ code }) => code)).toEqual([
      "print('first')",
      "print('first')\nprint('second')",
    ])
  )
  expect(document.querySelector(".markdown-shiki")).toBe(highlighted)

  await act(async () => {
    pendingHighlights[1].resolve(highlightedHtml(pendingHighlights[1].code))
  })
  await waitFor(() =>
    expect(document.querySelector(".markdown-shiki")?.textContent).toContain(
      "print('second')"
    )
  )
  expect(document.querySelector(".markdown-shiki")).toBe(highlighted)
})

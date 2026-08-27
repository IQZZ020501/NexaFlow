import { expect, spyOn, test } from "bun:test"

import {
  conversationMarkdown,
  downloadConversationMarkdown,
} from "@/lib/conversation-export"
import { workflowSpeechText } from "@/lib/browser-tts"

test("conversationMarkdown sorts by creation time and fills answers from errors", () => {
  const markdown = conversationMarkdown(" 周会 ", [
    {
      question: " 下半年计划 ",
      answer: " 保持节奏 ",
      createdAt: "2026-08-27T02:00:00Z",
    },
    {
      question: "先问的",
      error: " 出错了 ",
      createdAt: "2026-08-27T01:00:00Z",
    },
    {
      question: "没有答案",
      createdAt: "2026-08-27T03:00:00Z",
    },
  ])
  expect(markdown.startsWith("# 周会\n\n")).toBe(true)
  // Sorted oldest first; the error text fills the assistant slot.
  expect(markdown.indexOf("先问的")).toBeLessThan(markdown.indexOf("下半年计划"))
  expect(markdown).toContain("### 助手\n\n出错了")
  // A message without an answer or error leaves the assistant slot empty
  // (the final section ends with the trailing newline).
  expect(markdown.endsWith("### 助手\n\n\n")).toBe(true)
})

test("downloadConversationMarkdown sanitizes the filename", () => {
  const createObjectURL = spyOn(URL, "createObjectURL").mockImplementation(
    () => "blob:conv"
  )
  const revokeObjectURL = spyOn(URL, "revokeObjectURL")
  const captured: { anchor: HTMLAnchorElement | null } = { anchor: null }
  const click = spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    function (this: HTMLAnchorElement) {
      captured.anchor = this
    }
  )

  downloadConversationMarkdown('a/b\\c:d*e?"f<g>h|i', [])

  expect(captured.anchor).not.toBeNull()
  expect(captured.anchor!.download).toBe("a-b-c-d-e-f-g-h-i.md")
  expect(createObjectURL).toHaveBeenCalledTimes(1)
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:conv")
  createObjectURL.mockRestore()
  revokeObjectURL.mockRestore()
  click.mockRestore()
})

test("workflowSpeechText prefers result then text and stringifies the rest", () => {
  expect(workflowSpeechText({ result: "结果", text: "文本" })).toBe("结果")
  expect(workflowSpeechText({ text: "文本" })).toBe("文本")
  expect(workflowSpeechText({ other: 1 })).toBe('{"other":1}')
  expect(workflowSpeechText({})).toBe("{}")
})

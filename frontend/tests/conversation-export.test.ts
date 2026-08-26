import { describe, expect, test } from "bun:test"

import { conversationMarkdown } from "@/lib/conversation-export"

describe("conversation export", () => {
  test("writes every turn in chronological order and keeps failures", () => {
    const markdown = conversationMarkdown("制度问答", [
      {
        question: "第二问",
        answer: "第二答",
        createdAt: "2026-01-02T00:00:00Z",
      },
      {
        question: "第一问",
        error: "回答失败",
        createdAt: "2026-01-01T00:00:00Z",
      },
    ])

    expect(markdown).toBe(
      "# 制度问答\n\n### 用户\n\n第一问\n\n### 助手\n\n回答失败\n\n### 用户\n\n第二问\n\n### 助手\n\n第二答\n"
    )
  })
})

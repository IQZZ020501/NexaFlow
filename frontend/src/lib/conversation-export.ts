export type ConversationExportMessage = {
  question: string
  answer?: string | null
  error?: string | null
  createdAt?: string
}

function safeFilename(value: string) {
  return (
    value.trim().replace(/[\\/:*?"<>|\r\n]+/g, "-") || "conversation"
  ).slice(0, 80)
}

export function conversationMarkdown(
  title: string,
  messages: ConversationExportMessage[]
) {
  const sections = messages
    .slice()
    .sort((left, right) =>
      (left.createdAt ?? "").localeCompare(right.createdAt ?? "")
    )
    .map((message) => {
      const answer = message.answer?.trim() || message.error?.trim() || ""
      return [`### 用户`, message.question.trim(), `### 助手`, answer].join(
        "\n\n"
      )
    })
  return [`# ${title.trim() || "对话记录"}`, ...sections].join("\n\n") + "\n"
}

export function downloadConversationMarkdown(
  title: string,
  messages: ConversationExportMessage[]
) {
  const anchor = document.createElement("a")
  const url = URL.createObjectURL(
    new Blob([conversationMarkdown(title, messages)], {
      type: "text/markdown;charset=utf-8",
    })
  )
  anchor.href = url
  anchor.download = `${safeFilename(title)}.md`
  anchor.click()
  URL.revokeObjectURL(url)
}

"use client"

import * as React from "react"

function formatToolInput(input: Record<string, unknown>) {
  return Object.entries(input)
    .map(([field, value]) => {
      const content =
        typeof value === "string"
          ? value
          : JSON.stringify(value, null, 2) ?? String(value)
      return `${field}:\n${content}`
    })
    .join("\n\n")
}

export function ToolInputPreview({
  input,
  streaming,
}: {
  input: Record<string, unknown>
  streaming: boolean
}) {
  const content = formatToolInput(input)
  const scrollRef = React.useRef<HTMLPreElement>(null)
  const shouldFollowRef = React.useRef(true)

  React.useLayoutEffect(() => {
    const element = scrollRef.current
    if (!streaming || !element || !shouldFollowRef.current) return
    element.scrollTop = element.scrollHeight
  }, [content, streaming])

  if (!content) return null
  return (
    <pre
      ref={scrollRef}
      className="max-h-64 overflow-auto rounded-md bg-background p-3 font-mono leading-5 [overflow-wrap:anywhere] whitespace-pre-wrap"
      onScroll={(event) => {
        const element = event.currentTarget
        shouldFollowRef.current =
          element.scrollHeight - element.scrollTop - element.clientHeight <= 24
      }}
    >
      {content}
    </pre>
  )
}

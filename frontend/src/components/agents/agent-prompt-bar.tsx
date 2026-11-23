"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

export function AgentPromptBar({
  className,
  ...props
}: React.ComponentProps<"form">) {
  return (
    <form
      {...props}
      className={`${cn(
        "agent-beautiful bui-prompt-bar mx-auto max-w-3xl",
        "border-input bg-muted/20 shadow-xs",
        className
      )} bg-card shadow-sm`}
    />
  )
}

export function AgentPromptInput({
  className,
  value,
  ...props
}: React.ComponentProps<"textarea">) {
  const ref = React.useRef<HTMLTextAreaElement>(null)

  React.useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    element.style.height = "auto"
    element.style.height = `${Math.min(160, Math.max(32, element.scrollHeight))}px`
  }, [value])

  return (
    <textarea
      {...props}
      ref={ref}
      value={value}
      className={cn("bui-prompt-input", className)}
    />
  )
}

"use client"

import * as React from "react"
import {
  ChevronRightIcon,
  CircleCheckIcon,
  CircleXIcon,
  SparklesIcon,
} from "lucide-react"

export function useAgentProcessDisclosure(status: string) {
  const defaultOpen = status !== "succeeded" && status !== "cancelled"
  const [disclosure, setDisclosure] = React.useState({
    status,
    open: defaultOpen,
  })
  return {
    isOpen: disclosure.status === status ? disclosure.open : defaultOpen,
    onToggle: (event: React.SyntheticEvent<HTMLDetailsElement>) => {
      setDisclosure({ status, open: event.currentTarget.open })
    },
  }
}

export function AgentReasoningStep({
  title,
  status,
  reasoning,
}: {
  title: string
  status: "running" | "succeeded" | "failed"
  reasoning?: string
}) {
  const [isOpen, setIsOpen] = React.useState(false)
  const contentId = React.useId()
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const shouldFollowRef = React.useRef(true)

  React.useLayoutEffect(() => {
    const element = scrollRef.current
    if (!element || !shouldFollowRef.current) return
    const scrollToBottom = () => {
      if (shouldFollowRef.current) element.scrollTop = element.scrollHeight
    }
    scrollToBottom()
    const frame = requestAnimationFrame(scrollToBottom)
    const observer = new ResizeObserver(scrollToBottom)
    observer.observe(element)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [isOpen, reasoning])

  const heading = (
    <>
      {status === "running" ? (
        <SparklesIcon className="size-3.5 shrink-0" aria-hidden="true" />
      ) : status === "failed" ? (
        <CircleXIcon className="size-3.5 shrink-0 text-destructive" />
      ) : (
        <CircleCheckIcon className="size-3.5 shrink-0" />
      )}
      <span
        className={
          status === "running"
            ? "bui-thinking-busy min-w-0 [overflow-wrap:anywhere]"
            : "min-w-0 [overflow-wrap:anywhere]"
        }
      >
        {title}
      </span>
      {reasoning ? (
        <ChevronRightIcon
          className={`size-3 shrink-0 transition-transform motion-reduce:transition-none ${isOpen ? "rotate-90" : ""}`}
        />
      ) : null}
    </>
  )

  return (
    <div className="agent-beautiful">
      {reasoning ? (
        <button
          type="button"
          className="bui-reasoning-trigger"
          aria-expanded={isOpen}
          aria-controls={contentId}
          onClick={() => setIsOpen((current) => !current)}
        >
          {heading}
        </button>
      ) : (
        <div className="bui-reasoning-trigger">{heading}</div>
      )}
      {reasoning && isOpen ? (
        <div
          id={contentId}
          ref={scrollRef}
          className="bui-reasoning-content"
          onScroll={(event) => {
            const element = event.currentTarget
            shouldFollowRef.current =
              element.scrollHeight - element.scrollTop - element.clientHeight <=
              64
          }}
        >
          {reasoning}
        </div>
      ) : null}
    </div>
  )
}

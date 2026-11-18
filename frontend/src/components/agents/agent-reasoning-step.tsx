"use client"

import * as React from "react"
import {
  ChevronRightIcon,
  CircleCheckIcon,
  CircleXIcon,
  LoaderCircleIcon,
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
        <LoaderCircleIcon className="size-3.5 shrink-0 animate-spin motion-reduce:animate-none" />
      ) : status === "failed" ? (
        <CircleXIcon className="size-3.5 shrink-0 text-destructive" />
      ) : (
        <CircleCheckIcon className="size-3.5 shrink-0" />
      )}
      <span className="min-w-0 [overflow-wrap:anywhere]">{title}</span>
      {reasoning ? (
        <ChevronRightIcon
          className={`size-3 shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`}
        />
      ) : null}
    </>
  )

  return (
    <div className="text-xs leading-5 text-muted-foreground">
      {reasoning ? (
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-sm px-1 py-1.5 text-left hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          aria-expanded={isOpen}
          aria-controls={contentId}
          onClick={() => setIsOpen((current) => !current)}
        >
          {heading}
        </button>
      ) : (
        <div className="flex items-center gap-2 px-1 py-1.5">{heading}</div>
      )}
      {reasoning && isOpen ? (
        <div
          id={contentId}
          ref={scrollRef}
          className="mt-1 mb-2 ml-6 max-h-48 overflow-y-auto border-l pl-3 [overflow-wrap:anywhere] whitespace-pre-wrap"
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

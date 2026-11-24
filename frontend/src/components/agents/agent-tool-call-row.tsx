"use client"

import * as React from "react"
import { ChevronRightIcon } from "lucide-react"

import { toolInputSummary } from "@/lib/tool-display"
import { cn } from "@/lib/utils"

/** A compact tool summary that keeps the full input and result on demand. */
export function AgentToolCallRow({
  title,
  functionName,
  sourceName,
  icon,
  statusIcon,
  detail,
  input,
  expandable = true,
  children,
}: {
  title: string
  functionName?: string
  sourceName?: string
  icon: React.ReactNode
  statusIcon: React.ReactNode
  detail?: string | null
  input?: Record<string, unknown>
  expandable?: boolean
  children: () => React.ReactNode
}) {
  const [isOpen, setIsOpen] = React.useState(false)
  const contentId = React.useId()
  const summary = toolInputSummary(input)
  const heading = (
    <>
      <span className="bui-tool-icon" aria-hidden="true">
        <span className="bui-tool-icon-glyph">{icon}</span>
        {expandable ? <ChevronRightIcon className="bui-tool-chevron" /> : null}
      </span>
      <span className="bui-tool-main">
        <span
          className="bui-tool-label"
          title={sourceName ? `${title} @ ${sourceName}` : title}
        >
          <span>{title}</span>
          {sourceName ? (
            <span className="bui-tool-source">@ {sourceName}</span>
          ) : null}
        </span>
        {summary && !isOpen ? (
          <span className={cn("bui-tool-chip", summary.isCode && "font-mono")}>
            {summary.text}
          </span>
        ) : null}
        {detail ? (
          <span className="bui-tool-detail" title={detail}>
            {detail}
          </span>
        ) : null}
      </span>
      <span className="flex shrink-0 items-center">{statusIcon}</span>
    </>
  )

  return (
    <div className="agent-beautiful min-w-0">
      {expandable ? (
        <button
          type="button"
          className="bui-tool-trigger"
          data-summary={Boolean(summary) && !isOpen}
          aria-expanded={isOpen}
          aria-controls={isOpen ? contentId : undefined}
          onClick={() => setIsOpen((current) => !current)}
        >
          {heading}
        </button>
      ) : (
        <div className="bui-tool-trigger" data-summary={Boolean(summary)}>
          {heading}
        </div>
      )}
      {expandable && isOpen ? (
        <div id={contentId} className="bui-tool-content">
          {functionName && functionName !== title ? (
            <p className="text-[11px] text-muted-foreground">
              <code>{functionName}</code>
            </p>
          ) : null}
          {children()}
        </div>
      ) : null}
    </div>
  )
}

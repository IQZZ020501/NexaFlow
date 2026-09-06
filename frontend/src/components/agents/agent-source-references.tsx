"use client"

import * as React from "react"
import { FileTextIcon } from "lucide-react"
import { Popover as PopoverPrimitive } from "radix-ui"
import type { Components } from "react-markdown"

import {
  MarkdownContent,
  MarkdownLink,
} from "@/components/knowledge/markdown-content"
import type { TFunction } from "@/i18n"
import type { AgentRunSource } from "@/lib/api/agents"

const SOURCE_HREF_PATTERN =
  /^#nex(?:aflow|faow)-source-([a-f0-9]{16})$/i
const SOURCE_LINK_PATTERN =
  /[ \t]*\[[^\]\r\n]*\]\(#nex(?:aflow|faow)-source-([a-f0-9]{16})\)/gi

function sourceRefFromHref(href?: string) {
  return href?.match(SOURCE_HREF_PATTERN)?.[1] ?? null
}

export function stripAgentSourceLinks(content: string) {
  return content.replace(SOURCE_LINK_PATTERN, "")
}

function deduplicateAgentSourceLinks(
  content: string,
  sourceByRef: Map<string, AgentRunSource>
) {
  const seen = new Set<string>()
  return content.replace(SOURCE_LINK_PATTERN, (link, sourceRef: string) => {
    if (!sourceByRef.has(sourceRef) || !seen.has(sourceRef)) {
      seen.add(sourceRef)
      return link
    }
    return ""
  })
}

function sourceLocation(source: AgentRunSource, t: TFunction) {
  return (
    source.parent_title ||
    source.section_path.at(-1) ||
    (source.chunk_index === null
      ? ""
      : t("片段 {value}", { value: source.chunk_index + 1 }))
  )
}

function sourceLabel(source: AgentRunSource, t: TFunction) {
  const document = source.document || t("未知文档")
  const location = sourceLocation(source, t)
  return location ? `${document} · ${location}` : document
}

function AgentSourceReference({
  source,
  t,
  inline = false,
}: {
  source: AgentRunSource
  t: TFunction
  inline?: boolean
}) {
  const label = sourceLabel(source, t)
  const displayLabel = source.document || t("未知文档")
  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          className={`inline-flex max-w-52 items-center gap-1 rounded-full border bg-muted/70 px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none ${inline ? "mx-1 align-middle" : ""}`}
          aria-label={`${t("来源")}：${label}`}
          title={label}
        >
          <FileTextIcon className="size-3 shrink-0" />
          <span className="truncate">{displayLabel}</span>
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={16}
          className="z-50 max-h-[min(28rem,calc(100vh-2rem))] w-[calc(100vw-2rem)] max-w-md overflow-y-auto rounded-lg border bg-popover p-4 text-popover-foreground shadow-md outline-none"
        >
          <p className="font-medium break-words">
            {source.document || t("未知文档")}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {[source.knowledge_base, sourceLocation(source, t)]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <p className="mt-3 text-sm leading-6 break-words whitespace-pre-wrap">
            {source.content}
          </p>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}

export function AgentSourceReferences({
  sources,
  t,
}: {
  sources?: AgentRunSource[]
  t: TFunction
}) {
  if (!sources?.length) return null

  return (
    <div className="mt-3 flex flex-wrap gap-2" aria-label={t("回答来源")}>
      {sources.map((source) => (
        <AgentSourceReference key={source.source_ref} source={source} t={t} />
      ))}
    </div>
  )
}

export function AgentAnswer({
  content,
  sources,
  t,
  className,
}: {
  content: string
  sources?: AgentRunSource[]
  t: TFunction
  className?: string
}) {
  const sourceByRef = React.useMemo(
    () => new Map((sources ?? []).map((source) => [source.source_ref, source])),
    [sources]
  )
  const deduplicatedContent = React.useMemo(
    () => deduplicateAgentSourceLinks(content, sourceByRef),
    [content, sourceByRef]
  )
  const hasInlineSource = React.useMemo(
    () =>
      Array.from(deduplicatedContent.matchAll(SOURCE_LINK_PATTERN)).some((match) =>
        sourceByRef.has(match[1])
      ),
    [deduplicatedContent, sourceByRef]
  )
  const components = React.useMemo<Components>(
    () => ({
      a(props) {
        const sourceRef = sourceRefFromHref(props.href)
        if (!sourceRef) return <MarkdownLink {...props} />
        const source = sourceByRef.get(sourceRef)
        return source ? (
          <AgentSourceReference source={source} t={t} inline />
        ) : null
      },
    }),
    [sourceByRef, t]
  )

  return (
    <>
      <MarkdownContent
        content={deduplicatedContent}
        className={className}
        components={components}
      />
      {hasInlineSource ? null : (
        <AgentSourceReferences sources={sources} t={t} />
      )}
    </>
  )
}

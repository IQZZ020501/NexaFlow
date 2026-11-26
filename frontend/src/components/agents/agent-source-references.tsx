"use client"

import * as React from "react"
import { ChevronRightIcon, FileTextIcon } from "lucide-react"
import { Popover as PopoverPrimitive } from "radix-ui"
import type { Components } from "react-markdown"

import { AgentArtifactPreviews } from "@/components/agents/artifacts/agent-artifact-previews"
import { AgentContextCard } from "@/components/agents/agent-context-card"
import {
  MarkdownContent,
  MarkdownLink,
} from "@/components/knowledge/markdown-content"
import type { TFunction } from "@/i18n"
import type { ArtifactEvent } from "@/lib/agent-artifacts"
import type { AgentRunSource } from "@/lib/api/agents"
import { cn } from "@/lib/utils"

type AgentSourceEvent = {
  type?: string
  tool_kind?: string
  status?: string
  output?: unknown
  hits?: unknown
}

const SOURCE_HREF_PATTERN = /(?:^|#)nex(?:aflow|faow)-source-([^\s)>'"]+)$/i
const SOURCE_HREF_MARKER_PATTERN = /(?:^|#)nex(?:aflow|faow)-source-/i
const SOURCE_LINK_PATTERN =
  /[ \t]*\[[^\]\r\n]*\]\s*\(\s*(?:<\s*)?(?:[^\s<>()#"']*)?#nex(?:aflow|faow)-source-([^\s)>'"]+)\s*(?:>|(?:["'][^)]*["']))?\s*\)/gi
const INCOMPLETE_SOURCE_LINK_PATTERN =
  /[ \t]*\[(?:source|来源)\]\s*\(\s*(?:<\s*)?(?:[^)\r\n]*#nex(?:aflow|faow)-source-[^)\r\n]*)?(?=$|\r?\n)/gi
const BARE_SOURCE_LABEL_PATTERN = /[ \t]*\[(?:source|来源)\](?!\s*\()/gi
const SOURCE_LINK_BEFORE_SENTENCE_PUNCTUATION_PATTERN = new RegExp(
  `(${SOURCE_LINK_PATTERN.source})([。！？.!?]+)`,
  "gi"
)

function normalizeSourceRef(value: string) {
  let decoded = value.trim()
  try {
    decoded = decodeURIComponent(decoded)
  } catch {
    // Keep the original token when a legacy answer contains malformed escapes.
  }
  return decoded.toLowerCase()
}

function sourceHitSignature(value: Record<string, unknown>) {
  const document =
    typeof value.document === "string" ? value.document.trim() : ""
  const content = typeof value.content === "string" ? value.content : ""
  if (!document || !content) return null
  const knowledgeBase =
    typeof value.knowledge_base === "string" ? value.knowledge_base.trim() : ""
  return JSON.stringify([knowledgeBase, document, content])
}

export function agentSourcesForEvents(
  sources: AgentRunSource[] | undefined,
  events: readonly AgentSourceEvent[]
) {
  if (!sources?.length) return []

  const sourceRefs = new Set<string>()
  const sourceSignatures = new Set<string>()
  for (const event of events) {
    if (
      event.status !== "succeeded" ||
      (event.tool_kind !== "knowledge" && event.type !== "knowledge")
    ) {
      continue
    }
    const output =
      event.output && typeof event.output === "object"
        ? (event.output as Record<string, unknown>)
        : null
    const hits = Array.isArray(event.hits)
      ? event.hits
      : Array.isArray(output?.hits)
        ? output.hits
        : []
    for (const hit of hits) {
      if (!hit || typeof hit !== "object") continue
      const value = hit as Record<string, unknown>
      if (typeof value.source_ref === "string" && value.source_ref.trim()) {
        sourceRefs.add(normalizeSourceRef(value.source_ref))
      }
      const signature = sourceHitSignature(value)
      if (signature) sourceSignatures.add(signature)
    }
  }

  const seen = new Set<string>()
  return sources.filter((source) => {
    const sourceRef = normalizeSourceRef(source.source_ref)
    const matches =
      sourceRefs.has(sourceRef) ||
      sourceSignatures.has(
        sourceHitSignature({
          knowledge_base: source.knowledge_base,
          document: source.document,
          content: source.content,
        }) ?? ""
      )
    if (!matches || seen.has(sourceRef)) return false
    seen.add(sourceRef)
    return true
  })
}

function sourceRefFromHref(href?: string) {
  const value = href?.trim()
  const rawSourceRef = value?.match(SOURCE_HREF_PATTERN)?.[1]
  return rawSourceRef ? normalizeSourceRef(rawSourceRef) : null
}

function isSourceHref(href?: string) {
  return SOURCE_HREF_MARKER_PATTERN.test(href?.trim() ?? "")
}

export function stripAgentSourceLinks(content: string) {
  return content.replace(SOURCE_LINK_PATTERN, "")
}

function hideIncompleteAgentSourceLinks(content: string) {
  return content
    .replace(INCOMPLETE_SOURCE_LINK_PATTERN, "")
    .replace(BARE_SOURCE_LABEL_PATTERN, "")
}

function normalizeAgentSourceLinks(
  content: string,
  sourceByRef: Map<string, AgentRunSource>
) {
  return content.replace(SOURCE_LINK_PATTERN, (_link, rawSourceRef: string) => {
    const sourceRef = normalizeSourceRef(rawSourceRef)
    if (!sourceByRef.has(sourceRef)) return _link
    return `[source](#nexaflow-source-${sourceRef})`
  })
}

function normalizeAgentSourcePlacement(content: string) {
  return content.replace(
    SOURCE_LINK_BEFORE_SENTENCE_PUNCTUATION_PATTERN,
    (_match, link: string, _sourceRef: string, punctuation: string) =>
      `${punctuation} ${link.trim()}`
  )
}

function deduplicateAgentSourceLinks(
  content: string,
  sourceByRef: Map<string, AgentRunSource>
) {
  const seen = new Set<string>()
  return content.replace(SOURCE_LINK_PATTERN, (link, sourceRef: string) => {
    const normalizedSourceRef = normalizeSourceRef(sourceRef)
    if (
      !sourceByRef.has(normalizedSourceRef) ||
      !seen.has(normalizedSourceRef)
    ) {
      seen.add(normalizedSourceRef)
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
          className={cn(
            "agent-beautiful bui-source-chip",
            inline && "bui-source-chip-inline"
          )}
          aria-label={`${t("来源")}：${label}`}
          title={label}
        >
          <span className="bui-source-icon" aria-hidden="true">
            <FileTextIcon className="size-2.5" />
          </span>
          <span className="truncate">{displayLabel}</span>
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={16}
          className="agent-beautiful bui-source-popover"
        >
          <AgentContextCard
            title={
              source.parent_title ||
              sourceLocation(source, t) ||
              source.document ||
              t("未知文档")
            }
            content={source.content}
            document={source.document || t("未知文档")}
            meta={[source.knowledge_base, sourceLocation(source, t)]
              .filter(Boolean)
              .join(" · ")}
            t={t}
          />
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
    <details
      className="agent-beautiful group/sources mt-3"
      aria-label={t("回答来源")}
    >
      <summary className="flex w-fit max-w-full cursor-pointer list-none items-center gap-1.5 rounded-md py-1 text-xs font-medium text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
        <FileTextIcon className="size-3.5 shrink-0" aria-hidden="true" />
        <span>{t("回答来源（{count}）", { count: sources.length })}</span>
        <ChevronRightIcon
          className="size-3.5 shrink-0 transition-transform group-open/sources:rotate-90 motion-reduce:transition-none"
          aria-hidden="true"
        />
      </summary>
      <div className="mt-2 flex flex-wrap gap-2">
        {sources.map((source) => (
          <AgentSourceReference key={source.source_ref} source={source} t={t} />
        ))}
      </div>
    </details>
  )
}

export const AgentAnswer = React.memo(function AgentAnswer({
  content,
  events = [],
  sources,
  t,
  className,
  components: customComponents,
}: {
  content: string
  events?: readonly ArtifactEvent[]
  sources?: AgentRunSource[]
  t: TFunction
  className?: string
  components?: Components
}) {
  const sourceByRef = React.useMemo(
    () =>
      new Map(
        (sources ?? []).map((source) => [
          normalizeSourceRef(source.source_ref),
          source,
        ])
      ),
    [sources]
  )
  const normalizedContent = React.useMemo(
    () =>
      normalizeAgentSourceLinks(
        normalizeAgentSourcePlacement(content),
        sourceByRef
      ),
    [content, sourceByRef]
  )
  const deduplicatedContent = React.useMemo(
    () =>
      hideIncompleteAgentSourceLinks(
        deduplicateAgentSourceLinks(normalizedContent, sourceByRef)
      ),
    [normalizedContent, sourceByRef]
  )
  const hasInlineSource = React.useMemo(
    () =>
      Array.from(deduplicatedContent.matchAll(SOURCE_LINK_PATTERN)).some(
        (match) => sourceByRef.has(normalizeSourceRef(match[1]))
      ),
    [deduplicatedContent, sourceByRef]
  )
  const hasUnresolvedSource = React.useMemo(
    () =>
      Array.from(deduplicatedContent.matchAll(SOURCE_LINK_PATTERN)).some(
        (match) => !sourceByRef.has(normalizeSourceRef(match[1]))
      ),
    [deduplicatedContent, sourceByRef]
  )
  const inlineSourceRefs = React.useMemo(
    () =>
      new Set(
        Array.from(deduplicatedContent.matchAll(SOURCE_LINK_PATTERN))
          .map((match) => normalizeSourceRef(match[1]))
          .filter((sourceRef) => sourceByRef.has(sourceRef))
      ),
    [deduplicatedContent, sourceByRef]
  )
  const fallbackSources = React.useMemo(
    () =>
      (sources ?? []).filter(
        (source) => !inlineSourceRefs.has(normalizeSourceRef(source.source_ref))
      ),
    [inlineSourceRefs, sources]
  )
  const components = React.useMemo<Components>(
    () => ({
      ...customComponents,
      a(props) {
        const sourceRef = sourceRefFromHref(props.href)
        if (!sourceRef) {
          if (isSourceHref(props.href)) return null
          const customAnchor = customComponents?.a
          if (customAnchor) {
            return React.createElement(customAnchor, props)
          }
          return <MarkdownLink {...props} />
        }
        const source = sourceByRef.get(sourceRef)
        return source ? (
          <AgentSourceReference source={source} t={t} inline />
        ) : null
      },
    }),
    [customComponents, sourceByRef, t]
  )

  return (
    <>
      <MarkdownContent
        content={deduplicatedContent}
        className={className}
        components={components}
      />
      <AgentArtifactPreviews events={events} />
      {hasInlineSource && !hasUnresolvedSource ? null : (
        <AgentSourceReferences
          sources={hasInlineSource ? fallbackSources : sources}
          t={t}
        />
      )}
    </>
  )
})

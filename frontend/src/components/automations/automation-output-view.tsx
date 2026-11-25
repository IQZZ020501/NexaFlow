"use client"

import * as React from "react"
import {
  ArrowUpRightIcon,
  DownloadIcon,
  EyeIcon,
  GlobeIcon,
  Link2Icon,
  LoaderCircleIcon,
} from "lucide-react"
import type { Components } from "react-markdown"

import type { useAgentArtifactPreview } from "@/components/agents/artifacts/agent-artifact-preview-context"
import { AgentAnswer } from "@/components/agents/agent-source-references"
import {
  getDocumentFileIcon,
  getDocumentFileIconColor,
} from "@/components/knowledge/document-file-icon"
import {
  ArtifactDownloadLink,
  MarkdownContent,
} from "@/components/knowledge/markdown-content"
import { Button } from "@/components/ui/button"
import type { TFunction } from "@/i18n"
import type { PreviewArtifact } from "@/lib/agent-artifacts"
import type { AgentRunEvent } from "@/lib/api/agents"
import type {
  AutomationArtifactLink,
  AutomationExecutionDetail,
} from "@/lib/api/automations"
import { cn } from "@/lib/utils"

export type EventUrlEntry = {
  url: string
  hostname: string
  title?: string
}

export type ExtractedExternalLink = {
  url: string
  label: string
  hostname: string
  displayPath: string
}

export type PreviewableArtifactEntry = {
  artifact: AutomationArtifactLink
  preview: PreviewArtifact | null
}

const FENCED_CODE_BLOCK_RE = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g
const INLINE_CODE_URL_RE = /`(https?:\/\/[^\s`<>]+)`/g
const MARKDOWN_OR_BARE_URL_RE =
  /\[[^\]\r\n]*\]\([^)\r\n]+\)|<(https?:\/\/[^>\s]+)>|(https?:\/\/[^\s<>()[\]`'"]+(?:\([^\s<>()[\]`'"]*\))*)/g
const BARE_DOMAIN_CITATION_RE =
  /(?<!\])([（(])([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)([)）])/gi
const REPO_SLUG_IN_TEXT_RE =
  /\[[^\]\r\n]*\]\([^)\r\n]+\)|\*\*([A-Za-z][A-Za-z0-9-]{1,38}\/[A-Za-z0-9][A-Za-z0-9._-]{1,99})\*\*|`([A-Za-z][A-Za-z0-9-]{1,38}\/[A-Za-z0-9][A-Za-z0-9._-]{1,99})`|((?:^|\n)[ \t]*(?:[-*+]|\d+\.)[ \t]+)([A-Za-z][A-Za-z0-9-]{1,38}\/[A-Za-z0-9][A-Za-z0-9._-]{1,99})(?=[ \t]*[—–\-:：(（])/g
const MARKDOWN_LINK_RE = /\[([^\]\r\n]+)\]\((https?:\/\/[^)\s]+)\)/g
const TRAILING_URL_PUNCTUATION_RE = /[.,;:!?。，；！？、》】」』）]+$/

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function normalizeHostname(rawHost: string) {
  return rawHost.replace(/^www\./i, "").toLowerCase()
}

function tryParseHttpUrl(raw: string): URL | null {
  try {
    const parsed = new URL(raw)
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function trimBareUrl(rawUrl: string) {
  let clean = rawUrl.replace(TRAILING_URL_PUNCTUATION_RE, "")
  while (clean.endsWith(")")) {
    const opens = (clean.match(/\(/g) ?? []).length
    const closes = (clean.match(/\)/g) ?? []).length
    if (closes > opens) {
      clean = clean.slice(0, -1)
    } else {
      break
    }
  }
  return clean
}

function omitNode<T extends { node?: unknown }>(props: T) {
  const next = { ...props }
  delete next.node
  return next
}

/** Collects http(s) URLs surfaced in tool outputs during an Agent run. */
export function collectEventUrls(
  events?: readonly AgentRunEvent[]
): EventUrlEntry[] {
  if (!events?.length) return []
  const byUrl = new Map<string, EventUrlEntry>()
  const visited = new Set<unknown>()

  function record(rawUrl: string, title?: string) {
    const clean = trimBareUrl(rawUrl.trim())
    const parsed = tryParseHttpUrl(clean)
    if (!parsed) return
    const existing = byUrl.get(parsed.href)
    if (!existing) {
      byUrl.set(parsed.href, {
        url: parsed.href,
        hostname: normalizeHostname(parsed.hostname),
        ...(title?.trim() ? { title: title.trim() } : {}),
      })
    } else if (!existing.title && title?.trim()) {
      existing.title = title.trim()
    }
  }

  function walk(value: unknown, depth: number) {
    if (depth > 5 || value === null || value === undefined) return
    if (typeof value === "string") {
      const matches = value.match(/https?:\/\/[^\s"'<>`]+/g)
      if (matches) {
        for (const match of matches) record(match)
      }
      return
    }
    if (typeof value !== "object") return
    if (visited.has(value)) return
    visited.add(value)

    if (Array.isArray(value)) {
      for (const item of value) walk(item, depth + 1)
      return
    }

    const obj = value as Record<string, unknown>
    if (typeof obj.url === "string") {
      const title =
        typeof obj.title === "string"
          ? obj.title
          : typeof obj.name === "string"
            ? obj.name
            : undefined
      record(obj.url, title)
    }
    for (const child of Object.values(obj)) {
      walk(child, depth + 1)
    }
  }

  for (const event of events) {
    walk(event.output, 0)
  }

  return Array.from(byUrl.values())
}

function isLikelyRepoSlug(owner: string, repo: string) {
  if (!/^[A-Za-z][A-Za-z0-9-]{1,38}$/.test(owner)) return false
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$/.test(repo)) return false
  if (!/[A-Za-z]/.test(repo)) return false
  const isUpperAcronym = (value: string) => /^[A-Z0-9._-]+$/.test(value)
  if (isUpperAcronym(owner) && isUpperAcronym(repo)) return false
  const hasSeparator = /[-_.]/.test(owner) || /[-_.]/.test(repo)
  const bothLower = owner === owner.toLowerCase() && repo === repo.toLowerCase()
  const repoLower = repo === repo.toLowerCase()
  return hasSeparator || bothLower || repoLower
}

/** Upgrades inline-code URLs, bare URLs, verified domain citations, and repo slugs into Markdown links. */
export function prepareAutomationMarkdown(
  markdown: string,
  events?: readonly AgentRunEvent[]
) {
  if (!markdown) return ""
  const eventUrls = collectEventUrls(events)
  const urlsByHost = new Map<string, EventUrlEntry[]>()
  const repoUrlBySlug = new Map<string, string>()
  for (const entry of eventUrls) {
    const bucket = urlsByHost.get(entry.hostname) ?? []
    bucket.push(entry)
    urlsByHost.set(entry.hostname, bucket)

    const parsed = tryParseHttpUrl(entry.url)
    if (parsed) {
      const segments = parsed.pathname.split("/").filter(Boolean)
      if (segments.length === 2) {
        const slugKey = `${segments[0]}/${segments[1]}`.toLowerCase()
        if (!repoUrlBySlug.has(slugKey)) {
          repoUrlBySlug.set(slugKey, entry.url)
        }
      }
    }
  }

  return markdown
    .split(FENCED_CODE_BLOCK_RE)
    .map((segment, index) => {
      if (index % 2 === 1) return segment

      let next = segment.replace(INLINE_CODE_URL_RE, (_m, rawUrl: string) => {
        const clean = trimBareUrl(rawUrl)
        return tryParseHttpUrl(clean) ? `[${clean}](${clean})` : _m
      })

      next = next.replace(
        MARKDOWN_OR_BARE_URL_RE,
        (match, angleUrl?: string, bareUrl?: string) => {
          if (angleUrl) {
            const clean = trimBareUrl(angleUrl)
            return tryParseHttpUrl(clean) ? `[${clean}](${clean})` : match
          }
          if (bareUrl) {
            const clean = trimBareUrl(bareUrl)
            if (!tryParseHttpUrl(clean)) return match
            const suffix = bareUrl.slice(clean.length)
            return `[${clean}](${clean})${suffix}`
          }
          return match
        }
      )

      if (urlsByHost.size > 0) {
        next = next.replace(
          BARE_DOMAIN_CITATION_RE,
          (match, openParen: string, domain: string, closeParen: string) => {
            const candidates = urlsByHost.get(normalizeHostname(domain))
            if (!candidates?.length) return match
            const target = candidates[0]!
            return `${openParen}[${domain}](${target.url})${closeParen}`
          }
        )
      }

      next = next.replace(
        REPO_SLUG_IN_TEXT_RE,
        (
          match,
          boldSlug?: string,
          codeSlug?: string,
          listPrefix?: string,
          listSlug?: string
        ) => {
          const slug = boldSlug ?? codeSlug ?? listSlug
          if (!slug) return match
          const [owner = "", repo = ""] = slug.split("/")
          const eventTarget = repoUrlBySlug.get(slug.toLowerCase())
          if (!eventTarget && !isLikelyRepoSlug(owner, repo)) {
            return match
          }
          const targetUrl = eventTarget ?? `https://github.com/${owner}/${repo}`
          if (boldSlug) return `[**${slug}**](${targetUrl})`
          if (codeSlug) return `[\`${slug}\`](${targetUrl})`
          return `${listPrefix ?? ""}[${slug}](${targetUrl})`
        }
      )

      return next
    })
    .join("")
}

function stripFormattingFromLabel(rawLabel: string) {
  return rawLabel
    .trim()
    .replace(/^(\*\*|__|`)([\s\S]*)\1$/, "$2")
    .trim()
}

function formatLinkLabel(rawLabel: string, parsed: URL) {
  const trimmed = stripFormattingFromLabel(rawLabel)
  const hostname = normalizeHostname(parsed.hostname)
  const pathPart =
    parsed.pathname === "/" && !parsed.search
      ? ""
      : `${parsed.pathname}${parsed.search}`.replace(/\/$/, "")
  const displayPath = `${hostname}${pathPart}`

  const isRawUrlLabel =
    !trimmed ||
    trimmed === parsed.href ||
    trimmed.startsWith("http://") ||
    trimmed.startsWith("https://")

  if (isRawUrlLabel) {
    if (hostname === "github.com") {
      const segments = parsed.pathname.split("/").filter(Boolean)
      if (segments.length >= 2) {
        return {
          label: `${segments[0]}/${segments[1]}`,
          hostname,
          displayPath,
        }
      }
    }
    return { label: displayPath, hostname, displayPath }
  }

  return { label: trimmed, hostname, displayPath }
}

/** Extracts unique external http(s) links from prepared Markdown for quick-jump cards. */
export function extractExternalLinks(
  preparedMarkdown: string
): ExtractedExternalLink[] {
  if (!preparedMarkdown) return []
  const byUrl = new Map<string, ExtractedExternalLink>()

  for (const match of preparedMarkdown.matchAll(MARKDOWN_LINK_RE)) {
    const rawLabel = match[1] ?? ""
    const rawUrl = match[2] ?? ""
    if (
      !rawUrl ||
      rawUrl.includes("#nexaflow-source-") ||
      rawUrl.startsWith("/api/v1/artifacts/")
    ) {
      continue
    }
    const parsed = tryParseHttpUrl(rawUrl)
    if (!parsed) continue
    const formatted = formatLinkLabel(rawLabel, parsed)
    const existing = byUrl.get(parsed.href)
    if (!existing) {
      byUrl.set(parsed.href, {
        url: parsed.href,
        ...formatted,
      })
    } else if (
      existing.label === existing.displayPath &&
      formatted.label !== formatted.displayPath
    ) {
      existing.label = formatted.label
    }
  }

  return Array.from(byUrl.values())
}

const editorialMarkdownComponents: Components = {
  h1(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <h1
        className={cn(
          "mt-6 mb-4 border-b border-border/70 pb-2.5 text-lg font-semibold tracking-tight text-foreground first:mt-0",
          className
        )}
        {...restProps}
      />
    )
  },
  h2(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <h2
        className={cn(
          "mt-6 mb-3 flex items-center gap-2 border-b border-border/50 pb-2 text-[15px] font-semibold tracking-tight text-foreground first:mt-0 before:h-3.5 before:w-1 before:shrink-0 before:rounded-full before:bg-primary/70",
          className
        )}
        {...restProps}
      />
    )
  },
  h3(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <h3
        className={cn(
          "mt-5 mb-2 text-sm font-semibold text-foreground first:mt-0",
          className
        )}
        {...restProps}
      />
    )
  },
  p(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <p
        className={cn(
          "my-2.5 text-[14px] leading-7 text-foreground/90 first:mt-0 last:mb-0",
          className
        )}
        {...restProps}
      />
    )
  },
  ul(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <ul
        className={cn(
          "my-3 list-disc space-y-2 pl-5 text-[14px] leading-7 text-foreground/90 marker:text-primary/50",
          className
        )}
        {...restProps}
      />
    )
  },
  ol(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <ol
        className={cn(
          "my-3 list-decimal space-y-2 pl-5 text-[14px] leading-7 text-foreground/90 marker:text-primary/60",
          className
        )}
        {...restProps}
      />
    )
  },
  li(props) {
    const { className, ...restProps } = omitNode(props)
    return <li className={cn("pl-0.5", className)} {...restProps} />
  },
  blockquote(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <blockquote
        className={cn(
          "my-4 rounded-r-xl border-l-2 border-primary/50 bg-muted/30 px-4 py-3 text-[13.5px] leading-6 text-muted-foreground",
          className
        )}
        {...restProps}
      />
    )
  },
  hr(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <hr className={cn("my-6 border-border/60", className)} {...restProps} />
    )
  },
  code(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <code
        className={cn(
          "rounded-md border border-border/60 bg-muted/50 px-1.5 py-0.5 font-mono text-[12.5px] max-sm:break-all",
          className
        )}
        {...restProps}
      />
    )
  },
  table(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <div className="my-4 max-w-full overflow-x-auto rounded-xl border border-border/70">
        <table
          className={cn(
            "w-full border-collapse text-left text-[13px]",
            className
          )}
          {...restProps}
        />
      </div>
    )
  },
  th(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <th
        className={cn(
          "bg-muted/45 px-3 py-2 text-xs font-semibold text-muted-foreground",
          className
        )}
        {...restProps}
      />
    )
  },
  td(props) {
    const { className, ...restProps } = omitNode(props)
    return (
      <td
        className={cn("border-t border-border/50 px-3 py-2 align-top", className)}
        {...restProps}
      />
    )
  },
  a(props) {
    const { className, href, children, ...restProps } = omitNode(props)
    if (href?.startsWith("/api/v1/artifacts/")) {
      return (
        <ArtifactDownloadLink href={href} className={className}>
          {children}
        </ArtifactDownloadLink>
      )
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "inline-flex items-baseline gap-0.5 font-medium text-sky-600 underline decoration-sky-500/40 underline-offset-4 transition-colors hover:text-sky-500 hover:decoration-sky-400 max-sm:break-all dark:text-sky-400 dark:decoration-sky-400/50 dark:hover:text-sky-300",
          className
        )}
        {...restProps}
      >
        <span>{children}</span>
        <ArrowUpRightIcon
          aria-hidden="true"
          className="inline size-3 shrink-0 translate-y-[1px] opacity-80"
        />
      </a>
    )
  },
}

export function AutomationOutputView({
  detail,
  resultMarkdown,
  isActive,
  previewableEntries,
  preview,
  downloadingArtifactId,
  onDownloadArtifact,
  t,
}: {
  detail: AutomationExecutionDetail
  resultMarkdown: string
  isActive: boolean
  previewableEntries: PreviewableArtifactEntry[]
  preview: ReturnType<typeof useAgentArtifactPreview>
  downloadingArtifactId: string | null
  onDownloadArtifact: (artifact: AutomationArtifactLink) => void
  t: TFunction
}) {
  const preparedMarkdown = React.useMemo(
    () => prepareAutomationMarkdown(resultMarkdown, detail.agent_run?.events),
    [detail.agent_run?.events, resultMarkdown]
  )

  const externalLinks = React.useMemo(
    () => extractExternalLinks(preparedMarkdown),
    [preparedMarkdown]
  )

  return (
    <div className="max-w-4xl space-y-6">
      <section>
        <h2 className="sr-only">{t("执行结果")}</h2>
        {preparedMarkdown ? (
          detail.agent_run ? (
            <AgentAnswer
              content={preparedMarkdown}
              events={[]}
              sources={detail.agent_run.sources}
              components={editorialMarkdownComponents}
              t={t}
            />
          ) : (
            <MarkdownContent
              content={preparedMarkdown}
              components={editorialMarkdownComponents}
            />
          )
        ) : isActive ? (
          <div className="flex items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-10 text-xs text-muted-foreground">
            <LoaderCircleIcon className="size-4 animate-spin motion-reduce:animate-none" />
            <span>{t("任务正在执行中")}</span>
          </div>
        ) : (
          <p className="rounded-xl border border-dashed px-4 py-10 text-center text-xs text-muted-foreground">
            {t("无输出内容")}
          </p>
        )}
      </section>

      {externalLinks.length > 0 ? (
        <section className="space-y-3 border-t border-border/60 pt-5">
          <div className="flex items-center gap-2">
            <Link2Icon className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-medium">{t("相关链接")}</h2>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground tabular-nums">
              {externalLinks.length}
            </span>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {externalLinks.map((item) => (
              <a
                key={item.url}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex min-w-0 items-center gap-3 rounded-xl border bg-muted/15 px-3.5 py-2.5 transition-colors hover:border-sky-500/40 hover:bg-muted/35"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background/80 text-muted-foreground transition-colors group-hover:border-sky-500/30 group-hover:text-sky-500">
                  <GlobeIcon className="size-4" />
                </span>
                <span className="min-w-0 flex-1 space-y-0.5">
                  <span className="block truncate text-xs font-medium text-foreground group-hover:text-sky-600 dark:group-hover:text-sky-400">
                    {item.label}
                  </span>
                  <span className="block truncate font-mono text-[11px] text-muted-foreground">
                    {item.displayPath}
                  </span>
                </span>
                <ArrowUpRightIcon
                  aria-hidden="true"
                  className="size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-sky-500"
                />
              </a>
            ))}
          </div>
        </section>
      ) : null}

      {previewableEntries.length > 0 ? (
        <section className="space-y-3 border-t border-border/60 pt-5">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium">{t("生成产物")}</h2>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground tabular-nums">
              {previewableEntries.length}
            </span>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {previewableEntries.map(({ artifact, preview: pItem }) => {
              const busyDownload =
                downloadingArtifactId === artifact.artifact_id
              const FileIcon = getDocumentFileIcon(artifact.filename)
              const isPreviewSelected =
                pItem !== null &&
                preview.selection?.artifact.downloadUrl === pItem.downloadUrl
              return (
                <div
                  key={artifact.artifact_id}
                  className="flex items-center justify-between gap-3 rounded-xl border bg-muted/15 px-3.5 py-3 text-xs transition-colors hover:border-border hover:bg-muted/30"
                >
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background/80">
                      <FileIcon
                        className={cn(
                          "text-xl",
                          getDocumentFileIconColor(artifact.filename)
                        )}
                      />
                    </div>
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <p className="truncate font-medium text-foreground">
                        {artifact.filename}
                      </p>
                      <p className="truncate text-[11px] text-muted-foreground">
                        {artifact.format.toUpperCase()} ·{" "}
                        {formatFileSize(artifact.size_bytes)}
                        {artifact.relative_path
                          ? ` · ${artifact.relative_path}`
                          : ""}
                      </p>
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-1">
                    {pItem ? (
                      <Button
                        type="button"
                        size="xs"
                        variant={isPreviewSelected ? "secondary" : "ghost"}
                        aria-expanded={isPreviewSelected}
                        aria-controls={
                          preview.selection ? preview.panelId : undefined
                        }
                        onClick={(event) =>
                          preview.open(pItem, event.currentTarget)
                        }
                      >
                        <EyeIcon />
                        <span>{t("预览")}</span>
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      disabled={busyDownload}
                      onClick={() => onDownloadArtifact(artifact)}
                    >
                      {busyDownload ? (
                        <LoaderCircleIcon className="animate-spin" />
                      ) : (
                        <DownloadIcon />
                      )}
                      <span>{t("下载产物")}</span>
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      ) : null}
    </div>
  )
}

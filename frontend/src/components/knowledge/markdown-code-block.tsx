"use client"

import * as React from "react"
import { CheckIcon, Code2Icon, CopyIcon, ImageIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import { copyText } from "@/lib/clipboard"
import { cn } from "@/lib/utils"

// ponytail: skip rich rendering above 50 KB; move it off-thread if larger blocks matter.
const MAX_RICH_CODE_CHARS = 50_000

type CopyState = "idle" | "copied" | "failed"
type HighlightedCode = { code: string; language: string; html: string }
type MermaidRender = { code: string; isDark: boolean; svg: string | null }

/**
 * Observes theme-related class changes on the document root.
 *
 * @param onChange - Callback invoked when the document root's class attribute changes
 * @returns A function that stops observing theme changes
 */
function subscribeToTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange)
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  })
  return () => observer.disconnect()
}

/**
 * Determines whether the document is using the dark theme.
 *
 * @returns `true` if the document root has the `dark` class, `false` otherwise.
 */
function isDarkTheme() {
  return document.documentElement.classList.contains("dark")
}

function CopyFeedback({ state }: { state: CopyState }) {
  const { t } = useLanguage()
  if (state === "idle") return null
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn(
        "text-[11px]",
        state === "failed" ? "text-destructive" : "text-muted-foreground"
      )}
    >
      {t(state === "failed" ? "复制失败" : "已复制")}
    </span>
  )
}

/**
 * Tracks the status of an asynchronous copy operation.
 *
 * @returns The current copy state and a function that marks the operation as copied or failed.
 */
function useCopyState() {
  const [state, setState] = React.useState<CopyState>("idle")
  const copy = React.useCallback(async (operation: () => Promise<void>) => {
    try {
      await operation()
      setState("copied")
    } catch {
      setState("failed")
    }
  }, [])
  return { state, copy }
}

/**
 * Provides a bordered layout for rendered code blocks with a language label and action controls.
 *
 * @param language - The language displayed for the code block
 * @param actions - Controls rendered alongside the language label
 * @param children - The rendered code-block content
 */
function CodeFrame({
  language,
  actions,
  children,
}: {
  language: string
  actions: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="my-3 min-w-0 overflow-hidden rounded-md border bg-muted/30">
      <div className="flex min-h-8 items-center justify-between gap-2 border-b bg-muted/40 px-2 text-xs text-muted-foreground">
        <span className="truncate font-mono">{language || "text"}</span>
        <div className="flex shrink-0 items-center gap-1">{actions}</div>
      </div>
      {children}
    </div>
  )
}

/**
 * Renders a code block with optional syntax highlighting and copy controls.
 *
 * @param code - The source code to display.
 * @param language - The code language used for labeling and syntax highlighting.
 * @returns A rendered code block.
 */
function SourceCodeBlock({ code, language }: MarkdownCodeBlockProps) {
  const { t } = useLanguage()
  const { state, copy } = useCopyState()
  const [highlighted, setHighlighted] =
    React.useState<HighlightedCode | null>(null)
  const highlightedHtml =
    code.length <= MAX_RICH_CODE_CHARS && highlighted?.language === language
      ? highlighted.html
      : null

  React.useEffect(() => {
    if (!language || code.length > MAX_RICH_CODE_CHARS) return
    let active = true
    void import("shiki/bundle/web")
      .then(({ codeToHtml }) =>
        codeToHtml(code, {
          lang: language as never,
          themes: { light: "github-light", dark: "github-dark" },
          defaultColor: false,
        })
      )
      .then((html) => {
        if (active) setHighlighted({ code, language, html })
      })
      .catch(() => {
        if (active) setHighlighted(null)
      })
    return () => {
      active = false
    }
  }, [code, language])

  return (
    <CodeFrame
      language={language}
      actions={
        <>
          <CopyFeedback state={state} />
          <Button
            type="button"
            variant="ghost"
            size="xs"
            aria-label={t("复制代码")}
            onClick={() => void copy(() => copyText(code))}
          >
            {state === "copied" ? <CheckIcon /> : <CopyIcon />}
            {t("复制")}
          </Button>
        </>
      }
    >
      {highlightedHtml ? (
        <div
          className="markdown-shiki overflow-x-auto [&_.shiki]:m-0 [&_.shiki]:min-w-max [&_.shiki]:bg-transparent [&_.shiki]:p-3 [&_.shiki]:text-xs [&_.shiki]:leading-5"
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />
      ) : (
        <pre className="overflow-x-auto p-3 text-xs leading-5">
          <code>{code}</code>
        </pre>
      )}
    </CodeFrame>
  )
}

/**
 * Copies SVG markup to the clipboard as an SVG image.
 *
 * @param svg - The SVG markup to copy
 */
async function copySvg(svg: string) {
  if (
    typeof navigator === "undefined" ||
    !navigator.clipboard?.write ||
    typeof ClipboardItem === "undefined"
  ) {
    throw new Error("SVG clipboard is unavailable")
  }
  const blob = new Blob([svg], { type: "image/svg+xml" })
  await navigator.clipboard.write([
    new ClipboardItem({ "image/svg+xml": blob }),
  ])
}

/**
 * Renders a Mermaid diagram with source-code fallback and copy controls.
 *
 * @param code - Mermaid source code to render
 */
function MermaidCodeBlock({ code }: MarkdownCodeBlockProps) {
  const { t } = useLanguage()
  const { state, copy } = useCopyState()
  const [showSource, setShowSource] = React.useState(false)
  const isDark = React.useSyncExternalStore(
    subscribeToTheme,
    isDarkTheme,
    () => false,
  )
  const [rendered, setRendered] = React.useState<MermaidRender | null>(null)
  const currentRender = rendered?.isDark === isDark ? rendered : null

  React.useEffect(() => {
    if (code.length > MAX_RICH_CODE_CHARS) return
    let active = true
    void import("beautiful-mermaid")
      .then(({ renderMermaidSVG }) => {
        try {
          const svg = renderMermaidSVG(code, {
            bg: isDark ? "#18181b" : "#ffffff",
            fg: isDark ? "#fafafa" : "#27272a",
            transparent: true,
          })
          if (active) setRendered({ code, isDark, svg })
        } catch {
          if (active) setRendered({ code, isDark, svg: null })
        }
      })
      .catch(() => {
        if (active) setRendered({ code, isDark, svg: null })
      })
    return () => {
      active = false
    }
  }, [code, isDark])

  if (!currentRender?.svg) {
    const failed =
      code.length > MAX_RICH_CODE_CHARS || currentRender?.svg === null
    return (
      <CodeFrame
        language="mermaid"
        actions={
          <>
            <CopyFeedback state={state} />
            <Button
              type="button"
              variant="ghost"
              size="xs"
              aria-label={t("复制源码")}
              onClick={() => void copy(() => copyText(code))}
            >
              {state === "copied" ? <CheckIcon /> : <CopyIcon />}
              {t("复制")}
            </Button>
          </>
        }
      >
        {failed ? (
          <p role="alert" className="border-b px-3 py-2 text-xs text-destructive">
            {t("图表渲染失败")}
          </p>
        ) : null}
        <pre className="overflow-x-auto p-3 text-xs leading-5">
          <code>{code}</code>
        </pre>
      </CodeFrame>
    )
  }

  const renderedSvg = currentRender.svg

  return (
    <CodeFrame
      language="mermaid"
      actions={
        <>
          <CopyFeedback state={state} />
          <Button
            type="button"
            variant="ghost"
            size="xs"
            aria-label={t(showSource ? "显示图表" : "显示源码")}
            onClick={() => setShowSource((current) => !current)}
          >
            {showSource ? <ImageIcon /> : <Code2Icon />}
            {t(showSource ? "图表" : "源码")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            aria-label={t(showSource ? "复制源码" : "复制图表")}
            onClick={() =>
              void copy(() =>
                showSource ? copyText(code) : copySvg(renderedSvg),
              )
            }
          >
            {state === "copied" ? <CheckIcon /> : <CopyIcon />}
            {t("复制")}
          </Button>
        </>
      }
    >
      {showSource ? (
        <pre className="overflow-x-auto p-3 text-xs leading-5">
          <code>{code}</code>
        </pre>
      ) : (
        <div className="overflow-x-auto p-3">
          {/* Generated SVG is kept in an image sandbox instead of injected into the DOM. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(renderedSvg)}`}
            alt={t("Mermaid 图表")}
            className="mx-auto h-auto max-w-none"
          />
        </div>
      )}
    </CodeFrame>
  )
}

type MarkdownCodeBlockProps = {
  code: string
  language: string
}

/**
 * Renders a Markdown code block with language-specific formatting.
 *
 * @param props - The code content and language to render
 */
export function MarkdownCodeBlock(props: MarkdownCodeBlockProps) {
  return props.language === "mermaid" ? (
    <MermaidCodeBlock {...props} />
  ) : (
    <SourceCodeBlock {...props} />
  )
}

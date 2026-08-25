"use client"

import * as React from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkCjkFriendly from "remark-cjk-friendly/parseOnly"
import remarkGfm from "remark-gfm"

import { MarkdownCodeBlock } from "@/components/knowledge/markdown-code-block"
import { cn } from "@/lib/utils"
import { useLanguage } from "@/contexts/language-provider"

type MarkdownContentProps = {
  content: string
  className?: string
}

/**
 * Removes the Markdown parser's internal node property from component props.
 *
 * @param props - Component props that may include a Markdown parser node
 * @returns A copy of the props without the `node` property
 */
function omitMarkdownNode<T extends { node?: unknown }>(props: T) {
  const nextProps = { ...props }
  delete nextProps.node
  return nextProps
}

/**
 * Renders a Markdown image or a localized placeholder for unsupported image sources.
 *
 * @param props - Image attributes parsed from the Markdown content.
 * @returns An image element for allowed sources, or placeholder text for empty, data, custom asset, or blob sources.
 */
function MarkdownImage(
  props: React.ImgHTMLAttributes<HTMLImageElement> & { node?: unknown },
) {
  const { t } = useLanguage()
  const src = String(props.src ?? "")
  if (
    !src ||
    src.startsWith("data:") ||
    src.startsWith("nexaflow-asset:") ||
    src.startsWith("blob:")
  ) {
    return (
      <span className="text-xs text-muted-foreground">{t("图片")}</span>
    )
  }
  const { className, ...restProps } = omitMarkdownNode(props)
  return (
    // Markdown may contain arbitrary external URLs that are not configured for next/image.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={cn(
        "my-2 max-h-64 max-w-full rounded border object-contain",
        className
      )}
      loading="lazy"
      decoding="async"
      {...restProps}
    />
  )
}

/**
 * Renders Markdown code blocks with extracted language metadata and source text.
 *
 * Falls back to a standard `<pre>` element when the expected code child is absent.
 *
 * @returns A rendered code block or preformatted element.
 */
function MarkdownPre(
  props: React.HTMLAttributes<HTMLPreElement> & { node?: unknown },
) {
  const child = React.Children.toArray(props.children)[0]
  if (
    !React.isValidElement<{
      className?: string
      children?: React.ReactNode
    }>(child)
  ) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return <pre className={className} {...restProps} />
  }
  const language =
    /(?:^|\s)language-([^\s]+)/.exec(child.props.className ?? "")?.[1]
      ?.toLowerCase()
      .slice(0, 64) ?? ""
  const code = React.Children.toArray(child.props.children)
    .map((value) =>
      typeof value === "string" || typeof value === "number" ? value : ""
    )
    .join("")
    .replace(/\n$/, "")
  return <MarkdownCodeBlock code={code} language={language} />
}

const markdownComponents: Components = {
  h1(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <h1
        className={cn("mb-3 mt-4 text-xl font-semibold first:mt-0", className)}
        {...restProps}
      />
    )
  },
  h2(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <h2
        className={cn("mb-3 mt-4 text-lg font-semibold first:mt-0", className)}
        {...restProps}
      />
    )
  },
  h3(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <h3
        className={cn("mb-2 mt-3 text-base font-semibold first:mt-0", className)}
        {...restProps}
      />
    )
  },
  p(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <p className={cn("my-2 first:mt-0 last:mb-0", className)} {...restProps} />
    )
  },
  a(props) {
    const { className, href, ...restProps } = omitMarkdownNode(props)
    const isArtifact = href?.startsWith("/api/v1/artifacts/") ?? false
    return (
      <a
        className={cn(
          isArtifact
            ? "font-medium text-sky-600 underline decoration-sky-600/40 underline-offset-4 hover:text-sky-700 dark:text-sky-400 dark:decoration-sky-400/50 dark:hover:text-sky-300"
            : "font-medium text-primary underline-offset-4 hover:underline",
          className
        )}
        href={href}
        download={isArtifact ? "" : undefined}
        target={isArtifact ? undefined : "_blank"}
        rel={isArtifact ? undefined : "noreferrer"}
        {...restProps}
      />
    )
  },
  ul(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return <ul className={cn("my-2 list-disc pl-5", className)} {...restProps} />
  },
  ol(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <ol className={cn("my-2 list-decimal pl-5", className)} {...restProps} />
    )
  },
  li(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return <li className={cn("my-1", className)} {...restProps} />
  },
  blockquote(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <blockquote
        className={cn("my-3 border-l-2 pl-3 text-muted-foreground", className)}
        {...restProps}
      />
    )
  },
  code(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <code
        className={cn(
          "rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]",
          className
        )}
        {...restProps}
      />
    )
  },
  pre: MarkdownPre,
  table(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <div className="my-3 overflow-x-auto">
        <table
          className={cn("w-full border-collapse text-left text-sm", className)}
          {...restProps}
        />
      </div>
    )
  },
  th(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <th
        className={cn("border bg-muted/60 px-2 py-1 font-semibold", className)}
        {...restProps}
      />
    )
  },
  td(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <td
        className={cn("border px-2 py-1 align-top", className)}
        {...restProps}
      />
    )
  },
}

/**
 * Renders Markdown content with styled elements and localized empty-content messaging.
 *
 * @param content - The Markdown content to render
 * @param className - Optional CSS class name applied to the rendered content
 */
export function MarkdownContent({ content, className }: MarkdownContentProps) {
  const { t } = useLanguage()
  const value = content.trim()
  const components = React.useMemo<Components>(
    () => ({ ...markdownComponents, img: MarkdownImage }),
    [],
  )

  if (!value) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        {t("暂无内容")}
      </p>
    )
  }

  return (
    <div className={cn("min-w-0 text-sm leading-6 text-foreground", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkCjkFriendly]}
        components={components}
      >
        {value}
      </ReactMarkdown>
    </div>
  )
}

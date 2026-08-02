import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

type MarkdownContentProps = {
  content: string
  className?: string
}

function omitMarkdownNode<T extends { node?: unknown }>(props: T) {
  const nextProps = { ...props }
  delete nextProps.node
  return nextProps
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
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <a
        className={cn(
          "font-medium text-primary underline-offset-4 hover:underline",
          className
        )}
        target="_blank"
        rel="noreferrer"
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
  pre(props) {
    const { className, ...restProps } = omitMarkdownNode(props)
    return (
      <pre
        className={cn(
          "my-3 overflow-x-auto rounded-md border bg-muted/40 p-3 text-xs leading-5",
          className
        )}
        {...restProps}
      />
    )
  },
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

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  const value = content.trim()

  if (!value) {
    return <p className={cn("text-sm text-muted-foreground", className)}>暂无内容</p>
  }

  return (
    <div className={cn("min-w-0 text-sm leading-6 text-foreground", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {value}
      </ReactMarkdown>
    </div>
  )
}

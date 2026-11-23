import type { ReactNode } from "react"
import { FileTextIcon } from "lucide-react"

import type { TFunction } from "@/i18n"

/** The same source card is used in retrieval results and citation details. */
export function AgentContextCard({
  title,
  content,
  document,
  meta,
  footer,
  t,
}: {
  title: string
  content: string
  document: string
  meta?: string
  footer?: ReactNode
  t: TFunction
}) {
  const extension = document.match(/\.([a-z0-9]{1,8})$/i)?.[1].toUpperCase()
  return (
    <article className="agent-beautiful bui-context-card">
      <div className="bui-context-header">
        <span className="bui-context-title">
          <FileTextIcon className="size-3 shrink-0" aria-hidden="true" />
          <span className="truncate">{title || document || t("未知文档")}</span>
        </span>
        <span className="bui-context-count">
          {t("字符数")} {content.length.toLocaleString()}
        </span>
      </div>
      {meta ? <p className="bui-context-meta">{meta}</p> : null}
      <p className="bui-context-body">{content}</p>
      <div className="bui-context-footer">
        {footer ?? (
          <span className="bui-context-file" title={document}>
            <span className="bui-file-type" data-type={extension}>
              {extension || t("文档")}
            </span>
            <span className="truncate">{document || t("未知文档")}</span>
          </span>
        )}
      </div>
    </article>
  )
}

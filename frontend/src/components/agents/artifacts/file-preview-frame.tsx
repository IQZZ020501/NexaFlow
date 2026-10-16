"use client"

import * as React from "react"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  LoaderCircleIcon,
  MinusIcon,
  PlusIcon,
} from "lucide-react"
import { IconButton } from "@/components/ui/icon-button"
import { useLanguage } from "@/contexts/language-provider"
import {
  filePreviewDocument,
  type OfficePreviewFormat,
  type PreviewMetadata,
  type PreviewPosition,
} from "./preview-protocol"

export function FilePreviewFrame({
  bytes,
  format,
  title,
  onError,
}: {
  bytes: ArrayBuffer
  format: OfficePreviewFormat
  title: string
  onError: () => void
}) {
  const { t } = useLanguage()
  const frame = React.useRef<HTMLIFrameElement>(null)
  const [channel] = React.useState(() =>
    Array.from(crypto.getRandomValues(new Uint32Array(4)), (value) =>
      value.toString(16)
    ).join("-")
  )
  const [metadata, setMetadata] = React.useState<PreviewMetadata | null>(null)
  const [position, setPosition] = React.useState<PreviewPosition>({
    page: 1,
    sheet: 0,
    zoom: 1,
  })
  const document = React.useMemo(
    () => filePreviewDocument(window.location.origin, channel),
    [channel]
  )
  const emptyLabel = t("工作表为空")

  React.useEffect(() => {
    let sent = false
    const timeout = window.setTimeout(onError, 30_000)
    function receive(event: MessageEvent) {
      if (
        event.source !== frame.current?.contentWindow ||
        event.origin !== "null" ||
        event.data?.channel !== channel
      )
        return
      if (event.data.type === "ready" && !sent) {
        sent = true
        const copy = bytes.slice(0)
        frame.current?.contentWindow?.postMessage(
          { type: "open", channel, format, bytes: copy, emptyLabel },
          "*",
          [copy]
        )
      } else if (sent && event.data.type === "rendered") {
        const next = event.data.metadata as PreviewMetadata | undefined
        if (
          !next ||
          !Number.isSafeInteger(next.pageCount) ||
          next.pageCount < 0 ||
          !Array.isArray(next.sheets) ||
          next.sheets.length > 2500 ||
          !next.sheets.every(
            (name) => typeof name === "string" && name.length <= 255
          ) ||
          typeof next.truncated !== "boolean"
        )
          return
        window.clearTimeout(timeout)
        setMetadata(next)
      } else if (sent && event.data.type === "failed") {
        window.clearTimeout(timeout)
        onError()
      }
    }
    window.addEventListener("message", receive)
    return () => {
      window.clearTimeout(timeout)
      window.removeEventListener("message", receive)
    }
  }, [bytes, channel, format, emptyLabel, onError])

  React.useEffect(() => {
    frame.current?.contentWindow?.postMessage(
      { type: "position", channel, position },
      "*"
    )
  }, [channel, position])

  return (
    <>
      <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b px-3 py-1.5">
        {metadata?.sheets.length ? (
          <select
            aria-label={t("选择工作表")}
            value={position.sheet}
            onChange={(event) =>
              setPosition((current) => ({
                ...current,
                sheet: Number(event.target.value),
              }))
            }
            className="h-8 max-w-48 min-w-0 rounded-md border bg-background px-2 text-sm"
          >
            {metadata.sheets.map((name, index) => (
              <option key={index} value={index}>
                {name}
              </option>
            ))}
          </select>
        ) : null}
        {metadata && metadata.pageCount > 0 ? (
          <div className="flex items-center gap-1">
            <IconButton
              label={t("上一页")}
              className="size-8"
              disabled={position.page <= 1}
              onClick={() =>
                setPosition((current) => ({
                  ...current,
                  page: current.page - 1,
                }))
              }
            >
              <ChevronLeftIcon className="size-4" />
            </IconButton>
            <span
              className="min-w-14 text-center text-xs tabular-nums"
              aria-live="polite"
            >
              {position.page} / {metadata.pageCount}
            </span>
            <IconButton
              label={t("下一页")}
              className="size-8"
              disabled={position.page >= metadata.pageCount}
              onClick={() =>
                setPosition((current) => ({
                  ...current,
                  page: current.page + 1,
                }))
              }
            >
              <ChevronRightIcon className="size-4" />
            </IconButton>
          </div>
        ) : null}
        <div className="ml-auto flex items-center gap-1">
          <IconButton
            label={t("缩小")}
            className="size-8"
            disabled={!metadata || position.zoom <= 0.5}
            onClick={() =>
              setPosition((current) => ({
                ...current,
                zoom: current.zoom - 0.25,
              }))
            }
          >
            <MinusIcon className="size-4" />
          </IconButton>
          <span className="w-10 text-center text-xs tabular-nums">
            {Math.round(position.zoom * 100)}%
          </span>
          <IconButton
            label={t("放大")}
            className="size-8"
            disabled={!metadata || position.zoom >= 2}
            onClick={() =>
              setPosition((current) => ({
                ...current,
                zoom: current.zoom + 0.25,
              }))
            }
          >
            <PlusIcon className="size-4" />
          </IconButton>
        </div>
      </div>
      {metadata?.truncated ? (
        <p
          role="status"
          className="border-b px-3 py-2 text-xs text-muted-foreground"
        >
          {t("预览仅显示前 500 行、50 列，完整内容请下载文件。")}
        </p>
      ) : null}
      <div className="relative min-h-0 flex-1">
        {!metadata ? (
          <div
            role="status"
            className="absolute inset-0 z-10 flex items-center justify-center gap-2 bg-muted text-sm text-muted-foreground"
          >
            <LoaderCircleIcon className="size-4 animate-spin" />
            {t("正在加载文件预览")}
          </div>
        ) : null}
        <iframe
          ref={frame}
          title={title}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          srcDoc={document}
          className="h-full w-full border-0 bg-white"
        />
      </div>
    </>
  )
}

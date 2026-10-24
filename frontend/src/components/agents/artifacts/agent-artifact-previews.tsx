"use client"

import * as React from "react"
import { DownloadIcon, EyeIcon, LoaderCircleIcon, XIcon } from "lucide-react"
import {
  getDocumentFileIcon,
  getDocumentFileIconColor,
} from "@/components/knowledge/document-file-icon"
import { ArtifactDownloadLink } from "@/components/knowledge/markdown-content"
import { Button } from "@/components/ui/button"
import { IconButton } from "@/components/ui/icon-button"
import { useLanguage } from "@/contexts/language-provider"
import {
  previewArtifactsForEvents,
  htmlPreviewDocument,
  MAX_PREVIEW_BYTES,
  PREVIEW_MIME_TYPES,
  type ArtifactEvent,
  type PreviewArtifact,
} from "@/lib/agent-artifacts"
import { ApiError, requestBlob } from "@/lib/api-client"
import { FilePreviewFrame } from "./file-preview-frame"
import { AgentArtifactPreviewContext } from "./agent-artifact-preview-context"
import { ArtifactPreviewPane } from "./artifact-preview-pane"

type PreviewState =
  | { status: "html"; document: string }
  | { status: "file"; bytes: ArrayBuffer }
  | { status: "loading" | "failed" | "unavailable" }

function ArtifactPreviewBody({ artifact }: { artifact: PreviewArtifact }) {
  const { t } = useLanguage()
  const [state, setState] = React.useState<PreviewState>({ status: "loading" })
  const [attempt, setAttempt] = React.useState(0)
  const fail = React.useCallback(() => setState({ status: "failed" }), [])
  const title = t("文件预览：{filename}", { filename: artifact.filename })
  React.useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      controller.abort()
      setState({ status: "failed" })
    }, 30_000)
    async function load() {
      try {
        const blob = await requestBlob("/api/v1/artifacts/download", {
          method: "POST",
          credentials: "omit",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token: artifact.downloadUrl.slice("/api/v1/artifacts/".length),
          }),
          signal: controller.signal,
        })
        if (
          !blob.size ||
          blob.size > MAX_PREVIEW_BYTES ||
          blob.type.split(";")[0] !== PREVIEW_MIME_TYPES[artifact.format]
        )
          throw new Error("Invalid preview file")
        const next: PreviewState =
          artifact.format === "html"
            ? {
                status: "html",
                document: htmlPreviewDocument(await blob.text()),
              }
            : { status: "file", bytes: await blob.arrayBuffer() }
        if (!controller.signal.aborted) setState(next)
      } catch (error) {
        if (!controller.signal.aborted)
          setState({
            status:
              error instanceof ApiError && [404, 410].includes(error.status)
                ? "unavailable"
                : "failed",
          })
      } finally {
        window.clearTimeout(timeout)
      }
    }
    void load()
    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [artifact.downloadUrl, artifact.format, attempt])

  if (state.status === "html")
    return (
      <iframe
        title={title}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        srcDoc={state.document}
        className="min-h-0 w-full flex-1 border-0 bg-white"
      />
    )
  if (state.status === "file" && artifact.format !== "html")
    return (
      <FilePreviewFrame
        bytes={state.bytes}
        format={artifact.format}
        title={title}
        onError={fail}
      />
    )
  return (
    <div
      role="status"
      className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted-foreground"
    >
      {state.status === "loading" ? (
        <>
          <LoaderCircleIcon className="size-5 animate-spin" />
          {t("正在加载文件预览")}
        </>
      ) : (
        <>
          <p>
            {state.status === "unavailable"
              ? t("文件已过期或不可用，请重新生成。")
              : t("文件预览失败，可重试或下载原文件查看。")}
          </p>
          {state.status === "failed" ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setState({ status: "loading" })
                setAttempt((value) => value + 1)
              }}
            >
              {t("重试")}
            </Button>
          ) : null}
        </>
      )}
    </div>
  )
}

function DownloadFile({ artifact }: { artifact: PreviewArtifact }) {
  const { t } = useLanguage()
  return (
    <ArtifactDownloadLink
      href={artifact.downloadUrl}
      filename={artifact.filename}
      className="flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground no-underline hover:bg-muted hover:text-foreground"
    >
      <DownloadIcon className="size-4" />
      <span className="sr-only">{t("下载原文")}</span>
    </ArtifactDownloadLink>
  )
}

export function AgentArtifactPreviews({
  events,
}: {
  events: readonly ArtifactEvent[]
}) {
  const { t } = useLanguage()
  const preview = React.useContext(AgentArtifactPreviewContext)
  const ownerId = React.useId()
  const artifacts = React.useMemo(
    () => previewArtifactsForEvents(events),
    [events]
  )
  const updateSource = preview?.updateSource
  React.useEffect(() => {
    updateSource?.(
      ownerId,
      artifacts.map((artifact) => artifact.downloadUrl)
    )
  }, [artifacts, ownerId, updateSource])
  React.useEffect(() => () => updateSource?.(ownerId), [ownerId, updateSource])
  if (!artifacts.length) return null
  if (!preview)
    throw new Error("Artifact previews require a conversation provider")
  return (
    <div className="mt-3 grid min-w-0 gap-2">
      {artifacts.map((artifact) => {
        const Icon = getDocumentFileIcon(artifact.filename)
        return (
          <div
            key={artifact.downloadUrl}
            className="flex min-w-0 items-center gap-1 rounded-lg border bg-background p-1"
          >
            <button
              type="button"
              aria-label={t("预览文件：{filename}", {
                filename: artifact.filename,
              })}
              aria-expanded={
                preview.selection?.artifact.downloadUrl === artifact.downloadUrl
              }
              aria-controls={preview.selection ? preview.panelId : undefined}
              onClick={(event) => {
                preview.open(artifact, event.currentTarget)
              }}
              className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring aria-expanded:bg-muted"
            >
              <Icon
                className={`shrink-0 text-2xl ${getDocumentFileIconColor(artifact.filename)}`}
              />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">
                {artifact.filename}
              </span>
              <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                <EyeIcon className="size-3.5" />
                {t("预览")}
              </span>
            </button>
            <DownloadFile artifact={artifact} />
          </div>
        )
      })}
    </div>
  )
}

export function AgentArtifactPreviewPanel() {
  const { t } = useLanguage()
  const preview = React.useContext(AgentArtifactPreviewContext)
  const selected = preview?.selection?.artifact
  const headingRef = React.useRef<HTMLHeadingElement>(null)
  React.useEffect(() => {
    if (selected) headingRef.current?.focus({ preventScroll: true })
  }, [selected])
  if (!preview || !selected) return null

  return (
    <ArtifactPreviewPane
      id={preview.panelId}
      label={t("文件预览：{filename}", { filename: selected.filename })}
      onClose={preview.close}
    >
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="min-w-0 flex-1 truncate text-sm font-medium outline-none"
        >
          {selected.filename}
        </h2>
        <DownloadFile artifact={selected} />
        <IconButton
          label={t("关闭")}
          className="size-9 shrink-0"
          onClick={preview.close}
        >
          <XIcon className="size-4" />
        </IconButton>
      </div>
      <ArtifactPreviewBody key={selected.downloadUrl} artifact={selected} />
    </ArtifactPreviewPane>
  )
}

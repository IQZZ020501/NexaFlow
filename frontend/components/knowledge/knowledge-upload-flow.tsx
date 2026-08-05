import * as React from "react"
import {
  AlertCircleIcon,
  ArrowLeftIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  FileTextIcon,
  FilesIcon,
  FolderOpenIcon,
  LoaderCircleIcon,
  RotateCcwIcon,
  ScissorsIcon,
  type LucideIcon,
  UploadIcon,
  XIcon,
} from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"
import {
  indexKnowledgeDocument,
  listKnowledgeDocumentChunks,
  listKnowledgeDocuments,
  parseKnowledgeDocument,
  uploadKnowledgeDocument,
} from "@/lib/api/knowledge"
import { ChunkPreviewList } from "@/components/knowledge/chunk-preview-list"
import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeDocumentChunk,
} from "@/lib/api/knowledge"
import type { TFunction, TranslationKey } from "@/i18n"
import {
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
  MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
  type KnowledgeUploadParseSettings,
  type KnowledgeUploadRouteState,
  type KnowledgeUploadStep,
} from "@/lib/knowledge-upload-route"
import { cn } from "@/lib/utils"
import { formatBytes } from "@/components/knowledge/status-labels"

type SegmentMode = KnowledgeUploadParseSettings["segmentMode"]

type UploadedDocument = KnowledgeDocument & {
  chunks: KnowledgeDocumentChunk[]
}

const UNPARSED_STATUS = "uploaded"
const PARSING_STATUSES = new Set(["parse_queued", "parsing"])
const SUPPORTED_FILE_TYPES = [".docx", ".md", ".markdown", ".pdf", ".txt"]
const SMART_CHUNK_SIZE = DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkSize
const SMART_CHUNK_OVERLAP =
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkOverlap
const SMART_CLEANING_RULES =
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.cleaningRules
const SMART_SPLIT_SEPARATOR =
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.splitSeparator
const PREVIEW_POLL_INTERVAL_MS = 1200
const PREVIEW_POLL_TIMEOUT_MS = 60_000

function hasOpenPreviewTask(documents: UploadedDocument[]) {
  return documents.some((document) => PARSING_STATUSES.has(document.status))
}

export function KnowledgeUploadFlow({
  token,
  workspaceId,
  knowledgeBase,
  step,
  routeState,
  onCancel,
  onRouteSegment,
  onBackToFiles,
  onDone,
  onNotify,
}: {
  token: string
  workspaceId: string
  knowledgeBase: KnowledgeBase
  step: KnowledgeUploadStep
  routeState?: KnowledgeUploadRouteState
  onCancel: () => void
  onRouteSegment: (routeState: KnowledgeUploadRouteState) => void
  onBackToFiles: () => void
  onDone: () => void | Promise<void>
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { t } = useLanguage()
  const cleaningRuleOptions = [
    { value: "trim_lines", label: t("去除行首尾空白") },
    { value: "remove_empty_lines", label: t("删除空行") },
    { value: "collapse_spaces", label: t("合并连续空白") },
  ]
  const splitSeparatorOptions = [
    { value: "\n\n", label: t("空行（段落）") },
    { value: "\n", label: t("换行") },
    { value: "。", label: t("中文句号（。）") },
    { value: ".", label: t("英文句号（.）") },
  ]
  const [files, setFiles] = React.useState<File[]>([])
  const [uploadedDocuments, setUploadedDocuments] = React.useState<
    UploadedDocument[]
  >([])
  const [selectedDocumentId, setSelectedDocumentId] = React.useState<
    string | null
  >(null)
  const [segmentMode, setSegmentMode] = React.useState<SegmentMode>(
    routeState?.parseSettings.segmentMode ?? "smart",
  )
  const [chunkSize, setChunkSize] = React.useState(
    routeState?.parseSettings.chunkSize ?? SMART_CHUNK_SIZE,
  )
  const [chunkOverlap, setChunkOverlap] = React.useState(
    routeState?.parseSettings.chunkOverlap ?? SMART_CHUNK_OVERLAP,
  )
  const [cleaningRules, setCleaningRules] = React.useState<string[]>(() => [
    ...(routeState?.parseSettings.cleaningRules ?? SMART_CLEANING_RULES),
  ])
  const [splitSeparator, setSplitSeparator] = React.useState(
    routeState?.parseSettings.splitSeparator ?? SMART_SPLIT_SEPARATOR,
  )
  const [previewOptionsSignature, setPreviewOptionsSignature] = React.useState<
    string | null
  >(null)
  const [isDragActive, setIsDragActive] = React.useState(false)
  const [isUploading, setIsUploading] = React.useState(false)
  const [isParsing, setIsParsing] = React.useState(false)
  const [isRefreshing, setIsRefreshing] = React.useState(false)
  const [isIndexing, setIsIndexing] = React.useState(false)
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const folderInputRef = React.useRef<HTMLInputElement>(null)
  const pendingPreviewOptionsSignatureRef = React.useRef<string | null>(null)

  React.useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "")
  }, [])

  const totalChunks = uploadedDocuments.reduce(
    (count, document) => count + document.chunks.length,
    0,
  )
  const selectedDocument =
    uploadedDocuments.find((document) => document.id === selectedDocumentId) ??
    uploadedDocuments[0] ??
    null
  const selectedFileBytes = files.reduce((total, file) => total + file.size, 0)
  const hasPendingParsing = uploadedDocuments.some((document) =>
    PARSING_STATUSES.has(document.status),
  )
  const hasUnpreviewedDocuments = uploadedDocuments.some(
    (document) =>
      document.status === UNPARSED_STATUS ||
      PARSING_STATUSES.has(document.status),
  )
  const hasFailedParsing = uploadedDocuments.some((document) =>
    document.status.endsWith("_failed"),
  )
  const isPreviewRunning = isParsing || hasPendingParsing
  const isSegmentInvalid =
    segmentMode === "advanced" && chunkOverlap >= chunkSize

  const reportError = React.useCallback(
    (error: unknown) => {
      onNotify("error", getErrorMessage(error, t))
    },
    [onNotify, t],
  )

  const loadPreviewDocuments = React.useCallback(
    async (documentIds: string[]) => {
      const documents = await listKnowledgeDocuments(
        token,
        workspaceId,
        knowledgeBase.id,
        { includeStaged: true },
      )
      const documentsById = new Map(
        documents.map((document) => [document.id, document]),
      )
      const loadedDocuments = await Promise.all(
        documentIds.map(async (documentId) => {
          const document = documentsById.get(documentId)
          if (!document) {
            return null
          }
          const chunks = await listKnowledgeDocumentChunks(
            token,
            workspaceId,
            knowledgeBase.id,
            documentId,
          )
          return { ...document, chunks }
        }),
      )
      return loadedDocuments.filter(
        (document): document is UploadedDocument => document !== null,
      )
    },
    [knowledgeBase.id, token, workspaceId],
  )

  const applyPreviewDocuments = React.useCallback(
    (nextDocuments: UploadedDocument[]) => {
      setUploadedDocuments(nextDocuments)
      setSelectedDocumentId(
        (current) => current ?? nextDocuments[0]?.id ?? null,
      )
    },
    [],
  )

  const refreshPreview = React.useCallback(async () => {
    if (!uploadedDocuments.length) {
      return
    }

    setIsRefreshing(true)
    try {
      const nextDocuments = await loadPreviewDocuments(
        uploadedDocuments.map((document) => document.id),
      )
      applyPreviewDocuments(nextDocuments)
      if (!hasOpenPreviewTask(nextDocuments)) {
        if (
          pendingPreviewOptionsSignatureRef.current !== null &&
          nextDocuments.every(
            (document) =>
              document.status === "parsed" && document.chunks.length > 0,
          )
        ) {
          setPreviewOptionsSignature(pendingPreviewOptionsSignatureRef.current)
        }
        pendingPreviewOptionsSignatureRef.current = null
      }
    } catch (error) {
      reportError(error)
    } finally {
      setIsRefreshing(false)
    }
  }, [
    applyPreviewDocuments,
    loadPreviewDocuments,
    reportError,
    uploadedDocuments,
  ])

  React.useEffect(() => {
    if (step !== "segment" || !hasPendingParsing) {
      return
    }

    const interval = window.setInterval(() => {
      void refreshPreview()
    }, 2000)

    return () => window.clearInterval(interval)
  }, [hasPendingParsing, refreshPreview, step])

  function chooseFiles(nextFiles: File[]) {
    if (!nextFiles.length) {
      return
    }

    const supportedFiles = nextFiles.filter((file) =>
      SUPPORTED_FILE_TYPES.some((extension) =>
        file.name.toLowerCase().endsWith(extension),
      ),
    )
    const limitedFiles = supportedFiles.slice(
      0,
      MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
    )
    setFiles(limitedFiles)
    if (supportedFiles.length !== nextFiles.length) {
      onNotify("error", t("已忽略不支持的文件格式"))
    }
    if (supportedFiles.length > MAX_KNOWLEDGE_UPLOAD_DOCUMENTS) {
      onNotify(
        "error",
        t("每次最多上传 {value} 个文件", {
          value: MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
        }),
      )
    }
  }

  function removeFile(indexToRemove: number) {
    setFiles((current) => current.filter((_, index) => index !== indexToRemove))
  }

  function currentParseSettings(): KnowledgeUploadParseSettings {
    return segmentMode === "smart"
      ? {
          ...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
          cleaningRules: [...SMART_CLEANING_RULES],
        }
      : {
          segmentMode,
          chunkSize,
          chunkOverlap,
          splitSeparator,
          cleaningRules,
        }
  }

  const currentParseOptionsSignature = JSON.stringify(currentParseSettings())
  const hasStalePreview =
    previewOptionsSignature !== currentParseOptionsSignature
  const canStartIndex =
    uploadedDocuments.length > 0 &&
    !hasUnpreviewedDocuments &&
    !hasFailedParsing &&
    !hasStalePreview &&
    uploadedDocuments.every(
      (document) => document.status === "parsed" && document.chunks.length > 0,
    )

  React.useEffect(() => {
    if (step !== "segment") {
      return
    }
    if (!routeState?.documentIds.length) {
      onBackToFiles()
      return
    }

    let cancelled = false
    const routeSignature = JSON.stringify(routeState.parseSettings)
    pendingPreviewOptionsSignatureRef.current = routeSignature
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsRefreshing(true)

    void loadPreviewDocuments(routeState.documentIds)
      .then((nextDocuments) => {
        if (cancelled) {
          return
        }
        if (!nextDocuments.length) {
          onBackToFiles()
          return
        }

        applyPreviewDocuments(nextDocuments)
        if (!hasOpenPreviewTask(nextDocuments)) {
          if (
            nextDocuments.every(
              (document) =>
                document.status === "parsed" && document.chunks.length > 0,
            )
          ) {
            setPreviewOptionsSignature(routeSignature)
          }
          pendingPreviewOptionsSignatureRef.current = null
        }
      })
      .catch(reportError)
      .finally(() => {
        if (!cancelled) {
          setIsRefreshing(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [
    applyPreviewDocuments,
    loadPreviewDocuments,
    onBackToFiles,
    reportError,
    routeState,
    step,
  ])

  async function waitForPreviewDocuments(seedDocuments: UploadedDocument[]) {
    let latestDocuments = seedDocuments
    const deadline = Date.now() + PREVIEW_POLL_TIMEOUT_MS

    while (Date.now() < deadline) {
      latestDocuments = await loadPreviewDocuments(
        latestDocuments.map((document) => document.id),
      )
      applyPreviewDocuments(latestDocuments)

      if (!hasOpenPreviewTask(latestDocuments)) {
        return latestDocuments
      }

      await new Promise((resolve) =>
        window.setTimeout(resolve, PREVIEW_POLL_INTERVAL_MS),
      )
    }

    return latestDocuments
  }

  async function generatePreviewForDocuments(
    documents: UploadedDocument[],
    options: { announceSuccess: boolean } = { announceSuccess: true },
  ) {
    if (!documents.length || isSegmentInvalid) {
      return
    }

    setIsParsing(true)
    try {
      const parseSettings = currentParseSettings()
      const parseOptionsSignature = JSON.stringify(parseSettings)
      const results = await Promise.allSettled(
        documents.map((document) =>
          parseKnowledgeDocument(
            token,
            workspaceId,
            knowledgeBase.id,
            document.id,
            {
              chunk_size: parseSettings.chunkSize,
              chunk_overlap: parseSettings.chunkOverlap,
              split_separator: parseSettings.splitSeparator,
              cleaning_rules: parseSettings.cleaningRules,
              auto_index: false,
            },
          ),
        ),
      )
      const queuedDocuments = documents.map((document, index) =>
        results[index]?.status === "fulfilled"
          ? { ...document, chunks: [], status: "parse_queued" }
          : document,
      )
      const firstFailure = results.find(
        (result) => result.status === "rejected",
      )
      const allQueued = results.every(
        (result) => result.status === "fulfilled",
      )

      applyPreviewDocuments(queuedDocuments)
      pendingPreviewOptionsSignatureRef.current = allQueued
        ? parseOptionsSignature
        : null
      if (step === "files" || allQueued) {
        onRouteSegment({
          documentIds: documents.map((document) => document.id),
          parseSettings,
        })
      }

      if (firstFailure?.status === "rejected") {
        reportError(firstFailure.reason)
        return
      }

      const nextDocuments = await waitForPreviewDocuments(queuedDocuments)
      const failedDocuments = nextDocuments.filter((document) =>
        document.status.endsWith("_failed"),
      )
      if (hasOpenPreviewTask(nextDocuments)) {
        onNotify("error", t("分段任务仍在处理中，请稍后刷新预览"))
        return
      }

      if (failedDocuments.length) {
        onNotify(
          "error",
          failedDocuments.length === 1
            ? t("{value} 分段失败", {
                value: failedDocuments[0].filename,
              })
            : t("{value} 个文档分段失败", {
                value: failedDocuments.length,
              }),
        )
        return
      }

      const emptyPreviewDocuments = nextDocuments.filter(
        (document) => !document.chunks.length,
      )
      if (emptyPreviewDocuments.length) {
        onNotify(
          "error",
          emptyPreviewDocuments.length === 1
            ? t("{value} 未返回分段片段", {
                value: emptyPreviewDocuments[0].filename,
              })
            : t("{value} 个文档未返回分段片段", {
                value: emptyPreviewDocuments.length,
              }),
        )
        return
      }

      setPreviewOptionsSignature(parseOptionsSignature)
      pendingPreviewOptionsSignatureRef.current = null

      if (options.announceSuccess) {
        onNotify("success", t("已生成分段预览"))
      }
    } catch (error) {
      reportError(error)
    } finally {
      setIsParsing(false)
    }
  }

  async function handleUploadFiles() {
    if (!files.length) {
      return
    }

    setIsUploading(true)
    try {
      const results = await Promise.allSettled(
        files.map((file) =>
          uploadKnowledgeDocument(token, workspaceId, knowledgeBase.id, file, {
            autoParse: false,
          }),
        ),
      )
      const documents = results.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : [],
      )
      const failedCount = results.filter(
        (result) => result.status === "rejected",
      ).length
      const firstFailure = results.find(
        (result) => result.status === "rejected",
      )
      setFiles(
        files.filter((_, index) => results[index]?.status === "rejected"),
      )

      if (!documents.length) {
        if (firstFailure?.status === "rejected") {
          reportError(firstFailure.reason)
        }
        return
      }

      const uploaded = documents.map((document) => ({
        ...document,
        chunks: [],
      }))
      const nextDocuments = [...uploadedDocuments, ...uploaded]
      setUploadedDocuments(nextDocuments)
      setSelectedDocumentId((current) => current ?? documents[0]?.id ?? null)
      setPreviewOptionsSignature(null)
      onNotify(
        failedCount ? "error" : "success",
        failedCount
          ? t("已上传 {uploaded} 个文件，{failed} 个上传失败", {
              uploaded: documents.length,
              failed: failedCount,
            })
          : t("已上传 {value} 个文件", { value: documents.length }),
      )
      await generatePreviewForDocuments(nextDocuments, {
        announceSuccess: false,
      })
    } catch (error) {
      reportError(error)
    } finally {
      setIsUploading(false)
    }
  }

  async function handleGeneratePreview() {
    if (!uploadedDocuments.length || isSegmentInvalid) {
      return
    }

    await generatePreviewForDocuments(uploadedDocuments)
  }

  async function handleStartImport() {
    if (!canStartIndex) {
      return
    }

    setIsIndexing(true)
    try {
      const results = await Promise.allSettled(
        uploadedDocuments.map((document) =>
          indexKnowledgeDocument(
            token,
            workspaceId,
            knowledgeBase.id,
            document.id,
          ),
        ),
      )
      const succeededCount = results.filter(
        (result) => result.status === "fulfilled",
      ).length
      const failedCount = results.length - succeededCount
      const firstFailure = results.find(
        (result) => result.status === "rejected",
      )

      if (!succeededCount) {
        if (firstFailure?.status === "rejected") {
          reportError(firstFailure.reason)
        }
        return
      }

      onNotify(
        failedCount ? "error" : "success",
        failedCount
          ? t("已提交 {submitted} 个向量化任务，{failed} 个提交失败", {
              submitted: succeededCount,
              failed: failedCount,
            })
          : t("已提交 {value} 个向量化任务", { value: succeededCount }),
      )
      await onDone()
    } catch (error) {
      reportError(error)
    } finally {
      setIsIndexing(false)
    }
  }

  function toggleCleaningRule(rule: string, checked: boolean) {
    setCleaningRules((current) =>
      checked
        ? current.includes(rule)
          ? current
          : [...current, rule]
        : current.filter((item) => item !== rule),
    )
  }

  return (
    <div className="-mx-4 min-h-[calc(100svh-6.5rem)] border-y bg-muted/20 sm:-mx-6 lg:-mx-8">
      <header className="border-b bg-background">
        <div className="mx-auto flex w-full max-w-[90rem] items-center px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("返回知识库")}
              onClick={onCancel}
            >
              <ArrowLeftIcon />
            </Button>
            <div className="min-w-0">
              <p className="text-xs font-medium text-muted-foreground">
                {t("知识库导入")}
              </p>
              <h1 className="truncate text-xl font-semibold text-foreground">
                {knowledgeBase.name}
              </h1>
            </div>
          </div>
        </div>
      </header>

      {step === "files" ? (
        <>
          <div className="mx-auto w-full max-w-[90rem] px-4 py-5 sm:px-6 lg:px-8">
            <main className="min-w-0 space-y-5">
              <section className="overflow-hidden rounded-lg border bg-background shadow-sm">
                <div className="border-b px-5 py-4">
                  <SectionTitle
                    icon={UploadIcon}
                    title={t("选择导入材料")}
                    description={t(
                      "文件会先上传暂存，确认分段效果后再进入向量化。",
                    )}
                  />
                </div>

                <div
                  className={cn(
                    "m-5 flex min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors",
                    isDragActive
                      ? "border-primary bg-primary/5"
                      : "border-border bg-muted/20 hover:bg-muted/30",
                  )}
                  onDragOver={(event) => {
                    event.preventDefault()
                    setIsDragActive(true)
                  }}
                  onDragLeave={() => setIsDragActive(false)}
                  onDrop={(event) => {
                    event.preventDefault()
                    setIsDragActive(false)
                    chooseFiles(Array.from(event.dataTransfer.files))
                  }}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={SUPPORTED_FILE_TYPES.join(",")}
                    multiple
                    className="hidden"
                    onChange={(event) =>
                      chooseFiles(Array.from(event.target.files ?? []))
                    }
                  />
                  <input
                    ref={folderInputRef}
                    type="file"
                    accept={SUPPORTED_FILE_TYPES.join(",")}
                    multiple
                    className="hidden"
                    onChange={(event) =>
                      chooseFiles(Array.from(event.target.files ?? []))
                    }
                  />
                  <span className="flex size-14 items-center justify-center rounded-lg border bg-background shadow-sm">
                    <UploadIcon className="size-6 text-primary" />
                  </span>
                  <div className="mt-5 space-y-2">
                    <p className="text-lg font-semibold text-foreground">
                      {t("拖入文件或文件夹")}
                    </p>
                    <p className="mx-auto max-w-xl text-sm leading-6 text-muted-foreground">
                      {t(
                        "保留文档标题和段落结构，表格会在预览阶段转换为 Markdown。",
                      )}
                    </p>
                  </div>
                  <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
                    <Button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <FilesIcon data-icon="inline-start" />
                      {t("选择文件")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => folderInputRef.current?.click()}
                    >
                      <FolderOpenIcon data-icon="inline-start" />
                      {t("选择文件夹")}
                    </Button>
                  </div>
                </div>
              </section>

              <FileList files={files} onRemove={removeFile} />
            </main>
          </div>

          <div className="sticky bottom-0 z-10 border-t bg-background/95 px-4 py-3 shadow-sm sm:px-6 lg:px-8">
            <div className="mx-auto flex w-full max-w-[90rem] flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">
                {files.length
                  ? t("已选择 {count} 个文件，合计 {size}", {
                      count: files.length,
                      size: formatBytes(selectedFileBytes),
                    })
                  : t("等待选择文件")}
              </p>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={onCancel}>
                  {t("取消")}
                </Button>
                <Button
                  type="button"
                  disabled={!files.length || isUploading}
                  onClick={() => void handleUploadFiles()}
                >
                  {isUploading ? (
                    <LoaderCircleIcon
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <UploadIcon data-icon="inline-start" />
                  )}
                  {t("上传并继续")}
                </Button>
              </div>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="mx-auto grid w-full max-w-[90rem] gap-4 px-4 py-5 sm:px-6 lg:h-[calc(100svh-17rem)] lg:min-h-[34rem] lg:grid-cols-[18rem_minmax(0,1fr)] lg:px-8 xl:grid-cols-[19rem_minmax(0,1fr)]">
            <aside className="space-y-4 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
              <section className="rounded-lg border bg-background p-4 shadow-sm">
                <SectionTitle
                  icon={ScissorsIcon}
                  title={t("分段规则")}
                  description={t("先用智能规则生成预览，需要时再精调。")}
                />

                <div className="mt-4 space-y-3">
                  <SegmentModeOption
                    checked={segmentMode === "smart"}
                    title={t("智能分段")}
                    description={t(
                      "按常见文档结构自动设置长度、重叠和清洗规则。",
                    )}
                    onSelect={() => setSegmentMode("smart")}
                  />
                  <SegmentModeOption
                    checked={segmentMode === "advanced"}
                    title={t("高级分段")}
                    description={t(
                      "手动控制片段字符数、重叠字符和文本清洗规则。",
                    )}
                    onSelect={() => setSegmentMode("advanced")}
                  />
                </div>

                {segmentMode === "advanced" ? (
                  <FieldGroup className="mt-5">
                    <div className="grid grid-cols-2 gap-3">
                      <Field>
                        <FieldLabel htmlFor="knowledge-chunk-size">
                          {t("片段字符")}
                        </FieldLabel>
                        <Input
                          id="knowledge-chunk-size"
                          type="number"
                          min={100}
                          max={8000}
                          value={chunkSize}
                          onChange={(event) =>
                            setChunkSize(
                              Number(event.target.value) || SMART_CHUNK_SIZE,
                            )
                          }
                        />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="knowledge-chunk-overlap">
                          {t("重叠字符")}
                        </FieldLabel>
                        <Input
                          id="knowledge-chunk-overlap"
                          type="number"
                          min={0}
                          max={2000}
                          value={chunkOverlap}
                          onChange={(event) =>
                            setChunkOverlap(Number(event.target.value) || 0)
                          }
                        />
                      </Field>
                    </div>
                    <Field>
                      <FieldLabel htmlFor="knowledge-split-separator">
                        {t("切分字符")}
                      </FieldLabel>
                      <select
                        id="knowledge-split-separator"
                        className="h-9 rounded-md border bg-background px-3 text-sm"
                        value={splitSeparator}
                        onChange={(event) =>
                          setSplitSeparator(event.target.value)
                        }
                      >
                        {splitSeparatorOptions.map((separator) => (
                          <option key={separator.value} value={separator.value}>
                            {separator.label}
                          </option>
                        ))}
                      </select>
                    </Field>
                    {isSegmentInvalid ? (
                      <FieldDescription className="text-destructive">
                        {t("重叠字符必须小于片段字符")}
                      </FieldDescription>
                    ) : null}
                    <Field>
                      <FieldLabel>{t("清洗规则")}</FieldLabel>
                      <div className="space-y-2">
                        {cleaningRuleOptions.map((rule) => (
                          <label
                            key={rule.value}
                            className="flex min-h-9 items-center gap-2 text-sm"
                          >
                            <input
                              type="checkbox"
                              className="size-4"
                              checked={cleaningRules.includes(rule.value)}
                              onChange={(event) =>
                                toggleCleaningRule(
                                  rule.value,
                                  event.target.checked,
                                )
                              }
                            />
                            {rule.label}
                          </label>
                        ))}
                      </div>
                    </Field>
                  </FieldGroup>
                ) : null}

                <Button
                  type="button"
                  className="mt-5 w-full"
                  variant="outline"
                  disabled={
                    !uploadedDocuments.length ||
                    isPreviewRunning ||
                    isSegmentInvalid
                  }
                  onClick={() => void handleGeneratePreview()}
                >
                  {isPreviewRunning ? (
                    <LoaderCircleIcon
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <ScissorsIcon data-icon="inline-start" />
                  )}
                  {isPreviewRunning
                    ? t("正在生成预览")
                    : totalChunks
                      ? t("重新生成预览")
                      : t("生成分段预览")}
                </Button>
              </section>

              <section className="rounded-lg border bg-background p-4 shadow-sm">
                <SectionTitle
                  icon={DatabaseIcon}
                  title={t("入库状态")}
                  description={t("预览无误后提交向量化任务。")}
                />
                <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
                  <MetricItem
                    label={t("文档")}
                    value={`${uploadedDocuments.length}`}
                  />
                  <MetricItem label={t("片段")} value={`${totalChunks}`} />
                  <MetricItem
                    label={t("规则")}
                    value={segmentMode === "smart" ? t("智能") : t("高级")}
                  />
                  <MetricItem
                    label={t("状态")}
                    value={canStartIndex ? t("可入库") : t("待预览")}
                  />
                </dl>
              </section>
            </aside>

            <main className="min-w-0 overflow-hidden rounded-lg border bg-background shadow-sm lg:flex lg:min-h-0 lg:flex-col">
              <div className="flex shrink-0 flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <SectionTitle
                  icon={FileTextIcon}
                  title={t("分段预览")}
                  description={t("按文件查看解析后的片段内容。")}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isRefreshing}
                  onClick={() => void refreshPreview()}
                >
                  {isRefreshing ? (
                    <LoaderCircleIcon
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <RotateCcwIcon data-icon="inline-start" />
                  )}
                  {t("刷新")}
                </Button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {uploadedDocuments.map((document) => (
                    <button
                      key={document.id}
                      type="button"
                      className={cn(
                        "inline-flex h-9 max-w-64 shrink-0 items-center gap-2 rounded-md border px-3 text-sm font-medium transition-colors",
                        selectedDocument?.id === document.id
                          ? "border-primary bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                      )}
                      onClick={() => setSelectedDocumentId(document.id)}
                    >
                      <FileTextIcon className="size-4 shrink-0" />
                      <span className="truncate">{document.filename}</span>
                    </button>
                  ))}
                </div>

                <PreviewPane document={selectedDocument} />
              </div>
            </main>
          </div>

          <div className="sticky bottom-0 z-10 border-t bg-background/95 px-4 py-3 shadow-sm sm:px-6 lg:px-8">
            <div className="mx-auto flex w-full max-w-[90rem] flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">
                {canStartIndex
                  ? t("{documents} 个文档、{chunks} 个片段可入库", {
                      documents: uploadedDocuments.length,
                      chunks: totalChunks,
                    })
                  : hasStalePreview && totalChunks
                    ? t("分段规则已修改，请重新生成预览后再入库")
                    : t("生成预览并确认片段后才能入库")}
              </p>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={onCancel}>
                  {t("取消")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={onBackToFiles}
                >
                  {t("上一步")}
                </Button>
                <Button
                  type="button"
                  disabled={!canStartIndex || isIndexing}
                  onClick={() => void handleStartImport()}
                >
                  {isIndexing ? (
                    <LoaderCircleIcon
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <CheckCircle2Icon data-icon="inline-start" />
                  )}
                  {t("开始入库")}
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function SectionTitle({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon
  title: string
  description: string
}) {
  return (
    <div className="flex min-w-0 items-start gap-3">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/40">
        <Icon className="size-4 text-primary" />
      </span>
      <div className="min-w-0">
        <h2 className="truncate text-base font-semibold text-foreground">
          {title}
        </h2>
        <p className="mt-1 text-sm leading-5 text-muted-foreground">
          {description}
        </p>
      </div>
    </div>
  )
}

function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-t pt-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold text-foreground">
        {value}
      </dd>
    </div>
  )
}

function SegmentModeOption({
  checked,
  title,
  description,
  onSelect,
}: {
  checked: boolean
  title: string
  description: string
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border px-3 py-3 text-left transition-colors",
        checked
          ? "border-primary bg-primary/5"
          : "border-border bg-background hover:bg-muted/40",
      )}
      onClick={onSelect}
    >
      <span
        className={cn(
          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border",
          checked ? "border-primary bg-primary" : "border-border bg-muted/30",
        )}
      >
        {checked ? (
          <span className="size-1.5 rounded-full bg-primary-foreground" />
        ) : null}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-foreground">
          {title}
        </span>
        <span className="mt-1 block text-sm leading-5 text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  )
}

function FileList({
  files,
  onRemove,
}: {
  files: File[]
  onRemove: (index: number) => void
}) {
  const { t } = useLanguage()
  if (!files.length) {
    return null
  }

  return (
    <section className="overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <SectionTitle
          icon={FilesIcon}
          title={t("待上传队列")}
          description={t("确认这些文件后继续进入分段预览。")}
        />
        <Badge variant="outline">
          {t("{value} 个", { value: files.length })}
        </Badge>
      </div>
      <div className="divide-y">
        {files.map((file, index) => (
          <div
            key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
            className="grid min-h-12 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 px-4 py-2 text-sm"
          >
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
                <FileTextIcon className="size-4 text-muted-foreground" />
              </span>
              <span className="min-w-0 truncate font-medium text-foreground">
                {file.name}
              </span>
            </div>
            <Badge variant="outline">{formatBytes(file.size)}</Badge>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("移除 {value}", { value: file.name })}
              onClick={() => onRemove(index)}
            >
              <XIcon />
            </Button>
          </div>
        ))}
      </div>
    </section>
  )
}

function PreviewPane({ document }: { document: UploadedDocument | null }) {
  const { t } = useLanguage()
  if (!document) {
    return (
      <div className="mt-4 flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed px-4 text-center text-sm text-muted-foreground">
        <FolderOpenIcon className="mb-2 size-5" />
        {t("暂无文件")}
      </div>
    )
  }

  const isFailed = document.status.endsWith("_failed")
  const isParsing = PARSING_STATUSES.has(document.status)
  if (isFailed || !document.chunks.length) {
    return (
      <div
        className={cn(
          "mt-4 flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed px-4 text-center text-sm text-muted-foreground",
          isFailed && "border-destructive/40 bg-destructive/5 text-destructive",
        )}
      >
        {isFailed ? (
          <AlertCircleIcon className="mb-2 size-5" />
        ) : isParsing ? (
          <LoaderCircleIcon className="mb-2 size-5 animate-spin" />
        ) : (
          <ScissorsIcon className="mb-2 size-5" />
        )}
        {document.last_error ??
          (isParsing ? t("正在生成分段预览") : t("生成分段预览后查看片段内容"))}
      </div>
    )
  }

  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/20 px-4 py-3">
        <h2 className="truncate text-base font-semibold text-foreground">
          {document.filename}
        </h2>
        <Badge
          variant={
            document.status.endsWith("_failed") ? "destructive" : "outline"
          }
        >
          {documentStatusLabel(document.status, t)}
        </Badge>
      </div>
      <ChunkPreviewList chunks={document.chunks} />
    </div>
  )
}

function documentStatusLabel(status: string, t: TFunction) {
  const labels: Record<string, TranslationKey> = {
    uploaded: "待分段",
    parse_queued: "分段排队中",
    parsing: "分段中",
    parsed: "待向量化",
    index_queued: "向量化排队中",
    indexing: "向量化中",
    indexed: "已向量化",
    parse_failed: "分段失败",
    index_failed: "向量化失败",
  }

  const labelKey = labels[status]
  return labelKey ? t(labelKey) : status
}

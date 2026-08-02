import * as React from "react"
import {
  AlertCircleIcon,
  ArrowLeftIcon,
  FileTextIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SlidersHorizontalIcon,
  Trash2Icon,
} from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  deleteKnowledgeDocument,
  indexKnowledgeDocument,
  listKnowledgeBases,
  listKnowledgeDocumentChunks,
  listKnowledgeDocuments,
  listKnowledgeTasks,
  parseKnowledgeDocument,
} from "@/features/knowledge/api"
import { ChunkPreviewList } from "@/features/knowledge/chunk-preview-list"
import {
  documentStatusDotClassName,
  documentStatusLabel,
  formatBytes,
  taskStatusDotClassName,
  taskStatusLabel,
  taskTypeLabel,
} from "@/features/knowledge/status-labels"
import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeDocumentChunk,
  KnowledgeTask,
} from "@/features/knowledge/types"
import { formatDateTime } from "@/app/display"
import { getErrorMessage } from "@/app/errors"
import type { AppNotification } from "@/app/notifications"
import { cn } from "@/lib/utils"
import { languageLocales } from "@/lib/i18n"

const SMART_CHUNK_SIZE = 1200
const SMART_CHUNK_OVERLAP = 150
const SMART_CLEANING_RULES = ["trim_lines", "remove_empty_lines"]
const SMART_SPLIT_SEPARATOR = "\n\n"

const CLEANING_RULE_OPTIONS: Array<{
  value: string
  labelKey: "去除行首尾空白" | "删除空行" | "合并连续空白"
}> = [
  { value: "trim_lines", labelKey: "去除行首尾空白" },
  { value: "remove_empty_lines", labelKey: "删除空行" },
  { value: "collapse_spaces", labelKey: "合并连续空白" },
]

const SPLIT_SEPARATOR_OPTIONS: Array<{
  value: string
  labelKey: "换行" | "空行（段落）" | "中文句号（。）" | "英文句号（.）"
}> = [
  { value: "\n", labelKey: "换行" },
  { value: "\n\n", labelKey: "空行（段落）" },
  { value: "。", labelKey: "中文句号（。）" },
  { value: ".", labelKey: "英文句号（.）" },
]

const PROCESSING_DOCUMENT_STATUSES: Record<string, true> = {
  parse_queued: true,
  parsing: true,
  index_queued: true,
  indexing: true,
}

const PROCESSING_TASK_STATUSES: Record<string, true> = {
  queued: true,
  running: true,
}

export function DocumentDetailPage({
  token,
  selectedWorkspaceId,
  knowledgeBaseId,
  documentId,
  onBack,
  onNotify,
}: {
  token: string
  selectedWorkspaceId: string | null
  knowledgeBaseId: string
  documentId: string
  onBack: () => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const [knowledgeBase, setKnowledgeBase] = React.useState<KnowledgeBase | null>(
    null
  )
  const [document, setDocument] = React.useState<KnowledgeDocument | null>(null)
  const [chunks, setChunks] = React.useState<KnowledgeDocumentChunk[]>([])
  const [tasks, setTasks] = React.useState<KnowledgeTask[]>([])
  const [isLoading, setIsLoading] = React.useState(true)
  const [isSubmittingTask, setIsSubmittingTask] = React.useState(false)
  const [isSegmentDialogOpen, setIsSegmentDialogOpen] = React.useState(false)
  const [segmentMode, setSegmentMode] = React.useState<"smart" | "advanced">(
    "smart"
  )
  const [chunkSize, setChunkSize] = React.useState(SMART_CHUNK_SIZE)
  const [chunkOverlap, setChunkOverlap] = React.useState(SMART_CHUNK_OVERLAP)
  const [splitSeparator, setSplitSeparator] = React.useState(
    SMART_SPLIT_SEPARATOR
  )
  const [cleaningRules, setCleaningRules] = React.useState<string[]>(
    SMART_CLEANING_RULES
  )

  const load = React.useCallback(async () => {
    if (!selectedWorkspaceId) {
      return
    }

    setIsLoading(true)
    try {
      const [bases, documents, documentChunks, documentTasks] =
        await Promise.all([
          listKnowledgeBases(token, selectedWorkspaceId),
          listKnowledgeDocuments(token, selectedWorkspaceId, knowledgeBaseId),
          listKnowledgeDocumentChunks(
            token,
            selectedWorkspaceId,
            knowledgeBaseId,
            documentId
          ),
          listKnowledgeTasks(
            token,
            selectedWorkspaceId,
            knowledgeBaseId,
            documentId
          ),
        ])
      setKnowledgeBase(
        bases.find((base) => base.id === knowledgeBaseId) ?? null
      )
      setDocument(
        documents.find((item) => item.id === documentId) ?? null
      )
      setChunks(documentChunks)
      setTasks(documentTasks)
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsLoading(false)
    }
  }, [
    documentId,
    knowledgeBaseId,
    onNotify,
    selectedWorkspaceId,
    t,
    token,
  ])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  const hasProcessingTasks = tasks.some((task) =>
    PROCESSING_TASK_STATUSES[task.status]
  )
  const isDocumentProcessing =
    PROCESSING_DOCUMENT_STATUSES[document?.status ?? ""] ||
    hasProcessingTasks

  React.useEffect(() => {
    if (!isDocumentProcessing) {
      return
    }

    const timer = window.setInterval(() => {
      void load()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [isDocumentProcessing, load])

  async function handleParse() {
    if (!selectedWorkspaceId || !document) {
      return
    }

    setIsSubmittingTask(true)
    try {
      await parseKnowledgeDocument(
        token,
        selectedWorkspaceId,
        knowledgeBaseId,
        document.id,
        segmentMode === "smart"
          ? {
              chunk_size: SMART_CHUNK_SIZE,
              chunk_overlap: SMART_CHUNK_OVERLAP,
              cleaning_rules: SMART_CLEANING_RULES,
              split_separator: SMART_SPLIT_SEPARATOR,
              auto_index: false,
            }
          : {
              chunk_size: chunkSize,
              chunk_overlap: chunkOverlap,
              cleaning_rules: cleaningRules,
              split_separator: splitSeparator,
              auto_index: false,
            }
      )
      onNotify("success", t("已提交解析任务"))
      setIsSegmentDialogOpen(false)
      await load()
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsSubmittingTask(false)
    }
  }

  async function handleIndex() {
    if (!selectedWorkspaceId || !document) {
      return
    }

    setIsSubmittingTask(true)
    try {
      await indexKnowledgeDocument(
        token,
        selectedWorkspaceId,
        knowledgeBaseId,
        document.id
      )
      onNotify("success", t("已提交向量化任务"))
      await load()
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsSubmittingTask(false)
    }
  }

  async function handleDelete() {
    if (!selectedWorkspaceId || !document) {
      return
    }

    if (
      !window.confirm(
        t("永久删除 {name}？此操作不可恢复。", { name: document.filename })
      )
    ) {
      return
    }

    try {
      await deleteKnowledgeDocument(
        token,
        selectedWorkspaceId,
        knowledgeBaseId,
        document.id
      )
      onNotify("success", t("文档已删除"))
      onBack()
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    }
  }

  const canEdit = knowledgeBase?.permission === "edit"

  if (isLoading) {
    return (
      <main className="flex min-h-[calc(100svh-6.5rem)] items-center justify-center bg-background">
        <LoaderCircleIcon className="animate-spin text-muted-foreground" />
      </main>
    )
  }

  if (!knowledgeBase || !document) {
    return (
      <main className="flex min-h-[calc(100svh-6.5rem)] items-center justify-center bg-background p-6">
        <div className="flex w-full max-w-sm flex-col items-center gap-4 rounded-lg border bg-background p-6 text-center">
          <span className="flex size-10 items-center justify-center rounded-lg bg-muted">
            <FileTextIcon className="size-5 text-muted-foreground" />
          </span>
          <p className="text-sm text-muted-foreground">
            {t("文档不存在或已被删除")}
          </p>
          <Button type="button" variant="outline" onClick={onBack}>
            <ArrowLeftIcon data-icon="inline-start" />
            {t("返回知识库")}
          </Button>
        </div>
      </main>
    )
  }

  const isFailed = document.status.endsWith("_failed")
  const isPending =
    document.status.endsWith("_queued") ||
    document.status === "parsing" ||
    document.status === "indexing"

  return (
    <main className="min-h-[calc(100svh-6.5rem)] bg-background">
      <div className="border-b px-4 py-4 lg:px-8">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-sm">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("返回知识库")}
              onClick={onBack}
            >
              <ArrowLeftIcon />
            </Button>
            <button
              type="button"
              className="max-w-48 truncate text-muted-foreground outline-none hover:text-foreground"
              title={knowledgeBase.name}
              onClick={onBack}
            >
              {knowledgeBase.name}
            </button>
            <span className="text-muted-foreground" aria-hidden="true">
              /
            </span>
            <span className="truncate font-medium">{document.filename}</span>
          </div>

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl font-semibold">
                  {document.filename}
                </h1>
                <span
                  className={cn(
                    "size-2.5 shrink-0 rounded-full",
                    documentStatusDotClassName(document.status)
                  )}
                />
                <Badge variant="outline">
                  {documentStatusLabel(document.status, t)}
                </Badge>
                {!document.is_active ? (
                  <Badge variant="outline">{t("已停用")}</Badge>
                ) : null}
              </div>
              <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <div className="flex items-center gap-1">
                  <dt>{t("大小")}</dt>
                  <dd>{formatBytes(document.size_bytes)}</dd>
                </div>
                <div className="flex items-center gap-1">
                  <dt>{t("分段")}</dt>
                  <dd>{chunks.length}</dd>
                </div>
                <div className="flex items-center gap-1">
                  <dt>{t("创建时间")}</dt>
                  <dd>{formatDateTime(document.created_at, locale)}</dd>
                </div>
                <div className="flex items-center gap-1">
                  <dt>{t("更新时间")}</dt>
                  <dd>{formatDateTime(document.updated_at, locale)}</dd>
                </div>
              </dl>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!canEdit || isSubmittingTask}
                onClick={() => setIsSegmentDialogOpen(true)}
              >
                {isSubmittingTask ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    data-icon="inline-start"
                  />
                ) : (
                  <RotateCcwIcon data-icon="inline-start" />
                )}
                {t("重新分段")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!canEdit || isSubmittingTask}
                onClick={() => void handleIndex()}
              >
                <SlidersHorizontalIcon data-icon="inline-start" />
                {t("向量化")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={isLoading}
                onClick={() => void load()}
              >
                <RefreshCwIcon data-icon="inline-start" />
                {t("刷新")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!canEdit || isSubmittingTask}
                onClick={() => void handleDelete()}
              >
                <Trash2Icon data-icon="inline-start" />
                {t("删除")}
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div className="px-4 py-4 lg:px-8">
        {isFailed ? (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-8 text-center text-sm text-destructive">
            <AlertCircleIcon className="size-5" />
            <p>{document.last_error ?? t("解析失败")}</p>
            <Button
              type="button"
              variant="outline"
              disabled={!canEdit || isSubmittingTask}
              onClick={() => setIsSegmentDialogOpen(true)}
            >
              <RotateCcwIcon data-icon="inline-start" />
              {t("重新分段")}
            </Button>
          </div>
        ) : chunks.length ? (
          <ChunkPreviewList chunks={chunks} />
        ) : (
          <div className="flex min-h-72 flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 text-center text-sm text-muted-foreground">
            {isPending ? (
              <LoaderCircleIcon className="size-5 animate-spin" />
            ) : (
              <FileTextIcon className="size-5" />
            )}
            <p>
              {isPending
                ? t("正在处理中，请稍后刷新")
                : t("暂无分段，点击重新分段生成预览")}
            </p>
          </div>
        )}

        {tasks.length ? (
          <section className="mt-6 rounded-lg border bg-background">
            <div className="border-b px-4 py-3">
              <h2 className="text-sm font-semibold">{t("文档任务")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("解析、向量化和失败重试状态")}
              </p>
            </div>
            <div className="divide-y">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  className="flex items-center justify-between gap-3 px-4 py-3 text-sm"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="font-medium">
                      {taskTypeLabel(task.task_type, t)}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      {formatDateTime(task.created_at, locale)}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
                    <span>
                      {task.processed_items}/{task.total_items}
                    </span>
                    <span className="flex items-center gap-2">
                      <span
                        className={cn(
                          "size-2.5 rounded-full",
                          taskStatusDotClassName(task.status)
                        )}
                      />
                      {taskStatusLabel(task.status, t)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>

      <Dialog
        open={isSegmentDialogOpen}
        onOpenChange={setIsSegmentDialogOpen}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("重新分段")}</DialogTitle>
            <DialogDescription>
              {t("先用智能规则生成预览，需要时再精调。")}
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void handleParse()
            }}
          >
            <FieldGroup>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    segmentMode === "smart"
                      ? "border-primary bg-primary/5"
                      : "hover:bg-muted"
                  )}
                  onClick={() => setSegmentMode("smart")}
                >
                  <span className="block text-sm font-medium">
                    {t("智能分段")}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    {t("按常见文档结构自动设置长度、重叠和清洗规则。")}
                  </span>
                </button>
                <button
                  type="button"
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    segmentMode === "advanced"
                      ? "border-primary bg-primary/5"
                      : "hover:bg-muted"
                  )}
                  onClick={() => setSegmentMode("advanced")}
                >
                  <span className="block text-sm font-medium">
                    {t("高级分段")}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    {t("手动控制片段字符数、重叠字符和文本清洗规则。")}
                  </span>
                </button>
              </div>

              {segmentMode === "advanced" ? (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field>
                      <FieldLabel htmlFor="doc-segment-size">
                        {t("片段字符")}
                      </FieldLabel>
                      <Input
                        id="doc-segment-size"
                        type="number"
                        min={100}
                        max={8000}
                        value={chunkSize}
                        onChange={(event) =>
                          setChunkSize(Number(event.target.value))
                        }
                        required
                      />
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="doc-segment-overlap">
                        {t("重叠字符")}
                      </FieldLabel>
                      <Input
                        id="doc-segment-overlap"
                        type="number"
                        min={0}
                        max={2000}
                        value={chunkOverlap}
                        onChange={(event) =>
                          setChunkOverlap(Number(event.target.value))
                        }
                        required
                      />
                    </Field>
                  </div>
                  {chunkOverlap >= chunkSize ? (
                    <p className="text-sm text-destructive">
                      {t("重叠字符必须小于片段字符")}
                    </p>
                  ) : null}
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field>
                      <FieldLabel>{t("切分字符")}</FieldLabel>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-9 w-full justify-between font-normal"
                          >
                            <span className="truncate">
                              {t(
                                SPLIT_SEPARATOR_OPTIONS.find(
                                  (option) =>
                                    option.value === splitSeparator
                                )?.labelKey ?? "空行（段落）"
                              )}
                            </span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          {SPLIT_SEPARATOR_OPTIONS.map((option) => (
                            <DropdownMenuItem
                              key={option.value}
                              onSelect={() =>
                                setSplitSeparator(option.value)
                              }
                            >
                              {t(option.labelKey)}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </Field>
                    <Field>
                      <FieldLabel>{t("清洗规则")}</FieldLabel>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-9 w-full justify-between font-normal"
                          >
                            <span className="truncate">
                              {cleaningRules.length
                                ? cleaningRules
                                    .map(
                                      (rule) =>
                                        t(
                                          CLEANING_RULE_OPTIONS.find(
                                            (option) =>
                                              option.value === rule
                                          )?.labelKey ?? "去除行首尾空白"
                                        )
                                    )
                                    .join(t("列表分隔符"))
                                : t("不使用")}
                            </span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          {CLEANING_RULE_OPTIONS.map((option) => (
                            <DropdownMenuItem
                              key={option.value}
                              onSelect={() =>
                                setCleaningRules((current) =>
                                  current.includes(option.value)
                                    ? current.filter(
                                        (rule) => rule !== option.value
                                      )
                                    : [...current, option.value]
                                )
                              }
                            >
                              {t(option.labelKey)}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </Field>
                  </div>
                </>
              ) : null}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsSegmentDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button
                type="submit"
                disabled={
                  isSubmittingTask ||
                  (segmentMode === "advanced" && chunkOverlap >= chunkSize)
                }
              >
                {isSubmittingTask ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    data-icon="inline-start"
                  />
                ) : null}
                {t("开始入库")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </main>
  )
}

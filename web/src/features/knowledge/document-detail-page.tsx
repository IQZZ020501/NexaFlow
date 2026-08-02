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
        {
          chunk_size: 1200,
          chunk_overlap: 150,
          cleaning_rules: [],
          auto_index: false,
        }
      )
      onNotify("success", t("已提交解析任务"))
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
                onClick={() => void handleParse()}
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
              onClick={() => void handleParse()}
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
    </main>
  )
}

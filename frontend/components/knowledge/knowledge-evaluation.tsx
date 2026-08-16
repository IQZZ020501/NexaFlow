"use client"

import * as React from "react"
import {
  CircleAlertIcon,
  LoaderCircleIcon,
  PlayIcon,
  PlusIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react"
import { Popover as PopoverPrimitive } from "radix-ui"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLanguage } from "@/contexts/language-provider"
import {
  createKnowledgeEvaluationCase,
  createKnowledgeEvaluationRun,
  deleteKnowledgeEvaluationCase,
  deleteKnowledgeEvaluationRun,
  getKnowledgeEvaluationRun,
  getKnowledgeEvaluationSummary,
  listKnowledgeEvaluationCases,
  listKnowledgeEvaluationRuns,
} from "@/lib/api/knowledge"
import type {
  KnowledgeDocument,
  KnowledgeEvaluationCase,
  KnowledgeEvaluationSummary,
  KnowledgeQueryInspectResult,
  KnowledgeSearchMode,
  KnowledgeTask,
} from "@/lib/api/knowledge"
import { languageLocales, type TranslationKey } from "@/i18n"
import { formatDateTime } from "@/lib/display"
import { taskStatusLabel } from "@/components/knowledge/status-labels"
import { KnowledgeHitTest } from "@/components/knowledge/knowledge-hit-test"

type KnowledgeEvaluationProps = {
  token: string
  workspaceId: string
  knowledgeBaseId: string
  documents: KnowledgeDocument[]
  canEdit: boolean
  reportError: (error: unknown) => void
}

function metric(value: number) {
  return Number(value.toFixed(3)).toString()
}

export function KnowledgeEvaluation({
  token,
  workspaceId,
  knowledgeBaseId,
  documents,
  canEdit,
  reportError,
}: KnowledgeEvaluationProps) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const activeDocuments = React.useMemo(
    () => documents.filter((document) => document.is_active),
    [documents],
  )
  const documentNames = React.useMemo(
    () => new Map(documents.map((document) => [document.id, document.filename])),
    [documents],
  )
  const [cases, setCases] = React.useState<KnowledgeEvaluationCase[]>([])
  const [runs, setRuns] = React.useState<KnowledgeTask[]>([])
  const [selectedCaseIds, setSelectedCaseIds] = React.useState<string[]>([])
  const [testedQuery, setTestedQuery] = React.useState("")
  const [limit, setLimit] = React.useState(5)
  const [searchMode, setSearchMode] = React.useState<KnowledgeSearchMode>("blend")
  const [similarity, setSimilarity] = React.useState(0.6)
  const [includeReferences, setIncludeReferences] = React.useState(true)
  const [expectedDocumentIds, setExpectedDocumentIds] = React.useState<string[]>([])
  const [activeTask, setActiveTask] = React.useState<KnowledgeTask | null>(null)
  const [summary, setSummary] = React.useState<KnowledgeEvaluationSummary | null>(null)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isDeleting, setIsDeleting] = React.useState(false)
  const [deleteTarget, setDeleteTarget] = React.useState<
    | { type: "case"; item: KnowledgeEvaluationCase }
    | { type: "run"; item: KnowledgeTask }
    | null
  >(null)

  const handleTested = React.useCallback((payload: {
    query: string
    result: KnowledgeQueryInspectResult
    limit: number
    searchMode: KnowledgeSearchMode
    similarity: number
    includeReferences: boolean
  }) => {
    const activeDocumentIds = new Set(activeDocuments.map((document) => document.id))
    setTestedQuery(payload.query)
    setExpectedDocumentIds(
      [...new Set(payload.result.hits.map((hit) => hit.document_id))].filter((id) =>
        activeDocumentIds.has(id),
      ),
    )
    setLimit(payload.limit)
    setSearchMode(payload.searchMode)
    setSimilarity(payload.similarity)
    setIncludeReferences(payload.includeReferences)
  }, [activeDocuments])

  const load = React.useCallback(async () => {
    try {
      const [nextCases, nextRuns] = await Promise.all([
        listKnowledgeEvaluationCases(token, workspaceId, knowledgeBaseId),
        listKnowledgeEvaluationRuns(token, workspaceId, knowledgeBaseId),
      ])
      setCases(nextCases)
      setRuns(nextRuns)
      setSelectedCaseIds((current) =>
        current.filter((id) => nextCases.some((item) => item.id === id)),
      )
      if (nextRuns[0]) {
        setActiveTask(nextRuns[0])
        setSummary(
          await getKnowledgeEvaluationSummary(
            token,
            workspaceId,
            knowledgeBaseId,
            nextRuns[0].id,
          ),
        )
      } else {
        setActiveTask(null)
        setSummary(null)
      }
    } catch (error) {
      reportError(error)
    }
  }, [knowledgeBaseId, reportError, token, workspaceId])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  React.useEffect(() => {
    if (!activeTask || !["queued", "running"].includes(activeTask.status)) return
    let cancelled = false
    let timeout: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const task = await getKnowledgeEvaluationRun(
          token,
          workspaceId,
          knowledgeBaseId,
          activeTask.id,
        )
        if (cancelled) return
        setActiveTask(task)
        setRuns((current) => [task, ...current.filter((item) => item.id !== task.id)])
        if (["succeeded", "failed"].includes(task.status)) {
          setSummary(
            await getKnowledgeEvaluationSummary(
              token,
              workspaceId,
              knowledgeBaseId,
              task.id,
            ),
          )
        } else {
          timeout = setTimeout(() => void poll(), 1000)
        }
      } catch (error) {
        if (!cancelled) reportError(error)
      }
    }
    timeout = setTimeout(() => void poll(), 1000)
    return () => {
      cancelled = true
      clearTimeout(timeout)
    }
  }, [activeTask, knowledgeBaseId, reportError, token, workspaceId])

  async function addCase(payload: {
    question: string
    expected_document_ids: string[]
  }) {
    const created = await createKnowledgeEvaluationCase(
      token,
      workspaceId,
      knowledgeBaseId,
      payload,
    )
    setCases((current) => [created, ...current])
    setSelectedCaseIds((current) => [...new Set([...current, created.id])])
    return created
  }

  async function handleSaveTest() {
    if (!testedQuery.trim() || !expectedDocumentIds.length) return
    setIsSaving(true)
    try {
      await addCase({
        question: testedQuery.trim(),
        expected_document_ids: expectedDocumentIds,
      })
      setExpectedDocumentIds([])
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteCase(item: KnowledgeEvaluationCase) {
    await deleteKnowledgeEvaluationCase(token, workspaceId, knowledgeBaseId, item.id)
    setCases((current) => current.filter((entry) => entry.id !== item.id))
    setSelectedCaseIds((current) => current.filter((id) => id !== item.id))
  }

  async function handleDeleteRun(item: KnowledgeTask) {
    await deleteKnowledgeEvaluationRun(
      token,
      workspaceId,
      knowledgeBaseId,
      item.id,
    )
    setRuns((current) => current.filter((entry) => entry.id !== item.id))
    if (activeTask?.id === item.id) {
      setActiveTask(null)
      setSummary(null)
    }
  }

  async function confirmDelete() {
    if (!deleteTarget || isDeleting) return
    const target = deleteTarget
    setIsDeleting(true)
    try {
      if (target.type === "case") {
        await handleDeleteCase(target.item)
      } else {
        await handleDeleteRun(target.item)
      }
      setDeleteTarget(null)
    } catch (error) {
      reportError(error)
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleRun() {
    if (!selectedCaseIds.length) return
    setIsSaving(true)
    try {
      const task = await createKnowledgeEvaluationRun(
        token,
        workspaceId,
        knowledgeBaseId,
        {
          case_ids: selectedCaseIds,
          limit,
          search_mode: searchMode,
          similarity,
          include_references: includeReferences,
        },
      )
      setActiveTask(task)
      setSummary(null)
      setRuns((current) => [task, ...current])
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function openRun(task: KnowledgeTask) {
    setActiveTask(task)
    try {
      setSummary(
        await getKnowledgeEvaluationSummary(
          token,
          workspaceId,
          knowledgeBaseId,
          task.id,
        ),
      )
    } catch (error) {
      reportError(error)
    }
  }

  return (
    <div className="p-4 lg:p-5">
      <div className="max-w-6xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">{t("检索评测")}</h1>
          </div>
          <Button type="button" variant="outline" onClick={() => void load()}>
            <RotateCcwIcon data-icon="inline-start" />
            {t("刷新")}
          </Button>
        </div>

        <KnowledgeHitTest
          token={token}
          workspaceId={workspaceId}
          knowledgeBaseId={knowledgeBaseId}
          reportError={reportError}
          onTested={handleTested}
        />

        {canEdit && testedQuery ? (
          <section className="mt-4 rounded-lg border p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold">{t("保存当前检索")}</h3>
                <p className="mt-1 break-words text-sm text-muted-foreground">
                  {testedQuery}
                </p>
              </div>
              <Button
                type="button"
                disabled={isSaving || !expectedDocumentIds.length}
                onClick={() => void handleSaveTest()}
              >
                <PlusIcon data-icon="inline-start" />
                {t("添加用例")}
              </Button>
            </div>
            <fieldset className="mt-3">
              <legend className="text-sm font-medium">{t("期望文档")}</legend>
              <div className="mt-2 max-h-36 space-y-2 overflow-y-auto rounded-md border p-3">
                {activeDocuments.length ? activeDocuments.map((document) => (
                  <label key={document.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={expectedDocumentIds.includes(document.id)}
                      onChange={(event) => setExpectedDocumentIds((current) =>
                        event.target.checked
                          ? [...current, document.id]
                          : current.filter((id) => id !== document.id),
                      )}
                    />
                    <span className="break-all">{document.filename}</span>
                  </label>
                )) : <p className="text-sm text-muted-foreground">{t("暂无已启用文档")}</p>}
              </div>
            </fieldset>
          </section>
        ) : null}

        <section className="mt-4 rounded-lg border">
          <div className="border-b p-4">
            <h2 className="text-sm font-semibold">{t("评测用例")}</h2>
          </div>
          {cases.length ? (
            <div className="divide-y">
              {cases.map((item) => (
                <article key={item.id} className="flex items-start gap-3 p-4">
                  <input
                    type="checkbox"
                    className="mt-1 size-4"
                    aria-label={t("选择用例：{value}", { value: item.question })}
                    checked={selectedCaseIds.includes(item.id)}
                    onChange={(event) => setSelectedCaseIds((current) =>
                      event.target.checked
                        ? [...current, item.id]
                        : current.filter((id) => id !== item.id),
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-sm font-medium">{item.question}</p>
                    <p className="mt-1 break-all text-xs text-muted-foreground">
                      {t("期望文档：{value}", {
                        value: item.expected_document_ids
                          .map((id) => documentNames.get(id) ?? id)
                          .join(t("列表分隔符")),
                      })}
                    </p>
                  </div>
                  {canEdit ? (
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t("删除用例：{value}", { value: item.question })}
                      onClick={() => setDeleteTarget({ type: "case", item })}
                    >
                      <Trash2Icon />
                    </Button>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <div className="flex min-h-32 items-center justify-center text-sm text-muted-foreground">
              {t("暂无评测用例")}
            </div>
          )}
        </section>

        {canEdit ? (
          <section className="mt-4 rounded-lg border p-4">
            <h2 className="text-sm font-semibold">{t("运行评测")}</h2>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <Button
                type="button"
                disabled={isSaving || !selectedCaseIds.length || Boolean(activeTask && ["queued", "running"].includes(activeTask.status))}
                onClick={() => void handleRun()}
              >
                <PlayIcon data-icon="inline-start" />
                {t("开始评测（{value} 条）", { value: selectedCaseIds.length })}
              </Button>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>
                  {t("{label}：{value}", {
                    label: t("检索模式"),
                    value: t(
                      searchMode === "embedding"
                        ? "向量检索"
                        : searchMode === "keywords"
                          ? "关键词检索"
                          : "混合检索",
                    ),
                  })}
                </span>
                <span>{t("{label}：{value}", { label: t("返回数量"), value: limit })}</span>
                <span>{t("{label}：{value}", { label: t("相似度"), value: similarity })}</span>
                <span>
                  {t("{label}：{value}", {
                    label: t("扩展文档引用"),
                    value: t(includeReferences ? "是" : "否"),
                  })}
                </span>
              </div>
            </div>
            {activeTask ? (
              <p className="mt-3 text-sm text-muted-foreground" aria-live="polite">
                {t("评测状态：{status}，进度 {done}/{total}", {
                  status: taskStatusLabel(activeTask.status, t),
                  done: activeTask.processed_items,
                  total: activeTask.total_items,
                })}
              </p>
            ) : null}
          </section>
        ) : null}

        <div className="mt-4 grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
          <section className="rounded-lg border">
            <div className="border-b p-4"><h2 className="text-sm font-semibold">{t("运行历史")}</h2></div>
            {runs.length ? runs.map((task) => (
              <div key={task.id} className="flex items-center border-b last:border-b-0 hover:bg-muted/40">
                <button
                  type="button"
                  className="min-w-0 flex-1 p-3 text-left text-sm"
                  onClick={() => void openRun(task)}
                >
                  <span className="block font-medium">{taskStatusLabel(task.status, t)}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">{formatDateTime(task.created_at, locale)}</span>
                </button>
                {canEdit && ["succeeded", "failed"].includes(task.status) ? (
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    className="mr-2"
                    title={t("删除运行记录：{value}", { value: formatDateTime(task.created_at, locale) })}
                    aria-label={t("删除运行记录：{value}", { value: formatDateTime(task.created_at, locale) })}
                    disabled={isDeleting}
                    onClick={(event) => {
                      event.stopPropagation()
                      setDeleteTarget({ type: "run", item: task })
                    }}
                  >
                    <Trash2Icon />
                  </Button>
                ) : null}
              </div>
            )) : <div className="p-4 text-sm text-muted-foreground">{t("暂无评测记录")}</div>}
          </section>

          <section className="min-w-0 rounded-lg border">
            <div className="flex items-center gap-1 border-b p-4">
              <h2 className="text-sm font-semibold">{t("评测结果")}</h2>
              <PopoverPrimitive.Root>
                <PopoverPrimitive.Trigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    className="-my-1 text-muted-foreground"
                    aria-label={t("查看评测说明")}
                    title={t("查看评测说明")}
                  >
                    <CircleAlertIcon className="size-4" />
                  </Button>
                </PopoverPrimitive.Trigger>
                <PopoverPrimitive.Portal>
                  <PopoverPrimitive.Content
                    side="right"
                    align="center"
                    sideOffset={6}
                    collisionPadding={16}
                    className="z-50 max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-lg overflow-y-auto rounded-lg border bg-popover p-4 text-popover-foreground shadow-md outline-none"
                  >
                    <p className="font-semibold">{t("评测指标说明")}</p>
                    <div className="mt-3 space-y-3 text-sm leading-6">
                      <p>
                        {t("输入一个问题后，系统召回的前 K 个结果，是否来自你事先标记的“期望文档”，以及这些文档排得够不够靠前。")}
                      </p>
                      <p className="text-muted-foreground">
                        {t("它不是在评测召回片段的正文是否真的包含答案，也不评测 Agent 最终回答是否正确。")}
                      </p>
                      <div className="rounded-md bg-muted/50 p-3">
                        <p className="font-medium">{t("示例")}</p>
                        <div className="mt-2 space-y-1 text-muted-foreground">
                          <p>{t("测试问题：怎么申请年假？")}</p>
                          <p>{t("期望文档：A《员工手册》、B《请假制度》")}</p>
                          <p>{t("实际召回文档顺序：B、X、A")}</p>
                        </div>
                        <ul className="mt-3 list-disc space-y-1 pl-5">
                          {([
                            "Hit@K = 1：至少命中了一篇期望文档",
                            "Recall@K = 1：A、B 两篇都找到了",
                            "MRR = 1：第一名就是期望文档",
                            "nDCG@K ≈ 0.92：都找到了，但 A 排到第三名，因此被扣一点分",
                            "P50/P95：检索耗时",
                          ] as TranslationKey[]).map((item) => (
                            <li key={item}>{t(item)}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </PopoverPrimitive.Content>
                </PopoverPrimitive.Portal>
              </PopoverPrimitive.Root>
            </div>
            {summary ? (
              <div>
                <dl className="grid grid-cols-2 gap-3 p-4 text-sm sm:grid-cols-4">
                  {[
                    ["Hit@K 命中率" as TranslationKey, metric(summary.mean_hit_at_k)],
                    ["Recall@K 召回率" as TranslationKey, metric(summary.mean_recall_at_k)],
                    ["MRR 首次命中排名" as TranslationKey, metric(summary.mean_reciprocal_rank)],
                    ["nDCG@K 排序质量" as TranslationKey, metric(summary.mean_ndcg_at_k)],
                    ["P50 延迟" as TranslationKey, t("{value} 毫秒", { value: metric(summary.p50_latency_ms) })],
                    ["P95 延迟" as TranslationKey, t("{value} 毫秒", { value: metric(summary.p95_latency_ms) })],
                    ["成功用例" as TranslationKey, summary.count],
                    ["失败用例" as TranslationKey, summary.failed_count],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-md bg-muted/50 p-3">
                      <dt className="text-xs text-muted-foreground">{t(label as TranslationKey)}</dt>
                      <dd className="mt-1 font-semibold">{value}</dd>
                    </div>
                  ))}
                </dl>
                <div className="overflow-x-auto border-t">
                  <div className="min-w-[760px]">
                    <div className="grid grid-cols-[minmax(260px,1fr)_90px_90px_90px_90px_120px] border-b px-4 py-2 text-xs font-medium text-muted-foreground">
                      <span>{t("问题 / 错误")}</span><span>{t("Hit@K")}</span><span>{t("Recall@K")}</span><span>{t("MRR")}</span><span>{t("nDCG@K")}</span><span>{t("延迟")}</span>
                    </div>
                    {summary.results.map((result) => (
                      <div key={result.id} className="grid grid-cols-[minmax(260px,1fr)_90px_90px_90px_90px_120px] border-b px-4 py-3 text-sm last:border-b-0">
                        <span className="min-w-0 break-words pr-3">
                          {result.question}
                          {result.error ? <small className="mt-1 block text-destructive">{result.error}</small> : null}
                        </span>
                        <span>{metric(result.hit_at_k)}</span>
                        <span>{metric(result.recall_at_k)}</span>
                        <span>{metric(result.reciprocal_rank)}</span>
                        <span>{metric(result.ndcg_at_k)}</span>
                        <span>{t("{value} 毫秒", { value: metric(result.latency_ms) })}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                {t("暂无评测结果")}
              </div>
            )}
          </section>
        </div>
      </div>
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !isDeleting) setDeleteTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {deleteTarget?.type === "run"
                ? t("删除运行记录")
                : t("删除评测用例")}
            </DialogTitle>
            <DialogDescription>
              {deleteTarget?.type === "run"
                ? t("删除运行记录说明")
                : t("删除评测用例说明")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={isDeleting}
              onClick={() => setDeleteTarget(null)}
            >
              {t("取消")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={isDeleting}
              onClick={() => void confirmDelete()}
            >
              {isDeleting ? (
                <LoaderCircleIcon data-icon="inline-start" className="animate-spin" />
              ) : null}
              {t("删除")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

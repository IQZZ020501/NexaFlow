"use client"

import * as React from "react"
import {
  LoaderCircleIcon,
  PlayIcon,
  PlusIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import {
  createKnowledgeEvaluationCase,
  createKnowledgeEvaluationRun,
  deleteKnowledgeEvaluationCase,
  getKnowledgeEvaluationRun,
  getKnowledgeEvaluationSummary,
  listKnowledgeEvaluationCases,
  listKnowledgeEvaluationRuns,
} from "@/lib/api/knowledge"
import type {
  KnowledgeDocument,
  KnowledgeEvaluationCase,
  KnowledgeEvaluationSummary,
  KnowledgeSearchMode,
  KnowledgeTask,
} from "@/lib/api/knowledge"
import { languageLocales, type TranslationKey } from "@/i18n"
import { formatDateTime } from "@/lib/display"
import { taskStatusLabel } from "@/components/knowledge/status-labels"

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
  const [question, setQuestion] = React.useState("")
  const [expectedDocumentIds, setExpectedDocumentIds] = React.useState<string[]>([])
  const [answerPoints, setAnswerPoints] = React.useState("")
  const [limit, setLimit] = React.useState(5)
  const [searchMode, setSearchMode] = React.useState<KnowledgeSearchMode>("blend")
  const [similarity, setSimilarity] = React.useState(2)
  const [includeReferences, setIncludeReferences] = React.useState(true)
  const [activeTask, setActiveTask] = React.useState<KnowledgeTask | null>(null)
  const [summary, setSummary] = React.useState<KnowledgeEvaluationSummary | null>(null)
  const [isLoading, setIsLoading] = React.useState(true)
  const [isSaving, setIsSaving] = React.useState(false)

  const load = React.useCallback(async () => {
    setIsLoading(true)
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
    } finally {
      setIsLoading(false)
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
    answer_points: string[]
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

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSaving(true)
    try {
      await addCase({
        question: question.trim(),
        expected_document_ids: expectedDocumentIds,
        answer_points: answerPoints
          .split("\n")
          .map((value) => value.trim())
          .filter(Boolean),
      })
      setQuestion("")
      setExpectedDocumentIds([])
      setAnswerPoints("")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDelete(item: KnowledgeEvaluationCase) {
    if (!window.confirm(t("删除评测用例？"))) return
    try {
      await deleteKnowledgeEvaluationCase(token, workspaceId, knowledgeBaseId, item.id)
      setCases((current) => current.filter((entry) => entry.id !== item.id))
      setSelectedCaseIds((current) => current.filter((id) => id !== item.id))
    } catch (error) {
      reportError(error)
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

  if (isLoading) {
    return (
      <div className="flex min-h-64 items-center justify-center">
        <LoaderCircleIcon className="animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-4 lg:p-5">
      <div className="max-w-6xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">{t("检索评测")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("用固定问题和期望文档持续验证真实检索链路")}
            </p>
          </div>
          <Button type="button" variant="outline" onClick={() => void load()}>
            <RotateCcwIcon data-icon="inline-start" />
            {t("刷新")}
          </Button>
        </div>

        {canEdit ? (
          <div className="mt-4">
            <form className="rounded-lg border p-4" onSubmit={(event) => void handleCreate(event)}>
              <h2 className="text-sm font-semibold">{t("新建评测用例")}</h2>
              <label className="mt-3 grid gap-1 text-sm font-medium" htmlFor="evaluation-question">
                {t("问题")}
                <textarea
                  id="evaluation-question"
                  className="min-h-20 rounded-md border bg-background px-3 py-2 text-sm"
                  value={question}
                  maxLength={2000}
                  onChange={(event) => setQuestion(event.target.value)}
                />
              </label>
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
              <label className="mt-3 grid gap-1 text-sm font-medium" htmlFor="evaluation-answer-points">
                {t("答案要点（每行一个）")}
                <textarea
                  id="evaluation-answer-points"
                  className="min-h-20 rounded-md border bg-background px-3 py-2 text-sm"
                  value={answerPoints}
                  onChange={(event) => setAnswerPoints(event.target.value)}
                />
              </label>
              <Button
                type="submit"
                className="mt-3"
                disabled={isSaving || !question.trim() || !expectedDocumentIds.length}
              >
                <PlusIcon data-icon="inline-start" />
                {t("添加用例")}
              </Button>
            </form>
          </div>
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
                      onClick={() => void handleDelete(item)}
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
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="grid gap-1 text-sm font-medium" htmlFor="evaluation-mode">
                {t("检索模式")}
                <select
                  id="evaluation-mode"
                  className="h-9 rounded-md border bg-background px-3 text-sm"
                  value={searchMode}
                  onChange={(event) => setSearchMode(event.target.value as KnowledgeSearchMode)}
                >
                  <option value="blend">{t("混合检索")}</option>
                  <option value="embedding">{t("向量检索")}</option>
                  <option value="keywords">{t("关键词检索")}</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm font-medium" htmlFor="evaluation-distance">
                {t("最大余弦距离")}
                <Input
                  id="evaluation-distance"
                  type="number"
                  min={0}
                  max={2}
                  step={0.05}
                  value={similarity}
                  onChange={(event) => setSimilarity(Math.min(2, Math.max(0, Number(event.target.value) || 0)))}
                />
              </label>
              <label className="grid gap-1 text-sm font-medium" htmlFor="evaluation-limit">
                {t("Top K")}
                <Input
                  id="evaluation-limit"
                  type="number"
                  min={1}
                  max={20}
                  value={limit}
                  onChange={(event) => setLimit(Math.min(20, Math.max(1, Number(event.target.value) || 1)))}
                />
              </label>
              <label className="flex min-h-9 items-center gap-2 self-end text-sm font-medium">
                <input
                  type="checkbox"
                  checked={includeReferences}
                  onChange={(event) => setIncludeReferences(event.target.checked)}
                />
                {t("扩展文档引用")}
              </label>
            </div>
            <Button
              type="button"
              className="mt-3"
              disabled={isSaving || !selectedCaseIds.length || Boolean(activeTask && ["queued", "running"].includes(activeTask.status))}
              onClick={() => void handleRun()}
            >
              <PlayIcon data-icon="inline-start" />
              {t("开始评测（{value} 条）", { value: selectedCaseIds.length })}
            </Button>
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
              <button
                key={task.id}
                type="button"
                className="block w-full border-b p-3 text-left text-sm last:border-b-0 hover:bg-muted/40"
                onClick={() => void openRun(task)}
              >
                <span className="block font-medium">{taskStatusLabel(task.status, t)}</span>
                <span className="mt-1 block text-xs text-muted-foreground">{formatDateTime(task.created_at, locale)}</span>
              </button>
            )) : <div className="p-4 text-sm text-muted-foreground">{t("暂无评测记录")}</div>}
          </section>

          <section className="min-w-0 rounded-lg border">
            <div className="border-b p-4"><h2 className="text-sm font-semibold">{t("评测结果")}</h2></div>
            {summary ? (
              <div>
                <dl className="grid grid-cols-2 gap-3 p-4 text-sm sm:grid-cols-4">
                  {[
                    ["Hit@K" as TranslationKey, metric(summary.mean_hit_at_k)],
                    ["Recall@K" as TranslationKey, metric(summary.mean_recall_at_k)],
                    ["MRR" as TranslationKey, metric(summary.mean_reciprocal_rank)],
                    ["nDCG@K" as TranslationKey, metric(summary.mean_ndcg_at_k)],
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
    </div>
  )
}

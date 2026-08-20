"use client"

import * as React from "react"
import { LoaderCircleIcon, TargetIcon } from "lucide-react"
import { FilterDropdown } from "@/components/app/filter-dropdown"
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
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { inspectKnowledgeBase } from "@/lib/api/knowledge"
import type {
  KnowledgeQueryInspectResult,
  KnowledgeQueryHit,
  KnowledgeRetrievalTrace,
  KnowledgeSearchMode,
} from "@/lib/api/knowledge"
import type { TFunction, TranslationKey } from "@/i18n"
import { MarkdownContent } from "@/components/knowledge/markdown-content"

type KnowledgeHitTestProps = {
  token: string
  workspaceId: string
  knowledgeBaseId: string
  reportError: (error: unknown) => void
  onTested: (payload: {
    query: string
    result: KnowledgeQueryInspectResult
    limit: number
    searchMode: KnowledgeSearchMode
    similarity: number
    includeReferences: boolean
  }) => void
}

const stageLabels: Record<string, TranslationKey> = {
  candidates: "候选召回",
  entities: "数据过滤",
  rerank: "重排",
  assemble: "结果组装",
}

function formatNumber(value: number | null, digits = 3) {
  if (value === null || !Number.isFinite(value)) return "-"
  return Number(value.toFixed(digits)).toString()
}

function hitSummary(hit: KnowledgeQueryHit) {
  const source = hit.kind === "qa" && hit.question ? hit.question : hit.content
  const summary = source.replace(/\s+/g, " ").trim()
  if (!summary) return "-"
  if (summary.length <= 220) return summary
  return `${summary.slice(0, 217).trimEnd()}...`
}

function sourceLabel(
  t: TFunction,
  source: "vector" | "keywords" | "reference"
) {
  if (source === "vector") return t("向量检索")
  if (source === "keywords") return t("关键词检索")
  return t("文档引用")
}

function rerankStatusLabel(
  t: TFunction,
  status: KnowledgeRetrievalTrace["rerank_status"]
) {
  if (status === "not_configured") return t("未配置")
  if (status === "applied") return t("已应用")
  if (status === "fallback") return t("已回退")
  return t("已跳过")
}

export function KnowledgeHitTest({
  token,
  workspaceId,
  knowledgeBaseId,
  reportError,
  onTested,
}: KnowledgeHitTestProps) {
  const { t } = useLanguage()
  const [queryText, setQueryText] = React.useState("")
  const [queryLimit, setQueryLimit] = React.useState(5)
  const [searchMode, setSearchMode] =
    React.useState<KnowledgeSearchMode>("blend")
  const [minSimilarity, setMinSimilarity] = React.useState(0.6)
  const [includeReferences, setIncludeReferences] = React.useState(true)
  const [result, setResult] =
    React.useState<KnowledgeQueryInspectResult | null>(null)
  const [isQuerying, setIsQuerying] = React.useState(false)
  const [selectedHit, setSelectedHit] =
    React.useState<KnowledgeQueryHit | null>(null)
  const selectedTriggerRef = React.useRef<HTMLButtonElement | null>(null)

  function openHitDetails(
    hit: KnowledgeQueryHit,
    event: React.MouseEvent<HTMLButtonElement>
  ) {
    selectedTriggerRef.current = event.currentTarget
    setSelectedHit(hit)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = queryText.trim()
    if (!query) return

    setSelectedHit(null)
    setIsQuerying(true)
    try {
      const nextResult = await inspectKnowledgeBase(
        token,
        workspaceId,
        knowledgeBaseId,
        {
          query,
          limit: queryLimit,
          search_mode: searchMode,
          similarity: minSimilarity,
          include_references: includeReferences,
        }
      )
      setResult(nextResult)
      onTested({
        query,
        result: nextResult,
        limit: queryLimit,
        searchMode,
        similarity: minSimilarity,
        includeReferences,
      })
    } catch (error) {
      setResult(null)
      setSelectedHit(null)
      reportError(error)
    } finally {
      setIsQuerying(false)
    }
  }

  const trace = result?.trace
  return (
    <>
      <section className="mt-4 rounded-lg border p-4">
        <h2 className="text-sm font-semibold">{t("命中测试")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("使用当前知识库的向量索引和权威切片状态验证召回结果")}
        </p>

        <form className="mt-3" onSubmit={(event) => void handleSubmit(event)}>
          <label className="text-sm font-medium" htmlFor="query-text">
            {t("查询内容")}
          </label>
          <textarea
            id="query-text"
            value={queryText}
            onChange={(event) => setQueryText(event.target.value)}
            className="mt-2 min-h-28 w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder={t("输入要测试的检索问题")}
          />
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="grid gap-1 text-sm font-medium">
              <span>{t("检索模式")}</span>
              <div className="[&_button]:h-9">
                <FilterDropdown
                  ariaLabel={t("检索模式")}
                  value={searchMode}
                  options={[
                    { value: "blend", label: t("混合检索") },
                    { value: "embedding", label: t("向量检索") },
                    { value: "keywords", label: t("关键词检索") },
                  ]}
                  onChange={(value) =>
                    setSearchMode(value as KnowledgeSearchMode)
                  }
                />
              </div>
            </div>
            <label
              className="grid gap-1 text-sm font-medium"
              htmlFor="query-similarity"
            >
              {t("相似度")}
              <Input
                id="query-similarity"
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={minSimilarity}
                onChange={(event) =>
                  setMinSimilarity(
                    Math.min(1, Math.max(0, Number(event.target.value) || 0))
                  )
                }
              />
            </label>
            <label
              className="grid gap-1 text-sm font-medium"
              htmlFor="query-limit"
            >
              {t("返回数量")}
              <Input
                id="query-limit"
                type="number"
                min={1}
                max={20}
                value={queryLimit}
                onChange={(event) =>
                  setQueryLimit(
                    Math.min(20, Math.max(1, Number(event.target.value) || 1))
                  )
                }
              />
            </label>
            <label className="flex min-h-9 items-center gap-2 self-end text-sm font-medium">
              <input
                type="checkbox"
                className="size-4"
                checked={includeReferences}
                onChange={(event) => setIncludeReferences(event.target.checked)}
              />
              {t("扩展文档引用")}
            </label>
          </div>
          <Button
            type="submit"
            className="mt-3"
            disabled={!queryText.trim() || isQuerying}
          >
            {isQuerying ? (
              <LoaderCircleIcon
                className="animate-spin"
                data-icon="inline-start"
              />
            ) : (
              <TargetIcon data-icon="inline-start" />
            )}
            {t("测试召回")}
          </Button>
        </form>
      </section>

      {trace ? (
        <section className="mt-4 rounded-lg border bg-background p-4">
          <h2 className="text-sm font-semibold">{t("检索追踪")}</h2>
          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
            <span>
              {t("{label}：{value}", {
                label: t("追踪 ID"),
                value: trace.trace_id,
              })}
            </span>
            <span>
              {t("{label}：{value}", {
                label: t("向量候选"),
                value: trace.vector_candidates,
              })}
            </span>
            <span>
              {t("{label}：{value}", {
                label: t("关键词候选"),
                value: trace.keyword_candidates,
              })}
            </span>
            <span>
              {t("{label}：{value}", {
                label: t("引用候选"),
                value: trace.reference_candidates,
              })}
            </span>
            <span>
              {t("{label}：{value}", {
                label: t("融合候选"),
                value: trace.fused_candidates,
              })}
            </span>
            <span>
              {t("{label}：{value}", {
                label: t("重排状态"),
                value: rerankStatusLabel(t, trace.rerank_status),
              })}
            </span>
            <span>
              {t("{label}：{value}", {
                label: t("总耗时"),
                value: t("{value} 毫秒", {
                  value: formatNumber(trace.duration_ms),
                }),
              })}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {Object.entries(trace.stage_duration_ms ?? {}).map(
              ([stage, duration]) => {
                const label = stageLabels[stage]
                return label ? (
                  <span key={stage}>
                    {t("{label}：{value}", {
                      label: t(label),
                      value: t("{value} 毫秒", {
                        value: formatNumber(duration),
                      }),
                    })}
                  </span>
                ) : null
              }
            )}
          </div>
        </section>
      ) : null}

      <section className="mt-4 rounded-lg border bg-background">
        <div className="border-b px-4 py-3">
          <h2 className="text-sm font-semibold">{t("召回结果")}</h2>
        </div>
        {result?.hits.length ? (
          <div className="grid gap-3 p-4 md:grid-cols-2">
            {result.hits.map((hit, index) => (
              <button
                key={hit.chunk_id}
                type="button"
                aria-haspopup="dialog"
                className="group flex min-h-44 min-w-0 flex-col rounded-lg border p-4 text-left transition-colors outline-none hover:border-primary/50 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(event) => openHitDetails(hit, event)}
              >
                <div className="flex min-w-0 items-start gap-2">
                  <span className="shrink-0 rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold text-primary tabular-nums">
                    #{index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                    {hit.document_filename}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    #{hit.chunk_index + 1}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground tabular-nums">
                  <span>
                    {t("{label}：{value}", {
                      label: t("相似度"),
                      value: formatNumber(hit.similarity, 4),
                    })}
                  </span>
                  {hit.rerank_score !== null ? (
                    <span>
                      {t("{label}：{value}", {
                        label: t("重排分数"),
                        value: formatNumber(hit.rerank_score),
                      })}
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 flex min-h-6 flex-wrap items-center gap-1.5">
                  {hit.sources.length ? (
                    hit.sources.map((source) => (
                      <Badge key={source} variant="outline">
                        {sourceLabel(t, source)}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-xs text-muted-foreground">-</span>
                  )}
                  {hit.reference_hops > 0 ? (
                    <Badge variant="secondary">
                      {t("{label}：{value}", {
                        label: t("引用跳数"),
                        value: hit.reference_hops,
                      })}
                    </Badge>
                  ) : null}
                </div>
                <p className="mt-3 line-clamp-3 text-sm leading-5 text-muted-foreground">
                  {hitSummary(hit)}
                </p>
              </button>
            ))}
          </div>
        ) : (
          <div className="flex min-h-40 items-center justify-center px-4 text-sm text-muted-foreground">
            {t("暂无测试结果")}
          </div>
        )}
      </section>

      <Dialog
        open={selectedHit !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedHit(null)
        }}
      >
        <DialogContent
          className="grid max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] max-w-3xl grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden p-0"
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            selectedTriggerRef.current?.focus()
          }}
        >
          {selectedHit ? (
            <>
              <DialogHeader className="border-b px-6 py-5">
                <DialogTitle className="break-words">
                  {selectedHit.document_filename} / #
                  {selectedHit.chunk_index + 1}
                </DialogTitle>
                <DialogDescription className="tabular-nums">
                  {t("{label}：{value}", {
                    label: t("排名"),
                    value: `#${
                      (result?.hits.findIndex(
                        (hit) => hit.chunk_id === selectedHit.chunk_id
                      ) ?? -1) + 1
                    }`,
                  })}
                  {" · "}
                  {t("{label}：{value}", {
                    label: t("相似度"),
                    value: formatNumber(selectedHit.similarity, 4),
                  })}
                  {selectedHit.rerank_score !== null
                    ? ` · ${t("{label}：{value}", {
                        label: t("重排分数"),
                        value: formatNumber(selectedHit.rerank_score),
                      })}`
                    : null}
                </DialogDescription>
              </DialogHeader>
              <div className="min-h-0 overflow-y-auto px-6 py-5">
                <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                  <div className="min-w-0">
                    <dt className="text-xs text-muted-foreground">
                      {t("分段 ID")}
                    </dt>
                    <dd className="mt-1 font-mono text-xs break-all">
                      {selectedHit.chunk_id}
                    </dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-xs text-muted-foreground">
                      {t("文档 ID")}
                    </dt>
                    <dd className="mt-1 font-mono text-xs break-all">
                      {selectedHit.document_id}
                    </dd>
                  </div>
                  {selectedHit.parent_id ? (
                    <div className="min-w-0">
                      <dt className="text-xs text-muted-foreground">
                        {t("父分段 ID")}
                      </dt>
                      <dd className="mt-1 font-mono text-xs break-all">
                        {selectedHit.parent_id}
                      </dd>
                    </div>
                  ) : null}
                  <div>
                    <dt className="text-xs text-muted-foreground">
                      {t("来源")}
                    </dt>
                    <dd className="mt-1 flex flex-wrap gap-1.5">
                      {selectedHit.sources.length
                        ? selectedHit.sources.map((source) => (
                            <Badge key={source} variant="outline">
                              {sourceLabel(t, source)}
                            </Badge>
                          ))
                        : "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">
                      {t("引用跳数")}
                    </dt>
                    <dd className="mt-1 tabular-nums">
                      {selectedHit.reference_hops}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">
                      {t("相似度")}
                    </dt>
                    <dd className="mt-1 tabular-nums">
                      {formatNumber(selectedHit.similarity, 4)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">
                      {t("重排分数")}
                    </dt>
                    <dd className="mt-1 tabular-nums">
                      {formatNumber(selectedHit.rerank_score)}
                    </dd>
                  </div>
                </dl>
                <div className="mt-6 border-t pt-5">
                  <h3 className="text-sm font-semibold">{t("内容")}</h3>
                  <MarkdownContent
                    content={selectedHit.content}
                    className="mt-3"
                  />
                </div>
              </div>
              <DialogFooter className="border-t px-6 py-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setSelectedHit(null)}
                >
                  {t("关闭")}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}

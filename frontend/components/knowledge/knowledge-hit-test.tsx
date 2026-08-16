"use client"

import * as React from "react"
import { LoaderCircleIcon, TargetIcon } from "lucide-react"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { inspectKnowledgeBase } from "@/lib/api/knowledge"
import type {
  KnowledgeQueryInspectResult,
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

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = queryText.trim()
    if (!query) return

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
        },
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

      <form
        className="mt-3"
        onSubmit={(event) => void handleSubmit(event)}
      >
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
          <div className="divide-y">
            {result.hits.map((hit) => (
              <article key={hit.chunk_id} className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">
                    {hit.document_filename} / #{hit.chunk_index + 1}
                  </span>
                  <span>
                    {t("{label}：{value}", {
                      label: t("相似度"),
                      value: formatNumber(hit.similarity, 4),
                    })}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>
                    {t("{label}：{value}", {
                      label: t("分段 ID"),
                      value: hit.chunk_id,
                    })}
                  </span>
                  <span>
                    {t("{label}：{value}", {
                      label: t("文档 ID"),
                      value: hit.document_id,
                    })}
                  </span>
                  {hit.parent_id ? (
                    <span>
                      {t("{label}：{value}", {
                        label: t("父分段 ID"),
                        value: hit.parent_id,
                      })}
                    </span>
                  ) : null}
                  <span>
                    {t("{label}：{value}", {
                      label: t("来源"),
                      value:
                        hit.sources
                          .map((source) => sourceLabel(t, source))
                          .join(t("列表分隔符")) || "-",
                    })}
                  </span>
                  <span>
                    {t("{label}：{value}", {
                      label: t("引用跳数"),
                      value: hit.reference_hops,
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
                <MarkdownContent content={hit.content} className="mt-3" />
              </article>
            ))}
          </div>
        ) : (
          <div className="flex min-h-40 items-center justify-center px-4 text-sm text-muted-foreground">
            {t("暂无测试结果")}
          </div>
        )}
      </section>
    </>
  )
}

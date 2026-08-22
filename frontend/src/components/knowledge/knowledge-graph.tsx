"use client"

import * as React from "react"
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  FileJsonIcon,
  GitBranchIcon,
  LoaderCircleIcon,
  NetworkIcon,
  RefreshCwIcon,
  SearchIcon,
  SettingsIcon,
  ShieldCheckIcon,
  UploadIcon,
  XIcon,
} from "lucide-react"

import { FilterDropdown } from "@/components/app/filter-dropdown"
import { KnowledgeGraphCanvas } from "@/components/knowledge/knowledge-graph-canvas"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { languageLocales, type TFunction } from "@/i18n"
import {
  getKnowledgeGraphEntity,
  getKnowledgeGraphOverview,
  getKnowledgeGraphSchema,
  getKnowledgeGraphSettings,
  getKnowledgeGraphStatus,
  importKnowledgeGraphRecords,
  listKnowledgeGraphEntities,
  listKnowledgeGraphReviews,
  queryKnowledgeGraphNeighborhood,
  queryKnowledgeGraphPath,
  rebuildKnowledgeGraph,
  resolveKnowledgeGraphReview,
  updateKnowledgeGraphSchema,
  updateKnowledgeGraphSettings,
} from "@/lib/api/knowledge"
import type {
  KnowledgeGraphEntity,
  KnowledgeGraphEntityDetail,
  KnowledgeGraphQueryResult,
  KnowledgeGraphReviewItem,
  KnowledgeGraphSchema,
  KnowledgeGraphSettings,
  KnowledgeGraphStatus,
} from "@/lib/api/knowledge"
import { formatDateTime } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"
import { cn } from "@/lib/utils"

type GraphWorkspaceView = "explore" | "reviews" | "settings"

const TEXTAREA_CLASS =
  "flex min-h-24 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"

function isAbortError(error: unknown) {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  )
}

function stringValues(value: unknown) {
  return Array.isArray(value)
    ? value.map(String).filter(Boolean)
    : typeof value === "string" && value
      ? [value]
      : []
}

function payloadIds(payload: Record<string, unknown>, name: string) {
  return [
    ...stringValues(payload[`${name}_ids`]),
    ...stringValues(payload[`${name}_id`]),
  ].filter((value, index, values) => values.indexOf(value) === index)
}

function schemaNames(schema: KnowledgeGraphSchema | null, key: string) {
  const values = schema?.schema_json[key]
  if (!Array.isArray(values)) return []
  return values.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return []
    const name = (value as Record<string, unknown>).name
    return typeof name === "string" && name ? [name] : []
  })
}

function numericStat(stats: Record<string, unknown> | undefined, key: string) {
  const value = stats?.[key]
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function graphStatusLabel(status: string | null, t: TFunction) {
  if (status === "building") return t("构建中")
  if (status === "published") return t("已发布")
  if (status === "failed") return t("失败")
  if (status === "queued") return t("排队中")
  return t("尚未构建")
}

function graphBuildActive(status: KnowledgeGraphStatus | null) {
  return ["queued", "running", "cancelling"].includes(
    status?.build_task_status ?? ""
  )
}

function reviewKindLabel(kind: string, t: TFunction) {
  if (kind === "ambiguous_entity") return t("实体存在歧义")
  if (kind === "possible_duplicate") return t("可能重复实体")
  if (kind === "implicit_relation") return t("隐含关系")
  if (kind === "conflict") return t("关系冲突")
  return kind
}

export function KnowledgeGraph({
  token,
  workspaceId,
  knowledgeBaseId,
  canEdit,
  notify,
  reportError,
}: {
  token: string
  workspaceId: string
  knowledgeBaseId: string
  canEdit: boolean
  notify: (kind: AppNotification["kind"], message: string) => void
  reportError: (error: unknown) => void
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const [view, setView] = React.useState<GraphWorkspaceView>("explore")
  const [settings, setSettings] = React.useState<KnowledgeGraphSettings | null>(
    null
  )
  const [status, setStatus] = React.useState<KnowledgeGraphStatus | null>(null)
  const [schema, setSchema] = React.useState<KnowledgeGraphSchema | null>(null)
  const [entities, setEntities] = React.useState<KnowledgeGraphEntity[]>([])
  const [entityTotal, setEntityTotal] = React.useState(0)
  const [reviews, setReviews] = React.useState<KnowledgeGraphReviewItem[]>([])
  const [reviewTotal, setReviewTotal] = React.useState(0)
  const [isLoading, setIsLoading] = React.useState(true)
  const [loadedKnowledgeBaseId, setLoadedKnowledgeBaseId] = React.useState<
    string | null
  >(null)
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [busyAction, setBusyAction] = React.useState<string | null>(null)
  const [pollBaseline, setPollBaseline] = React.useState<number | undefined>()
  const pollAttemptsRef = React.useRef(0)
  const pollSawRunningRef = React.useRef(false)

  const [entitySearch, setEntitySearch] = React.useState("")
  const [sourceEntity, setSourceEntity] = React.useState("")
  const [targetEntity, setTargetEntity] = React.useState("")
  const [maxHops, setMaxHops] = React.useState(3)
  const [relationFilters, setRelationFilters] = React.useState<string[]>([])
  const [queryResult, setQueryResult] =
    React.useState<KnowledgeGraphQueryResult | null>(null)
  const [overviewState, setOverviewState] = React.useState<{
    knowledgeBaseId: string
    result: KnowledgeGraphQueryResult
  } | null>(null)
  const [queryError, setQueryError] = React.useState<string | null>(null)
  const [isQuerying, setIsQuerying] = React.useState(false)
  const [selectedClaimId, setSelectedClaimId] = React.useState<string | null>(
    null
  )
  const [selectedEntity, setSelectedEntity] =
    React.useState<KnowledgeGraphEntityDetail | null>(null)
  const [isEntityLoading, setIsEntityLoading] = React.useState(false)
  const entityRequestRef = React.useRef<AbortController | null>(null)

  const [selectedReviewId, setSelectedReviewId] = React.useState<string | null>(
    null
  )
  const [mergeSearch, setMergeSearch] = React.useState("")
  const [mergeCandidates, setMergeCandidates] = React.useState<
    KnowledgeGraphEntity[]
  >([])
  const [mergeTargetId, setMergeTargetId] = React.useState("")
  const [splitName, setSplitName] = React.useState("")
  const [splitType, setSplitType] = React.useState("")
  const [splitMentionIds, setSplitMentionIds] = React.useState<string[]>([])
  const [splitClaimIds, setSplitClaimIds] = React.useState<string[]>([])

  const [formEnabled, setFormEnabled] = React.useState(false)
  const [schemaText, setSchemaText] = React.useState("")
  const [importFile, setImportFile] = React.useState<File | null>(null)

  const refreshLists = React.useCallback(
    async (signal?: AbortSignal) => {
      const [entityPage, reviewPage] = await Promise.all([
        listKnowledgeGraphEntities(
          token,
          workspaceId,
          knowledgeBaseId,
          { limit: 20, offset: 0 },
          signal
        ),
        listKnowledgeGraphReviews(
          token,
          workspaceId,
          knowledgeBaseId,
          { limit: 20, offset: 0 },
          signal
        ),
      ])
      if (signal?.aborted) return
      setEntities(entityPage.items)
      setEntityTotal(entityPage.total)
      setReviews(reviewPage.items)
      setReviewTotal(reviewPage.total)
      setSelectedReviewId((current) =>
        reviewPage.items.some((item) => item.id === current)
          ? current
          : (reviewPage.items[0]?.id ?? null)
      )
    },
    [knowledgeBaseId, token, workspaceId]
  )

  React.useEffect(() => {
    const controller = new AbortController()

    void Promise.all([
      getKnowledgeGraphSettings(
        token,
        workspaceId,
        knowledgeBaseId,
        controller.signal
      ),
      getKnowledgeGraphStatus(
        token,
        workspaceId,
        knowledgeBaseId,
        controller.signal
      ),
      getKnowledgeGraphSchema(
        token,
        workspaceId,
        knowledgeBaseId,
        controller.signal
      ),
      listKnowledgeGraphEntities(
        token,
        workspaceId,
        knowledgeBaseId,
        { limit: 20, offset: 0 },
        controller.signal
      ),
      listKnowledgeGraphReviews(
        token,
        workspaceId,
        knowledgeBaseId,
        { limit: 20, offset: 0 },
        controller.signal
      ),
    ])
      .then(
        ([nextSettings, nextStatus, nextSchema, entityPage, reviewPage]) => {
          if (controller.signal.aborted) return
          setSettings(nextSettings)
          setStatus(nextStatus)
          setSchema(nextSchema)
          setEntities(entityPage.items)
          setEntityTotal(entityPage.total)
          setReviews(reviewPage.items)
          setReviewTotal(reviewPage.total)
          setSelectedReviewId(reviewPage.items[0]?.id ?? null)
          setLoadedKnowledgeBaseId(knowledgeBaseId)
          setQueryResult(null)
          setSelectedEntity(null)
          setSelectedClaimId(null)
          setFormEnabled(nextSettings.enabled)
          setSchemaText(
            nextSchema ? JSON.stringify(nextSchema.schema_json, null, 2) : ""
          )
          if (graphBuildActive(nextStatus)) {
            pollAttemptsRef.current = 0
            pollSawRunningRef.current = true
            setPollBaseline(nextStatus.revision_no ?? 0)
          }
        }
      )
      .catch((error) => {
        if (isAbortError(error)) return
        setLoadError(getErrorMessage(error, t))
        reportError(error)
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })

    return () => {
      controller.abort()
      entityRequestRef.current?.abort()
    }
  }, [knowledgeBaseId, reportError, t, token, workspaceId])

  React.useEffect(() => {
    if (
      loadedKnowledgeBaseId !== knowledgeBaseId ||
      !status?.active_revision_id ||
      !settings?.enabled
    )
      return
    const controller = new AbortController()
    void getKnowledgeGraphOverview(
      token,
      workspaceId,
      knowledgeBaseId,
      controller.signal
    )
      .then((result) => {
        if (!controller.signal.aborted) {
          setOverviewState({ knowledgeBaseId, result })
          setQueryError(null)
        }
      })
      .catch((error) => {
        if (isAbortError(error)) return
        setQueryError(getErrorMessage(error, t))
        reportError(error)
      })
    return () => controller.abort()
  }, [
    knowledgeBaseId,
    loadedKnowledgeBaseId,
    reportError,
    settings?.enabled,
    status?.active_revision_id,
    t,
    token,
    workspaceId,
  ])

  React.useEffect(() => {
    if (pollBaseline === undefined) return
    let cancelled = false
    let timeout: ReturnType<typeof setTimeout>

    const poll = async () => {
      try {
        const next = await getKnowledgeGraphStatus(
          token,
          workspaceId,
          knowledgeBaseId
        )
        if (cancelled) return
        setStatus(next)
        const running =
          graphBuildActive(next) ||
          ["building", "queued"].includes(next.revision_status ?? "")
        const changed = (next.revision_no ?? 0) > pollBaseline
        pollSawRunningRef.current ||= running
        if (!running && (changed || pollSawRunningRef.current)) {
          const [nextSettings, nextSchema] = await Promise.all([
            getKnowledgeGraphSettings(token, workspaceId, knowledgeBaseId),
            getKnowledgeGraphSchema(token, workspaceId, knowledgeBaseId),
            refreshLists(),
          ])
          if (cancelled) return
          setSettings(nextSettings)
          setFormEnabled(nextSettings.enabled)
          setSchema(nextSchema)
          setSchemaText(
            nextSchema ? JSON.stringify(nextSchema.schema_json, null, 2) : ""
          )
          setPollBaseline(undefined)
          return
        }

        pollAttemptsRef.current += 1
        // ponytail: cap passive polling at two minutes; task state survives refresh.
        if (pollAttemptsRef.current < 40 || graphBuildActive(next)) {
          timeout = setTimeout(() => void poll(), 3000)
        } else {
          setPollBaseline(undefined)
        }
      } catch (error) {
        if (cancelled || isAbortError(error)) return
        setPollBaseline(undefined)
        reportError(error)
      }
    }

    timeout = setTimeout(() => void poll(), 3000)
    return () => {
      cancelled = true
      clearTimeout(timeout)
    }
  }, [
    knowledgeBaseId,
    pollBaseline,
    refreshLists,
    reportError,
    token,
    workspaceId,
  ])

  const selectedReview =
    reviews.find((item) => item.id === selectedReviewId) ?? null
  const relationNames = schemaNames(schema, "relations")
  const entityTypeNames = schemaNames(schema, "entity_types")
  const overviewResult =
    overviewState?.knowledgeBaseId === knowledgeBaseId
      ? overviewState.result
      : null
  const displayResult = queryResult ?? overviewResult
  const isOverviewLoading = Boolean(
    settings?.enabled &&
    status?.active_revision_id &&
    !overviewResult &&
    !queryError
  )
  const selectedClaim =
    selectedEntity?.claims.find((claim) => claim.id === selectedClaimId) ??
    displayResult?.claims.find((claim) => claim.id === selectedClaimId)
  const evidenceById = new Map(
    [
      ...(displayResult?.evidence ?? []),
      ...(selectedEntity?.evidence ?? []),
    ].map((item) => [item.id, item])
  )
  const selectedEvidence = (selectedClaim?.evidence_ids ?? []).flatMap((id) => {
    const evidence = evidenceById.get(id)
    return evidence ? [evidence] : []
  })
  const graphEntities = new Map(
    [
      ...(displayResult?.resolved_entities ?? []),
      ...(displayResult?.nodes ?? []),
    ].map((entity) => [entity.id, entity])
  )
  const orderedEntityIds =
    queryResult?.paths[0]?.nodes.map((entity) => entity.id) ?? []
  const claimCount = numericStat(status?.stats, "claim_count")
  const graphBusy = pollBaseline !== undefined || graphBuildActive(status)
  const showGraphDetail = Boolean(
    isEntityLoading || selectedClaim || selectedEntity
  )

  function beginPolling(
    baseline = status?.revision_no ?? 0,
    sawRunning = false
  ) {
    pollAttemptsRef.current = 0
    pollSawRunningRef.current = sawRunning
    setPollBaseline(baseline)
  }

  function localError(message: string) {
    setLoadError(message)
    notify("error", message)
  }

  async function handleSettingsSave(enabled = formEnabled) {
    setBusyAction("settings")
    try {
      const wasEnabled = settings?.enabled ?? false
      const next = await updateKnowledgeGraphSettings(
        token,
        workspaceId,
        knowledgeBaseId,
        {
          enabled,
        }
      )
      setSettings(next)
      setFormEnabled(next.enabled)
      setStatus((current) =>
        current ? { ...current, enabled: next.enabled } : current
      )
      setLoadError(null)
      if (next.enabled && !wasEnabled) {
        notify("success", t("知识关联已启用，正在自动抽取已有文件"))
        beginPolling()
      } else {
        notify("success", t(next.enabled ? "知识关联已启用" : "知识关联已关闭"))
      }
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function handleEntitySearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyAction("entity-search")
    try {
      const page = await listKnowledgeGraphEntities(
        token,
        workspaceId,
        knowledgeBaseId,
        { query: entitySearch.trim() || undefined, limit: 20, offset: 0 }
      )
      setEntities(page.items)
      setEntityTotal(page.total)
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function selectEntity(entityId: string, claimId: string | null = null) {
    entityRequestRef.current?.abort()
    const controller = new AbortController()
    entityRequestRef.current = controller
    setSelectedClaimId(claimId)
    setSelectedEntity(null)
    setIsEntityLoading(true)
    try {
      const detail = await getKnowledgeGraphEntity(
        token,
        workspaceId,
        knowledgeBaseId,
        entityId,
        controller.signal
      )
      if (!controller.signal.aborted) setSelectedEntity(detail)
    } catch (error) {
      if (!isAbortError(error)) reportError(error)
    } finally {
      if (!controller.signal.aborted) setIsEntityLoading(false)
    }
  }

  function selectClaim(claimId: string) {
    const claim = displayResult?.claims.find((item) => item.id === claimId)
    setSelectedClaimId(claimId)
    setSelectedEntity(null)
    if (claim && !claim.evidence_ids.length) {
      void selectEntity(claim.subject_entity_id, claimId)
    }
  }

  function showOverview() {
    setQueryResult(null)
    setQueryError(null)
    clearGraphSelection()
  }

  function clearGraphSelection() {
    entityRequestRef.current?.abort()
    setIsEntityLoading(false)
    setSelectedClaimId(null)
    setSelectedEntity(null)
  }

  async function handleQuery(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const source = sourceEntity.trim()
    const target = targetEntity.trim()
    if (!source) return
    setIsQuerying(true)
    setQueryError(null)
    setSelectedClaimId(null)
    setSelectedEntity(null)
    try {
      const next = target
        ? await queryKnowledgeGraphPath(token, workspaceId, knowledgeBaseId, {
            source_entity: source,
            target_entity: target,
            max_hops: Math.min(8, Math.max(1, maxHops)),
            relation_filters: relationFilters,
          })
        : await queryKnowledgeGraphNeighborhood(
            token,
            workspaceId,
            knowledgeBaseId,
            {
              entity: source,
              max_hops: Math.min(3, Math.max(1, maxHops)),
              relation_filters: relationFilters,
            }
          )
      setQueryResult(next)
    } catch (error) {
      setQueryResult(null)
      setQueryError(getErrorMessage(error, t))
      reportError(error)
    } finally {
      setIsQuerying(false)
    }
  }

  async function handleMergeSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!mergeSearch.trim()) return
    setBusyAction("merge-search")
    try {
      const page = await listKnowledgeGraphEntities(
        token,
        workspaceId,
        knowledgeBaseId,
        { query: mergeSearch.trim(), limit: 20, offset: 0 }
      )
      setMergeCandidates(page.items)
      setMergeTargetId(page.items[0]?.id ?? "")
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function handleReviewDecision(
    action: "approve_claim" | "reject_claim" | "merge_entities" | "split_entity"
  ) {
    if (!selectedReview) return
    const reviewClaimIds = payloadIds(selectedReview.payload, "claim")
    if (action === "merge_entities" && !mergeTargetId) {
      localError(t("请选择合并目标实体"))
      return
    }
    if (
      action === "split_entity" &&
      (!splitName.trim() ||
        !splitType ||
        (!splitMentionIds.length && !splitClaimIds.length))
    ) {
      localError(t("拆分实体需要名称、类型和至少一条记录"))
      return
    }
    setBusyAction("review")
    try {
      await resolveKnowledgeGraphReview(
        token,
        workspaceId,
        knowledgeBaseId,
        selectedReview.id,
        action === "merge_entities"
          ? { action, target_entity_id: mergeTargetId }
          : action === "split_entity"
            ? {
                action,
                canonical_name: splitName.trim(),
                entity_type: splitType,
                mention_ids: splitMentionIds,
                claim_ids: splitClaimIds,
              }
            : { action, claim_ids: reviewClaimIds }
      )
      notify("success", t("审核决定已提交"))
      beginPolling()
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function handleSchemaSave() {
    let parsed: unknown
    try {
      parsed = JSON.parse(schemaText)
    } catch {
      localError(t("Schema JSON 无效"))
      return
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      localError(t("Schema JSON 必须是对象"))
      return
    }
    setBusyAction("schema")
    try {
      const next = await updateKnowledgeGraphSchema(
        token,
        workspaceId,
        knowledgeBaseId,
        parsed as Record<string, unknown>
      )
      setSchema(next)
      setSchemaText(JSON.stringify(next.schema_json, null, 2))
      setLoadError(null)
      notify("success", t("Schema 草稿已保存，重建发布后生效"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function handleRebuild() {
    setBusyAction("rebuild")
    try {
      await rebuildKnowledgeGraph(token, workspaceId, knowledgeBaseId)
      notify("success", t("知识关联重建已提交"))
      beginPolling()
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function handleImport() {
    if (!importFile) return
    setBusyAction("import")
    try {
      await importKnowledgeGraphRecords(
        token,
        workspaceId,
        knowledgeBaseId,
        importFile
      )
      setImportFile(null)
      notify("success", t("知识关联导入已提交"))
      beginPolling()
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex min-h-72 items-center justify-center" role="status">
        <LoaderCircleIcon className="size-5 animate-spin" />
        <span className="ml-2 text-sm text-muted-foreground">
          {t("正在加载知识关联")}
        </span>
      </div>
    )
  }

  if (!settings || !status) {
    return (
      <div className="m-4 border border-destructive/40 p-4 text-sm text-destructive">
        {loadError ?? t("知识关联加载失败")}
      </div>
    )
  }

  const reviewClaimIds = selectedReview
    ? payloadIds(selectedReview.payload, "claim")
    : []
  const reviewMentionIds = selectedReview
    ? payloadIds(selectedReview.payload, "mention")
    : []
  const reviewCanResolveEntity =
    selectedReview?.kind === "ambiguous_entity" ||
    selectedReview?.kind === "possible_duplicate"

  return (
    <div className="min-w-0">
      <section className="border-b px-4 py-4 lg:px-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">{t("知识关联")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("探索可追溯实体关系，并管理构建与审核")}
            </p>
          </div>
          <div className="flex items-center gap-2 text-sm">
            {graphBusy ? (
              <LoaderCircleIcon className="size-4 animate-spin" />
            ) : status.enabled ? (
              <CheckCircle2Icon className="size-4 text-emerald-600" />
            ) : (
              <AlertCircleIcon className="size-4 text-muted-foreground" />
            )}
            <span>{t(status.enabled ? "已启用" : "已关闭")}</span>
          </div>
        </div>
        <dl className="mt-4 grid gap-px overflow-hidden border bg-border text-sm sm:grid-cols-2 xl:grid-cols-6">
          {[
            [
              t("活动修订"),
              status.revision_no
                ? `#${status.revision_no} · ${graphStatusLabel(status.revision_status, t)}`
                : t("尚未构建"),
            ],
            [t("实体数"), entityTotal],
            [t("关系数"), claimCount ?? overviewResult?.claims.length ?? "—"],
            [t("待审核"), status.pending_review_count],
            [
              t("最后发布时间"),
              status.published_at
                ? formatDateTime(status.published_at, locale)
                : "—",
            ],
            [t("活动修订 ID"), status.active_revision_id ?? "—"],
          ].map(([label, value]) => (
            <div key={String(label)} className="min-w-0 bg-background p-3">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-1 truncate font-medium" title={String(value)}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
        {status.last_error ? (
          <p className="mt-3 border-l-2 border-destructive pl-3 text-sm text-destructive">
            {t("构建失败：{value}", { value: status.last_error })}
          </p>
        ) : null}
        {loadError ? (
          <p className="mt-3 text-sm text-destructive">{loadError}</p>
        ) : null}
      </section>

      <div
        role="tablist"
        aria-label={t("知识关联工作区")}
        className="flex gap-1 border-b px-4 py-2 lg:px-5"
      >
        {(
          [
            ["explore", t("探索"), NetworkIcon],
            ["reviews", t("审核"), ShieldCheckIcon],
            ["settings", t("设置"), SettingsIcon],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={view === key}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
              view === key && "bg-muted text-foreground"
            )}
            onClick={() => setView(key)}
          >
            <Icon className="size-4" />
            {label}
            {key === "reviews" && reviewTotal ? (
              <span className="rounded-full bg-primary/10 px-1.5 text-xs text-primary">
                {reviewTotal}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {view === "explore" ? (
        <div className="min-w-0">
          {!settings.enabled ? (
            <section className="m-4 border p-5 lg:m-5">
              <h2 className="font-semibold">{t("知识关联尚未启用")}</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {t(
                  "启用后，上传文件会在索引完成后自动抽取实体和关系；首次启用会自动处理已有文件"
                )}
              </p>
              {canEdit ? (
                <div className="mt-4">
                  <Button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void handleSettingsSave(true)}
                  >
                    {busyAction === "settings" ? (
                      <LoaderCircleIcon className="animate-spin" />
                    ) : null}
                    {t("启用知识关联")}
                  </Button>
                </div>
              ) : null}
            </section>
          ) : !status.active_revision_id ? (
            <section className="m-4 border p-5 lg:m-5">
              <h2 className="font-semibold">{t("尚无活动修订")}</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {t("正在自动抽取已有文件；完成后将在这里显示实体关系图")}
              </p>
              {canEdit ? (
                <Button
                  type="button"
                  className="mt-4"
                  disabled={busyAction !== null || graphBusy}
                  onClick={() => setView("settings")}
                >
                  {t("前往设置")}
                </Button>
              ) : null}
            </section>
          ) : (
            <>
              <div className="grid min-w-0 lg:grid-cols-[15rem_minmax(0,1fr)]">
                <aside className="min-w-0 border-b p-4 lg:min-h-[42rem] lg:border-r lg:border-b-0">
                  <form className="flex gap-2" onSubmit={handleEntitySearch}>
                    <Input
                      aria-label={t("实体搜索")}
                      placeholder={t("搜索实体")}
                      value={entitySearch}
                      onChange={(event) => setEntitySearch(event.target.value)}
                    />
                    <Button
                      type="submit"
                      variant="outline"
                      size="icon"
                      aria-label={t("搜索实体")}
                      disabled={busyAction === "entity-search"}
                    >
                      {busyAction === "entity-search" ? (
                        <LoaderCircleIcon className="animate-spin" />
                      ) : (
                        <SearchIcon />
                      )}
                    </Button>
                  </form>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("共 {value} 个实体", { value: entityTotal })}
                  </p>
                  <div className="mt-3 max-h-[34rem] overflow-y-auto border">
                    {entities.length ? (
                      entities.map((entity) => (
                        <button
                          key={entity.id}
                          type="button"
                          className={cn(
                            "flex w-full items-center justify-between gap-3 border-b px-3 py-3 text-left text-sm last:border-b-0 hover:bg-muted",
                            sourceEntity === entity.canonical_name && "bg-muted"
                          )}
                          onClick={() => {
                            setSourceEntity(entity.canonical_name)
                            setTargetEntity("")
                            void selectEntity(entity.id)
                          }}
                        >
                          <span className="truncate">
                            {entity.canonical_name}
                          </span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {entity.entity_type}
                          </span>
                        </button>
                      ))
                    ) : (
                      <p className="p-3 text-sm text-muted-foreground">
                        {t("暂无实体")}
                      </p>
                    )}
                  </div>
                </aside>

                <main className="min-w-0">
                  <section className="border-b p-4 lg:p-5">
                    <form onSubmit={handleQuery} className="grid gap-3">
                      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem_auto] sm:items-end">
                        <label className="grid gap-1 text-sm font-medium">
                          {t("起点实体")}
                          <Input
                            value={sourceEntity}
                            placeholder={t("输入实体名称")}
                            onChange={(event) =>
                              setSourceEntity(event.target.value)
                            }
                          />
                        </label>
                        <label className="grid gap-1 text-sm font-medium">
                          {t("终点实体（可选）")}
                          <Input
                            value={targetEntity}
                            placeholder={t("留空时查询邻域")}
                            onChange={(event) =>
                              setTargetEntity(event.target.value)
                            }
                          />
                        </label>
                        <label className="grid gap-1 text-sm font-medium">
                          {t("最大图谱跳数")}
                          <Input
                            type="number"
                            min={1}
                            max={targetEntity.trim() ? 8 : 3}
                            value={maxHops}
                            onChange={(event) =>
                              setMaxHops(Number(event.target.value) || 1)
                            }
                          />
                        </label>
                        <div className="flex gap-2">
                          <Button
                            type="submit"
                            disabled={isQuerying || !sourceEntity.trim()}
                          >
                            {isQuerying ? (
                              <LoaderCircleIcon className="animate-spin" />
                            ) : (
                              <GitBranchIcon />
                            )}
                            {t(targetEntity.trim() ? "查找路径" : "查询邻域")}
                          </Button>
                          {queryResult ? (
                            <Button
                              type="button"
                              variant="outline"
                              onClick={showOverview}
                            >
                              {t("全部图谱")}
                            </Button>
                          ) : null}
                        </div>
                      </div>
                      {relationNames.length ? (
                        <details>
                          <summary className="cursor-pointer text-sm font-medium text-muted-foreground">
                            {t("关系类型过滤")}
                          </summary>
                          <div className="mt-3 flex flex-wrap gap-3">
                            {relationNames.map((name) => (
                              <label
                                key={name}
                                className="flex items-center gap-2 text-sm"
                              >
                                <input
                                  type="checkbox"
                                  checked={relationFilters.includes(name)}
                                  onChange={(event) =>
                                    setRelationFilters((current) =>
                                      event.target.checked
                                        ? [...current, name]
                                        : current.filter(
                                            (item) => item !== name
                                          )
                                    )
                                  }
                                />
                                {name}
                              </label>
                            ))}
                          </div>
                        </details>
                      ) : null}
                    </form>
                  </section>

                  {queryError ? (
                    <p className="m-4 border border-destructive/40 p-4 text-sm text-destructive lg:m-5">
                      {queryError}
                    </p>
                  ) : null}
                  {displayResult ? (
                    <div
                      className={cn(
                        "grid min-w-0",
                        showGraphDetail && "lg:grid-cols-[minmax(0,1fr)_22rem]"
                      )}
                    >
                      <section className="min-w-0 border-b lg:border-r lg:border-b-0">
                        {displayResult.truncated ? (
                          <p className="border-b bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                            {t("结果已截断：{reason}，已访问 {value} 个实体", {
                              reason:
                                displayResult.limit_reason === "timeout"
                                  ? t("查询超时")
                                  : t("达到大小限制"),
                              value: displayResult.visited_nodes,
                            })}
                          </p>
                        ) : null}
                        {displayResult.operation === "ambiguous" ? (
                          <div className="border-b p-4">
                            <p className="font-medium text-amber-700 dark:text-amber-300">
                              {t("实体匹配存在歧义")}
                            </p>
                            <p className="mt-1 text-sm text-muted-foreground">
                              {t("请从候选实体中确认后重新查询")}
                            </p>
                          </div>
                        ) : displayResult.operation === "not_found" ? (
                          <p className="border-b p-4 text-sm text-muted-foreground">
                            {t("未找到匹配实体")}
                          </p>
                        ) : displayResult.operation === "path" &&
                          !displayResult.paths.length ? (
                          <p className="border-b p-4 text-sm text-muted-foreground">
                            {t("未找到路径")}
                          </p>
                        ) : null}

                        {displayResult.nodes.length ? (
                          <div className="border-b">
                            <KnowledgeGraphCanvas
                              entities={displayResult.nodes}
                              claims={displayResult.claims}
                              orderedEntityIds={orderedEntityIds}
                              onEntitySelect={(id) => void selectEntity(id)}
                              onClaimSelect={selectClaim}
                            />
                          </div>
                        ) : null}

                        {queryResult ? (
                          <div className="p-4">
                            <h2 className="text-sm font-semibold">
                              {t("实体与逐跳关系")}
                            </h2>
                            <div className="mt-3 flex flex-wrap gap-2">
                              {queryResult.nodes.map((entity) => (
                                <button
                                  key={entity.id}
                                  type="button"
                                  className="rounded-full border px-3 py-1 text-sm hover:bg-muted"
                                  onClick={() => void selectEntity(entity.id)}
                                >
                                  {entity.canonical_name}
                                </button>
                              ))}
                            </div>
                            <div className="mt-4 space-y-2">
                              {queryResult.paths.length
                                ? queryResult.paths.flatMap((path, pathIndex) =>
                                    path.steps.map((step, stepIndex) => (
                                      <button
                                        key={`${pathIndex}-${step.claim_id}-${stepIndex}`}
                                        type="button"
                                        className="grid w-full gap-1 border p-3 text-left text-sm hover:bg-muted"
                                        onClick={() =>
                                          selectClaim(step.claim_id)
                                        }
                                      >
                                        <span className="font-medium">
                                          {graphEntities.get(
                                            step.source_entity_id
                                          )?.canonical_name ??
                                            step.source_entity_id}
                                          {" → "}
                                          {step.predicate}
                                          {" → "}
                                          {graphEntities.get(
                                            step.target_entity_id
                                          )?.canonical_name ??
                                            step.target_entity_id}
                                        </span>
                                        <span className="text-xs text-muted-foreground">
                                          {t(
                                            "方向：{direction} · 支持数：{value}",
                                            {
                                              direction: t(
                                                step.semantic_direction ===
                                                  "forward"
                                                  ? "正向"
                                                  : "反向"
                                              ),
                                              value: step.support_count,
                                            }
                                          )}
                                        </span>
                                        {!step.evidence_ids.length ? (
                                          <span className="text-xs text-destructive">
                                            {t(
                                              "此关系没有证据，不能视为已证实"
                                            )}
                                          </span>
                                        ) : null}
                                      </button>
                                    ))
                                  )
                                : queryResult.claims.map((claim) => (
                                    <button
                                      key={claim.id}
                                      type="button"
                                      className="grid w-full gap-1 border p-3 text-left text-sm hover:bg-muted"
                                      onClick={() => selectClaim(claim.id)}
                                    >
                                      <span className="font-medium">
                                        {graphEntities.get(
                                          claim.subject_entity_id
                                        )?.canonical_name ??
                                          claim.subject_entity_id}
                                        {" → "}
                                        {claim.predicate}
                                        {" → "}
                                        {claim.object_entity_id
                                          ? (graphEntities.get(
                                              claim.object_entity_id
                                            )?.canonical_name ??
                                            claim.object_entity_id)
                                          : String(claim.object_value ?? "—")}
                                      </span>
                                      <span className="text-xs text-muted-foreground">
                                        {t("支持数：{value}", {
                                          value: claim.support_count,
                                        })}
                                      </span>
                                    </button>
                                  ))}
                            </div>
                          </div>
                        ) : null}
                      </section>

                      {showGraphDetail ? (
                        <aside className="relative min-w-0 border-t p-4 lg:border-t-0 lg:border-l">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute top-2 right-2"
                            aria-label={t("关闭")}
                            onClick={clearGraphSelection}
                          >
                            <XIcon />
                          </Button>
                          {isEntityLoading ? (
                            <p className="flex items-center gap-2 text-sm text-muted-foreground">
                              <LoaderCircleIcon className="size-4 animate-spin" />
                              {t("正在加载实体详情")}
                            </p>
                          ) : selectedClaim ? (
                            <div className="pr-8">
                              <h2 className="font-semibold">
                                {selectedClaim.predicate}
                              </h2>
                              <p className="mt-2 text-xs text-muted-foreground">
                                {t("质量 {quality} · 支持数 {value}", {
                                  quality: selectedClaim.quality_score,
                                  value: selectedClaim.support_count,
                                })}
                              </p>
                              <h3 className="mt-5 text-sm font-semibold">
                                {t("逐边证据")}
                              </h3>
                              {selectedEvidence.length ? (
                                <div className="mt-2 space-y-3">
                                  {selectedEvidence.map((evidence) => (
                                    <blockquote
                                      key={evidence.id}
                                      className="border-l-2 pl-3 text-sm"
                                    >
                                      <p className="whitespace-pre-wrap">
                                        {evidence.quote}
                                      </p>
                                      <footer className="mt-2 text-xs text-muted-foreground">
                                        {t(
                                          "{document} · 分段 {chunk} · 字符 {start}-{end}",
                                          {
                                            document:
                                              evidence.document_filename,
                                            chunk: evidence.chunk_id,
                                            start: evidence.start_offset,
                                            end: evidence.end_offset,
                                          }
                                        )}
                                      </footer>
                                    </blockquote>
                                  ))}
                                </div>
                              ) : (
                                <p className="mt-2 text-sm text-destructive">
                                  {t("此关系没有证据，不能视为已证实")}
                                </p>
                              )}
                            </div>
                          ) : selectedEntity ? (
                            <div className="pr-8">
                              <h2 className="font-semibold">
                                {selectedEntity.canonical_name}
                              </h2>
                              <p className="mt-1 text-sm text-muted-foreground">
                                {selectedEntity.entity_type}
                              </p>
                              {selectedEntity.aliases.length ? (
                                <p className="mt-3 text-sm">
                                  {t("别名：{value}", {
                                    value: selectedEntity.aliases.join(", "),
                                  })}
                                </p>
                              ) : null}
                              <h3 className="mt-5 text-sm font-semibold">
                                {t("实体知识页")}
                              </h3>
                              <p className="mt-2 text-sm whitespace-pre-wrap text-muted-foreground">
                                {selectedEntity.profile_markdown ||
                                  t("暂无实体知识页")}
                              </p>
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              {t("选择实体或关系查看详情与证据")}
                            </p>
                          )}
                        </aside>
                      ) : null}
                    </div>
                  ) : (
                    <div className="flex min-h-64 items-center justify-center p-6 text-center text-sm text-muted-foreground">
                      {graphBusy || isOverviewLoading
                        ? t(
                            "正在自动抽取已有文件；完成后将在这里显示实体关系图"
                          )
                        : t("输入起点探索邻域，或同时输入终点查找路径")}
                    </div>
                  )}
                </main>
              </div>
            </>
          )}
        </div>
      ) : null}

      {view === "reviews" ? (
        <div className="grid min-w-0 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <section className="border-b lg:border-r lg:border-b-0">
            <div className="border-b p-4 text-sm font-medium">
              {t("待审核 {value} 条", { value: reviewTotal })}
            </div>
            {reviews.length ? (
              reviews.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    "w-full border-b p-3 text-left text-sm hover:bg-muted",
                    item.id === selectedReviewId && "bg-muted"
                  )}
                  onClick={() => {
                    setSelectedReviewId(item.id)
                    setMergeCandidates([])
                    setMergeTargetId("")
                    setSplitName("")
                    setSplitMentionIds([])
                    setSplitClaimIds([])
                  }}
                >
                  <span className="block font-medium">
                    {reviewKindLabel(item.kind, t)}
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted-foreground">
                    {item.id}
                  </span>
                </button>
              ))
            ) : (
              <p className="p-4 text-sm text-muted-foreground">
                {t("暂无待审核项")}
              </p>
            )}
          </section>

          <section className="min-w-0 p-4 lg:p-5">
            {selectedReview ? (
              <div className="max-w-3xl">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="font-semibold">
                      {reviewKindLabel(selectedReview.kind, t)}
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t("修订 {revision} · {time}", {
                        revision: selectedReview.revision_id,
                        time: formatDateTime(selectedReview.created_at, locale),
                      })}
                    </p>
                  </div>
                  {!canEdit ? (
                    <span className="text-xs text-muted-foreground">
                      {t("只读审核详情")}
                    </span>
                  ) : null}
                </div>
                <pre className="mt-4 max-h-72 overflow-auto border bg-muted/30 p-3 text-xs whitespace-pre-wrap">
                  {JSON.stringify(selectedReview.payload, null, 2)}
                </pre>

                {canEdit && reviewClaimIds.length ? (
                  <div className="mt-4 flex flex-wrap gap-2 border-t pt-4">
                    <Button
                      type="button"
                      disabled={busyAction !== null || graphBusy}
                      onClick={() => void handleReviewDecision("approve_claim")}
                    >
                      {t("批准关系")}
                    </Button>
                    <Button
                      type="button"
                      variant="destructive"
                      disabled={busyAction !== null || graphBusy}
                      onClick={() => void handleReviewDecision("reject_claim")}
                    >
                      {t("拒绝关系")}
                    </Button>
                  </div>
                ) : null}

                {canEdit && reviewCanResolveEntity ? (
                  <div className="mt-5 grid items-start gap-4 border-t pt-5 xl:grid-cols-2">
                    <section className="rounded-lg border bg-muted/15 p-4">
                      <h3 className="font-semibold">{t("合并实体")}</h3>
                      <form
                        className="mt-4 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]"
                        onSubmit={handleMergeSearch}
                      >
                        <Input
                          aria-label={t("搜索合并目标")}
                          value={mergeSearch}
                          onChange={(event) =>
                            setMergeSearch(event.target.value)
                          }
                        />
                        <Button
                          type="submit"
                          variant="outline"
                          disabled={busyAction !== null || !mergeSearch.trim()}
                        >
                          {t("搜索")}
                        </Button>
                      </form>
                      {mergeCandidates.length ? (
                        <div className="mt-3 max-h-40 overflow-auto rounded-md border bg-background">
                          {mergeCandidates.map((entity) => (
                            <label
                              key={entity.id}
                              className="flex items-center gap-2 border-b p-3 text-sm last:border-b-0 hover:bg-muted"
                            >
                              <input
                                type="radio"
                                name="merge-target"
                                checked={mergeTargetId === entity.id}
                                onChange={() => setMergeTargetId(entity.id)}
                              />
                              {entity.canonical_name}
                            </label>
                          ))}
                        </div>
                      ) : null}
                      <Button
                        type="button"
                        className="mt-4 w-fit"
                        disabled={
                          busyAction !== null || graphBusy || !mergeTargetId
                        }
                        onClick={() =>
                          void handleReviewDecision("merge_entities")
                        }
                      >
                        {t("确认合并")}
                      </Button>
                    </section>

                    <section className="rounded-lg border bg-muted/15 p-4">
                      <h3 className="font-semibold">{t("拆分实体")}</h3>
                      <div className="mt-4 grid gap-4">
                        <label className="grid gap-1 text-sm">
                          {t("新实体名称")}
                          <Input
                            value={splitName}
                            onChange={(event) =>
                              setSplitName(event.target.value)
                            }
                          />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t("实体类型")}
                          <FilterDropdown
                            ariaLabel={t("实体类型")}
                            value={splitType}
                            options={entityTypeNames.map((name) => ({
                              value: name,
                              label: name,
                            }))}
                            onChange={setSplitType}
                          />
                        </label>
                        {[...reviewMentionIds, ...reviewClaimIds].length ? (
                          <fieldset className="border p-3">
                            <legend className="px-1 text-sm font-medium">
                              {t("选择要移动的记录")}
                            </legend>
                            {[...reviewMentionIds, ...reviewClaimIds].map(
                              (id) => {
                                const mention = reviewMentionIds.includes(id)
                                const selected = mention
                                  ? splitMentionIds.includes(id)
                                  : splitClaimIds.includes(id)
                                return (
                                  <label
                                    key={`${mention ? "mention" : "claim"}-${id}`}
                                    className="mt-2 flex items-center gap-2 text-sm"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={selected}
                                      onChange={(event) => {
                                        const setter = mention
                                          ? setSplitMentionIds
                                          : setSplitClaimIds
                                        setter((current) =>
                                          event.target.checked
                                            ? [...current, id]
                                            : current.filter(
                                                (item) => item !== id
                                              )
                                        )
                                      }}
                                    />
                                    {mention ? t("提及") : t("关系")} · {id}
                                  </label>
                                )
                              }
                            )}
                          </fieldset>
                        ) : (
                          <p className="text-sm text-muted-foreground">
                            {t("此审核项没有可拆分记录")}
                          </p>
                        )}
                        <Button
                          type="button"
                          className="w-fit"
                          disabled={
                            busyAction !== null ||
                            graphBusy ||
                            !splitName.trim() ||
                            !splitType ||
                            (!splitMentionIds.length && !splitClaimIds.length)
                          }
                          onClick={() =>
                            void handleReviewDecision("split_entity")
                          }
                        >
                          {t("确认拆分")}
                        </Button>
                      </div>
                    </section>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("选择审核项查看详情")}
              </p>
            )}
          </section>
        </div>
      ) : null}

      {view === "settings" ? (
        <div className="grid gap-0 lg:grid-cols-2">
          <section className="border-b p-4 lg:border-r lg:p-5">
            <h2 className="font-semibold">{t("图谱设置")}</h2>
            <div className="mt-4 grid gap-4">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={formEnabled}
                  disabled={!canEdit || busyAction !== null}
                  onChange={(event) => setFormEnabled(event.target.checked)}
                />
                {t("启用知识关联")}
              </label>
              {canEdit ? (
                <Button
                  type="button"
                  className="w-fit"
                  disabled={busyAction !== null}
                  onClick={() => void handleSettingsSave()}
                >
                  {busyAction === "settings" ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : null}
                  {t("保存图谱设置")}
                </Button>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("你只有查看权限")}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {t("关闭知识关联不会删除已有数据")}
              </p>
            </div>
          </section>

          <section className="border-b p-4 lg:p-5">
            <h2 className="font-semibold">{t("自动抽取与高级设置")}</h2>
            <p className="mt-4 text-sm text-muted-foreground">
              {t(
                "启用后，上传文件会在索引完成后自动抽取实体和关系；首次启用会自动处理已有文件"
              )}
            </p>
            {canEdit ? (
              <Button
                type="button"
                className="mt-4"
                disabled={busyAction !== null || graphBusy || !settings.enabled}
                onClick={() => void handleRebuild()}
              >
                {busyAction === "rebuild" ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <RefreshCwIcon />
                )}
                {t("重新抽取全部文件")}
              </Button>
            ) : null}
            <details className="mt-5 border p-3">
              <summary className="cursor-pointer text-sm font-medium">
                {t("自定义 Schema（高级）")}
              </summary>
              <p className="mt-3 text-xs text-muted-foreground">
                {t("默认使用内置 Schema；仅在需要限定实体类型和关系时修改")}
              </p>
              <label className="mt-3 grid gap-1 text-sm font-medium">
                {t("Schema JSON")}
                <textarea
                  className={`${TEXTAREA_CLASS} min-h-72 font-mono text-xs`}
                  value={schemaText}
                  spellCheck={false}
                  placeholder={t("留空使用内置 Schema")}
                  disabled={!canEdit || busyAction !== null}
                  onChange={(event) => setSchemaText(event.target.value)}
                />
              </label>
              {schema ? (
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("Schema 版本 {version} · {status}", {
                    version: schema.version,
                    status: schema.status,
                  })}
                </p>
              ) : null}
              {canEdit ? (
                <Button
                  type="button"
                  variant="outline"
                  className="mt-4"
                  disabled={busyAction !== null || !schemaText.trim()}
                  onClick={() => void handleSchemaSave()}
                >
                  <FileJsonIcon />
                  {t("保存 Schema 草稿")}
                </Button>
              ) : null}
            </details>
          </section>

          <section className="p-4 lg:col-span-2 lg:p-5">
            <h2 className="font-semibold">{t("结构化记录导入")}</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {t("支持 JSON 或 JSONL，每条记录必须包含可验证证据")}
            </p>
            {canEdit ? (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <Input
                  type="file"
                  className="max-w-md"
                  aria-label={t("选择图谱导入文件")}
                  accept=".json,.jsonl,application/json,application/x-ndjson"
                  disabled={busyAction !== null}
                  onChange={(event) =>
                    setImportFile(event.target.files?.[0] ?? null)
                  }
                />
                <Button
                  type="button"
                  disabled={
                    busyAction !== null ||
                    graphBusy ||
                    !settings.enabled ||
                    !importFile
                  }
                  onClick={() => void handleImport()}
                >
                  {busyAction === "import" ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : (
                    <UploadIcon />
                  )}
                  {t("导入结构化记录")}
                </Button>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  )
}

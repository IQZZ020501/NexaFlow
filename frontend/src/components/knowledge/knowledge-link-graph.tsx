"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import {
  FileQuestionIcon,
  FileTextIcon,
  LoaderCircleIcon,
  NetworkIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react"

import { FilterDropdown } from "@/components/app/filter-dropdown"
import { KnowledgeGraphCanvas } from "@/components/knowledge/knowledge-graph-canvas"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import {
  getKnowledgeLinkGraph,
  type KnowledgeLinkGraph,
  type KnowledgeLinkGraphEdge,
  type KnowledgeLinkGraphNode,
} from "@/lib/api/knowledge"
import { getErrorMessage } from "@/lib/errors"
import { cn } from "@/lib/utils"

export type LinkGraphDirection = "both" | "incoming" | "outgoing"

export type LinkGraphFilters = {
  query: string
  includeUnresolved: boolean
  includeOrphans: boolean
  rootId: string | null
  depth: number
  direction: LinkGraphDirection
}

export function filterKnowledgeLinkGraph(
  graph: KnowledgeLinkGraph,
  filters: LinkGraphFilters
): { nodes: KnowledgeLinkGraphNode[]; edges: KnowledgeLinkGraphEdge[] } {
  const query = filters.query.trim().toLocaleLowerCase()
  const candidates = new Set(
    graph.nodes
      .filter((node) => filters.includeUnresolved || node.kind === "document")
      .filter(
        (node) =>
          filters.includeOrphans ||
          node.degree > 0 ||
          node.id === filters.rootId
      )
      .map((node) => node.id)
  )
  let visibleIds = candidates

  if (filters.rootId && candidates.has(filters.rootId)) {
    visibleIds = new Set([filters.rootId])
    let frontier = new Set([filters.rootId])
    for (let level = 0; level < Math.max(1, filters.depth); level += 1) {
      const next = new Set<string>()
      for (const edge of graph.edges) {
        if (!candidates.has(edge.source) || !candidates.has(edge.target))
          continue
        if (
          filters.direction !== "incoming" &&
          frontier.has(edge.source) &&
          !visibleIds.has(edge.target)
        ) {
          next.add(edge.target)
        }
        if (
          filters.direction !== "outgoing" &&
          frontier.has(edge.target) &&
          !visibleIds.has(edge.source)
        ) {
          next.add(edge.source)
        }
      }
      if (!next.size) break
      next.forEach((id) => visibleIds.add(id))
      frontier = next
    }
  }

  if (query) {
    visibleIds = new Set(
      graph.nodes
        .filter((node) => visibleIds.has(node.id))
        .filter((node) =>
          `${node.label}\n${node.filename}`.toLocaleLowerCase().includes(query)
        )
        .map((node) => node.id)
    )
  }

  return {
    nodes: graph.nodes.filter((node) => visibleIds.has(node.id)),
    edges: graph.edges.filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)
    ),
  }
}

function resolveHighlightedNodeIds(
  edges: KnowledgeLinkGraphEdge[],
  visibleNodeIds: ReadonlySet<string>,
  selectedNodeId: string | null
) {
  if (!selectedNodeId || !visibleNodeIds.has(selectedNodeId)) {
    return new Set<string>()
  }
  const ids = new Set([selectedNodeId])
  for (const edge of edges) {
    if (edge.source === selectedNodeId && visibleNodeIds.has(edge.target)) {
      ids.add(edge.target)
    }
    if (edge.target === selectedNodeId && visibleNodeIds.has(edge.source)) {
      ids.add(edge.source)
    }
  }
  return ids
}

export function KnowledgeLinkGraph({
  token,
  workspaceId,
  knowledgeBaseId,
  reportError,
}: {
  token: string
  workspaceId: string
  knowledgeBaseId: string
  reportError: (error: unknown) => void
}) {
  const { t } = useLanguage()
  const router = useRouter()
  const [graph, setGraph] = React.useState<KnowledgeLinkGraph | null>(null)
  const [isLoading, setIsLoading] = React.useState(true)
  const [isRefreshing, setIsRefreshing] = React.useState(false)
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [query, setQuery] = React.useState("")
  const [mode, setMode] = React.useState<"global" | "local">("global")
  const [direction, setDirection] = React.useState<LinkGraphDirection>("both")
  const [depth, setDepth] = React.useState(2)
  const [includeUnresolved, setIncludeUnresolved] = React.useState(true)
  const [includeOrphans, setIncludeOrphans] = React.useState(true)
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(
    null
  )
  const [rootId, setRootId] = React.useState<string | null>(null)

  const loadGraph = React.useCallback(
    async (signal?: AbortSignal, quiet = false) => {
      if (!quiet) setIsRefreshing(true)
      try {
        const next = await getKnowledgeLinkGraph(
          token,
          workspaceId,
          knowledgeBaseId,
          signal
        )
        if (signal?.aborted) return
        setGraph((current) =>
          current?.revision === next.revision ? current : next
        )
        setLoadError(null)
        setSelectedNodeId((current) =>
          next.nodes.some((node) => node.id === current)
            ? current
            : (next.nodes[0]?.id ?? null)
        )
        setRootId((current) =>
          next.nodes.some((node) => node.id === current) ? current : null
        )
      } catch (error) {
        if (signal?.aborted) return
        setLoadError(getErrorMessage(error, t))
        if (!quiet) reportError(error)
      } finally {
        if (!signal?.aborted) {
          setIsLoading(false)
          if (!quiet) setIsRefreshing(false)
        }
      }
    },
    [knowledgeBaseId, reportError, t, token, workspaceId]
  )

  React.useEffect(() => {
    const controller = new AbortController()
    const frame = window.requestAnimationFrame(() => {
      void loadGraph(controller.signal)
    })
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible")
        void loadGraph(undefined, true)
    }, 15_000)
    return () => {
      controller.abort()
      window.cancelAnimationFrame(frame)
      window.clearInterval(interval)
    }
  }, [loadGraph])

  const root = mode === "local" ? rootId : null
  const filtered = React.useMemo(
    () =>
      graph
        ? filterKnowledgeLinkGraph(graph, {
            query,
            includeUnresolved,
            includeOrphans,
            rootId: root,
            depth,
            direction,
          })
        : { nodes: [], edges: [] },
    [depth, direction, graph, includeOrphans, includeUnresolved, query, root]
  )
  const selectedNode =
    graph?.nodes.find((node) => node.id === selectedNodeId) ?? null
  const selectedEdges = graph?.edges.filter(
    (edge) => edge.source === selectedNodeId || edge.target === selectedNodeId
  )
  const visibleNodeIds = React.useMemo(
    () => new Set(filtered.nodes.map((node) => node.id)),
    [filtered.nodes]
  )
  const highlightedNodeIds = React.useMemo(
    () =>
      resolveHighlightedNodeIds(filtered.edges, visibleNodeIds, selectedNodeId),
    [filtered.edges, selectedNodeId, visibleNodeIds]
  )

  function openNode(nodeId: string) {
    const node = graph?.nodes.find((item) => item.id === nodeId)
    if (node?.document_id) {
      router.push(
        `/app/knowledge/${knowledgeBaseId}/documents/${node.document_id}`
      )
    }
  }

  if (isLoading) {
    return (
      <div className="flex min-h-72 items-center justify-center" role="status">
        <LoaderCircleIcon className="size-5 animate-spin" />
        <span className="ml-2 text-sm text-muted-foreground">
          {t("正在加载关系图谱")}
        </span>
      </div>
    )
  }

  if (!graph) {
    return (
      <div className="m-4 border border-destructive/40 p-4 text-sm text-destructive">
        {loadError ?? t("关系图谱加载失败")}
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-col">
      <section className="border-b px-4 py-4 lg:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-semibold">
              <NetworkIcon className="size-5" />
              {t("关系图谱")}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("基于 Markdown 显式链接生成，不使用 AI 或语义向量")}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isRefreshing}
            onClick={() => void loadGraph()}
          >
            <RefreshCwIcon className={cn(isRefreshing && "animate-spin")} />
            {t("刷新")}
          </Button>
        </div>
        <dl className="mt-4 grid gap-px overflow-hidden border bg-border text-sm sm:grid-cols-3">
          {[
            [t("文档数"), graph.document_count],
            [t("链接数"), graph.edge_count],
            [t("未解析链接"), graph.unresolved_count],
          ].map(([label, value]) => (
            <div key={String(label)} className="bg-background p-3">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-1 font-medium">{value}</dd>
            </div>
          ))}
        </dl>
        {graph.truncated ? (
          <p className="mt-2 text-xs text-amber-600">
            {t("图谱过大，当前仅显示部分节点和链接")}
          </p>
        ) : null}
        {loadError ? (
          <p className="mt-2 text-xs text-destructive">{loadError}</p>
        ) : null}
      </section>

      <section className="grid gap-3 border-b p-3 lg:grid-cols-[minmax(12rem,1fr)_10rem_10rem_7rem_auto_auto] lg:items-center lg:px-5">
        <label className="relative block">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-8"
            aria-label={t("搜索图谱文档")}
            placeholder={t("搜索文件名")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <FilterDropdown
          ariaLabel={t("图谱范围")}
          value={mode}
          options={[
            { value: "global", label: t("全局图谱") },
            { value: "local", label: t("局部图谱") },
          ]}
          onChange={(value) => {
            const next = value as "global" | "local"
            setMode(next)
            if (next === "local" && !rootId) {
              setRootId(selectedNodeId ?? graph.nodes[0]?.id ?? null)
            }
          }}
        />
        <FilterDropdown
          ariaLabel={t("链接方向")}
          value={direction}
          disabled={mode === "global"}
          options={[
            { value: "both", label: t("双向") },
            { value: "incoming", label: t("仅入链") },
            { value: "outgoing", label: t("仅出链") },
          ]}
          onChange={(value) => setDirection(value as LinkGraphDirection)}
        />
        <FilterDropdown
          ariaLabel={t("遍历深度")}
          value={String(depth)}
          disabled={mode === "global"}
          options={[1, 2, 3, 4].map((value) => ({
            value: String(value),
            label: t("深度 {value}", { value }),
          }))}
          onChange={(value) => setDepth(Number(value))}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={includeUnresolved}
            onChange={(event) => setIncludeUnresolved(event.target.checked)}
          />
          {t("显示未解析链接")}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={includeOrphans}
            onChange={(event) => setIncludeOrphans(event.target.checked)}
          />
          {t("显示孤立文档")}
        </label>
      </section>

      <div className="grid min-h-0 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <main className="min-w-0">
          {filtered.nodes.length ? (
            <KnowledgeGraphCanvas
              nodes={filtered.nodes}
              edges={filtered.edges}
              selectedNodeId={selectedNodeId}
              highlightedNodeIds={highlightedNodeIds}
              onNodeSelect={setSelectedNodeId}
              onNodeOpen={openNode}
            />
          ) : (
            <div className="flex min-h-[36rem] items-center justify-center bg-muted/15 px-6 text-center text-sm text-muted-foreground">
              {t("没有符合当前筛选条件的节点")}
            </div>
          )}
        </main>

        <aside className="min-h-0 border-t p-4 lg:border-t-0 lg:border-l">
          {selectedNode ? (
            <div className="grid gap-4">
              <div className="flex min-w-0 items-start gap-3">
                {selectedNode.kind === "document" ? (
                  <FileTextIcon className="mt-0.5 size-5 shrink-0 text-primary" />
                ) : (
                  <FileQuestionIcon className="mt-0.5 size-5 shrink-0 text-destructive" />
                )}
                <div className="min-w-0">
                  <h2 className="font-semibold break-words">
                    {selectedNode.filename}
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t(
                      selectedNode.kind === "document"
                        ? "已解析文档节点"
                        : "尚未创建的链接目标"
                    )}
                  </p>
                </div>
              </div>
              <dl className="grid grid-cols-3 gap-px overflow-hidden border bg-border text-center text-xs">
                {[
                  [t("入链"), selectedNode.incoming],
                  [t("出链"), selectedNode.outgoing],
                  [t("总连接"), selectedNode.degree],
                ].map(([label, value]) => (
                  <div key={String(label)} className="bg-background p-2">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="mt-1 font-medium">{value}</dd>
                  </div>
                ))}
              </dl>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setMode("local")
                    setRootId(selectedNode.id)
                  }}
                >
                  {t("设为局部图中心")}
                </Button>
                {selectedNode.document_id ? (
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => openNode(selectedNode.id)}
                  >
                    {t("打开文档")}
                  </Button>
                ) : null}
              </div>
              <div>
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("相邻链接")}
                </h3>
                <div className="mt-2 max-h-80 overflow-y-auto border">
                  {selectedEdges?.length ? (
                    selectedEdges.map((edge) => {
                      const neighborId =
                        edge.source === selectedNode.id
                          ? edge.target
                          : edge.source
                      const neighbor = graph.nodes.find(
                        (node) => node.id === neighborId
                      )
                      return (
                        <button
                          key={edge.id}
                          type="button"
                          className="flex w-full items-center justify-between gap-3 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted"
                          onClick={() => setSelectedNodeId(neighborId)}
                        >
                          <span className="truncate">
                            {edge.source === selectedNode.id ? "→" : "←"}{" "}
                            {neighbor?.filename ?? edge.target_label}
                          </span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            ×{edge.count}
                          </span>
                        </button>
                      )
                    })
                  ) : (
                    <p className="p-3 text-sm text-muted-foreground">
                      {t("暂无相邻链接")}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("选择节点查看链接详情")}
            </p>
          )}
        </aside>
      </div>
    </div>
  )
}

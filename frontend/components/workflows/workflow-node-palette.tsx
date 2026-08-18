"use client"

import * as React from "react"
import {
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react"
import { Popover as PopoverPrimitive, Tabs as TabsPrimitive } from "radix-ui"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { TFunction, TranslationKey } from "@/i18n"
import type { Agent } from "@/lib/api/agents"
import type { ToolDetail } from "@/lib/api/tools"
import type { WorkflowGraph, WorkflowNodeType } from "@/lib/api/workflows"
import {
  toolDisplayDescription,
  toolDisplayName,
  toolSourceDisplayName,
} from "@/lib/tool-display"
import {
  WORKFLOW_BASIC_NODE_TYPES,
  WORKFLOW_NODE_PRESETS,
  workflowNodeLabel,
} from "@/lib/workflows/graph"

import { NODE_ICONS } from "./workflow-node"

type WorkflowNodePaletteProps = {
  tools: ToolDetail[]
  agents: Agent[]
  graph: WorkflowGraph
  onAdd: (
    type: WorkflowNodeType,
    title?: string,
    config?: Record<string, unknown>
  ) => void
  t: TFunction
  readOnly?: boolean
  disabled?: boolean
  isToolsLoading?: boolean
  toolsError?: string | null
  onRetryTools?: () => void
}

function publishedVersionId(agent: Agent) {
  return agent.current_published_version_id ?? null
}

function workflowToolDisabledReason(tool: ToolDetail): TranslationKey | null {
  if (!tool.can_use) return "没有使用权限"
  if (
    tool.status !== "active" ||
    tool.availability !== "available" ||
    !tool.current_version_id
  ) {
    return "工具当前不可用"
  }
  if (!tool.workflow_callable) return "不支持工作流调用"
  if (tool.approval === "each_call") return "需要逐次审批"
  if (tool.approval !== "auto") return "工具调用已禁用"
  return null
}

export function WorkflowNodePalette({
  tools,
  agents,
  graph,
  onAdd,
  t,
  readOnly = false,
  disabled = false,
  isToolsLoading = false,
  toolsError = null,
  onRetryTools,
}: WorkflowNodePaletteProps) {
  const [open, setOpen] = React.useState(false)
  const [tab, setTab] = React.useState("basic")
  const [search, setSearch] = React.useState("")

  const query = search.trim().toLowerCase()
  const visibleTools = tools.filter(
    (tool) =>
      tool.can_view &&
      tool.function_name !== "inline_python" &&
      (!query ||
        `${toolDisplayName(tool, t)} ${toolDisplayDescription(tool, t)} ${toolSourceDisplayName(tool.source, t)}`
          .toLowerCase()
          .includes(query))
  )
  const inlinePythonMatches =
    !query ||
    `${t("Python 代码")} ${t("在工作流沙箱中运行 Python 代码。")}`
      .toLowerCase()
      .includes(query)
  const availableAgents = agents.filter(
    (agent) =>
      agent.app_type === "agent" &&
      agent.status === "active" &&
      agent.published &&
      Boolean(publishedVersionId(agent)) &&
      (!query ||
        `${agent.name} ${agent.description}`.toLowerCase().includes(query))
  )
  const startNodeId =
    graph.nodes.find((node) => node.data.type === "start")?.id ?? "start"
  const InlinePythonIcon = NODE_ICONS.code

  function add(
    type: WorkflowNodeType,
    title?: string,
    config?: Record<string, unknown>
  ) {
    if (disabled) return
    onAdd(type, title, config)
    setOpen(false)
  }

  if (readOnly) return null

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (nextOpen) {
          setTab("basic")
          setSearch("")
        }
      }}
    >
      <PopoverPrimitive.Trigger asChild>
        <Button
          type="button"
          variant="outline"
          aria-label={t("添加节点")}
          disabled={disabled}
        >
          <PlusIcon />
          <span className="hidden sm:inline">{t("添加节点")}</span>
        </Button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="end"
          sideOffset={8}
          collisionPadding={12}
          className="z-50 flex h-[32rem] max-h-[calc(100svh-2rem)] w-[min(26rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-xl outline-none"
        >
          <div className="border-b px-4 py-3">
            <p className="text-sm font-semibold">{t("节点库")}</p>
          </div>
          <TabsPrimitive.Root
            value={tab}
            onValueChange={setTab}
            className="flex min-h-0 flex-1 flex-col"
          >
            <TabsPrimitive.List className="grid grid-cols-3 border-b bg-muted/30 p-1">
              <TabsPrimitive.Trigger
                value="basic"
                className="rounded-md px-2 py-2 text-xs font-medium text-muted-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-xs"
              >
                {t("基础节点")}
              </TabsPrimitive.Trigger>
              <TabsPrimitive.Trigger
                value="tools"
                className="rounded-md px-2 py-2 text-xs font-medium text-muted-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-xs"
              >
                {t("工具")}
              </TabsPrimitive.Trigger>
              <TabsPrimitive.Trigger
                value="agents"
                className="rounded-md px-2 py-2 text-xs font-medium text-muted-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-xs"
              >
                {t("Agent")}
              </TabsPrimitive.Trigger>
            </TabsPrimitive.List>

            {tab !== "basic" ? (
              <div className="border-b p-3">
                <div className="relative">
                  <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    role="searchbox"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    className="h-8 bg-background pl-8 text-xs"
                    placeholder={t("按名称搜索")}
                  />
                </div>
              </div>
            ) : null}

            <TabsPrimitive.Content
              value="basic"
              className="min-h-0 flex-1 overflow-y-auto p-3 outline-none"
            >
              <div className="grid grid-cols-2 gap-2">
                {WORKFLOW_BASIC_NODE_TYPES.map((type) => {
                  const Icon = NODE_ICONS[type]
                  const disabled =
                    ["start", "end"].includes(type) &&
                    graph.nodes.some((node) => node.data.type === type)
                  return (
                    <button
                      key={type}
                      type="button"
                      disabled={disabled}
                      className="flex min-h-10 items-center gap-2 rounded-md border bg-background px-2.5 py-2 text-left text-xs font-medium shadow-xs transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                      onClick={() => add(type)}
                    >
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">
                        {workflowNodeLabel(type, t)}
                      </span>
                    </button>
                  )
                })}
                {WORKFLOW_NODE_PRESETS.map((preset) => {
                  const Icon = NODE_ICONS[preset.type]
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      className="flex min-h-10 items-center gap-2 rounded-md border bg-background px-2.5 py-2 text-left text-xs font-medium shadow-xs transition-colors hover:bg-muted"
                      onClick={() =>
                        add(
                          preset.type,
                          t(preset.label),
                          preset.config(t, startNodeId)
                        )
                      }
                    >
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">{t(preset.label)}</span>
                    </button>
                  )
                })}
              </div>
            </TabsPrimitive.Content>

            <TabsPrimitive.Content
              value="tools"
              className="min-h-0 flex-1 overflow-y-auto p-3 outline-none"
            >
              {toolsError ? (
                <div
                  role="alert"
                  className="mb-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3"
                >
                  <p className="text-sm font-medium">{t("工具加载失败")}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {toolsError}
                  </p>
                  {onRetryTools ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="mt-3"
                      disabled={isToolsLoading}
                      onClick={onRetryTools}
                    >
                      {isToolsLoading ? (
                        <LoaderCircleIcon className="animate-spin" />
                      ) : (
                        <RefreshCwIcon />
                      )}
                      {t("重试")}
                    </Button>
                  ) : null}
                </div>
              ) : null}
              {isToolsLoading && !visibleTools.length ? (
                <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
                  <LoaderCircleIcon className="size-4 animate-spin" />
                  {t("正在加载工具")}
                </div>
              ) : inlinePythonMatches || visibleTools.length ? (
                <div className="space-y-2">
                  {inlinePythonMatches ? (
                    <button
                      type="button"
                      aria-label={t("Python 代码")}
                      className="flex w-full items-start gap-3 rounded-lg border bg-background p-3 text-left transition-colors hover:bg-muted"
                      onClick={() => add("code")}
                    >
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
                        <InlinePythonIcon className="size-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {t("Python 代码")}
                        </span>
                        <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-muted-foreground">
                          {t("在工作流沙箱中运行 Python 代码。")}
                        </span>
                      </span>
                    </button>
                  ) : null}
                  {visibleTools.map((tool) => {
                    const Icon = NODE_ICONS.tool
                    const disabledReason = workflowToolDisabledReason(tool)
                    return (
                      <button
                        key={tool.id}
                        type="button"
                        aria-label={toolDisplayName(tool, t)}
                        title={disabledReason ? t(disabledReason) : undefined}
                        disabled={Boolean(disabledReason)}
                        className="flex w-full items-start gap-3 rounded-lg border bg-background p-3 text-left transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={() => {
                          if (disabledReason || !tool.current_version_id) return
                          add("tool", toolDisplayName(tool, t), {
                            tool: {
                              tool_id: tool.id,
                              version_id: tool.current_version_id,
                            },
                            arguments: {},
                          })
                        }}
                      >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
                          <Icon className="size-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="truncate text-sm font-medium">
                              {toolDisplayName(tool, t)}
                            </span>
                            <Badge
                              variant="outline"
                              className="shrink-0 text-[10px]"
                            >
                              {toolSourceDisplayName(tool.source, t)}
                            </Badge>
                          </span>
                          {toolDisplayDescription(tool, t) ? (
                            <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-muted-foreground">
                              {toolDisplayDescription(tool, t)}
                            </span>
                          ) : null}
                          {disabledReason ? (
                            <span className="mt-1 block text-xs font-medium text-amber-700 dark:text-amber-400">
                              {t(disabledReason)}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ) : toolsError ? null : (
                <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                  {t("暂无可用工具")}
                </div>
              )}
            </TabsPrimitive.Content>

            <TabsPrimitive.Content
              value="agents"
              className="min-h-0 flex-1 overflow-y-auto p-3 outline-none"
            >
              {availableAgents.length ? (
                <div className="space-y-2">
                  {availableAgents.map((agent) => {
                    const Icon = NODE_ICONS.agent
                    const versionId = publishedVersionId(agent)
                    return (
                      <button
                        key={agent.id}
                        type="button"
                        aria-label={agent.name}
                        className="flex w-full items-start gap-3 rounded-lg border bg-background p-3 text-left transition-colors hover:bg-muted"
                        onClick={() =>
                          add("agent", agent.name, {
                            agent_id: agent.id,
                            agent_version_id: versionId,
                            input: `{{${startNodeId}.question}}`,
                          })
                        }
                      >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sky-500/10 text-sky-600 dark:text-sky-400">
                          <Icon className="size-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">
                            {agent.name}
                          </span>
                          {agent.description ? (
                            <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-muted-foreground">
                              {agent.description}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                  {t("暂无可用 Agent")}
                </div>
              )}
            </TabsPrimitive.Content>
          </TabsPrimitive.Root>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}

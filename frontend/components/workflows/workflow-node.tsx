"use client"

import type { ComponentType } from "react"
import {
  BracesIcon,
  BrainCircuitIcon,
  Code2Icon,
  DatabaseIcon,
  FlagIcon,
  GitBranchIcon,
  PlayIcon,
  RouteIcon,
  TextCursorInputIcon,
  WrenchIcon,
} from "lucide-react"
import { Handle, Position, type NodeProps } from "@xyflow/react"

import { useLanguage } from "@/contexts/language-provider"
import type { TFunction, TranslationKey } from "@/i18n"
import type {
  WorkflowNodeData,
  WorkflowNodeType,
} from "@/lib/api/workflows"
import { cn } from "@/lib/utils"

const NODE_LABELS: Record<WorkflowNodeType, TranslationKey> = {
  start: "开始节点",
  end: "结束节点",
  llm: "大语言模型",
  classifier: "问题分类器",
  knowledge: "知识检索节点",
  condition: "条件分支",
  template: "模板转换",
  variable: "变量赋值",
  mcp: "MCP 工具节点",
  code: "Python 代码",
}

export const NODE_ICONS: Record<
  WorkflowNodeType,
  ComponentType<{ className?: string }>
> = {
  start: PlayIcon,
  end: FlagIcon,
  llm: BrainCircuitIcon,
  classifier: RouteIcon,
  knowledge: DatabaseIcon,
  condition: GitBranchIcon,
  template: TextCursorInputIcon,
  variable: BracesIcon,
  mcp: WrenchIcon,
  code: Code2Icon,
}

export function workflowNodeLabel(type: WorkflowNodeType, t: TFunction) {
  return t(NODE_LABELS[type])
}

const STATUS_STYLES = {
  running: "border-sky-500 ring-2 ring-sky-500/20",
  succeeded: "border-emerald-500 ring-2 ring-emerald-500/15",
  failed: "border-destructive ring-2 ring-destructive/15",
  skipped: "border-muted-foreground/30 opacity-60",
} as const

export function WorkflowNodeCard({ data, selected }: NodeProps) {
  const { t } = useLanguage()
  const node = data as WorkflowNodeData
  const Icon = NODE_ICONS[node.type]
  const status = node.runtimeStatus
  const config = node.config
  const classifierHandles =
    node.type === "classifier" && Array.isArray(config.classes)
      ? [
          ...config.classes
            .filter(
              (item): item is Record<string, unknown> =>
                Boolean(item) && typeof item === "object"
            )
            .map((item) => String(item.handle ?? ""))
            .filter(Boolean),
          String(config.default_handle ?? "default"),
        ]
      : []
  const sourceHandles =
    node.type === "condition"
      ? ["true", "false"]
      : node.type === "classifier"
        ? classifierHandles
        : node.type === "end"
          ? []
          : [null]

  return (
    <div
      className={cn(
        "relative min-h-20 w-52 rounded-md border bg-background px-3 py-2.5 shadow-sm transition-[border-color,box-shadow,opacity]",
        selected && "border-foreground ring-2 ring-foreground/10",
        status && STATUS_STYLES[status]
      )}
    >
      {node.type !== "start" ? (
        <Handle
          type="target"
          position={Position.Left}
          className="!size-2.5 !border-2 !border-background !bg-muted-foreground"
        />
      ) : null}
      <div className="flex items-start gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-foreground">
          <Icon className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">
            {node.title}
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {workflowNodeLabel(node.type, t)}
          </span>
        </span>
        {status ? (
          <span
            className={cn(
              "mt-1 size-2 shrink-0 rounded-full",
              status === "running" && "animate-pulse bg-sky-500",
              status === "succeeded" && "bg-emerald-500",
              status === "failed" && "bg-destructive",
              status === "skipped" && "bg-muted-foreground"
            )}
            title={t(
              status === "running"
                ? "运行中"
                : status === "succeeded"
                  ? "运行成功"
                  : status === "failed"
                    ? "运行失败"
                    : "已跳过"
            )}
          />
        ) : null}
      </div>
      {sourceHandles.map((handle, index) => (
        <div
          key={handle ?? "default"}
          className="absolute right-0 flex translate-x-full items-center"
          style={{
            top:
              sourceHandles.length === 1
                ? "50%"
                : `${((index + 1) / (sourceHandles.length + 1)) * 100}%`,
          }}
        >
          {handle ? (
            <span className="mr-2 -translate-y-1/2 rounded bg-background px-1 text-[10px] text-muted-foreground shadow-sm">
              {handle}
            </span>
          ) : null}
          <Handle
            id={handle}
            type="source"
            position={Position.Right}
            className="!relative !right-auto !size-2.5 !translate-x-[-5px] !translate-y-[-50%] !border-2 !border-background !bg-foreground"
          />
        </div>
      ))}
    </div>
  )
}

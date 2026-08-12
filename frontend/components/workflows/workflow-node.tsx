"use client"

import * as React from "react"
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
  CheckCircle2Icon,
  CircleAlertIcon,
  CircleDotDashedIcon,
  LoaderCircleIcon,
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

const STATUS_LABELS = {
  running: "运行中",
  succeeded: "运行成功",
  failed: "运行失败",
  skipped: "已跳过",
} as const

const STATUS_ICONS = {
  running: LoaderCircleIcon,
  succeeded: CheckCircle2Icon,
  failed: CircleAlertIcon,
  skipped: CircleDotDashedIcon,
} as const

const NODE_ACCENTS: Record<WorkflowNodeType, string> = {
  start: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  end: "bg-slate-500/10 text-slate-600 dark:text-slate-300",
  llm: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  classifier: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  knowledge: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  condition: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  template: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
  variable: "bg-pink-500/10 text-pink-600 dark:text-pink-400",
  mcp: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
  code: "bg-purple-500/10 text-purple-600 dark:text-purple-400",
}

function previewValue(value: unknown) {
  if (typeof value !== "string") return ""
  const compact = value.replace(/\s+/g, " ").trim()
  return compact.length > 42 ? `${compact.slice(0, 42)}...` : compact
}

function configSummary(node: WorkflowNodeData, t: TFunction) {
  const config = node.config
  switch (node.type) {
    case "start": {
      const count = Array.isArray(config.inputs) ? config.inputs.length : 0
      return `${t("输入字段")} · ${count}`
    }
    case "end": {
      const outputs = config.outputs
      const count = outputs && typeof outputs === "object" ? Object.keys(outputs).length : 0
      return `${t("输出映射")} · ${count}`
    }
    case "llm":
      return config.model_id ? t("节点模型") : t("使用工作流默认模型")
    case "classifier": {
      const count = Array.isArray(config.classes) ? config.classes.length : 0
      return `${t("分类出口")} · ${count + (config.default_handle ? 1 : 0)}`
    }
    case "knowledge":
      return `${t("检索查询")} · ${previewValue(config.query) || t("未配置")}`
    case "condition": {
      const operators: Record<string, TranslationKey> = {
        equals: "等于",
        not_equals: "不等于",
        contains: "包含",
        not_contains: "不包含",
        greater_than: "大于",
        greater_or_equal: "大于等于",
        less_than: "小于",
        less_or_equal: "小于等于",
        is_empty: "为空",
        not_empty: "不为空",
      }
      return t(operators[String(config.operator)] ?? "运算符")
    }
    case "template":
      return `${t("模板内容")} · ${previewValue(config.template) || t("未配置")}`
    case "variable":
      return `${t("变量值")} · ${previewValue(config.value) || t("未配置")}`
    case "mcp":
      return previewValue(config.tool_name) || t("选择只读 MCP 工具")
    case "code": {
      const inputs = config.inputs
      const count = inputs && typeof inputs === "object" ? Object.keys(inputs).length : 0
      return `${t("代码输入")} · ${count}`
    }
  }
}

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
  const StatusIcon = status ? STATUS_ICONS[status] : CircleDotDashedIcon
  const summary = configSummary(node, t)

  return (
    <div
      className={cn(
        "relative min-h-24 w-60 rounded-xl border bg-card px-3.5 py-3 shadow-md transition-[border-color,box-shadow,opacity]",
        selected && "border-foreground shadow-lg ring-2 ring-foreground/10",
        status && STATUS_STYLES[status]
      )}
    >
      {node.type !== "start" ? (
        <Handle
          type="target"
          position={Position.Left}
          className="!pointer-events-auto !z-20 !size-4 !border-[3px] !border-card !bg-muted-foreground"
        />
      ) : null}
      <div className="flex items-start gap-2.5 pr-1">
        <span
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-lg",
            NODE_ACCENTS[node.type]
          )}
        >
          <Icon className="size-[18px]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold leading-5">
            {node.title}
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
            {workflowNodeLabel(node.type, t)}
          </span>
        </span>
        {status ? (
          <span
            className={cn(
              "mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium",
              status === "running" && "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400",
              status === "succeeded" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
              status === "failed" && "border-destructive/30 bg-destructive/10 text-destructive",
              status === "skipped" && "border-muted-foreground/30 bg-muted text-muted-foreground"
            )}
            title={t(STATUS_LABELS[status])}
          >
            <StatusIcon className={cn("size-3", status === "running" && "animate-spin")} />
            <span className="sr-only">{t(STATUS_LABELS[status])}</span>
          </span>
        ) : null}
      </div>
      <div className="mt-3 border-t border-border/70 pt-2 text-[11px] text-muted-foreground">
        <span className="block truncate">{summary}</span>
      </div>
      {sourceHandles.map((handle, index) => (
        <React.Fragment key={handle ?? "default"}>
          {handle ? (
            <span
              className="pointer-events-none absolute right-3 z-10 -translate-y-1/2 rounded bg-card px-1 text-[10px] text-muted-foreground"
              style={{
                top:
                  sourceHandles.length === 1
                    ? "50%"
                    : `${((index + 1) / (sourceHandles.length + 1)) * 100}%`,
              }}
            >
              {handle}
            </span>
          ) : null}
          <Handle
            id={handle}
            type="source"
            position={Position.Right}
            className="!pointer-events-auto !z-20 !size-4 !border-[3px] !border-card !bg-foreground"
            style={{
              top:
                sourceHandles.length === 1
                  ? "50%"
                  : `${((index + 1) / (sourceHandles.length + 1)) * 100}%`,
            }}
          />
        </React.Fragment>
      ))}
    </div>
  )
}

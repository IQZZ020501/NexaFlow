"use client"

import * as React from "react"
import type { ComponentType } from "react"
import ModelIcon from "@lobehub/icons/es/features/ModelIcon"
import {
  BracesIcon,
  BotIcon,
  BrainCircuitIcon,
  Code2Icon,
  DatabaseIcon,
  FileTextIcon,
  FlagIcon,
  GitBranchIcon,
  PlayIcon,
  RouteIcon,
  TextCursorInputIcon,
  WrenchIcon,
  CheckCircle2Icon,
  CheckIcon,
  CircleAlertIcon,
  CircleDotDashedIcon,
  LoaderCircleIcon,
  MessageSquareMoreIcon,
  ListFilterIcon,
  ClipboardListIcon,
  MinusIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CopyIcon,
  PencilIcon,
  PlusIcon,
  SettingsIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react"
import { Handle, Position, type NodeProps } from "@xyflow/react"

import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import type { TFunction, TranslationKey } from "@/i18n"
import type { Agent } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import type { ToolDetail, ToolRef } from "@/lib/api/tools"
import type {
  WorkflowNode,
  WorkflowNodeData,
  WorkflowNodeType,
} from "@/lib/api/workflows"
import { copyText } from "@/lib/clipboard"
import { toolDisplayName } from "@/lib/tool-display"
import { cn } from "@/lib/utils"
import {
  WORKFLOW_START_FIELDS,
  WORKFLOW_START_GLOBALS,
  upstreamWorkflowFields,
  workflowNodeLabel,
} from "@/lib/workflows/graph"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
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
import {
  DropdownMenu,
  DropdownMenuContent as BaseDropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { IconButton } from "@/components/ui/icon-button"

function DropdownMenuContent({
  className,
  ...props
}: React.ComponentProps<typeof BaseDropdownMenuContent>) {
  return (
    <BaseDropdownMenuContent
      className={cn(
        "min-w-0 rounded-md p-0.5 [&_[data-slot=dropdown-menu-item]]:gap-1.5 [&_[data-slot=dropdown-menu-item]]:rounded-sm [&_[data-slot=dropdown-menu-item]]:px-1.5 [&_[data-slot=dropdown-menu-item]]:py-1 [&_[data-slot=dropdown-menu-item]]:text-[11px] [&_[data-slot=dropdown-menu-item]]:leading-4 [&_[data-slot=dropdown-menu-item]]:whitespace-nowrap",
        className
      )}
      {...props}
    />
  )
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
  "reranker-node": ListFilterIcon,
  "form-node": ClipboardListIcon,
  "document-extract-node": FileTextIcon,
  condition: GitBranchIcon,
  "reply-node": MessageSquareMoreIcon,
  template: TextCursorInputIcon,
  variable: BracesIcon,
  tool: WrenchIcon,
  agent: BotIcon,
  mcp: WrenchIcon,
  code: Code2Icon,
}

const STATUS_STYLES = {
  running: "border-sky-500 ring-2 ring-sky-500/20",
  awaiting_input: "border-amber-500 ring-2 ring-amber-500/20",
  awaiting_child: "border-sky-500 ring-2 ring-sky-500/20",
  succeeded: "",
  failed: "border-destructive ring-2 ring-destructive/15",
  skipped: "border-muted-foreground/30 opacity-60",
} as const

const STATUS_LABELS = {
  running: "运行中",
  awaiting_input: "等待填写表单",
  awaiting_child: "等待执行",
  succeeded: "运行成功",
  failed: "运行失败",
  skipped: "已跳过",
} as const

const STATUS_ICONS = {
  running: LoaderCircleIcon,
  awaiting_input: ClipboardListIcon,
  awaiting_child: BotIcon,
  succeeded: CheckCircle2Icon,
  failed: CircleAlertIcon,
  skipped: CircleDotDashedIcon,
} as const

const NODE_ACCENTS: Record<WorkflowNodeType, string> = {
  start: "bg-muted text-muted-foreground",
  end: "bg-slate-500/10 text-slate-600 dark:text-slate-300",
  llm: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  classifier: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  knowledge: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  "reranker-node": "bg-teal-500/10 text-teal-600 dark:text-teal-400",
  "form-node": "bg-rose-500/10 text-rose-600 dark:text-rose-400",
  "document-extract-node": "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
  condition: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  "reply-node": "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  template: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
  variable: "bg-pink-500/10 text-pink-600 dark:text-pink-400",
  tool: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
  agent: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  mcp: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
  code: "bg-purple-500/10 text-purple-600 dark:text-purple-400",
}

const KNOWLEDGE_OUTPUT_FIELDS: Array<{
  field: string
  label: TranslationKey
}> = [
  { field: "paragraph_list", label: "检索结果的分段列表" },
  {
    field: "is_hit_handling_method_list",
    label: "满足直接回答的分段列表",
  },
  { field: "data", label: "检索结果" },
  { field: "directly_return", label: "满足直接回答的分段内容" },
]

const LLM_OUTPUT_FIELDS: Array<{
  field: string
  label: TranslationKey
}> = [
  { field: "text", label: "模型回复" },
  { field: "reasoning_content", label: "思考过程" },
]

const OUTPUT_FIELD_LABELS: Partial<
  Record<WorkflowNodeType, Record<string, TranslationKey>>
> = {
  classifier: { class: "分类结果" },
  template: { text: "模板内容" },
  variable: { value: "变量值" },
  tool: { result: "工具结果" },
  agent: { result: "执行结果" },
  mcp: { result: "工具结果" },
  code: { result: "执行结果", stdout: "标准输出", stderr: "错误输出" },
  "reranker-node": { result_list: "重排结果列表", result: "重排结果" },
  "form-node": { form_data: "表单数据", result: "返回内容" },
  "document-extract-node": { content: "文档内容" },
}

function outputFieldLabel(type: WorkflowNodeType, field: string, t: TFunction) {
  const label =
    type === "knowledge"
      ? KNOWLEDGE_OUTPUT_FIELDS.find((item) => item.field === field)?.label
      : type === "llm"
        ? LLM_OUTPUT_FIELDS.find((item) => item.field === field)?.label
        : OUTPUT_FIELD_LABELS[type]?.[field]
  return label ? t(label) : field
}

function workflowVariablePathLabel(
  sourceId: string,
  field: string,
  nodes: WorkflowNode[],
  t: TFunction
) {
  if (sourceId === "global") {
    const global = WORKFLOW_START_GLOBALS.find((item) => item.value === field)
    return global ? `${t("全局变量")} · ${t(global.label)}` : null
  }
  const source = nodes.find((item) => item.id === sourceId)
  if (!source) return null
  const startField =
    source.data.type === "start"
      ? WORKFLOW_START_FIELDS.find((item) => item.value === field)
      : undefined
  const sourceTitle =
    source.data.type === "start" ? t("开始节点") : source.data.title
  const fieldLabel = startField
    ? t(startField.label)
    : outputFieldLabel(source.data.type, field, t)
  return `${sourceTitle} · ${fieldLabel}`
}

function workflowVariableReferenceLabel(
  reference: string,
  nodes: WorkflowNode[],
  t: TFunction
) {
  const match = reference.match(
    /^{{\s*([A-Za-z0-9_-]+)\.([A-Za-z0-9_.-]+)\s*}}$/
  )
  return match
    ? (workflowVariablePathLabel(match[1], match[2], nodes, t) ?? reference)
    : reference
}

function workflowVariableTextLabel(
  rawValue: string,
  nodes: WorkflowNode[],
  t: TFunction
) {
  return rawValue.replace(
    /{{\s*([A-Za-z0-9_-]+)\.([A-Za-z0-9_.-]+)\s*}}/g,
    (reference, sourceId: string, field: string) => {
      const label = workflowVariablePathLabel(sourceId, field, nodes, t)
      return label ? `【${label}】` : reference
    }
  )
}

const KNOWLEDGE_SEARCH_MODES: Array<{
  value: string
  label: TranslationKey
}> = [
  { value: "embedding", label: "向量检索" },
  { value: "keywords", label: "关键词检索" },
  { value: "blend", label: "混合检索" },
]

const CONDITION_COMPARE_OPTIONS: Array<{
  value: string
  label: TranslationKey
}> = [
  { value: "is_null", label: "为空" },
  { value: "is_not_null", label: "不为空" },
  { value: "contain", label: "包含" },
  { value: "not_contain", label: "不包含" },
  { value: "eq", label: "等于" },
  { value: "ge", label: "大于等于" },
  { value: "gt", label: "大于" },
  { value: "le", label: "小于等于" },
  { value: "lt", label: "小于" },
  { value: "len_eq", label: "长度等于" },
  { value: "len_ge", label: "长度大于等于" },
  { value: "len_gt", label: "长度大于" },
  { value: "len_le", label: "长度小于等于" },
  { value: "len_lt", label: "长度小于" },
  { value: "is_true", label: "为真" },
  { value: "is_not_true", label: "不为真" },
]

const CONDITION_VALUELESS_COMPARE = new Set([
  "is_null",
  "is_not_null",
  "is_true",
  "is_not_true",
])

type ConditionRule = {
  field: [string, string]
  compare: string
  value: string
}

type ConditionBranch = {
  id: string
  type: string
  condition: "and" | "or"
  conditions: ConditionRule[]
}

type FormFieldConfig = {
  variable: string
  name: string
  type: "input" | "textarea" | "select" | "date" | "number"
  is_required: boolean
  default_value: unknown
  show_default_value: boolean
  optionList: string[]
}

function conditionBranches(
  config: Record<string, unknown>,
  startNodeId = "start"
): ConditionBranch[] {
  if (Array.isArray(config.branch)) {
    return (config.branch as ConditionBranch[]).map((branch) => ({
      ...branch,
      type: /^ELSE IF(?: [1-9][0-9]*)?$/.test(branch.type)
        ? "ELSE IF"
        : branch.type,
    }))
  }
  const fieldMatch = String(config.left ?? "").match(
    /^{{\s*([A-Za-z0-9_-]+)\.([A-Za-z0-9_.-]+)\s*}}$/
  )
  const legacyCompare: Record<string, string> = {
    equals: "eq",
    not_equals: "not_eq",
    contains: "contain",
    not_contains: "not_contain",
    greater_than: "gt",
    greater_than_or_equal: "ge",
    less_than: "lt",
    less_than_or_equal: "le",
    is_empty: "is_null",
    is_not_empty: "is_not_null",
    length_equals: "len_eq",
    length_greater_than: "len_gt",
    length_greater_than_or_equal: "len_ge",
    length_less_than: "len_lt",
    length_less_than_or_equal: "len_le",
    is_true: "is_true",
    is_false: "is_not_true",
  }
  return [
    {
      id: "true",
      type: "IF",
      condition: "and",
      conditions: [
        {
          field: fieldMatch
            ? [fieldMatch[1], fieldMatch[2]]
            : [startNodeId, "question"],
          compare: legacyCompare[String(config.operator)] ?? "eq",
          value: String(config.right ?? ""),
        },
      ],
    },
    { id: "false", type: "ELSE", condition: "and", conditions: [] },
  ]
}

function createConditionId() {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 12)
}

function normalizeConditionBranches(branches: ConditionBranch[]) {
  return branches.map((branch, index) => ({
    ...branch,
    type:
      index === 0
        ? "IF"
        : index === branches.length - 1 && branch.type === "ELSE"
          ? "ELSE"
          : "ELSE IF",
  }))
}

function previewValue(value: unknown) {
  if (typeof value !== "string") return ""
  const compact = value.replace(/\s+/g, " ").trim()
  return compact.length > 42 ? `${compact.slice(0, 42)}...` : compact
}

function publishedAgentVersionId(agent: Agent) {
  return agent.current_published_version_id ?? null
}

function configSummary(node: WorkflowNodeData, t: TFunction) {
  const config = node.config
  switch (node.type) {
    case "start":
      return null
    case "end": {
      const outputs = config.outputs
      const count =
        outputs && typeof outputs === "object" ? Object.keys(outputs).length : 0
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
    case "reranker-node": {
      const count = Array.isArray(config.reranker_reference_list)
        ? config.reranker_reference_list.length
        : 0
      return `${t("重排内容")} · ${count}`
    }
    case "form-node": {
      const count = Array.isArray(config.form_field_list)
        ? config.form_field_list.length
        : 0
      return `${t("表单字段")} · ${count}`
    }
    case "document-extract-node":
      return `${t("文档")} · ${previewValue(config.document_list) || t("未配置")}`
    case "condition": {
      return `${t("分支")} · ${conditionBranches(config).length}`
    }
    case "reply-node":
      return t(config.reply_type === "referencing" ? "引用变量" : "自定义")
    case "template":
      return `${t("模板内容")} · ${previewValue(config.template) || t("未配置")}`
    case "variable":
      return `${t("变量值")} · ${previewValue(config.value) || t("未配置")}`
    case "tool": {
      const reference =
        config.tool && typeof config.tool === "object"
          ? (config.tool as Record<string, unknown>)
          : null
      const tool = node.tools?.find((item) => item.id === reference?.tool_id)
      return tool
        ? toolDisplayName(tool, t)
        : previewValue(reference?.tool_id) || t("未配置")
    }
    case "agent":
      return (
        node.agents?.find(
          (item) =>
            item.id === config.agent_id ||
            publishedAgentVersionId(item) === config.agent_version_id
        )?.name ??
        (previewValue(config.agent_version_id) || t("暂无已发布版本"))
      )
    case "mcp":
      return previewValue(config.tool_name) || t("选择只读 MCP 工具")
    case "code": {
      const inputs = config.inputs
      const count =
        inputs && typeof inputs === "object" ? Object.keys(inputs).length : 0
      return `${t("代码输入")} · ${count}`
    }
  }
}

function JsonEditor({
  id,
  label,
  value,
  readOnly,
  onChange,
  t,
}: {
  id: string
  label: string
  value: unknown
  readOnly: boolean
  onChange: (value: unknown) => void
  t: TFunction
}) {
  const [text, setText] = React.useState(() => JSON.stringify(value, null, 2))
  const [invalid, setInvalid] = React.useState(false)

  return (
    <label className="grid min-w-0 gap-1.5 text-xs font-medium" htmlFor={id}>
      {label}
      <textarea
        id={id}
        className="min-h-28 resize-y rounded-md border bg-background p-2 font-mono text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive"
        value={text}
        readOnly={readOnly}
        aria-invalid={invalid}
        onChange={(event) => {
          const next = event.target.value
          setText(next)
          try {
            const parsed = JSON.parse(next)
            setInvalid(false)
            onChange(parsed)
          } catch {
            setInvalid(true)
          }
        }}
      />
      {invalid ? (
        <span className="font-normal text-destructive">
          {t("JSON 格式无效")}
        </span>
      ) : null}
    </label>
  )
}

function FormOptionsInput({
  value,
  readOnly,
  onChange,
  t,
}: {
  value: string[]
  readOnly: boolean
  onChange: (value: string[]) => void
  t: TFunction
}) {
  const [draft, setDraft] = React.useState("")
  const [editing, setEditing] = React.useState(false)
  const displayValue = editing ? draft : value.join(", ")

  return (
    <Input
      value={displayValue}
      readOnly={readOnly}
      aria-label={t("选项")}
      placeholder={t("用逗号分隔选项")}
      onFocus={(event) => {
        setDraft(event.currentTarget.value)
        setEditing(true)
      }}
      onBlur={() => setEditing(false)}
      onChange={(event) => {
        const next = event.target.value
        setDraft(next)
        onChange(
          next
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean)
        )
      }}
    />
  )
}

function VariablePicker({
  nodeId,
  node,
  t,
  label,
  className,
  disabled = false,
  onInsert,
}: {
  nodeId: string
  node: WorkflowNodeData
  t: TFunction
  label?: string
  className?: string
  disabled?: boolean
  onInsert: (reference: string, path: string[], description: string) => void
}) {
  const [open, setOpen] = React.useState(false)
  const startNodeId =
    (node.nodes ?? []).find((item) => item.data.type === "start")?.id ?? "start"
  const upstream = React.useMemo(() => {
    const nodes = node.nodes ?? []
    const edges = node.edges ?? []
    return upstreamWorkflowFields(nodes, edges, nodeId, outputFieldNames)
  }, [node.edges, node.nodes, nodeId])
  const upstreamFieldLabel = (sourceId: string, field: string) => {
    const source = (node.nodes ?? []).find((item) => item.id === sourceId)
    return source ? outputFieldLabel(source.data.type, field, t) : field
  }
  const displayLabel = label
    ? workflowVariableReferenceLabel(label, node.nodes ?? [], t)
    : t("插入变量")
  return (
    <DropdownMenu open={open} onOpenChange={setOpen} modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          disabled={disabled}
          className={cn(
            "h-6 px-1.5 text-[11px] font-normal text-muted-foreground",
            className
          )}
        >
          <span className="min-w-0 truncate">{displayLabel}</span>
          {label ? <ChevronDownIcon className="ml-auto size-3.5" /> : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="max-h-80 w-60 overflow-y-auto"
      >
        <p className="px-2 pt-1.5 pb-0.5 text-[10px] font-medium text-muted-foreground">
          {t("全局变量")}
        </p>
        {WORKFLOW_START_GLOBALS.map((field) => (
          <DropdownMenuItem
            key={field.value}
            onSelect={() => {
              onInsert(
                `{{global.${field.value}}}`,
                ["global", field.value],
                t(field.label)
              )
              setOpen(false)
            }}
          >
            <span className="min-w-0 flex-1 truncate text-xs">
              {t(field.label)}
            </span>
          </DropdownMenuItem>
        ))}
        <p className="px-2 pt-1.5 pb-0.5 text-[10px] font-medium text-muted-foreground">
          {t("开始节点")}
        </p>
        {WORKFLOW_START_FIELDS.map((field) => (
          <DropdownMenuItem
            key={field.value}
            onSelect={() => {
              onInsert(
                `{{${startNodeId}.${field.value}}}`,
                [startNodeId, field.value],
                t(field.label)
              )
              setOpen(false)
            }}
          >
            <span className="min-w-0 flex-1 truncate text-xs">
              {t(field.label)}
            </span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        {upstream.length ? (
          upstream.map((group) => (
            <React.Fragment key={group.id}>
              <p className="px-2 pt-1.5 pb-0.5 text-[10px] font-medium text-muted-foreground">
                {group.title}
              </p>
              {group.fields.map((field) => {
                const displayLabel = upstreamFieldLabel(group.id, field)
                return (
                  <DropdownMenuItem
                    key={field}
                    onSelect={() => {
                      onInsert(
                        `{{${group.id}.${field}}}`,
                        [group.id, field],
                        `${group.title} > ${displayLabel}`
                      )
                      setOpen(false)
                    }}
                  >
                    <span className="min-w-0 flex-1 truncate text-xs">
                      {displayLabel}
                    </span>
                  </DropdownMenuItem>
                )
              })}
            </React.Fragment>
          ))
        ) : (
          <p className="px-2 py-2 text-xs text-muted-foreground">
            {t("暂无可引用变量")}
          </p>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function TextEditor({
  id,
  label,
  value,
  readOnly,
  rows = 3,
  onChange,
  node,
  nodeId,
  t,
  insertVariables = false,
}: {
  id: string
  label: string
  value: unknown
  readOnly: boolean
  rows?: number
  onChange: (value: string) => void
  node: WorkflowNodeData
  nodeId: string
  t: TFunction
  insertVariables?: boolean
}) {
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null)
  const [editing, setEditing] = React.useState(false)
  const rawValue = typeof value === "string" ? value : JSON.stringify(value)
  const selectionRef = React.useRef({
    start: rawValue.length,
    end: rawValue.length,
  })
  const localizedValue = insertVariables
    ? workflowVariableTextLabel(rawValue, node.nodes ?? [], t)
    : rawValue
  const showLocalizedPreview = !editing && localizedValue !== rawValue
  const insertReference = React.useCallback(
    (reference: string) => {
      const { start, end } = selectionRef.current
      onChange(rawValue.slice(0, start) + reference + rawValue.slice(end))
      const nextPosition = start + reference.length
      selectionRef.current = { start: nextPosition, end: nextPosition }
      setEditing(true)
      requestAnimationFrame(() => {
        const textarea = textareaRef.current
        textarea?.focus()
        textarea?.setSelectionRange(nextPosition, nextPosition)
      })
    },
    [onChange, rawValue]
  )
  return (
    <div className="grid gap-1.5 text-xs font-medium">
      <span className="flex items-center justify-between gap-2">
        <label htmlFor={id}>{label}</label>
        {insertVariables && !readOnly ? (
          <VariablePicker
            nodeId={nodeId}
            node={node}
            t={t}
            onInsert={insertReference}
          />
        ) : null}
      </span>
      {showLocalizedPreview ? (
        <button
          type="button"
          id={id}
          className="w-full min-w-0 rounded-md border bg-background px-2.5 py-2 text-left text-sm leading-5 font-normal break-words whitespace-pre-wrap outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default"
          style={{ minHeight: `${rows * 20 + 18}px` }}
          disabled={readOnly}
          onClick={() => {
            setEditing(true)
            requestAnimationFrame(() => {
              const textarea = textareaRef.current
              textarea?.focus()
              textarea?.setSelectionRange(
                selectionRef.current.start,
                selectionRef.current.end
              )
            })
          }}
        >
          {localizedValue}
        </button>
      ) : (
        <textarea
          ref={textareaRef}
          id={id}
          rows={rows}
          className="w-full min-w-0 resize-y rounded-md border bg-background px-2.5 py-2 text-sm leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
          value={rawValue}
          readOnly={readOnly}
          onFocus={() => {
            if (!readOnly) setEditing(true)
          }}
          onSelect={(event) => {
            selectionRef.current = {
              start: event.currentTarget.selectionStart,
              end: event.currentTarget.selectionEnd,
            }
          }}
          onBlur={(event) => {
            selectionRef.current = {
              start: event.currentTarget.selectionStart,
              end: event.currentTarget.selectionEnd,
            }
            setEditing(false)
          }}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  )
}

function NumberStepper({
  id,
  value,
  min,
  max,
  step = 1,
  readOnly,
  onChange,
  t,
}: {
  id: string
  value: number
  min: number
  max: number
  step?: number
  readOnly: boolean
  onChange: (value: number) => void
  t: TFunction
}) {
  const updateValue = (next: number) =>
    onChange(Math.min(max, Math.max(min, Number(next.toFixed(10)))))

  return (
    <div className="grid h-8 w-20 grid-cols-[minmax(0,1fr)_1.25rem] overflow-hidden rounded-lg border border-input bg-transparent shadow-xs dark:bg-input/30">
      <input
        id={id}
        className="min-w-0 appearance-none bg-transparent px-1 text-center text-xs outline-none focus-visible:bg-accent/50 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        readOnly={readOnly}
        onChange={(event) => updateValue(Number(event.target.value))}
      />
      <div className="grid grid-rows-2 border-l border-input">
        <button
          type="button"
          className="grid place-items-center text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
          aria-label={t("增加数值")}
          disabled={readOnly || value >= max}
          onClick={() => updateValue(value + step)}
        >
          <PlusIcon className="size-2.5" />
        </button>
        <button
          type="button"
          className="grid place-items-center border-t border-input text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
          aria-label={t("减少数值")}
          disabled={readOnly || value <= min}
          onClick={() => updateValue(value - step)}
        >
          <MinusIcon className="size-2.5" />
        </button>
      </div>
    </div>
  )
}

function LlmSettingsDialog({
  open,
  onOpenChange,
  nodeId,
  node,
  readOnly,
  onUpdate,
  t,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  nodeId: string
  node: WorkflowNodeData
  readOnly: boolean
  onUpdate: (data: WorkflowNodeData) => void
  t: TFunction
}) {
  const config = node.config
  const modelParams = (config.model_params_setting ?? {}) as Record<
    string,
    unknown
  >
  const modelSetting = (config.model_setting ?? {}) as Record<string, unknown>
  const reasoningContentEnabled = modelSetting.reasoning_content_enable === true
  const paramValue = (key: string) => {
    const value = modelParams[key]
    return typeof value === "number" ? String(value) : ""
  }
  const updateParam = (key: string, next: string) => {
    const updated = { ...modelParams }
    const parsed = Number(next)
    if (next.trim() === "" || Number.isNaN(parsed)) {
      delete updated[key]
    } else {
      updated[key] = parsed
    }
    onUpdate({
      ...node,
      config: { ...config, model_params_setting: updated },
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="nodrag nowheel max-h-[calc(100svh-2rem)] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("高级模型设置")}</DialogTitle>
          <DialogDescription>
            {t("配置此节点的模型参数和扩展设置。")}
          </DialogDescription>
        </DialogHeader>
        <fieldset className="grid gap-3 text-sm font-medium">
          <legend>{t("模型参数")}</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <label
              className="grid gap-1.5 font-normal"
              htmlFor={`${nodeId}-llm-temperature`}
            >
              {t("温度")}
              <Input
                id={`${nodeId}-llm-temperature`}
                type="number"
                min={0}
                max={2}
                step={0.1}
                placeholder={t("跟随模型默认")}
                value={paramValue("temperature")}
                readOnly={readOnly}
                onChange={(event) =>
                  updateParam("temperature", event.target.value)
                }
              />
            </label>
            <label
              className="grid gap-1.5 font-normal"
              htmlFor={`${nodeId}-llm-top-p`}
            >
              {t("Top P")}
              <Input
                id={`${nodeId}-llm-top-p`}
                type="number"
                min={0}
                max={1}
                step={0.1}
                placeholder={t("跟随模型默认")}
                value={paramValue("top_p")}
                readOnly={readOnly}
                onChange={(event) => updateParam("top_p", event.target.value)}
              />
            </label>
            <label
              className="grid gap-1.5 font-normal sm:col-span-2"
              htmlFor={`${nodeId}-llm-max-tokens`}
            >
              {t("最大输出 Token")}
              <Input
                id={`${nodeId}-llm-max-tokens`}
                type="number"
                min={1}
                step={1}
                placeholder={t("默认 4096")}
                value={paramValue("max_tokens")}
                readOnly={readOnly}
                onChange={(event) =>
                  updateParam("max_tokens", event.target.value)
                }
              />
            </label>
          </div>
        </fieldset>
        <div className="flex items-center justify-between gap-3 text-sm font-medium">
          <span>{t("思考过程")}</span>
          <button
            type="button"
            role="switch"
            id={`${nodeId}-llm-reasoning-content`}
            aria-checked={reasoningContentEnabled}
            aria-label={t("思考过程")}
            disabled={readOnly}
            onClick={() =>
              onUpdate({
                ...node,
                config: {
                  ...config,
                  model_setting: {
                    ...modelSetting,
                    reasoning_content_enable: !reasoningContentEnabled,
                  },
                },
              })
            }
            className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${
              reasoningContentEnabled ? "bg-primary" : "bg-muted-foreground/40"
            }`}
          >
            <span
              className={`block size-4 rounded-full bg-background shadow-sm transition-transform ${
                reasoningContentEnabled
                  ? "translate-x-[18px]"
                  : "translate-x-0.5"
              }`}
            />
          </button>
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t("关闭")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ConditionEditor({
  nodeId,
  node,
  readOnly,
  onUpdate,
  t,
}: {
  nodeId: string
  node: WorkflowNodeData
  readOnly: boolean
  onUpdate: (data: WorkflowNodeData) => void
  t: TFunction
}) {
  const startNodeId =
    (node.nodes ?? []).find((item) => item.data.type === "start")?.id ?? "start"
  const branches = conditionBranches(node.config, startNodeId)
  const updateBranches = (next: ConditionBranch[]) =>
    onUpdate({
      ...node,
      config: {
        ...node.config,
        branch: normalizeConditionBranches(next),
      },
    })
  const fieldLabel = ([sourceId, field]: [string, string]) => {
    return (
      workflowVariablePathLabel(sourceId, field, node.nodes ?? [], t) ??
      `${sourceId} · ${field}`
    )
  }
  const updateBranch = (branchIndex: number, patch: Partial<ConditionBranch>) =>
    updateBranches(
      branches.map((branch, index) =>
        index === branchIndex ? { ...branch, ...patch } : branch
      )
    )
  const updateRule = (
    branchIndex: number,
    ruleIndex: number,
    patch: Partial<ConditionRule>
  ) =>
    updateBranch(branchIndex, {
      conditions: branches[branchIndex].conditions.map((rule, index) =>
        index === ruleIndex ? { ...rule, ...patch } : rule
      ),
    })
  const removeBranch = (branchIndex: number) =>
    updateBranches(branches.filter((_, index) => index !== branchIndex))

  return (
    <div className="grid gap-3">
      {branches.map((branch, branchIndex) => {
        const isElse = branch.type === "ELSE"
        const displayType =
          branch.type === "ELSE IF" && branchIndex > 1
            ? `ELSE IF ${branchIndex}`
            : branch.type
        return (
          <section
            key={branch.id}
            className="grid gap-2.5 border-t border-border/70 pt-3 first:border-t-0 first:pt-0"
          >
            <div className="relative flex min-h-7 items-center justify-between gap-2 pr-1">
              <span
                className={cn(
                  "inline-flex h-6 items-center rounded-md px-2 text-[11px] font-semibold",
                  isElse
                    ? "bg-muted text-muted-foreground"
                    : "bg-orange-500/10 text-orange-700 dark:text-orange-300"
                )}
              >
                {displayType}
              </span>
              <span className="flex items-center gap-1">
                {!isElse && branch.conditions.length > 1 ? (
                  <span className="inline-flex rounded-md border bg-muted/40 p-0.5">
                    {(["and", "or"] as const).map((condition) => (
                      <button
                        key={condition}
                        type="button"
                        className={cn(
                          "h-6 rounded px-2 text-[11px] font-medium",
                          branch.condition === condition &&
                            "bg-background text-foreground shadow-xs"
                        )}
                        disabled={readOnly}
                        onClick={() => updateBranch(branchIndex, { condition })}
                      >
                        {t(condition === "and" ? "全部满足" : "任一满足")}
                      </button>
                    ))}
                  </span>
                ) : null}
                {!isElse && branches.length > 2 ? (
                  <IconButton
                    label={t("删除分支")}
                    className="size-7"
                    disabled={readOnly}
                    onClick={() => removeBranch(branchIndex)}
                  >
                    <Trash2Icon className="size-3.5" />
                  </IconButton>
                ) : null}
              </span>
              <Handle
                id={branch.id}
                type="source"
                position={Position.Right}
                title={displayType}
                className="!pointer-events-auto !absolute !top-1/2 !right-[-1.375rem] !z-20 !size-4 !border-[3px] !border-card !bg-foreground"
              />
            </div>
            {isElse ? (
              <p className="px-2 text-[11px] leading-4 text-muted-foreground">
                {t("未命中以上条件时执行")}
              </p>
            ) : null}
            {!isElse
              ? branch.conditions.map((rule, ruleIndex) => (
                  <div
                    key={`${branch.id}-${ruleIndex}`}
                    className="grid gap-2 rounded-lg border border-border/70 bg-muted/20 p-2"
                  >
                    <VariablePicker
                      nodeId={nodeId}
                      node={node}
                      t={t}
                      disabled={readOnly}
                      label={fieldLabel(rule.field)}
                      className="h-8 w-full justify-between rounded-md border border-input bg-background px-2 text-xs text-foreground hover:bg-background"
                      onInsert={(_reference, path) =>
                        updateRule(branchIndex, ruleIndex, {
                          field: [path[0], path.slice(1).join(".")],
                        })
                      }
                    />
                    <div
                      className={cn(
                        "grid min-w-0 items-center gap-2",
                        CONDITION_VALUELESS_COMPARE.has(rule.compare)
                          ? "grid-cols-[minmax(0,1fr)_1.75rem]"
                          : "grid-cols-[7rem_minmax(0,1fr)_1.75rem]"
                      )}
                    >
                      <DropdownMenu modal={false}>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-8 w-full min-w-0 justify-between px-2 text-xs font-normal"
                            disabled={readOnly}
                          >
                            <span className="truncate">
                              {rule.compare === "not_eq"
                                ? t("不等于")
                                : t(
                                    CONDITION_COMPARE_OPTIONS.find(
                                      (item) => item.value === rule.compare
                                    )?.label ?? "运算符"
                                  )}
                            </span>
                            <ChevronDownIcon className="size-3.5 shrink-0" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="start"
                          className="max-h-80 w-(--radix-dropdown-menu-trigger-width) min-w-32 overflow-y-auto"
                        >
                          {CONDITION_COMPARE_OPTIONS.map((item) => (
                            <DropdownMenuItem
                              key={item.value}
                              className="justify-between"
                              onSelect={() =>
                                updateRule(branchIndex, ruleIndex, {
                                  compare: item.value,
                                })
                              }
                            >
                              {t(item.label)}
                              {rule.compare === item.value ? (
                                <CheckIcon className="text-primary" />
                              ) : null}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                      {!CONDITION_VALUELESS_COMPARE.has(rule.compare) ? (
                        <Input
                          className="h-8 min-w-0 text-xs"
                          value={rule.value}
                          readOnly={readOnly}
                          aria-label={t("比较值")}
                          placeholder={t("比较值")}
                          onChange={(event) =>
                            updateRule(branchIndex, ruleIndex, {
                              value: event.target.value,
                            })
                          }
                        />
                      ) : null}
                      <IconButton
                        label={t("删除条件")}
                        className="size-7"
                        disabled={
                          readOnly ||
                          (branches.length === 2 &&
                            branch.conditions.length === 1)
                        }
                        onClick={() => {
                          if (branch.conditions.length === 1) {
                            removeBranch(branchIndex)
                            return
                          }
                          updateBranch(branchIndex, {
                            conditions: branch.conditions.filter(
                              (_, index) => index !== ruleIndex
                            ),
                          })
                        }}
                      >
                        <Trash2Icon className="size-3.5" />
                      </IconButton>
                    </div>
                  </div>
                ))
              : null}
            {!isElse ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 w-fit px-1 text-xs text-primary hover:bg-transparent hover:text-primary/80"
                disabled={readOnly}
                onClick={() =>
                  updateBranch(branchIndex, {
                    conditions: [
                      ...branch.conditions,
                      {
                        field: [startNodeId, "question"],
                        compare: "eq",
                        value: "",
                      },
                    ],
                  })
                }
              >
                <PlusIcon />
                {t("添加条件")}
              </Button>
            ) : null}
          </section>
        )
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8 w-full border-dashed bg-transparent text-xs text-muted-foreground hover:bg-muted/40 hover:text-foreground"
        disabled={readOnly || branches.length >= 20}
        onClick={() => {
          const elseIndex = branches.findIndex(
            (branch) => branch.type === "ELSE"
          )
          const next = [...branches]
          next.splice(elseIndex < 0 ? next.length : elseIndex, 0, {
            id: createConditionId(),
            type: "ELSE IF",
            condition: "and",
            conditions: [
              { field: [startNodeId, "question"], compare: "eq", value: "" },
            ],
          })
          updateBranches(next)
        }}
      >
        <PlusIcon />
        {t("添加分支")}
      </Button>
      <section className="grid gap-2 border-t border-border/70 pt-3">
        <h3 className="px-1 text-[10px] font-medium text-muted-foreground">
          {t("输出参数")}
        </h3>
        <OutputFieldRow
          displayValue={t("分支名称")}
          reference={`{{${nodeId}.branch_name}}`}
          t={t}
        />
      </section>
    </div>
  )
}

function ToolArgumentsFields({
  nodeId,
  tool,
  value,
  readOnly,
  onChange,
  t,
}: {
  nodeId: string
  tool?: ToolDetail
  value: Record<string, unknown>
  readOnly: boolean
  onChange: (value: Record<string, unknown>) => void
  t: TFunction
}) {
  const schema =
    tool?.input_schema && typeof tool.input_schema === "object"
      ? tool.input_schema
      : null
  const properties =
    schema?.properties && typeof schema.properties === "object"
      ? (schema.properties as Record<string, unknown>)
      : {}
  const required = new Set(
    Array.isArray(schema?.required) ? schema.required.map(String) : []
  )
  const propertyEntries = Object.entries(properties)

  if (!propertyEntries.length) {
    return (
      <JsonEditor
        id={`${nodeId}-tool-arguments`}
        label={t("工具参数")}
        value={value}
        readOnly={readOnly}
        onChange={(nextValue) => {
          if (
            nextValue &&
            typeof nextValue === "object" &&
            !Array.isArray(nextValue)
          ) {
            onChange(nextValue as Record<string, unknown>)
          }
        }}
        t={t}
      />
    )
  }

  const knownNames = new Set(propertyEntries.map(([name]) => name))
  const extraEntries = Object.entries(value).filter(
    ([name]) => !knownNames.has(name)
  )

  return (
    <fieldset className="grid max-h-72 gap-2.5 overflow-y-auto pr-1">
      <legend className="text-xs font-medium">{t("工具参数")}</legend>
      {propertyEntries.map(([name, propertyValue]) => {
        const property =
          propertyValue && typeof propertyValue === "object"
            ? (propertyValue as Record<string, unknown>)
            : {}
        const title =
          typeof property.title === "string" && property.title.trim()
            ? property.title
            : name
        const description =
          typeof property.description === "string" ? property.description : ""
        const defaultValue = "default" in property ? property.default : null
        return (
          <div key={name} className="grid gap-1">
            <JsonEditor
              id={`${nodeId}-tool-argument-${name}`}
              label={`${title}${required.has(name) ? " *" : ""}`}
              value={name in value ? value[name] : defaultValue}
              readOnly={readOnly}
              onChange={(nextValue) =>
                onChange({ ...value, [name]: nextValue })
              }
              t={t}
            />
            {description ? (
              <p className="text-[11px] leading-4 text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
        )
      })}
      {extraEntries.map(([name, extraValue]) => (
        <JsonEditor
          key={name}
          id={`${nodeId}-tool-extra-${name}`}
          label={name}
          value={extraValue}
          readOnly={readOnly}
          onChange={(nextValue) => onChange({ ...value, [name]: nextValue })}
          t={t}
        />
      ))}
    </fieldset>
  )
}

function NodeConfigFields({
  nodeId,
  node,
  agent,
  models,
  knowledgeBases,
  mcpServers,
  tools,
  agents,
  readOnly,
  onUpdate,
  t,
}: {
  nodeId: string
  node: WorkflowNodeData
  agent: Agent
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  mcpServers: McpServer[]
  tools: ToolDetail[]
  agents: Agent[]
  readOnly: boolean
  onUpdate: (data: WorkflowNodeData) => void
  t: TFunction
}) {
  const config = node.config
  const updateConfig = (patch: Record<string, unknown>) =>
    onUpdate({ ...node, config: { ...config, ...patch } })
  const outputEntries =
    config.outputs && typeof config.outputs === "object"
      ? Object.entries(config.outputs as Record<string, unknown>)
      : []
  const updateOutputItem = (index: number, key: string, value: string) => {
    if (outputEntries.some(([itemKey], i) => i !== index && itemKey === key))
      return
    updateConfig({
      outputs: Object.fromEntries(
        outputEntries.map(([itemKey, itemValue], i) =>
          i === index ? [key, value] : [itemKey, itemValue]
        )
      ),
    })
  }
  const removeOutputItem = (index: number) =>
    updateConfig({
      outputs: Object.fromEntries(outputEntries.filter((_, i) => i !== index)),
    })
  const addOutputItem = () =>
    updateConfig({
      outputs: {
        ...(config.outputs as Record<string, unknown>),
        [`output_${outputEntries.length + 1}`]: "",
      },
    })
  const activeModels = models.filter(
    (model) => model.model_type === "LLM" && model.status === "active"
  )
  const rerankerModels = models.filter(
    (model) => model.model_type === "RERANKER" && model.status === "active"
  )
  const selectedReranker = rerankerModels.find(
    (model) => model.id === String(config.reranker_model_id ?? "")
  )
  const rerankerReferences = Array.isArray(config.reranker_reference_list)
    ? config.reranker_reference_list.map(String)
    : []
  const rerankerSetting =
    config.reranker_setting && typeof config.reranker_setting === "object"
      ? (config.reranker_setting as Record<string, unknown>)
      : {}
  const formFields = Array.isArray(config.form_field_list)
    ? (config.form_field_list as FormFieldConfig[])
    : []
  const updateFormField = (index: number, patch: Partial<FormFieldConfig>) =>
    updateConfig({
      form_field_list: formFields.map((field, fieldIndex) =>
        fieldIndex === index ? { ...field, ...patch } : field
      ),
    })
  const availableKnowledge = knowledgeBases.filter(
    (item) => item.status === "active" && item.permission !== "none"
  )
  const selectedKnowledgeIds = Array.isArray(config.knowledge_base_ids)
    ? config.knowledge_base_ids.map(String)
    : config.knowledge_base_id
      ? [String(config.knowledge_base_id)]
      : []
  const selectedKnowledgeNames = availableKnowledge
    .filter((item) => selectedKnowledgeIds.includes(item.id))
    .map((item) => item.name)
  const searchMode = String(config.search_mode ?? "embedding")
  const searchModeLabel =
    KNOWLEDGE_SEARCH_MODES.find((item) => item.value === searchMode)?.label ??
    "向量检索"
  const toggleKnowledgeBase = (knowledgeBaseId: string) =>
    updateConfig({
      knowledge_base_id: null,
      knowledge_base_ids: selectedKnowledgeIds.includes(knowledgeBaseId)
        ? selectedKnowledgeIds.filter((item) => item !== knowledgeBaseId)
        : [...selectedKnowledgeIds, knowledgeBaseId],
    })
  const availableMcp = mcpServers
    .filter((server) => server.status === "active")
    .flatMap((server) =>
      server.tools
        .filter((tool) => tool.policy_mode === "read_only")
        .map((tool) => ({
          server_id: server.id,
          tool_name: tool.name,
          label: `${server.name} / ${tool.name}`,
        }))
    )
  const availableWorkflowTools = tools.filter(
    (tool) =>
      tool.can_use &&
      tool.status === "active" &&
      tool.availability === "available" &&
      Boolean(tool.current_version_id) &&
      tool.approval === "auto" &&
      tool.workflow_callable
  )
  const availableLlmTools = availableWorkflowTools.filter(
    (tool) => tool.function_name !== "inline_python"
  )
  const selectedToolRefs = Array.isArray(config.tools)
    ? config.tools.flatMap((item) => {
        if (!item || typeof item !== "object") return []
        const reference = item as Record<string, unknown>
        return typeof reference.tool_id === "string" &&
          typeof reference.version_id === "string"
          ? [
              {
                tool_id: reference.tool_id,
                version_id: reference.version_id,
              },
            ]
          : []
      })
    : []
  const unavailableSelectedToolRefs = selectedToolRefs.filter(
    (reference) =>
      !availableLlmTools.some((tool) => tool.id === reference.tool_id)
  )
  const toolSelected = (toolId: string) =>
    selectedToolRefs.some((item) => item.tool_id === toolId)
  const toggleToolReference = (tool: ToolDetail, checked: boolean) => {
    if (!tool.current_version_id) return
    updateConfig({
      tools: checked
        ? [
            ...selectedToolRefs.filter((item) => item.tool_id !== tool.id),
            { tool_id: tool.id, version_id: tool.current_version_id },
          ]
        : selectedToolRefs.filter((item) => item.tool_id !== tool.id),
    })
  }
  const directToolReference =
    config.tool && typeof config.tool === "object"
      ? (config.tool as Partial<ToolRef>)
      : null
  const selectedDirectTool = directToolReference
    ? tools.find((tool) => tool.id === directToolReference.tool_id)
    : undefined
  const directToolWithMatchingSchema =
    selectedDirectTool?.version_id === directToolReference?.version_id
      ? selectedDirectTool
      : undefined
  const directToolUnavailable = Boolean(
    directToolReference &&
    (!selectedDirectTool ||
      !selectedDirectTool.can_use ||
      selectedDirectTool.status !== "active" ||
      selectedDirectTool.availability !== "available")
  )
  const directToolCurrentVersionId = selectedDirectTool?.current_version_id
  const directToolHasNewVersion = Boolean(
    directToolCurrentVersionId &&
    directToolCurrentVersionId !== directToolReference?.version_id
  )
  const directToolArguments =
    config.arguments &&
    typeof config.arguments === "object" &&
    !Array.isArray(config.arguments)
      ? (config.arguments as Record<string, unknown>)
      : {}
  const selectedAgentId = String(config.agent_id ?? "")
  const selectedAgentVersionId = String(config.agent_version_id ?? "")
  const selectedAgent = agents.find(
    (item) =>
      item.id === selectedAgentId ||
      publishedAgentVersionId(item) === selectedAgentVersionId
  )
  const selectedMcpRefs = Array.isArray(config.mcp_servers)
    ? (config.mcp_servers as Array<{ server_id: string; tool_name: string }>)
    : []
  const mcpSelected = (reference: { server_id: string; tool_name: string }) =>
    selectedMcpRefs.some(
      (item) =>
        item.server_id === reference.server_id &&
        item.tool_name === reference.tool_name
    )
  const toggleMcpReference = (
    reference: { server_id: string; tool_name: string },
    checked: boolean
  ) =>
    updateConfig({
      mcp_servers: checked
        ? [...selectedMcpRefs, reference]
        : selectedMcpRefs.filter(
            (item) =>
              item.server_id !== reference.server_id ||
              item.tool_name !== reference.tool_name
          ),
    })
  const isResult = config.is_result !== false
  const dialogueType = String(config.dialogue_type ?? "NODE")
  const selectedModelId = String(config.model_id ?? agent.model_id ?? "")
  const selectedModel = activeModels.find(
    (model) => model.id === selectedModelId
  )
  const replyType = String(config.reply_type ?? "custom")
  const replyFields = Array.isArray(config.fields) ? config.fields : null
  const replyFieldPath = Array.isArray(replyFields?.[0])
    ? replyFields[0].map(String)
    : []
  const replyFieldDescription =
    typeof replyFields?.[1] === "string" ? replyFields[1] : ""
  return (
    <div className="grid gap-3">
      {node.type === "end" ? (
        <fieldset className="grid gap-2">
          <legend className="text-xs font-medium">{t("输出映射")}</legend>
          {outputEntries.map(([key, value], index) => (
            <div
              key={index}
              className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2"
            >
              <Input
                value={key}
                readOnly={readOnly}
                aria-label={t("字段名")}
                onChange={(event) =>
                  updateOutputItem(
                    index,
                    event.target.value,
                    String(value ?? "")
                  )
                }
              />
              <Input
                className="min-w-0 font-mono"
                value={String(value ?? "")}
                readOnly={readOnly}
                aria-label={t("表达式")}
                onChange={(event) =>
                  updateOutputItem(index, key, event.target.value)
                }
              />
              {!readOnly ? (
                <IconButton
                  label={t("删除")}
                  className="size-6 shrink-0"
                  onClick={() => removeOutputItem(index)}
                >
                  <XIcon className="size-3.5" />
                </IconButton>
              ) : null}
            </div>
          ))}
          {!readOnly ? (
            <Button type="button" variant="outline" onClick={addOutputItem}>
              <PlusIcon />
              {t("添加")}
            </Button>
          ) : null}
        </fieldset>
      ) : null}
      {node.type === "llm" ? (
        <>
          <label
            className="grid gap-1.5 text-xs font-medium"
            htmlFor={`${nodeId}-llm-model`}
          >
            {t("节点模型")}
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button
                  id={`${nodeId}-llm-model`}
                  type="button"
                  variant="outline"
                  className="h-8 w-full justify-between px-2 text-xs font-normal"
                  disabled={readOnly}
                >
                  <span className="flex min-w-0 flex-1 items-center gap-2 truncate text-left">
                    {selectedModel ? (
                      <ModelIcon
                        model={selectedModel.model_name}
                        size={16}
                        type="color"
                        className="shrink-0"
                      />
                    ) : null}
                    <span className="min-w-0 truncate">
                      {selectedModel?.name ?? t("使用工作流默认模型")}
                    </span>
                  </span>
                  <ChevronDownIcon data-icon="inline-end" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                className="max-h-72 w-(--radix-dropdown-menu-trigger-width) min-w-0 overflow-y-auto"
              >
                <DropdownMenuItem
                  className="justify-between"
                  onSelect={() => updateConfig({ model_id: null })}
                >
                  {t("使用工作流默认模型")}
                  {!config.model_id ? (
                    <span className="text-primary">✓</span>
                  ) : null}
                </DropdownMenuItem>
                {activeModels.map((model) => (
                  <DropdownMenuItem
                    key={model.id}
                    className="justify-between"
                    onSelect={() => updateConfig({ model_id: model.id })}
                  >
                    <span className="flex min-w-0 items-center gap-2 truncate">
                      <ModelIcon
                        model={model.model_name}
                        size={16}
                        type="color"
                        className="shrink-0"
                      />
                      <span className="min-w-0 truncate">{model.name}</span>
                    </span>
                    {model.id === config.model_id ? (
                      <span className="text-primary">✓</span>
                    ) : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </label>
          <TextEditor
            id={`${nodeId}-llm-system`}
            label={t("角色设定")}
            value={config.system_prompt ?? ""}
            readOnly={readOnly}
            onChange={(system_prompt) => updateConfig({ system_prompt })}
            node={node}
            nodeId={nodeId}
            t={t}
            insertVariables
          />
          <TextEditor
            id={`${nodeId}-llm-prompt`}
            label={t("提示词")}
            value={config.prompt ?? ""}
            readOnly={readOnly}
            rows={6}
            onChange={(prompt) => updateConfig({ prompt })}
            node={node}
            nodeId={nodeId}
            t={t}
            insertVariables
          />
          <div className="grid gap-1.5 text-xs font-medium">
            <span className="flex items-center justify-between gap-2">
              <label
                id={`${nodeId}-llm-dialogue-label`}
                htmlFor={`${nodeId}-llm-dialogue`}
              >
                {t("多轮对话数")}
              </label>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    id={`${nodeId}-llm-dialogue-type`}
                    type="button"
                    variant="outline"
                    className="h-7 w-40 justify-between px-2 text-[11px] font-normal"
                    aria-label={t("多轮对话数")}
                    disabled={readOnly}
                  >
                    <span className="truncate">
                      {dialogueType === "WORKFLOW"
                        ? t("整条流程历史")
                        : t("仅取本节点历史")}
                    </span>
                    <ChevronDownIcon className="size-3 shrink-0 text-muted-foreground" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  side="bottom"
                  sideOffset={4}
                  className="w-(--radix-dropdown-menu-trigger-width) min-w-40"
                >
                  {(
                    [
                      ["NODE", "仅取本节点历史"],
                      ["WORKFLOW", "整条流程历史"],
                    ] as const
                  ).map(([value, label]) => (
                    <DropdownMenuItem
                      key={value}
                      className="justify-between whitespace-nowrap"
                      onSelect={() => updateConfig({ dialogue_type: value })}
                    >
                      {t(label)}
                      {dialogueType === value ? (
                        <CheckIcon className="size-4 text-primary" />
                      ) : null}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </span>
            <Input
              id={`${nodeId}-llm-dialogue`}
              type="number"
              min={0}
              max={20}
              step={1}
              value={Number(config.dialogue_number ?? 1)}
              readOnly={readOnly}
              onChange={(event) =>
                updateConfig({ dialogue_number: Number(event.target.value) })
              }
            />
          </div>
          <fieldset className="grid gap-1.5 text-xs font-medium">
            <legend>{t("工具")}</legend>
            <div className="grid max-h-36 gap-2 overflow-y-auto rounded-md border bg-background p-2">
              {availableLlmTools.length ||
              unavailableSelectedToolRefs.length ? (
                <>
                  {availableLlmTools.map((tool) => {
                    const checked = toolSelected(tool.id)
                    return (
                      <label
                        key={tool.id}
                        className="flex items-center gap-2 text-xs font-normal"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={
                            readOnly ||
                            (!checked && selectedToolRefs.length >= 20)
                          }
                          onChange={(event) =>
                            toggleToolReference(tool, event.target.checked)
                          }
                        />
                        <span className="min-w-0 truncate">
                          {toolDisplayName(tool, t)}
                        </span>
                      </label>
                    )
                  })}
                  {unavailableSelectedToolRefs.map((reference) => {
                    const tool = tools.find(
                      (item) => item.id === reference.tool_id
                    )
                    return (
                      <label
                        key={`${reference.tool_id}:${reference.version_id}`}
                        className="flex items-center gap-2 text-xs font-normal text-muted-foreground"
                      >
                        <input
                          type="checkbox"
                          checked
                          disabled={readOnly}
                          onChange={() =>
                            updateConfig({
                              tools: selectedToolRefs.filter(
                                (item) => item.tool_id !== reference.tool_id
                              ),
                            })
                          }
                        />
                        <span className="min-w-0 truncate">
                          {tool ? toolDisplayName(tool, t) : reference.tool_id}{" "}
                          {`(${t("不可用")})`}
                        </span>
                      </label>
                    )
                  })}
                </>
              ) : (
                <span className="font-normal text-muted-foreground">
                  {t("暂无可用工具")}
                </span>
              )}
            </div>
          </fieldset>
          {"mcp_enable" in config || "mcp_servers" in config ? (
            <>
              <div className="flex items-center justify-between gap-2 text-xs font-medium">
                <span>{t("启用 MCP")}</span>
                <button
                  type="button"
                  role="switch"
                  id={`${nodeId}-llm-mcp`}
                  aria-checked={Boolean(config.mcp_enable)}
                  aria-label={t("启用 MCP")}
                  disabled={readOnly}
                  onClick={() =>
                    updateConfig({
                      mcp_enable: !config.mcp_enable,
                      mcp_servers: config.mcp_enable ? [] : selectedMcpRefs,
                    })
                  }
                  className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${
                    config.mcp_enable ? "bg-primary" : "bg-muted-foreground/40"
                  }`}
                >
                  <span
                    className={`block size-4 rounded-full bg-background shadow-sm transition-transform ${
                      config.mcp_enable
                        ? "translate-x-[18px]"
                        : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>
              {config.mcp_enable ? (
                <fieldset className="grid gap-1.5 text-xs font-medium">
                  <legend>{t("MCP 工具（可多选）")}</legend>
                  <div className="grid max-h-32 gap-2 overflow-y-auto rounded-md border bg-background p-2">
                    {availableMcp.length ? (
                      availableMcp.map((item) => (
                        <label
                          key={`${item.server_id}:${item.tool_name}`}
                          className="flex items-center gap-2 text-xs font-normal"
                        >
                          <input
                            type="checkbox"
                            checked={mcpSelected(item)}
                            disabled={readOnly}
                            onChange={(event) =>
                              toggleMcpReference(item, event.target.checked)
                            }
                          />
                          <span className="min-w-0 truncate">{item.label}</span>
                        </label>
                      ))
                    ) : (
                      <span className="font-normal text-muted-foreground">
                        {t("暂无可用 MCP 工具")}
                      </span>
                    )}
                  </div>
                </fieldset>
              ) : null}
            </>
          ) : null}
          <div className="flex items-center justify-between gap-2 text-xs font-medium">
            <span>{t("返回内容")}</span>
            <button
              type="button"
              role="switch"
              id={`${nodeId}-llm-result`}
              aria-checked={isResult}
              aria-label={t("返回内容")}
              disabled={readOnly}
              onClick={() => updateConfig({ is_result: !isResult })}
              className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${
                isResult ? "bg-primary" : "bg-muted-foreground/40"
              }`}
            >
              <span
                className={`block size-4 rounded-full bg-background shadow-sm transition-transform ${
                  isResult ? "translate-x-[18px]" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>
          <section className="grid min-w-0 gap-2 border-t border-border/70 pt-3">
            <h3 className="px-1 text-[10px] font-medium text-muted-foreground">
              {t("输出参数")}
            </h3>
            {LLM_OUTPUT_FIELDS.map((item) => (
              <OutputFieldRow
                key={item.field}
                displayValue={t(item.label)}
                reference={`{{${nodeId}.${item.field}}}`}
                t={t}
              />
            ))}
          </section>
        </>
      ) : null}
      {node.type === "reply-node" ? (
        <>
          <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 text-xs font-medium">
            <span>{t("回复内容")}</span>
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button
                  id={`${nodeId}-reply-type`}
                  type="button"
                  variant="outline"
                  className="h-8 justify-between px-2 text-xs font-normal"
                  disabled={readOnly}
                >
                  {t(replyType === "referencing" ? "引用变量" : "自定义")}
                  <ChevronDownIcon className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                className="w-(--radix-dropdown-menu-trigger-width) min-w-0"
              >
                {(["referencing", "custom"] as const).map((type) => (
                  <DropdownMenuItem
                    key={type}
                    className="justify-between"
                    onSelect={() => updateConfig({ reply_type: type })}
                  >
                    {t(type === "referencing" ? "引用变量" : "自定义")}
                    {replyType === type ? (
                      <CheckIcon className="text-primary" />
                    ) : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {replyType === "referencing" ? (
            <div className="grid gap-1.5 text-xs font-medium">
              <span>{t("引用字段")}</span>
              <VariablePicker
                nodeId={nodeId}
                node={node}
                t={t}
                disabled={readOnly}
                label={
                  replyFieldDescription ||
                  (replyFieldPath.length
                    ? replyFieldPath.join(" > ")
                    : t("选择引用变量"))
                }
                className="h-9 w-full justify-start border bg-background px-2 text-xs text-foreground shadow-xs hover:bg-muted"
                onInsert={(_reference, path, description) =>
                  updateConfig({ fields: [path, description] })
                }
              />
            </div>
          ) : (
            <TextEditor
              id={`${nodeId}-reply-content`}
              label={t("内容")}
              value={config.content ?? ""}
              readOnly={readOnly}
              rows={6}
              onChange={(content) => updateConfig({ content })}
              node={node}
              nodeId={nodeId}
              t={t}
              insertVariables
            />
          )}
          <div className="flex items-center justify-between gap-2 text-xs font-medium">
            <span>{t("返回内容")}</span>
            <button
              type="button"
              role="switch"
              id={`${nodeId}-reply-result`}
              aria-checked={isResult}
              aria-label={t("返回内容")}
              disabled={readOnly}
              onClick={() => updateConfig({ is_result: !isResult })}
              className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${
                isResult ? "bg-primary" : "bg-muted-foreground/40"
              }`}
            >
              <span
                className={`block size-4 rounded-full bg-background shadow-sm transition-transform ${
                  isResult ? "translate-x-[18px]" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>
          <section className="grid min-w-0 gap-2 border-t border-border/70 pt-3">
            <h3 className="px-1 text-[10px] font-medium text-muted-foreground">
              {t("输出参数")}
            </h3>
            <OutputFieldRow
              displayValue={t("内容 {answer}")}
              reference={`{{${nodeId}.answer}}`}
              t={t}
            />
          </section>
        </>
      ) : null}
      {node.type === "classifier" ? (
        <>
          <div className="grid gap-1.5 text-xs font-medium">
            <span>{t("节点模型")}</span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  id={`${nodeId}-classifier-model`}
                  type="button"
                  className="flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-md border bg-background px-2 text-sm disabled:pointer-events-none disabled:opacity-50"
                  aria-label={t("节点模型")}
                  disabled={readOnly}
                >
                  <span className="truncate">
                    {activeModels.find(
                      (model) => model.id === String(config.model_id ?? "")
                    )?.name ?? t("使用工作流默认模型")}
                  </span>
                  <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                className="w-(--radix-dropdown-menu-trigger-width)"
              >
                {[
                  { id: "", name: t("使用工作流默认模型") },
                  ...activeModels,
                ].map((model) => (
                  <DropdownMenuItem
                    key={model.id || "default"}
                    className="justify-between"
                    onSelect={() =>
                      updateConfig({ model_id: model.id || null })
                    }
                  >
                    <span className="truncate">{model.name}</span>
                    {model.id === String(config.model_id ?? "") ? (
                      <CheckIcon className="text-primary" />
                    ) : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <TextEditor
            id={`${nodeId}-classifier-input`}
            label={t("分类输入")}
            value={config.input ?? ""}
            readOnly={readOnly}
            onChange={(input) => updateConfig({ input })}
            node={node}
            nodeId={nodeId}
            t={t}
            insertVariables
          />
          <JsonEditor
            id={`${nodeId}-classifier-classes`}
            label={t("分类出口")}
            value={config.classes ?? []}
            readOnly={readOnly}
            onChange={(classes) => updateConfig({ classes })}
            t={t}
          />
          <label
            className="grid gap-1.5 text-xs font-medium"
            htmlFor={`${nodeId}-classifier-default`}
          >
            {t("默认出口")}
            <Input
              id={`${nodeId}-classifier-default`}
              value={String(config.default_handle ?? "default")}
              readOnly={readOnly}
              onChange={(event) =>
                updateConfig({ default_handle: event.target.value })
              }
            />
          </label>
        </>
      ) : null}
      {node.type === "knowledge" ? (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5">
          <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3">
            <h3 className="px-1 text-[10px] font-medium text-muted-foreground">
              {t("节点设置")}
            </h3>

            <fieldset className="grid gap-3">
              <legend className="mb-1 text-xs font-medium">
                {t("检索范围")}
              </legend>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8 w-full justify-between px-2.5 text-xs font-normal"
                    disabled={readOnly || !availableKnowledge.length}
                  >
                    <span className="min-w-0 truncate text-left">
                      {selectedKnowledgeNames.length === 1
                        ? selectedKnowledgeNames[0]
                        : selectedKnowledgeNames.length > 1
                          ? t("已选择 {value} 个知识库", {
                              value: selectedKnowledgeNames.length,
                            })
                          : t("选择知识库")}
                    </span>
                    <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className="max-h-72 w-(--radix-dropdown-menu-trigger-width) min-w-0 overflow-y-auto"
                >
                  {availableKnowledge.map((item) => {
                    const selected = selectedKnowledgeIds.includes(item.id)
                    return (
                      <DropdownMenuItem
                        key={item.id}
                        className="min-h-8 justify-between px-2.5 py-1.5 text-xs"
                        onSelect={(event) => {
                          event.preventDefault()
                          toggleKnowledgeBase(item.id)
                        }}
                      >
                        <span className="min-w-0 truncate">{item.name}</span>
                        {selected ? (
                          <CheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    )
                  })}
                </DropdownMenuContent>
              </DropdownMenu>
              <p className="px-1 text-xs leading-5 text-muted-foreground">
                {availableKnowledge.length
                  ? t("工作区可用的知识库展示在这里")
                  : t("暂无可用知识库")}
              </p>
            </fieldset>

            <fieldset className="grid gap-1.5">
              <legend className="text-xs font-medium">{t("检索参数")}</legend>
              <div className="grid grid-cols-[minmax(0,1fr)_7.5rem] items-center gap-3 text-xs">
                <span
                  id={`${nodeId}-knowledge-mode-label`}
                  className="text-muted-foreground"
                >
                  {t("检索模式")}
                </span>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      id={`${nodeId}-knowledge-mode`}
                      type="button"
                      variant="outline"
                      className="h-7 w-full justify-between px-2 text-[11px] font-normal"
                      aria-labelledby={`${nodeId}-knowledge-mode-label`}
                      disabled={readOnly}
                    >
                      <span className="truncate">{t(searchModeLabel)}</span>
                      <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="end"
                    side="bottom"
                    sideOffset={4}
                    className="w-(--radix-dropdown-menu-trigger-width) min-w-24"
                  >
                    {KNOWLEDGE_SEARCH_MODES.map((item) => (
                      <DropdownMenuItem
                        key={item.value}
                        className="justify-between"
                        onSelect={() =>
                          updateConfig({ search_mode: item.value })
                        }
                      >
                        {t(item.label)}
                        {searchMode === item.value ? (
                          <CheckIcon className="size-4 text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 text-xs">
                <label
                  className="text-muted-foreground"
                  htmlFor={`${nodeId}-knowledge-similarity`}
                >
                  {t("相似度")}
                </label>
                <NumberStepper
                  id={`${nodeId}-knowledge-similarity`}
                  min={0}
                  max={1}
                  step={0.1}
                  value={Number(config.similarity ?? 0.6)}
                  readOnly={readOnly}
                  onChange={(similarity) => updateConfig({ similarity })}
                  t={t}
                />
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 text-xs">
                <label
                  className="text-muted-foreground"
                  htmlFor={`${nodeId}-knowledge-limit`}
                >
                  {t("引用分段数")}
                </label>
                <NumberStepper
                  id={`${nodeId}-knowledge-limit`}
                  min={1}
                  max={8}
                  value={Number(config.limit ?? 3)}
                  readOnly={readOnly}
                  onChange={(limit) => updateConfig({ limit })}
                  t={t}
                />
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 text-xs">
                <label
                  className="text-muted-foreground"
                  htmlFor={`${nodeId}-knowledge-max-chars`}
                >
                  {t("最大引用字符数")}
                </label>
                <NumberStepper
                  id={`${nodeId}-knowledge-max-chars`}
                  min={1}
                  max={20000}
                  step={100}
                  value={Number(config.max_paragraph_char_number ?? 5000)}
                  readOnly={readOnly}
                  onChange={(maxParagraphCharNumber) =>
                    updateConfig({
                      max_paragraph_char_number: maxParagraphCharNumber,
                    })
                  }
                  t={t}
                />
              </div>
            </fieldset>

            <TextEditor
              id={`${nodeId}-knowledge-query`}
              label={t("检索问题")}
              value={config.query ?? ""}
              readOnly={readOnly}
              rows={2}
              onChange={(query) => updateConfig({ query })}
              node={node}
              nodeId={nodeId}
              t={t}
              insertVariables
            />
          </section>

          <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 border-t border-border/70 pt-3">
            <h3 className="px-1 text-[10px] font-medium text-muted-foreground">
              {t("输出参数")}
            </h3>
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
              {KNOWLEDGE_OUTPUT_FIELDS.map((item) => (
                <OutputFieldRow
                  key={item.field}
                  displayValue={t(item.label)}
                  reference={`{{${nodeId}.${item.field}}}`}
                  t={t}
                />
              ))}
            </div>
          </section>
        </div>
      ) : null}
      {node.type === "reranker-node" ? (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3">
          <label className="grid min-w-0 gap-1.5 text-xs font-medium">
            {t("重排模型")}
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 w-full justify-between px-2 text-xs font-normal"
                  disabled={readOnly || !rerankerModels.length}
                >
                  <span className="truncate">
                    {selectedReranker?.name ?? t("选择重排模型")}
                  </span>
                  <ChevronDownIcon className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-(--radix-dropdown-menu-trigger-width)">
                {rerankerModels.map((model) => (
                  <DropdownMenuItem
                    key={model.id}
                    className="justify-between"
                    onSelect={() =>
                      updateConfig({ reranker_model_id: model.id })
                    }
                  >
                    {model.name}
                    {selectedReranker?.id === model.id ? <CheckIcon /> : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </label>
          <div className="grid min-w-0 gap-1.5 text-xs font-medium">
            <span>{t("检索问题")}</span>
            <VariablePicker
              nodeId={nodeId}
              node={node}
              t={t}
              disabled={readOnly}
              label={String(
                config.question_reference_address ?? t("选择引用变量")
              )}
              className="h-8 w-full justify-between border bg-background px-2 text-xs"
              onInsert={(reference) =>
                updateConfig({ question_reference_address: reference })
              }
            />
          </div>
          <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
            <legend className="text-xs font-medium">{t("重排内容")}</legend>
            {rerankerReferences.map((reference, index) => (
              <div
                key={`${reference}-${index}`}
                className="flex min-w-0 items-center gap-2"
              >
                <VariablePicker
                  nodeId={nodeId}
                  node={node}
                  t={t}
                  disabled={readOnly}
                  label={reference}
                  className="h-8 min-w-0 flex-1 justify-between border bg-background px-2 text-xs"
                  onInsert={(nextReference) =>
                    updateConfig({
                      reranker_reference_list: rerankerReferences.map(
                        (item, itemIndex) =>
                          itemIndex === index ? nextReference : item
                      ),
                    })
                  }
                />
                <IconButton
                  label={t("删除")}
                  className="size-7"
                  disabled={readOnly}
                  onClick={() =>
                    updateConfig({
                      reranker_reference_list: rerankerReferences.filter(
                        (_, itemIndex) => itemIndex !== index
                      ),
                    })
                  }
                >
                  <XIcon className="size-3.5" />
                </IconButton>
              </div>
            ))}
            {!readOnly ? (
              <VariablePicker
                nodeId={nodeId}
                node={node}
                t={t}
                label={t("添加引用")}
                className="h-8 w-full justify-center border border-dashed bg-background px-2 text-xs"
                onInsert={(reference) =>
                  updateConfig({
                    reranker_reference_list: [...rerankerReferences, reference],
                  })
                }
              />
            ) : null}
          </fieldset>
          {(
            [
              ["top_n", "引用分段数", 1, 50, 1],
              ["similarity", "相似度", 0, 2, 0.1],
              ["max_paragraph_char_number", "最大引用字符数", 1, 20000, 100],
            ] as const
          ).map(([key, label, min, max, step]) => (
            <div
              key={key}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <label
                htmlFor={`${nodeId}-reranker-${key}`}
                className="text-muted-foreground"
              >
                {t(label)}
              </label>
              <NumberStepper
                id={`${nodeId}-reranker-${key}`}
                value={Number(
                  rerankerSetting[key] ??
                    (key === "max_paragraph_char_number"
                      ? 5000
                      : key === "top_n"
                        ? 3
                        : 0)
                )}
                min={min}
                max={max}
                step={step}
                readOnly={readOnly}
                t={t}
                onChange={(value) =>
                  updateConfig({
                    reranker_setting: { ...rerankerSetting, [key]: value },
                  })
                }
              />
            </div>
          ))}
        </div>
      ) : null}
      {node.type === "form-node" ? (
        <div className="grid gap-3">
          <fieldset className="grid gap-2">
            <legend className="text-xs font-medium">{t("表单字段")}</legend>
            {formFields.map((field, index) => (
              <section key={index} className="grid gap-2 rounded-lg border p-2">
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    value={field.variable}
                    readOnly={readOnly}
                    aria-label={t("字段名")}
                    placeholder={t("字段名")}
                    onChange={(event) =>
                      updateFormField(index, { variable: event.target.value })
                    }
                  />
                  <Input
                    value={field.name}
                    readOnly={readOnly}
                    aria-label={t("显示名称")}
                    placeholder={t("显示名称")}
                    onChange={(event) =>
                      updateFormField(index, { name: event.target.value })
                    }
                  />
                </div>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-8 justify-between px-2 text-xs font-normal"
                      disabled={readOnly}
                    >
                      {t(
                        field.type === "select"
                          ? "下拉选择"
                          : field.type === "date"
                            ? "日期"
                            : field.type === "number"
                              ? "数字"
                              : field.type === "textarea"
                                ? "多行文本"
                                : "输入框"
                      )}
                      <ChevronDownIcon className="size-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent className="w-(--radix-dropdown-menu-trigger-width)">
                    {(
                      ["input", "textarea", "select", "date", "number"] as const
                    ).map((type) => (
                      <DropdownMenuItem
                        key={type}
                        onSelect={() => updateFormField(index, { type })}
                      >
                        {t(
                          type === "select"
                            ? "下拉选择"
                            : type === "date"
                              ? "日期"
                              : type === "number"
                                ? "数字"
                                : type === "textarea"
                                  ? "多行文本"
                                  : "输入框"
                        )}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
                {field.type === "select" ? (
                  <FormOptionsInput
                    value={field.optionList}
                    readOnly={readOnly}
                    onChange={(optionList) =>
                      updateFormField(index, { optionList })
                    }
                    t={t}
                  />
                ) : null}
                <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={field.is_required}
                      disabled={readOnly}
                      onChange={(event) =>
                        updateFormField(index, {
                          is_required: event.target.checked,
                        })
                      }
                    />
                    {t("必填")}
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={field.show_default_value}
                      disabled={readOnly}
                      onChange={(event) =>
                        updateFormField(index, {
                          show_default_value: event.target.checked,
                        })
                      }
                    />
                    {t("预填默认值")}
                  </label>
                  {!readOnly ? (
                    <button
                      type="button"
                      className="ml-auto text-destructive"
                      onClick={() =>
                        updateConfig({
                          form_field_list: formFields.filter(
                            (_, fieldIndex) => fieldIndex !== index
                          ),
                        })
                      }
                    >
                      {t("删除")}
                    </button>
                  ) : null}
                </div>
                {field.show_default_value ? (
                  <Input
                    value={String(field.default_value ?? "")}
                    readOnly={readOnly}
                    aria-label={t("默认值")}
                    placeholder={t("默认值")}
                    onChange={(event) =>
                      updateFormField(index, {
                        default_value: event.target.value,
                      })
                    }
                  />
                ) : null}
              </section>
            ))}
            {!readOnly ? (
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  updateConfig({
                    form_field_list: [
                      ...formFields,
                      {
                        variable: `field_${formFields.length + 1}`,
                        name: "",
                        type: "input",
                        is_required: false,
                        default_value: "",
                        show_default_value: false,
                        optionList: [],
                      },
                    ],
                  })
                }
              >
                <PlusIcon />
                {t("添加字段")}
              </Button>
            ) : null}
          </fieldset>
          <TextEditor
            id={`${nodeId}-form-content`}
            label={t("表单输出内容")}
            value={config.form_content_format ?? "{{ form }}"}
            readOnly={readOnly}
            rows={4}
            onChange={(form_content_format) =>
              updateConfig({ form_content_format })
            }
            node={node}
            nodeId={nodeId}
            t={t}
          />
          <label className="flex items-center gap-2 text-xs font-medium">
            <input
              type="checkbox"
              checked={config.is_result !== false}
              disabled={readOnly}
              onChange={(event) =>
                updateConfig({ is_result: event.target.checked })
              }
            />
            {t("返回内容")}
          </label>
        </div>
      ) : null}
      {node.type === "document-extract-node" ? (
        <TextEditor
          id={`${nodeId}-document-list`}
          label={t("文档")}
          value={config.document_list ?? ""}
          readOnly={readOnly}
          rows={2}
          onChange={(document_list) => updateConfig({ document_list })}
          node={node}
          nodeId={nodeId}
          t={t}
          insertVariables
        />
      ) : null}
      {node.type === "condition" ? (
        <ConditionEditor
          nodeId={nodeId}
          node={node}
          readOnly={readOnly}
          onUpdate={onUpdate}
          t={t}
        />
      ) : null}
      {node.type === "template" ? (
        <TextEditor
          id={`${nodeId}-template-value`}
          label={t("模板内容")}
          value={config.template ?? ""}
          readOnly={readOnly}
          rows={8}
          onChange={(template) => updateConfig({ template })}
          node={node}
          nodeId={nodeId}
          t={t}
          insertVariables
        />
      ) : null}
      {node.type === "variable" ? (
        <JsonEditor
          id={`${nodeId}-variable-value`}
          label={t("变量值")}
          value={config.value ?? null}
          readOnly={readOnly}
          onChange={(value) => updateConfig({ value })}
          t={t}
        />
      ) : null}
      {node.type === "tool" ? (
        <>
          <label className="grid gap-1.5 text-xs font-medium">
            {t("工具")}
            <Input
              value={
                (selectedDirectTool
                  ? toolDisplayName(selectedDirectTool, t)
                  : undefined) ??
                directToolReference?.tool_id ??
                ""
              }
              readOnly
              disabled
            />
          </label>
          <label className="grid gap-1.5 text-xs font-medium">
            {t("已发布版本")}
            <Input
              value={directToolReference?.version_id ?? ""}
              readOnly
              disabled
            />
          </label>
          {directToolUnavailable ? (
            <div
              role="alert"
              className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs leading-5 text-amber-900 dark:text-amber-200"
            >
              <p className="font-medium">{t("工具已不可用或授权已撤销")}</p>
              <p>{t("可从节点菜单移除该工具")}</p>
            </div>
          ) : !readOnly && directToolHasNewVersion ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                if (!selectedDirectTool || !directToolCurrentVersionId) return
                updateConfig({
                  tool: {
                    tool_id: selectedDirectTool.id,
                    version_id: directToolCurrentVersionId,
                  },
                })
              }}
            >
              {t("升级到当前版本")}
            </Button>
          ) : null}
          <ToolArgumentsFields
            key={`${directToolReference?.tool_id ?? "tool"}:${directToolReference?.version_id ?? "version"}`}
            nodeId={nodeId}
            tool={directToolWithMatchingSchema}
            value={directToolArguments}
            readOnly={readOnly}
            onChange={(argumentsValue) =>
              updateConfig({ arguments: argumentsValue })
            }
            t={t}
          />
        </>
      ) : null}
      {node.type === "agent" ? (
        <>
          <label className="grid gap-1.5 text-xs font-medium">
            {t("Agent")}
            <Input
              value={selectedAgent?.name ?? selectedAgentId}
              readOnly
              disabled
            />
          </label>
          <label className="grid gap-1.5 text-xs font-medium">
            {t("已发布版本")}
            <Input value={selectedAgentVersionId} readOnly disabled />
          </label>
          <TextEditor
            id={`${nodeId}-agent-input`}
            label={t("输入内容")}
            value={config.input ?? ""}
            readOnly={readOnly}
            rows={4}
            onChange={(input) => updateConfig({ input })}
            node={node}
            nodeId={nodeId}
            t={t}
            insertVariables
          />
        </>
      ) : null}
      {node.type === "mcp" ? (
        <>
          <fieldset className="grid gap-1.5 text-xs font-medium">
            <legend>{t("MCP 工具")}</legend>
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button
                  id={`${nodeId}-mcp-tool`}
                  type="button"
                  variant="outline"
                  className="h-8 w-full justify-between px-2 text-xs font-normal"
                  disabled={readOnly || !availableMcp.length}
                >
                  <span className="min-w-0 truncate text-left">
                    {availableMcp.find(
                      (item) =>
                        item.server_id === String(config.server_id ?? "") &&
                        item.tool_name === String(config.tool_name ?? "")
                    )?.label ?? t("选择只读 MCP 工具")}
                  </span>
                  <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                className="max-h-72 w-(--radix-dropdown-menu-trigger-width) overflow-y-auto"
              >
                {availableMcp.map((item) => {
                  const selected =
                    item.server_id === String(config.server_id ?? "") &&
                    item.tool_name === String(config.tool_name ?? "")
                  return (
                    <DropdownMenuItem
                      key={`${item.server_id}:${item.tool_name}`}
                      className="justify-between"
                      onSelect={() =>
                        updateConfig({
                          server_id: item.server_id,
                          tool_name: item.tool_name,
                        })
                      }
                    >
                      <span className="min-w-0 truncate">{item.label}</span>
                      {selected ? <CheckIcon className="text-primary" /> : null}
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          </fieldset>
          <JsonEditor
            id={`${nodeId}-mcp-arguments`}
            label={t("工具参数")}
            value={config.arguments ?? {}}
            readOnly={readOnly}
            onChange={(argumentsValue) =>
              updateConfig({ arguments: argumentsValue })
            }
            t={t}
          />
        </>
      ) : null}
      {node.type === "code" ? (
        <>
          <JsonEditor
            id={`${nodeId}-code-inputs`}
            label={t("代码输入")}
            value={config.inputs ?? {}}
            readOnly={readOnly}
            onChange={(inputs) => updateConfig({ inputs })}
            t={t}
          />
          <TextEditor
            id={`${nodeId}-code-body`}
            label={t("Python 代码")}
            value={config.code ?? ""}
            readOnly={readOnly}
            rows={10}
            onChange={(code) => updateConfig({ code })}
            node={node}
            nodeId={nodeId}
            t={t}
          />
        </>
      ) : null}
    </div>
  )
}

export function WorkflowNodeCard({ data, selected, id }: NodeProps) {
  const { t } = useLanguage()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const node = data as WorkflowNodeData
  const Icon = NODE_ICONS[node.type]
  const status = node.runtimeStatus
  const config = node.config
  const branches = node.type === "condition" ? conditionBranches(config) : []
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
  const StatusIcon = status ? STATUS_ICONS[status] : CircleDotDashedIcon
  const summary = configSummary(node, t)
  const [expanded, setExpanded] = React.useState(true)
  const [settingsOpen, setSettingsOpen] = React.useState(false)
  const [renaming, setRenaming] = React.useState(false)
  const [title, setTitle] = React.useState(node.title)
  const sourceHandles =
    node.type === "condition" && expanded
      ? []
      : node.type === "condition"
        ? branches.map((branch) => branch.id)
        : node.type === "classifier"
          ? classifierHandles
          : node.type === "end"
            ? []
            : [null]
  const outputFields = outputFieldNames(node)
  const canOperate = !node.readOnly && !["start", "end"].includes(node.type)
  const canRename = !node.readOnly && node.type === "start"
  const onRename = node.onRename as
    ((nodeId: string, title: string) => void) | undefined
  const onCopy = node.onCopy as ((nodeId: string) => void) | undefined
  const onDelete = node.onDelete as ((nodeId: string) => void) | undefined
  const onUpdate = node.onUpdate as
    ((data: WorkflowNodeData) => void) | undefined
  const nodeId = id

  const toggleExpanded = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    setExpanded((current) => !current)
  }

  const commitTitle = () => {
    const nextTitle = title.trim()
    if (nextTitle && nextTitle !== node.title) onRename?.(nodeId, nextTitle)
    if (!nextTitle) setTitle(node.title)
    setRenaming(false)
  }

  return (
    <div
      className={cn(
        "group relative min-h-24 rounded-xl border bg-card px-3.5 py-3 shadow-md transition-[border-color,box-shadow,opacity] hover:shadow-lg",
        node.type === "condition"
          ? "w-80"
          : [
                "llm",
                "knowledge",
                "reply-node",
                "reranker-node",
                "form-node",
                "agent",
              ].includes(node.type)
            ? "w-80"
            : "w-64",
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
          {renaming ? (
            <input
              autoFocus
              className="nodrag block h-6 w-full rounded border bg-background px-1.5 text-sm font-semibold outline-none focus:ring-2 focus:ring-ring"
              value={title}
              maxLength={120}
              aria-label={t("节点名称")}
              onChange={(event) => setTitle(event.target.value)}
              onBlur={commitTitle}
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                event.stopPropagation()
                if (event.key === "Enter") event.currentTarget.blur()
                if (event.key === "Escape") {
                  setTitle(node.title)
                  setRenaming(false)
                }
              }}
            />
          ) : (
            <span className="block truncate text-sm leading-5 font-semibold">
              {node.title}
            </span>
          )}
          <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
            {workflowNodeLabel(node.type, t)}
          </span>
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {status ? (
            <span
              className={cn(
                "mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium",
                status === "running" &&
                  "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400",
                status === "awaiting_input" &&
                  "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400",
                status === "awaiting_child" &&
                  "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400",
                status === "succeeded" &&
                  "border-foreground/15 bg-muted text-foreground",
                status === "failed" &&
                  "border-destructive/30 bg-destructive/10 text-destructive",
                status === "skipped" &&
                  "border-muted-foreground/30 bg-muted text-muted-foreground"
              )}
              title={t(STATUS_LABELS[status])}
            >
              <StatusIcon
                className={cn("size-3", status === "running" && "animate-spin")}
              />
              <span className="sr-only">{t(STATUS_LABELS[status])}</span>
            </span>
          ) : null}
          {node.type === "llm" && onUpdate ? (
            <IconButton
              label={t("高级模型设置")}
              className="nodrag"
              onClick={(event) => {
                event.stopPropagation()
                setSettingsOpen(true)
              }}
            >
              <SettingsIcon className="size-3.5" />
            </IconButton>
          ) : null}
          <IconButton
            label={expanded ? t("收起节点") : t("展开节点")}
            className="nodrag"
            aria-expanded={expanded}
            onClick={toggleExpanded}
          >
            {expanded ? (
              <ChevronUpIcon className="size-3.5" />
            ) : (
              <ChevronDownIcon className="size-3.5" />
            )}
          </IconButton>
          {canOperate ? (
            <span className="nodrag">
              <CardMoreMenu label={t("更多")}>
                <DropdownMenuItem
                  onSelect={() => {
                    setTitle(node.title)
                    setRenaming(true)
                  }}
                >
                  <PencilIcon />
                  {t("重命名")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => onCopy?.(nodeId)}>
                  <CopyIcon />
                  {t("复制节点")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() => {
                    void confirmAction({
                      description: t("确定删除节点“{name}”吗？", {
                        name: node.title,
                      }),
                      confirmLabel: t("删除"),
                      destructive: true,
                    }).then((confirmed) => {
                      if (confirmed) onDelete?.(nodeId)
                    })
                  }}
                >
                  <Trash2Icon />
                  {t("删除节点")}
                </DropdownMenuItem>
              </CardMoreMenu>
            </span>
          ) : canRename ? (
            <span className="nodrag">
              <CardMoreMenu label={t("更多")}>
                <DropdownMenuItem
                  onSelect={() => {
                    setTitle(node.title)
                    setRenaming(true)
                  }}
                >
                  <PencilIcon />
                  {t("重命名")}
                </DropdownMenuItem>
              </CardMoreMenu>
            </span>
          ) : null}
        </div>
      </div>
      {summary ? (
        <div className="mt-3 border-t border-border/70 pt-2 text-[11px] text-muted-foreground">
          <span className="block truncate">{summary}</span>
        </div>
      ) : null}
      {expanded &&
      ![
        "knowledge",
        "llm",
        "condition",
        "reply-node",
        "code",
        "document-extract-node",
        "form-node",
      ].includes(node.type) ? (
        <div className="mt-2 space-y-1.5 border-t border-border/70 pt-2">
          {node.type === "start" ? (
            <>
              <p className="px-1 text-[10px] font-medium text-muted-foreground">
                {t("全局变量")}
              </p>
              {WORKFLOW_START_GLOBALS.map((field) => (
                <OutputFieldRow
                  key={field.value}
                  label={t(field.label)}
                  reference={`{{global.${field.value}}}`}
                  t={t}
                />
              ))}
              <p className="px-1 pt-1 text-[10px] font-medium text-muted-foreground">
                {t("输入字段")}
              </p>
              {WORKFLOW_START_FIELDS.map((field) => (
                <OutputFieldRow
                  key={field.value}
                  label={t(field.label)}
                  reference={`{{${id}.${field.value}}}`}
                  t={t}
                />
              ))}
            </>
          ) : (
            outputFields.map((field) => (
              <OutputFieldRow
                key={field}
                displayValue={outputFieldLabel(node.type, field, t)}
                reference={`{{${id}.${field}}}`}
                t={t}
              />
            ))
          )}
        </div>
      ) : null}
      {expanded &&
      onUpdate &&
      node.agent &&
      node.models &&
      node.knowledgeBases &&
      node.mcpServers &&
      node.tools &&
      node.agents ? (
        <div className="nodrag mt-2 border-t border-border/70 pt-2">
          <NodeConfigFields
            nodeId={nodeId}
            node={node}
            agent={node.agent}
            models={node.models}
            knowledgeBases={node.knowledgeBases}
            mcpServers={node.mcpServers}
            tools={node.tools}
            agents={node.agents}
            readOnly={Boolean(node.readOnly)}
            onUpdate={onUpdate}
            t={t}
          />
        </div>
      ) : null}
      {expanded &&
      (node.type === "code" ||
        node.type === "document-extract-node" ||
        node.type === "form-node") ? (
        <div className="mt-2 space-y-1.5 border-t border-border/70 pt-2">
          {outputFields.map((field) => (
            <OutputFieldRow
              key={field}
              displayValue={outputFieldLabel(node.type, field, t)}
              reference={`{{${id}.${field}}}`}
              t={t}
            />
          ))}
        </div>
      ) : null}
      {node.type === "llm" && onUpdate ? (
        <LlmSettingsDialog
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          nodeId={nodeId}
          node={node}
          readOnly={Boolean(node.readOnly)}
          onUpdate={onUpdate}
          t={t}
        />
      ) : null}
      {sourceHandles.map((handle, index) => (
        <React.Fragment key={handle ?? "default"}>
          {handle && node.type !== "condition" ? (
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
      {confirmDialog}
    </div>
  )
}

function OutputFieldRow({
  label,
  displayValue,
  reference,
  t,
}: {
  label?: string
  displayValue?: string
  reference: string
  t: TFunction
}) {
  const { notify } = useSession()

  return (
    <div className="flex w-full min-w-0 items-center gap-2 overflow-hidden rounded-md bg-muted/50 px-2 py-1.5">
      {label ? (
        <span className="shrink-0 text-[10px] font-medium text-muted-foreground">
          {label}
        </span>
      ) : null}
      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
        {displayValue ?? reference}
      </span>
      <IconButton
        label={t("复制变量")}
        className="size-6"
        onClick={(event) => {
          event.stopPropagation()
          void copyText(reference)
            .then(() => notify("success", t("已复制")))
            .catch(() => notify("error", t("复制失败")))
        }}
      >
        <CopyIcon className="size-3" />
      </IconButton>
    </div>
  )
}

function outputFieldNames(node: WorkflowNodeData) {
  const config = node.config
  if (
    node.type === "end" &&
    config.outputs &&
    typeof config.outputs === "object"
  ) {
    return Object.keys(config.outputs)
  }
  if (node.type === "classifier" && Array.isArray(config.classes)) {
    return config.classes.flatMap((item) =>
      item &&
      typeof item === "object" &&
      typeof (item as Record<string, unknown>).handle === "string"
        ? [String((item as Record<string, unknown>).handle)]
        : []
    )
  }
  if (node.type === "tool" && config.tool && typeof config.tool === "object") {
    const reference = config.tool as Partial<ToolRef>
    const tool = node.tools?.find(
      (item) =>
        item.id === reference.tool_id &&
        item.version_id === reference.version_id
    )
    const properties =
      tool?.output_schema?.properties &&
      typeof tool.output_schema.properties === "object"
        ? Object.keys(tool.output_schema.properties)
        : []
    return properties.length ? properties : ["result"]
  }
  const fields: Partial<Record<WorkflowNodeType, string[]>> = {
    classifier: ["class"],
    knowledge: KNOWLEDGE_OUTPUT_FIELDS.map((item) => item.field),
    "reranker-node": ["result_list", "result"],
    "form-node": [
      ...(Array.isArray(config.form_field_list)
        ? config.form_field_list.flatMap((item) =>
            item && typeof item === "object" && "variable" in item
              ? [String((item as Record<string, unknown>).variable)]
              : []
          )
        : []),
      "form_data",
      "result",
    ],
    "document-extract-node": ["content"],
    condition: ["branch_name"],
    "reply-node": ["answer"],
    template: ["text"],
    variable: ["value"],
    agent: ["result"],
    mcp: ["result"],
    code: ["result", "stdout", "stderr"],
  }
  return fields[node.type] ?? []
}

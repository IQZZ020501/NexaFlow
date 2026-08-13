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
  ChevronDownIcon,
  ChevronUpIcon,
  CopyIcon,
  PlusIcon,
  XIcon,
} from "lucide-react"
import { Handle, Position, type NodeProps } from "@xyflow/react"

import { useLanguage } from "@/contexts/language-provider"
import type { TFunction, TranslationKey } from "@/i18n"
import type { Agent } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import type {
  WorkflowNodeData,
  WorkflowNodeType,
} from "@/lib/api/workflows"
import { cn } from "@/lib/utils"
import {
  WORKFLOW_START_FIELDS,
  WORKFLOW_START_GLOBALS,
  upstreamWorkflowFields,
} from "@/lib/workflows/graph"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { IconButton } from "@/components/ui/icon-button"

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
  succeeded: "",
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
  start: "bg-muted text-muted-foreground",
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
    case "start":
      return null
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
        greater_than_or_equal: "大于等于",
        less_than: "小于",
        less_than_or_equal: "小于等于",
        is_empty: "为空",
        is_not_empty: "不为空",
        length_equals: "长度等于",
        length_greater_than: "长度大于",
        length_greater_than_or_equal: "长度大于等于",
        length_less_than: "长度小于",
        length_less_than_or_equal: "长度小于等于",
        is_true: "为真",
        is_false: "为假",
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
    <label className="grid gap-1.5 text-xs font-medium" htmlFor={id}>
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
        <span className="font-normal text-destructive">{t("JSON 格式无效")}</span>
      ) : null}
    </label>
  )
}

function VariablePicker({
  nodeId,
  node,
  t,
  onInsert,
}: {
  nodeId: string
  node: WorkflowNodeData
  t: TFunction
  onInsert: (reference: string) => void
}) {
  const [open, setOpen] = React.useState(false)
  const upstream = React.useMemo(() => {
    const nodes = node.nodes ?? []
    const edges = node.edges ?? []
    return upstreamWorkflowFields(nodes, edges, nodeId, outputFieldNames)
  }, [node.edges, node.nodes, nodeId])
  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          className="h-6 px-1.5 text-[11px] font-normal text-muted-foreground"
        >
          <BracesIcon className="size-3.5" />
          {t("插入变量")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 w-60 overflow-y-auto">
        <p className="px-2 pt-1.5 pb-0.5 text-[10px] font-medium text-muted-foreground">
          {t("全局变量")}
        </p>
        {WORKFLOW_START_GLOBALS.map((field) => (
          <DropdownMenuItem
            key={field.value}
            onSelect={() => {
              onInsert(`{{global.${field.value}}}`)
              setOpen(false)
            }}
          >
            <span className="min-w-0 flex-1 truncate font-mono text-xs">
              {`{{global.${field.value}}}`}
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
              {group.fields.map((field) => (
                <DropdownMenuItem
                  key={field}
                  onSelect={() => {
                    onInsert(`{{${group.id}.${field}}}`)
                    setOpen(false)
                  }}
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">
                    {`{{${group.id}.${field}}}`}
                  </span>
                </DropdownMenuItem>
              ))}
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
  const insertReference = React.useCallback(
    (reference: string) => {
      const textarea = textareaRef.current
      const start = textarea?.selectionStart ?? (typeof value === "string" ? value.length : 0)
      const end = textarea?.selectionEnd ?? start
      onChange(
        `${typeof value === "string" ? value : JSON.stringify(value)}`
          .slice(0, start) + reference + `${typeof value === "string" ? value : JSON.stringify(value)}`.slice(end)
      )
      requestAnimationFrame(() => {
        textarea?.focus()
        textarea?.setSelectionRange(start + reference.length, start + reference.length)
      })
    },
    [onChange, value]
  )
  return (
    <label className="grid gap-1.5 text-xs font-medium" htmlFor={id}>
      <span className="flex items-center justify-between gap-2">
        {label}
        {insertVariables && !readOnly ? (
          <VariablePicker nodeId={nodeId} node={node} t={t} onInsert={insertReference} />
        ) : null}
      </span>
      <textarea
        ref={textareaRef}
        id={id}
        rows={rows}
        className="resize-y rounded-md border bg-background px-2.5 py-2 text-sm leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
        value={typeof value === "string" ? value : JSON.stringify(value)}
        readOnly={readOnly}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

function NodeConfigFields({
  nodeId,
  node,
  agent,
  models,
  knowledgeBases,
  mcpServers,
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
    if (outputEntries.some(([itemKey], i) => i !== index && itemKey === key)) return
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
      outputs: Object.fromEntries(
        outputEntries.filter((_, i) => i !== index)
      ),
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
  const boundKnowledge = knowledgeBases.filter((item) =>
    agent.knowledge_base_ids.includes(item.id)
  )
  const selectedKnowledgeIds = Array.isArray(config.knowledge_base_ids)
    ? config.knowledge_base_ids.map(String)
    : config.knowledge_base_id
      ? [String(config.knowledge_base_id)]
      : []
  const boundMcp = agent.mcp_tools
    .map((reference) => {
      const server = mcpServers.find((item) => item.id === reference.server_id)
      const tool = server?.tools.find(
        (item) => item.name === reference.tool_name
      )
      return {
        ...reference,
        policyMode: tool?.policy_mode,
        label: `${server?.name ?? reference.server_id} / ${reference.tool_name}`,
      }
    })
    .filter((item) => item.policyMode === "read_only")
  const conditionOperator = String(config.operator ?? "equals")
  const conditionHasRightValue = ![
    "is_empty",
    "is_not_empty",
    "is_true",
    "is_false",
  ].includes(conditionOperator)
  const conditionUsesLength = conditionOperator.startsWith("length_")

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
                  updateOutputItem(index, event.target.value, String(value ?? ""))
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
          <label className="grid gap-1.5 text-xs font-medium" htmlFor={`${nodeId}-llm-model`}>
            {t("节点模型")}
            <select
              id={`${nodeId}-llm-model`}
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={String(config.model_id ?? "")}
              disabled={readOnly}
              onChange={(event) =>
                updateConfig({ model_id: event.target.value || null })
              }
            >
              <option value="">{t("使用工作流默认模型")}</option>
              {activeModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))}
            </select>
          </label>
          <TextEditor
            id={`${nodeId}-llm-system`}
            label={t("系统提示词")}
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
            label={t("用户提示词")}
            value={config.prompt ?? ""}
            readOnly={readOnly}
            rows={6}
            onChange={(prompt) => updateConfig({ prompt })}
            node={node}
            nodeId={nodeId}
            t={t}
            insertVariables
          />
        </>
      ) : null}
      {node.type === "classifier" ? (
        <>
          <label className="grid gap-1.5 text-xs font-medium" htmlFor={`${nodeId}-classifier-model`}>
            {t("节点模型")}
            <select
              id={`${nodeId}-classifier-model`}
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={String(config.model_id ?? "")}
              disabled={readOnly}
              onChange={(event) =>
                updateConfig({ model_id: event.target.value || null })
              }
            >
              <option value="">{t("使用工作流默认模型")}</option>
              {activeModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))}
            </select>
          </label>
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
          <label className="grid gap-1.5 text-xs font-medium" htmlFor={`${nodeId}-classifier-default`}>
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
        <>
          <fieldset className="grid gap-1.5 text-xs font-medium">
            <legend>
              {t("知识库（可多选）")}
            </legend>
            <div className="grid max-h-32 gap-2 overflow-y-auto rounded-md border bg-background p-2">
              {boundKnowledge.length ? (
                boundKnowledge.map((item) => (
                  <label
                    key={item.id}
                    className="flex items-center gap-2 text-xs font-normal"
                  >
                    <input
                      type="checkbox"
                      checked={selectedKnowledgeIds.includes(item.id)}
                      disabled={readOnly}
                      onChange={(event) =>
                        updateConfig({
                          knowledge_base_id: null,
                          knowledge_base_ids: event.target.checked
                            ? [...selectedKnowledgeIds, item.id]
                            : selectedKnowledgeIds.filter(
                                (knowledgeBaseId) => knowledgeBaseId !== item.id
                              ),
                        })
                      }
                    />
                    <span className="min-w-0 truncate">{item.name}</span>
                  </label>
                ))
              ) : (
                <span className="font-normal text-muted-foreground">
                  {t("暂无可用知识库")}
                </span>
              )}
            </div>
          </fieldset>
          <label className="grid gap-1.5 text-xs font-medium" htmlFor={`${nodeId}-knowledge-limit`}>
            {t("返回条数")}
            <Input
              id={`${nodeId}-knowledge-limit`}
              type="number"
              min={1}
              max={8}
              value={Number(config.limit ?? 3)}
              readOnly={readOnly}
              onChange={(event) => updateConfig({ limit: Number(event.target.value) })}
            />
          </label>
          <TextEditor
            id={`${nodeId}-knowledge-query`}
            label={t("检索查询")}
            value={config.query ?? ""}
            readOnly={readOnly}
            onChange={(query) => updateConfig({ query })}
            node={node}
            nodeId={nodeId}
            t={t}
            insertVariables
          />
        </>
      ) : null}
      {node.type === "condition" ? (
        <>
          <TextEditor
            id={`${nodeId}-condition-left`}
            label={t("左值")}
            value={config.left ?? ""}
            readOnly={readOnly}
            onChange={(left) => updateConfig({ left })}
            node={node}
            nodeId={nodeId}
            t={t}
            insertVariables
          />
          <label className="grid gap-1.5 text-xs font-medium" htmlFor={`${nodeId}-condition-operator`}>
            {t("运算符")}
            <select
              id={`${nodeId}-condition-operator`}
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={String(config.operator ?? "equals")}
              disabled={readOnly}
              onChange={(event) =>
                updateConfig({ operator: event.target.value })
              }
            >
              {([
                ["equals", "等于"],
                ["not_equals", "不等于"],
                ["contains", "包含"],
                ["not_contains", "不包含"],
                ["greater_than", "大于"],
                ["greater_than_or_equal", "大于等于"],
                ["less_than", "小于"],
                ["less_than_or_equal", "小于等于"],
                ["is_empty", "为空"],
                ["is_not_empty", "不为空"],
                ["length_equals", "长度等于"],
                ["length_greater_than", "长度大于"],
                ["length_greater_than_or_equal", "长度大于等于"],
                ["length_less_than", "长度小于"],
                ["length_less_than_or_equal", "长度小于等于"],
                ["is_true", "为真"],
                ["is_false", "为假"],
              ] as const).map(([operator, label]) => (
                <option key={operator} value={operator}>
                  {t(label)}
                </option>
              ))}
            </select>
          </label>
          {conditionHasRightValue ? (
            conditionUsesLength ? (
              <label className="grid gap-1.5 text-xs font-medium" htmlFor={`${nodeId}-condition-right`}>
                {t("右值")}
                <Input
                  id={`${nodeId}-condition-right`}
                  type="number"
                  min={0}
                  step={1}
                  value={
                    typeof config.right === "number" ? config.right : 0
                  }
                  readOnly={readOnly}
                  onChange={(event) =>
                    updateConfig({ right: Number(event.target.value) })
                  }
                />
              </label>
            ) : (
              <JsonEditor
                id={`${nodeId}-condition-right`}
                label={t("右值")}
                value={config.right ?? ""}
                readOnly={readOnly}
                onChange={(right) => updateConfig({ right })}
                t={t}
              />
            )
          ) : null}
        </>
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
      {node.type === "mcp" ? (
        <>
          <label className="grid gap-1.5 text-xs font-medium" htmlFor={`${nodeId}-mcp-tool`}>
            {t("MCP 工具")}
            <select
              id={`${nodeId}-mcp-tool`}
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={`${String(config.server_id ?? "")}:${String(config.tool_name ?? "")}`}
              disabled={readOnly}
              onChange={(event) => {
                const [server_id, ...name] = event.target.value.split(":")
                updateConfig({ server_id, tool_name: name.join(":") })
              }}
            >
              <option value=":">{t("选择只读 MCP 工具")}</option>
              {boundMcp.map((item) => (
                <option
                  key={`${item.server_id}:${item.tool_name}`}
                  value={`${item.server_id}:${item.tool_name}`}
                >
                  {item.label}
                </option>
              ))}
            </select>
          </label>
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
          <JsonEditor
            id={`${nodeId}-code-inputs`}
            label={t("代码输入")}
            value={config.inputs ?? {}}
            readOnly={readOnly}
            onChange={(inputs) => updateConfig({ inputs })}
            t={t}
          />
        </>
      ) : null}
    </div>
  )
}

export function WorkflowNodeCard({ data, selected, id }: NodeProps) {
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
  const [expanded, setExpanded] = React.useState(node.type === "start" || node.type === "end")
  const [renaming, setRenaming] = React.useState(false)
  const [title, setTitle] = React.useState(node.title)
  const outputFields = outputFieldNames(node)
  const canOperate = !node.readOnly && !["start", "end"].includes(node.type)
  const canRename = !node.readOnly && node.type === "start"
  const onRename = node.onRename as
    | ((nodeId: string, title: string) => void)
    | undefined
  const onCopy = node.onCopy as ((nodeId: string) => void) | undefined
  const onDelete = node.onDelete as ((nodeId: string) => void) | undefined
  const onUpdate = node.onUpdate as
    | ((data: WorkflowNodeData) => void)
    | undefined
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
        "group relative min-h-24 w-64 rounded-xl border bg-card px-3.5 py-3 shadow-md transition-[border-color,box-shadow,opacity] hover:shadow-lg",
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
            <span className="block truncate text-sm font-semibold leading-5">
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
              status === "running" && "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400",
              status === "succeeded" && "border-foreground/15 bg-muted text-foreground",
              status === "failed" && "border-destructive/30 bg-destructive/10 text-destructive",
              status === "skipped" && "border-muted-foreground/30 bg-muted text-muted-foreground"
            )}
            title={t(STATUS_LABELS[status])}
          >
            <StatusIcon className={cn("size-3", status === "running" && "animate-spin")} />
            <span className="sr-only">{t(STATUS_LABELS[status])}</span>
          </span>
          ) : null}
          <IconButton
            label={expanded ? t("收起节点") : t("展开节点")}
            className="nodrag"
            aria-expanded={expanded}
            onClick={toggleExpanded}
          >
            {expanded ? <ChevronUpIcon className="size-3.5" /> : <ChevronDownIcon className="size-3.5" />}
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
                    if (window.confirm(t("确定删除节点“{name}”吗？", { name: node.title }))) {
                      onDelete?.(nodeId)
                    }
                  }}
                >
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
      {expanded ? (
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
                reference={`{{${id}.${field}}}`}
                t={t}
              />
            ))
          )}
        </div>
      ) : null}
      {expanded && onUpdate && node.agent && node.models && node.knowledgeBases && node.mcpServers ? (
        <div className="nodrag mt-2 border-t border-border/70 pt-2">
          <NodeConfigFields
            nodeId={nodeId}
            node={node}
            agent={node.agent}
            models={node.models}
            knowledgeBases={node.knowledgeBases}
            mcpServers={node.mcpServers}
            readOnly={Boolean(node.readOnly)}
            onUpdate={onUpdate}
            t={t}
          />
        </div>
      ) : null}
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

function OutputFieldRow({
  label,
  reference,
  t,
}: {
  label?: string
  reference: string
  t: TFunction
}) {
  return (
    <div className="flex items-center gap-2 rounded-md bg-muted/50 px-2 py-1.5">
      {label ? (
        <span className="shrink-0 text-[10px] font-medium text-muted-foreground">
          {label}
        </span>
      ) : null}
      <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted-foreground">
        {reference}
      </span>
      <IconButton
        label={t("复制变量")}
        className="size-6"
        onClick={(event) => {
          event.stopPropagation()
          void navigator.clipboard?.writeText(reference)
        }}
      >
        <CopyIcon className="size-3" />
      </IconButton>
    </div>
  )
}

function outputFieldNames(node: WorkflowNodeData) {
  const config = node.config
  if (node.type === "end" && config.outputs && typeof config.outputs === "object") {
    return Object.keys(config.outputs)
  }
  if (node.type === "classifier" && Array.isArray(config.classes)) {
    return config.classes.flatMap((item) =>
      item && typeof item === "object" && typeof (item as Record<string, unknown>).handle === "string"
        ? [String((item as Record<string, unknown>).handle)]
        : []
    )
  }
  const fields: Partial<Record<WorkflowNodeType, string[]>> = {
    llm: ["text"],
    classifier: ["class"],
    knowledge: ["content", "hits", "retrieval_stats", "evidence_status"],
    condition: ["matched"],
    template: ["text"],
    variable: ["value"],
    mcp: ["result"],
    code: ["result", "stdout", "stderr"],
  }
  return fields[node.type] ?? []
}

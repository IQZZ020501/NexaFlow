"use client"

import * as React from "react"
import {
  ArchiveIcon,
  BotIcon,
  BracesIcon,
  CircleCheckIcon,
  Code2Icon,
  ChevronDownIcon,
  LoaderCircleIcon,
  PlusIcon,
  PlayIcon,
  PowerIcon,
  RefreshCwIcon,
  SendIcon,
  Trash2Icon,
  WorkflowIcon,
} from "lucide-react"

import { useConfirmDialog } from "@/components/app/confirm-dialog"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { IconButton } from "@/components/ui/icon-button"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import {
  archivePythonTool,
  createPythonTool,
  getPythonToolTest,
  getTool,
  publishPythonTool,
  setPythonToolEnabled,
  testPythonTool,
  updatePythonToolDraft,
  type PythonToolPayload,
  type ToolDetail,
  type ToolInvocation,
  type ToolSummary,
} from "@/lib/api/tools"
import { getErrorMessage } from "@/lib/errors"

const TEXTAREA_CLASS =
  "min-h-24 w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"

type PythonForm = {
  displayName: string
  description: string
  inputSchema: string
  outputSchema: string
  code: string
  testArguments: string
}

const EMPTY_FORM: PythonForm = {
  displayName: "",
  description: "",
  inputSchema: JSON.stringify(
    { type: "object", properties: {}, additionalProperties: false },
    null,
    2
  ),
  outputSchema: JSON.stringify(
    { type: "object", properties: {}, additionalProperties: false },
    null,
    2
  ),
  code: "result = inputs",
  testArguments: "{}",
}

/**
 * Creates editable form data from the current tool details.
 *
 * @param detail - The tool details used to populate the form.
 * @returns Form data containing the tool's editable values and empty test arguments.
 */
function formFromDetail(detail: ToolDetail): PythonForm {
  const editable = detail.draft
  return {
    displayName: editable?.display_name ?? detail.display_name,
    description: editable?.description ?? detail.description,
    inputSchema: JSON.stringify(
      editable?.input_schema ?? detail.input_schema ?? {},
      null,
      2
    ),
    outputSchema: JSON.stringify(
      editable?.output_schema ?? detail.output_schema ?? {},
      null,
      2
    ),
    code: editable?.code ?? "",
    testArguments: "{}",
  }
}

/**
 * Parses a JSON string into an object value.
 *
 * @param value - The JSON string to parse
 * @returns The parsed object, or `null` if the string is invalid or does not contain a JSON object
 */
function parseObject(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value)
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

/**
 * Builds a Python tool payload from form values when all required fields and schemas are valid.
 *
 * @param form - The editable Python tool form values
 * @returns The normalized tool payload, or `null` when required values or schemas are invalid
 */
function payloadFromForm(form: PythonForm): PythonToolPayload | null {
  const inputSchema = parseObject(form.inputSchema)
  const outputSchema = parseObject(form.outputSchema)
  const displayName = form.displayName.trim()
  const code = form.code.trim()
  if (!displayName || !code || !inputSchema || !outputSchema) return null
  return {
    display_name: displayName,
    description: form.description.trim(),
    input_schema: inputSchema,
    output_schema: outputSchema,
    code,
  }
}

type SimpleSchemaType =
  "string" | "number" | "integer" | "boolean" | "object" | "array" | "custom"

type SchemaField = {
  name: string
  type: SimpleSchemaType
  description: string
  required: boolean
}

const SIMPLE_SCHEMA_TYPES: SimpleSchemaType[] = [
  "string",
  "number",
  "integer",
  "boolean",
  "object",
  "array",
]

function schemaTypeLabel(
  type: SimpleSchemaType,
  t: ReturnType<typeof useLanguage>["t"]
) {
  if (type === "string") return t("文本")
  if (type === "number") return t("数字")
  if (type === "integer") return t("整数")
  if (type === "boolean") return t("布尔值")
  if (type === "object") return t("JSON 对象")
  if (type === "array") return t("数组")
  return t("自定义")
}

function schemaType(value: unknown): SimpleSchemaType {
  return typeof value === "string" &&
    SIMPLE_SCHEMA_TYPES.includes(value as SimpleSchemaType)
    ? (value as SimpleSchemaType)
    : "custom"
}

function parseFlatSchema(value: string) {
  const parsed = parseObject(value)
  if (!parsed || parsed.type !== "object") return null
  const properties = parsed.properties
  if (
    properties !== undefined &&
    (!properties || typeof properties !== "object" || Array.isArray(properties))
  ) {
    return null
  }
  const required = new Set(
    Array.isArray(parsed.required) ? parsed.required.map(String) : []
  )
  const fields = Object.entries(
    (properties as Record<string, unknown> | undefined) ?? {}
  ).map(([name, value]) => {
    const property =
      value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
    return {
      name,
      type: schemaType(property.type),
      description:
        typeof property.description === "string" ? property.description : "",
      required: required.has(name),
    } satisfies SchemaField
  })
  return { parsed, fields }
}

function simplePropertySchema(
  type: SimpleSchemaType,
  description: string
): Record<string, unknown> {
  const property: Record<string, unknown> = {
    type: type === "custom" ? "string" : type,
  }
  if (property.type === "string") property.maxLength = 4096
  if (property.type === "array") {
    property.maxItems = 100
    property.items = { type: "string", maxLength: 4096 }
  }
  if (property.type === "object") {
    property.properties = {}
    property.additionalProperties = false
  }
  if (description.trim()) property.description = description.trim()
  return property
}

function updateFlatSchema(
  value: string,
  fieldName: string,
  update: Partial<SchemaField>
) {
  const parsed = parseObject(value)
  if (!parsed || parsed.type !== "object") return value
  const properties = parsed.properties
  if (
    !properties ||
    typeof properties !== "object" ||
    Array.isArray(properties)
  ) {
    return value
  }
  const propertyMap = properties as Record<string, unknown>
  const current = propertyMap[fieldName]
  if (!current || typeof current !== "object" || Array.isArray(current)) {
    return value
  }
  const currentProperty = current as Record<string, unknown>
  const nextName = update.name?.trim() || fieldName
  const nextProperty = { ...currentProperty }
  if (update.type && update.type !== schemaType(currentProperty.type)) {
    Object.assign(
      nextProperty,
      simplePropertySchema(
        update.type,
        update.description ??
          (typeof currentProperty.description === "string"
            ? currentProperty.description
            : "")
      )
    )
  } else if (update.description !== undefined) {
    if (update.description.trim())
      nextProperty.description = update.description.trim()
    else delete nextProperty.description
  }
  const nextProperties = { ...propertyMap }
  if (nextName !== fieldName && nextName in nextProperties) return value
  if (nextName !== fieldName) delete nextProperties[fieldName]
  nextProperties[nextName] = nextProperty
  parsed.properties = nextProperties
  const required = new Set(
    Array.isArray(parsed.required) ? parsed.required.map(String) : []
  )
  if (nextName !== fieldName && required.delete(fieldName)) {
    required.add(nextName)
  }
  if (update.required === true) required.add(nextName)
  if (update.required === false) required.delete(nextName)
  parsed.required = [...required].filter((name) => name in nextProperties)
  return JSON.stringify(parsed, null, 2)
}

function addFlatSchemaField(value: string) {
  const parsed = parseObject(value)
  if (!parsed || parsed.type !== "object") return value
  const properties =
    parsed.properties &&
    typeof parsed.properties === "object" &&
    !Array.isArray(parsed.properties)
      ? { ...(parsed.properties as Record<string, unknown>) }
      : {}
  let name = "input"
  let suffix = 2
  while (name in properties) name = `input_${suffix++}`
  properties[name] = simplePropertySchema("string", "")
  parsed.properties = properties
  parsed.additionalProperties = false
  return JSON.stringify(parsed, null, 2)
}

function removeFlatSchemaField(value: string, fieldName: string) {
  const parsed = parseObject(value)
  if (!parsed || parsed.type !== "object") return value
  const properties = parsed.properties
  if (
    !properties ||
    typeof properties !== "object" ||
    Array.isArray(properties)
  ) {
    return value
  }
  const nextProperties = { ...(properties as Record<string, unknown>) }
  delete nextProperties[fieldName]
  parsed.properties = nextProperties
  parsed.required = Array.isArray(parsed.required)
    ? parsed.required.filter((name) => name !== fieldName)
    : []
  return JSON.stringify(parsed, null, 2)
}

function SchemaFieldsEditor({
  label,
  value,
  disabled,
  onChange,
  t,
}: {
  label: string
  value: string
  disabled: boolean
  onChange: (value: string) => void
  t: ReturnType<typeof useLanguage>["t"]
}) {
  const [advanced, setAdvanced] = React.useState(false)
  const parsed = parseFlatSchema(value)

  return (
    <div className="rounded-xl border bg-muted/15 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{label}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {label === t("输入参数")
              ? t(
                  "Agent 会根据这些参数生成调用；工作流可以把上游结果连接到这里。"
                )
              : t("Python 代码通过 result 返回这些结果给 Agent 或工作流。")}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={() => setAdvanced((current) => !current)}
        >
          <BracesIcon />
          {t("高级 Schema")}
          <ChevronDownIcon
            className={
              advanced
                ? "rotate-180 transition-transform"
                : "transition-transform"
            }
          />
        </Button>
      </div>

      {advanced ? (
        <textarea
          aria-label={label}
          className={`${TEXTAREA_CLASS} mt-4 min-h-48 font-mono text-xs`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          spellCheck={false}
        />
      ) : parsed ? (
        <div className="mt-4 space-y-2">
          {parsed.fields.length ? (
            parsed.fields.map((field, index) => (
              <div
                key={`${field.name}-${index}`}
                className="grid gap-2 rounded-lg border bg-background p-3 md:grid-cols-[minmax(0,1fr)_9rem_minmax(0,1.4fr)_auto] md:items-center"
              >
                <Input
                  aria-label={`${t("参数名称")} ${index + 1}`}
                  value={field.name}
                  onChange={(event) =>
                    onChange(
                      updateFlatSchema(value, field.name, {
                        name: event.target.value,
                      })
                    )
                  }
                  disabled={disabled}
                  placeholder={t("参数名称")}
                />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="justify-between"
                      disabled={disabled}
                      aria-label={`${t("参数类型")} ${index + 1}`}
                    >
                      {schemaTypeLabel(field.type, t)}
                      <ChevronDownIcon />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    {SIMPLE_SCHEMA_TYPES.map((type) => (
                      <DropdownMenuItem
                        key={type}
                        onSelect={() =>
                          onChange(
                            updateFlatSchema(value, field.name, { type })
                          )
                        }
                      >
                        {schemaTypeLabel(type, t)}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
                <Input
                  aria-label={`${t("参数说明")} ${index + 1}`}
                  value={field.description}
                  onChange={(event) =>
                    onChange(
                      updateFlatSchema(value, field.name, {
                        description: event.target.value,
                      })
                    )
                  }
                  disabled={disabled}
                  placeholder={t("告诉 Agent 这个参数是什么")}
                />
                <div className="flex items-center justify-between gap-2 md:justify-end">
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={field.required}
                      onChange={(event) =>
                        onChange(
                          updateFlatSchema(value, field.name, {
                            required: event.target.checked,
                          })
                        )
                      }
                      disabled={disabled}
                    />
                    {t("必填")}
                  </label>
                  <IconButton
                    label={t("删除参数")}
                    disabled={disabled}
                    onClick={() =>
                      onChange(removeFlatSchemaField(value, field.name))
                    }
                  >
                    <Trash2Icon />
                  </IconButton>
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-lg border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
              {t("还没有参数；添加一个参数后，Agent 和工作流就知道要传什么。")}
            </div>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => onChange(addFlatSchemaField(value))}
          >
            <PlusIcon />
            {t("添加参数")}
          </Button>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground">
          {t("当前 Schema 不是简单参数表，请打开高级 Schema 编辑。")}
        </div>
      )}
    </div>
  )
}

const TERMINAL_INVOCATION_STATUSES = new Set<ToolInvocation["status"]>([
  "succeeded",
  "failed",
  "rejected",
  "uncertain",
  "cancelled",
])

/**
 * Converts a tool status value into its localized display label.
 *
 * @param status - The tool status to label
 * @param t - The localization function used to translate recognized statuses
 * @returns The localized label for a recognized status, or the original status
 */
function toolStatusLabel(
  status: string,
  t: ReturnType<typeof useLanguage>["t"]
) {
  if (status === "active") return t("已启用")
  if (status === "disabled") return t("已停用")
  if (status === "archived") return t("已归档")
  return status
}

/**
 * Provides a localized label for a tool invocation status.
 *
 * @param status - The invocation status to label
 * @param t - The localization function used to translate the label
 * @returns The localized status label
 */
function invocationStatusLabel(
  status: ToolInvocation["status"],
  t: ReturnType<typeof useLanguage>["t"]
) {
  if (status === "queued") return t("等待执行")
  if (status === "awaiting_approval") return t("需要逐次审批")
  if (status === "approved") return t("工具调用已批准")
  if (status === "running") return t("运行中")
  if (status === "succeeded") return t("运行成功")
  if (status === "failed") return t("运行失败")
  if (status === "rejected") return t("工具调用已拒绝")
  if (status === "uncertain") return t("工具执行结果不确定")
  return t("已取消")
}

/**
 * Renders a dialog for creating, editing, testing, publishing, enabling, disabling, and archiving a Python tool.
 *
 * @param open - Whether the dialog is open
 * @param onOpenChange - Handles changes to the dialog's open state
 * @param token - Authentication token used for tool operations
 * @param workspaceId - Workspace containing the tool
 * @param tool - Tool summary to load, or `null` when creating a tool
 * @param onChanged - Called with the updated tool details after a change
 * @param onArchived - Called with the identifier of an archived tool
 * @param onMessage - Reports operation success and error messages
 */
export function PythonToolDialog({
  open,
  onOpenChange,
  token,
  workspaceId,
  tool,
  onChanged,
  onArchived,
  onMessage,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string
  workspaceId: string
  tool: ToolSummary | null
  onChanged: (tool: ToolDetail) => void
  onArchived: (toolId: string) => void
  onMessage: (kind: "success" | "error", message: string) => void
}) {
  const { t } = useLanguage()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [detail, setDetail] = React.useState<ToolDetail | null>(null)
  const [form, setForm] = React.useState<PythonForm>(EMPTY_FORM)
  const [isLoading, setIsLoading] = React.useState(false)
  const [detailError, setDetailError] = React.useState<string | null>(null)
  const [busyAction, setBusyAction] = React.useState<string | null>(null)
  const [invocation, setInvocation] = React.useState<ToolInvocation | null>(
    null
  )
  const pollRef = React.useRef(0)

  const canManage = detail?.can_manage ?? tool?.can_manage ?? true
  const isCreate = !tool && !detail
  const currentToolId = detail?.id ?? tool?.id ?? null
  const isBusy = Boolean(busyAction)

  const reportError = React.useCallback(
    (error: unknown) => onMessage("error", getErrorMessage(error, t)),
    [onMessage, t]
  )

  const loadExistingTool = React.useCallback(
    async (toolId: string) => {
      const requestId = ++pollRef.current
      setIsLoading(true)
      setDetailError(null)
      try {
        const nextDetail = await getTool(token, workspaceId, toolId)
        if (requestId !== pollRef.current) return
        setDetail(nextDetail)
        setForm(formFromDetail(nextDetail))
      } catch (error) {
        if (requestId !== pollRef.current) return
        setDetail(null)
        setDetailError(getErrorMessage(error, t))
        reportError(error)
      } finally {
        if (requestId === pollRef.current) setIsLoading(false)
      }
    },
    [reportError, t, token, workspaceId]
  )

  React.useEffect(() => {
    if (!open) {
      pollRef.current += 1
      // Reset editor state and stop polling when the dialog closes.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDetail(null)
      setForm(EMPTY_FORM)
      setInvocation(null)
      setBusyAction(null)
      setDetailError(null)
      setIsLoading(false)
      return
    }
    if (!tool) {
      setDetail(null)
      setForm(EMPTY_FORM)
      setInvocation(null)
      setDetailError(null)
      return
    }
    void loadExistingTool(tool.id)
  }, [loadExistingTool, open, tool])

  async function save(showMessage = true) {
    const payload = payloadFromForm(form)
    if (!payload) return null
    setBusyAction(isCreate ? "create" : "save")
    try {
      if (!currentToolId) {
        const created = await createPythonTool(token, workspaceId, payload)
        setDetail(created)
        setForm(formFromDetail(created))
        onChanged(created)
        if (showMessage) onMessage("success", t("Python 工具已创建"))
        return created
      }
      const revision = detail?.draft?.revision
      if (revision == null) {
        onMessage("error", t("工具草稿不存在，请重新加载后重试"))
        return null
      }
      await updatePythonToolDraft(token, workspaceId, currentToolId, {
        ...payload,
        expected_revision: revision,
      })
      const updated = await getTool(token, workspaceId, currentToolId)
      if (updated.draft?.revision == null) {
        onMessage("error", t("工具草稿不存在，请重新加载后重试"))
        return null
      }
      setDetail(updated)
      setForm((current) => ({
        ...formFromDetail(updated),
        testArguments: current.testArguments,
      }))
      onChanged(updated)
      if (showMessage) onMessage("success", t("工具草稿已保存"))
      return updated
    } catch (error) {
      reportError(error)
      return null
    } finally {
      setBusyAction(null)
    }
  }

  async function pollTest(toolId: string, first: ToolInvocation) {
    const pollId = ++pollRef.current
    let current = first
    setInvocation(current)
    while (!TERMINAL_INVOCATION_STATUSES.has(current.status)) {
      await new Promise((resolve) => window.setTimeout(resolve, 600))
      if (pollRef.current !== pollId) return
      current = await getPythonToolTest(token, workspaceId, toolId, current.id)
      setInvocation(current)
    }
    onMessage(
      current.status === "succeeded" ? "success" : "error",
      current.status === "succeeded" ? t("工具测试通过") : t("工具测试失败")
    )
  }

  async function runTest() {
    const argumentsValue = parseObject(form.testArguments)
    if (!argumentsValue) {
      onMessage("error", t("测试参数必须是 JSON 对象"))
      return
    }
    const saved = canManage ? await save(false) : detail
    if (!saved) return
    setBusyAction("test")
    try {
      const created = await testPythonTool(
        token,
        workspaceId,
        saved.id,
        argumentsValue
      )
      await pollTest(saved.id, created)
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function publish() {
    const saved = await save(false)
    if (!saved) return
    setBusyAction("publish")
    try {
      const updated = await publishPythonTool(token, workspaceId, saved.id)
      setDetail(updated)
      setForm(formFromDetail(updated))
      onChanged(updated)
      onMessage("success", t("工具已发布"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function toggleEnabled() {
    if (!detail) return
    const enabled = detail.status !== "active"
    if (
      !enabled &&
      !(await confirmAction({
        description: t(
          "禁用工具“{name}”？已绑定的 Agent 和 Workflow 将无法调用它。",
          {
            name: detail.display_name,
          }
        ),
        confirmLabel: t("禁用"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyAction("toggle")
    try {
      const updated = await setPythonToolEnabled(
        token,
        workspaceId,
        detail.id,
        enabled
      )
      setDetail(updated)
      onChanged(updated)
      onMessage("success", enabled ? t("工具已启用") : t("工具已禁用"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  async function archive() {
    if (
      !detail ||
      !(await confirmAction({
        description: t("归档工具“{name}”？此操作会使所有已绑定版本不可用。", {
          name: detail.display_name,
        }),
        confirmLabel: t("归档"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyAction("archive")
    try {
      await archivePythonTool(token, workspaceId, detail.id)
      onArchived(detail.id)
      onOpenChange(false)
      onMessage("success", t("工具已归档"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => !isBusy && onOpenChange(nextOpen)}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <div className="flex items-start gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/10 text-violet-700 dark:text-violet-400">
                <Code2Icon className="size-5" />
              </span>
              <div className="min-w-0">
                <DialogTitle>
                  {isCreate ? t("创建 Python 工具") : t("Python 工具详情")}
                </DialogTitle>
                <DialogDescription className="mt-1">
                  {canManage
                    ? t("编辑草稿、运行测试并发布固定版本。")
                    : t("你拥有查看权限；草稿与代码不会显示。")}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {isLoading ? (
            <div className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t("正在加载")}
            </div>
          ) : detailError && tool ? (
            <div
              role="alert"
              className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/20 p-6 text-center"
            >
              <p className="font-medium">{t("工具加载失败")}</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                {detailError}
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => void loadExistingTool(tool.id)}
              >
                <RefreshCwIcon />
                {t("重试")}
              </Button>
            </div>
          ) : (
            <div className="space-y-5">
              {detail ? (
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">
                    {toolStatusLabel(detail.status, t)}
                  </Badge>
                  <Badge variant="outline">
                    {detail.current_version_id ? t("已发布") : t("未发布")}
                  </Badge>
                  {detail.version_id ? (
                    <Badge variant="outline">
                      {t("版本 {value}", { value: detail.version_id })}
                    </Badge>
                  ) : null}
                </div>
              ) : null}

              <div className="rounded-xl border border-sky-200/70 bg-sky-50/60 p-4 dark:border-sky-900/60 dark:bg-sky-950/20">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Code2Icon className="size-4 text-sky-700 dark:text-sky-300" />
                  {t("这个工具怎么被调用")}
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-sky-200/70 bg-background/80 p-3 dark:border-sky-900/60">
                    <div className="flex items-center gap-2 text-xs font-medium">
                      <BotIcon className="size-4 text-sky-700 dark:text-sky-300" />
                      {t("在 Agent 中")}
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {t("Agent 会根据工具描述和输入参数自动生成调用。")}
                    </p>
                  </div>
                  <div className="rounded-lg border border-sky-200/70 bg-background/80 p-3 dark:border-sky-900/60">
                    <div className="flex items-center gap-2 text-xs font-medium">
                      <WorkflowIcon className="size-4 text-sky-700 dark:text-sky-300" />
                      {t("在工作流中")}
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {t("把上游节点的输出连接到下面的输入参数。")}
                    </p>
                  </div>
                </div>
              </div>

              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="python-tool-name">
                    {t("显示名称")}
                  </FieldLabel>
                  <Input
                    id="python-tool-name"
                    value={form.displayName}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        displayName: event.target.value,
                      }))
                    }
                    disabled={!canManage || isBusy}
                    maxLength={120}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="python-tool-description">
                    {t("工具描述")}
                  </FieldLabel>
                  <textarea
                    id="python-tool-description"
                    className={TEXTAREA_CLASS}
                    value={form.description}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))
                    }
                    disabled={!canManage || isBusy}
                    maxLength={4000}
                    rows={3}
                  />
                </Field>
                <SchemaFieldsEditor
                  label={t("输入参数")}
                  value={form.inputSchema}
                  disabled={!canManage || isBusy}
                  onChange={(inputSchema) =>
                    setForm((current) => ({ ...current, inputSchema }))
                  }
                  t={t}
                />
                <SchemaFieldsEditor
                  label={t("输出结果")}
                  value={form.outputSchema}
                  disabled={!canManage || isBusy}
                  onChange={(outputSchema) =>
                    setForm((current) => ({ ...current, outputSchema }))
                  }
                  t={t}
                />
                {canManage ? (
                  <Field>
                    <FieldLabel htmlFor="python-tool-code">
                      {t("Python 代码")}
                    </FieldLabel>
                    <textarea
                      id="python-tool-code"
                      className={`${TEXTAREA_CLASS} min-h-60 font-mono text-xs`}
                      value={form.code}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          code: event.target.value,
                        }))
                      }
                      disabled={isBusy}
                      maxLength={8192}
                      spellCheck={false}
                    />
                    <FieldDescription>
                      {t(
                        "从 inputs 读取参数，并将 JSON 结果赋给 result 变量。"
                      )}
                    </FieldDescription>
                    <div className="rounded-lg border bg-muted/25 p-3 text-xs">
                      <div className="flex items-center gap-2 font-medium">
                        <BracesIcon className="size-4 text-muted-foreground" />
                        {t("代码约定")}
                      </div>
                      <pre className="mt-2 overflow-x-auto text-[11px] leading-5 whitespace-pre-wrap text-muted-foreground">
                        {t("Python 代码示例")}
                      </pre>
                    </div>
                  </Field>
                ) : null}
              </FieldGroup>

              {detail && canManage ? (
                <div className="rounded-xl border bg-muted/20 p-4">
                  <Field>
                    <FieldLabel htmlFor="python-tool-test-arguments">
                      {t("测试参数")}
                    </FieldLabel>
                    <textarea
                      id="python-tool-test-arguments"
                      className={`${TEXTAREA_CLASS} min-h-28 font-mono text-xs`}
                      value={form.testArguments}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          testArguments: event.target.value,
                        }))
                      }
                      disabled={isBusy}
                      spellCheck={false}
                    />
                  </Field>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={isBusy}
                      onClick={() => void runTest()}
                    >
                      {busyAction === "test" ? (
                        <LoaderCircleIcon className="animate-spin" />
                      ) : (
                        <PlayIcon />
                      )}
                      {busyAction === "test" ? t("测试运行中") : t("运行测试")}
                    </Button>
                    {invocation ? (
                      <Badge
                        variant={
                          invocation.status === "succeeded"
                            ? "secondary"
                            : "outline"
                        }
                      >
                        {invocation.status === "succeeded" ? (
                          <CircleCheckIcon />
                        ) : null}
                        {invocationStatusLabel(invocation.status, t)}
                      </Badge>
                    ) : null}
                  </div>
                  {invocation &&
                  TERMINAL_INVOCATION_STATUSES.has(invocation.status) ? (
                    <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">
                      {JSON.stringify(
                        invocation.status === "succeeded"
                          ? invocation.result_data
                          : {
                              error: invocation.error_message,
                              code: invocation.error_code,
                            },
                        null,
                        2
                      )}
                    </pre>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}

          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
            <div className="flex flex-wrap gap-2">
              {detail?.can_manage ? (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isBusy}
                    onClick={() => void toggleEnabled()}
                  >
                    <PowerIcon />
                    {detail.status === "active" ? t("禁用") : t("启用")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="text-destructive"
                    disabled={isBusy}
                    onClick={() => void archive()}
                  >
                    <ArchiveIcon />
                    {t("归档")}
                  </Button>
                </>
              ) : null}
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              <Button
                type="button"
                variant="outline"
                disabled={isBusy}
                onClick={() => onOpenChange(false)}
              >
                {t("关闭")}
              </Button>
              {canManage && !detailError ? (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isBusy || !payloadFromForm(form)}
                    onClick={() => void save()}
                  >
                    {busyAction === "save" || busyAction === "create" ? (
                      <LoaderCircleIcon className="animate-spin" />
                    ) : null}
                    {isCreate ? t("创建") : t("保存草稿")}
                  </Button>
                  {detail ? (
                    <Button
                      type="button"
                      disabled={isBusy || !payloadFromForm(form)}
                      onClick={() => void publish()}
                    >
                      {busyAction === "publish" ? (
                        <LoaderCircleIcon className="animate-spin" />
                      ) : (
                        <SendIcon />
                      )}
                      {t("发布")}
                    </Button>
                  ) : null}
                </>
              ) : null}
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </>
  )
}

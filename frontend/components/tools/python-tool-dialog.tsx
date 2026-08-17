"use client"

import * as React from "react"
import {
  ArchiveIcon,
  CircleCheckIcon,
  Code2Icon,
  LoaderCircleIcon,
  PlayIcon,
  PowerIcon,
  RefreshCwIcon,
  SendIcon,
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
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
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

const TERMINAL_INVOCATION_STATUSES = new Set<ToolInvocation["status"]>([
  "succeeded",
  "failed",
  "rejected",
  "uncertain",
  "cancelled",
])

function toolStatusLabel(
  status: string,
  t: ReturnType<typeof useLanguage>["t"]
) {
  if (status === "active") return t("已启用")
  if (status === "disabled") return t("已停用")
  if (status === "archived") return t("已归档")
  return status
}

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

  async function reload(toolId: string) {
    const nextDetail = await getTool(token, workspaceId, toolId)
    setDetail(nextDetail)
    setForm((current) => ({
      ...formFromDetail(nextDetail),
      testArguments: current.testArguments,
    }))
    onChanged(nextDetail)
    return nextDetail
  }

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
      if (!revision) return detail
      await updatePythonToolDraft(token, workspaceId, currentToolId, {
        ...payload,
        expected_revision: revision,
      })
      const updated = await reload(currentToolId)
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
                <div className="grid gap-4 md:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="python-tool-input-schema">
                      {t("输入 Schema")}
                    </FieldLabel>
                    <textarea
                      id="python-tool-input-schema"
                      className={`${TEXTAREA_CLASS} min-h-48 font-mono text-xs`}
                      value={form.inputSchema}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          inputSchema: event.target.value,
                        }))
                      }
                      disabled={!canManage || isBusy}
                      spellCheck={false}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="python-tool-output-schema">
                      {t("输出 Schema")}
                    </FieldLabel>
                    <textarea
                      id="python-tool-output-schema"
                      className={`${TEXTAREA_CLASS} min-h-48 font-mono text-xs`}
                      value={form.outputSchema}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          outputSchema: event.target.value,
                        }))
                      }
                      disabled={!canManage || isBusy}
                      spellCheck={false}
                    />
                  </Field>
                </div>
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

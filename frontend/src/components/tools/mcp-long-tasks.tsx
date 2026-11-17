"use client"

import * as React from "react"
import { useLanguage } from "@/contexts/language-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldLabel,
  FieldDescription,
  FieldGroup,
} from "@/components/ui/field"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import * as api from "@/lib/api/mcp"
import { getErrorMessage } from "@/lib/errors"

const empty: api.McpTaskContract = {
  status_tool: "",
  result_tool: "",
  cancel_tool: "",
  poll_seconds: 3,
}

export function McpLongTasksDialog({
  token,
  workspaceId,
  serverId,
  onClose,
  onChanged,
}: {
  token: string
  workspaceId: string
  serverId: string
  onClose: () => void
  onChanged: () => void
}) {
  const { t } = useLanguage()
  const [configuration, setConfiguration] =
    React.useState<api.McpTaskConfiguration | null>(null)
  const [submit, setSubmit] = React.useState("")
  const [contract, setContract] = React.useState(empty)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => {
    let active = true
    api
      .getMcpTaskConfiguration(token, workspaceId, serverId)
      .then((value) => {
        if (active) setConfiguration(value)
      })
      .catch((error) => {
        if (active) setError(getErrorMessage(error, t))
      })
    return () => {
      active = false
    }
  }, [token, workspaceId, serverId, t])
  async function save(remove = false) {
    if (!configuration || !submit) return
    setBusy(true)
    setError(null)
    const contracts = { ...configuration.contracts }
    if (remove) delete contracts[submit]
    else contracts[submit] = contract
    try {
      const saved = await api.configureMcpTasks(
        token,
        workspaceId,
        serverId,
        contracts
      )
      setConfiguration(saved)
      onChanged()
    } catch (error) {
      setError(getErrorMessage(error, t))
    } finally {
      setBusy(false)
    }
  }
  const fields = [
    ["status_tool", "状态查询工具"],
    ["result_tool", "结果读取工具"],
    ["cancel_tool", "取消任务工具"],
  ] as const
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
    >
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("长任务契约")}</DialogTitle>
          <DialogDescription>
            {t(
              "仅为支持请求身份、状态、结果和取消的连接器启用。普通 MCP 调用保持原有行为。"
            )}
          </DialogDescription>
        </DialogHeader>
        <FieldDescription>
          {t(
            "状态和结果操作必须只读，取消必须幂等。此工具的授权同时允许管理它提交的同一任务。保存后需重新审核工具策略。"
          )}
        </FieldDescription>
        {configuration ? (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void save()
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="mcp-job-submit">
                  {t("提交任务工具")}
                </FieldLabel>
                <select
                  id="mcp-job-submit"
                  className="h-9 rounded-md border bg-background px-3 text-sm"
                  required
                  disabled={busy}
                  value={submit}
                  onChange={(event) => {
                    const name = event.target.value
                    setSubmit(name)
                    setContract(configuration.contracts[name] ?? empty)
                  }}
                >
                  <option value="">{t("选择工具")}</option>
                  {Array.from(
                    new Set([
                      ...configuration.tools,
                      ...Object.keys(configuration.contracts),
                    ])
                  ).map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </Field>
              {fields.map(([key, label]) => (
                <Field key={key}>
                  <FieldLabel htmlFor={`mcp-job-${key}`}>{t(label)}</FieldLabel>
                  <select
                    id={`mcp-job-${key}`}
                    className="h-9 rounded-md border bg-background px-3 text-sm"
                    required
                    disabled={!submit || busy}
                    value={contract[key]}
                    onChange={(event) =>
                      setContract((current) => ({
                        ...current,
                        [key]: event.target.value,
                      }))
                    }
                  >
                    <option value="">{t("选择工具")}</option>
                    {configuration.tools
                      .filter((name) => name !== submit)
                      .map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                  </select>
                </Field>
              ))}
              <Field>
                <FieldLabel htmlFor="mcp-job-poll">
                  {t("查询间隔（秒）")}
                </FieldLabel>
                <Input
                  id="mcp-job-poll"
                  type="number"
                  min={1}
                  max={30}
                  required
                  value={contract.poll_seconds}
                  disabled={!submit || busy}
                  onChange={(event) =>
                    setContract((current) => ({
                      ...current,
                      poll_seconds: Number(event.target.value),
                    }))
                  }
                />
              </Field>
            </FieldGroup>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              {configuration.contracts[submit] ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void save(true)}
                >
                  {t("恢复普通调用")}
                </Button>
              ) : null}
              <Button type="submit" disabled={!submit || busy}>
                {t("保存契约")}
              </Button>
            </div>
          </form>
        ) : !error ? (
          <p>{t("正在加载")}</p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

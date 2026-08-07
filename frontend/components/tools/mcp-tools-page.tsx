"use client"

import * as React from "react"
import {
  KeyRoundIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

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
import { useSession } from "@/contexts/session-context"
import {
  createMcpServer,
  deleteMcpServer,
  listMcpServers,
  refreshMcpServer,
  updateMcpToolPolicy,
  type McpServer,
  type McpToolPolicyMode,
} from "@/lib/api/mcp"
import { getMembershipRole } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"

type McpForm = {
  name: string
  url: string
  bearerToken: string
}

type McpPreset = {
  name: string
  url: string
  description: string
  requiresToken: boolean
  icon: typeof SearchIcon
}

const EMPTY_FORM: McpForm = { name: "", url: "", bearerToken: "" }

export function McpToolsPage() {
  const { t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()
  const [servers, setServers] = React.useState<McpServer[]>([])
  const [form, setForm] = React.useState<McpForm>(EMPTY_FORM)
  const [isLoading, setIsLoading] = React.useState(false)
  const [isSaving, setIsSaving] = React.useState(false)
  const [busyServerId, setBusyServerId] = React.useState<string | null>(null)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)

  const canManage = getMembershipRole(me, selectedWorkspaceId) === "admin"

  const presets: McpPreset[] = [
    {
      name: "Tavily",
      url: "https://mcp.tavily.com/mcp",
      description: t(
        "通过 Tavily 搜索 API 进行实时网页搜索、网页提取和站点爬取，需填写 Tavily API Key。"
      ),
      requiresToken: true,
      icon: SearchIcon,
    },
  ]

  function handleUsePreset(preset: McpPreset) {
    setForm({
      name: preset.name,
      url: preset.url,
      bearerToken: "",
    })
  }

  const reportError = React.useCallback(
    (error: unknown) => notify("error", getErrorMessage(error, t)),
    [notify, t]
  )

  const loadServers = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId) {
      setServers([])
      return
    }
    setIsLoading(true)
    try {
      setServers(await listMcpServers(token, selectedWorkspaceId))
    } catch (error) {
      setServers([])
      reportError(error)
    } finally {
      setIsLoading(false)
    }
  }, [reportError, selectedWorkspaceId, token])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadServers()
  }, [loadServers])

  if (!token || !me) return null

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (
      !token ||
      !selectedWorkspaceId ||
      !form.name.trim() ||
      !form.url.trim()
    ) {
      return
    }
    setIsSaving(true)
    try {
      const created = await createMcpServer(token, selectedWorkspaceId, {
        name: form.name.trim(),
        url: form.url.trim(),
        bearer_token: form.bearerToken.trim() || undefined,
      })
      setServers((current) => [created, ...current])
      setForm(EMPTY_FORM)
      setIsDialogOpen(false)
      notify("success", t("MCP Server 已添加"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleRefresh(server: McpServer) {
    if (!token || !selectedWorkspaceId || busyServerId) return
    setBusyServerId(server.id)
    try {
      const updated = await refreshMcpServer(
        token,
        selectedWorkspaceId,
        server.id
      )
      setServers((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      )
      notify("success", t("MCP 工具列表已刷新"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyServerId(null)
    }
  }

  async function handleDelete(server: McpServer) {
    if (
      !token ||
      !selectedWorkspaceId ||
      busyServerId ||
      !window.confirm(
        t("确定删除 MCP Server“{name}”吗？", { name: server.name })
      )
    ) {
      return
    }
    setBusyServerId(server.id)
    try {
      await deleteMcpServer(token, selectedWorkspaceId, server.id)
      setServers((current) => current.filter((item) => item.id !== server.id))
      notify("success", t("MCP Server 已删除"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyServerId(null)
    }
  }

  async function handlePolicyChange(
    server: McpServer,
    toolName: string,
    mode: McpToolPolicyMode
  ) {
    if (!token || !selectedWorkspaceId || busyServerId) return
    if (
      mode === "read_only" &&
      !window.confirm(
        t("确认将工具“{name}”标记为只读并允许自动执行吗？", {
          name: toolName,
        })
      )
    ) {
      return
    }
    setBusyServerId(server.id)
    try {
      const policy = await updateMcpToolPolicy(
        token,
        selectedWorkspaceId,
        server.id,
        toolName,
        mode
      )
      setServers((current) =>
        current.map((item) =>
          item.id === server.id
            ? {
                ...item,
                tools: item.tools.map((tool) =>
                  tool.name === toolName
                    ? {
                        ...tool,
                        policy_mode: policy.mode,
                        definition_hash: policy.definition_hash,
                      }
                    : tool
                ),
              }
            : item
        )
      )
      notify("success", t("MCP 工具策略已更新"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyServerId(null)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{t("MCP 工具")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t("连接 Streamable HTTP MCP Server，供 Agent 选择和调用工具。")}
          </p>
        </div>
        {canManage ? (
          <Button
            type="button"
            onClick={() => {
              setForm(EMPTY_FORM)
              setIsDialogOpen(true)
            }}
          >
            <PlusIcon data-icon="inline-start" />
            {t("添加 MCP Server")}
          </Button>
        ) : null}
      </div>

      {!canManage ? (
        <p className="mt-4 rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
          {t("只有空间管理员可以添加、刷新或删除 MCP Server。")}
        </p>
      ) : null}

      {isLoading ? (
        <div className="mt-6 flex min-h-72 items-center justify-center rounded-lg border text-muted-foreground">
          <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
          {t("正在加载")}
        </div>
      ) : servers.length === 0 ? (
        <div className="mt-6 flex min-h-72 flex-col items-center justify-center rounded-lg border bg-background px-6 text-center">
          <span className="flex size-12 items-center justify-center rounded-lg bg-muted">
            <WrenchIcon className="size-5 text-muted-foreground" />
          </span>
          <p className="mt-4 font-medium">{t("还没有 MCP Server")}</p>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            {t("添加后会自动发现工具，创建 Agent 时可直接选择。")}
          </p>
          {canManage ? (
            <Button
              type="button"
              className="mt-4"
              onClick={() => setIsDialogOpen(true)}
            >
              <PlusIcon data-icon="inline-start" />
              {t("添加 MCP Server")}
            </Button>
          ) : null}
        </div>
      ) : (
        <div className="mt-6 overflow-hidden rounded-lg border bg-background">
          {servers.map((server) => (
            <section key={server.id} className="border-b p-4 last:border-b-0">
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <WrenchIcon className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="truncate font-medium">{server.name}</h2>
                    <Badge variant="secondary">
                      {t("{value} 个工具", { value: server.tools.length })}
                    </Badge>
                    {server.has_bearer_token ? (
                      <Badge variant="outline" className="gap-1">
                        <KeyRoundIcon className="size-3" />
                        {server.bearer_token_hint}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {server.url}
                  </p>
                  {server.last_error ? (
                    <p className="mt-2 text-sm text-destructive">
                      {server.last_error}
                    </p>
                  ) : null}
                </div>
                {canManage ? (
                  <div className="flex shrink-0 gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={t("刷新工具")}
                      title={t("刷新工具")}
                      disabled={busyServerId !== null}
                      onClick={() => void handleRefresh(server)}
                    >
                      <RefreshCwIcon
                        className={
                          busyServerId === server.id
                            ? "animate-spin"
                            : undefined
                        }
                      />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="text-destructive"
                      aria-label={t("删除 MCP Server")}
                      title={t("删除 MCP Server")}
                      disabled={busyServerId !== null}
                      onClick={() => void handleDelete(server)}
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                ) : null}
              </div>

              {server.tools.length > 0 ? (
                <details className="mt-3 border-t pt-3 text-sm">
                  <summary className="cursor-pointer text-muted-foreground select-none hover:text-foreground">
                    {t("查看工具列表")}
                  </summary>
                  <div className="mt-2 divide-y rounded-md border">
                    {server.tools.map((tool) => (
                      <div key={tool.name} className="px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="font-mono text-xs font-medium">
                            {tool.name}
                          </p>
                          {canManage ? (
                            <select
                              value={tool.policy_mode}
                              className="h-8 rounded-md border bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              aria-label={t("工具执行策略")}
                              disabled={busyServerId !== null}
                              onChange={(event) =>
                                void handlePolicyChange(
                                  server,
                                  tool.name,
                                  event.target.value as McpToolPolicyMode
                                )
                              }
                            >
                              <option value="approval_required">
                                {t("每次调用前审批")}
                              </option>
                              <option value="read_only">
                                {t("只读自动执行")}
                              </option>
                              <option value="disabled">{t("禁用")}</option>
                            </select>
                          ) : (
                            <Badge variant="outline">
                              {t(
                                tool.policy_mode === "read_only"
                                  ? "只读自动执行"
                                  : tool.policy_mode === "disabled"
                                    ? "禁用"
                                    : "每次调用前审批"
                              )}
                            </Badge>
                          )}
                        </div>
                        {tool.description ? (
                          <p className="mt-1 text-xs leading-5 text-muted-foreground">
                            {tool.description}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
            </section>
          ))}
        </div>
      )}

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("添加 MCP Server")}</DialogTitle>
            <DialogDescription>
              {t("保存时会连接 Server 并发现可用工具。")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <p className="text-sm font-medium">{t("从内置预设快速填写")}</p>
              <p className="text-xs text-muted-foreground">
                {t("点击预设自动填写名称和地址。")}
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 [&>:only-child]:sm:col-span-2">
              {presets.map((preset) => (
                <button
                  key={preset.url}
                  type="button"
                  className="group flex w-full items-start gap-3 rounded-lg border bg-background p-3.5 text-left transition-[border-color,background-color,box-shadow] outline-none hover:border-primary/50 hover:bg-muted/40 hover:shadow-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  onClick={() => handleUsePreset(preset)}
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted text-foreground transition-colors group-hover:text-primary">
                    <preset.icon className="size-4" aria-hidden="true" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      {preset.name}
                      {preset.requiresToken ? (
                        <Badge variant="outline" className="gap-1 text-[10px]">
                          <KeyRoundIcon className="size-3" aria-hidden="true" />
                          {t("需要 Token")}
                        </Badge>
                      ) : null}
                    </span>
                    <span
                      className="mt-1 block truncate font-mono text-xs text-muted-foreground"
                      title={preset.url}
                    >
                      {preset.url}
                    </span>
                    <span className="mt-2 block text-xs leading-5 text-muted-foreground">
                      {preset.description}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
          <form onSubmit={handleCreate}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="mcp-name">{t("名称")}</FieldLabel>
                <Input
                  id="mcp-name"
                  value={form.name}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  placeholder={t("例如：业务工具")}
                  maxLength={120}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="mcp-url">{t("MCP 地址")}</FieldLabel>
                <Input
                  id="mcp-url"
                  type="url"
                  value={form.url}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      url: event.target.value,
                    }))
                  }
                  placeholder="https://mcp.example.com/mcp"
                  maxLength={2000}
                  required
                />
                <FieldDescription>
                  {t("公网地址必须使用 HTTPS；内网地址需由服务端显式开启。")}
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="mcp-token">
                  {t("Bearer Token（可选）")}
                </FieldLabel>
                <Input
                  id="mcp-token"
                  type="password"
                  value={form.bearerToken}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      bearerToken: event.target.value,
                    }))
                  }
                  autoComplete="new-password"
                  maxLength={8000}
                />
                <FieldDescription>
                  {t("Token 会加密保存，之后不会返回明文。")}
                </FieldDescription>
              </Field>
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button
                type="submit"
                disabled={isSaving || !form.name.trim() || !form.url.trim()}
              >
                {isSaving ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : null}
                {isSaving ? t("连接并发现中") : t("添加 MCP Server")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

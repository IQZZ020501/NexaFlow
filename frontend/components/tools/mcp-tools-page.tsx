"use client"

import * as React from "react"
import {
  KeyRoundIcon,
  LoaderCircleIcon,
  NetworkIcon,
  PlusIcon,
  RadioTowerIcon,
  RefreshCwIcon,
  SearchIcon,
  TerminalIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
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
  type McpServerCreatePayload,
  type McpToolPolicyMode,
  type McpTransport,
} from "@/lib/api/mcp"
import { getMembershipRole } from "@/lib/display"
import {
  CARD_BATCH_SIZE,
  useInfiniteScroll,
} from "@/lib/use-infinite-scroll"
import { getErrorMessage } from "@/lib/errors"

export type McpForm = {
  name: string
  transport: McpTransport
  url: string
  bearerToken: string
  stdioConfig: string
}

type McpPreset = {
  name: string
  url: string
  description: string
  requiresToken: boolean
  icon: typeof SearchIcon
}

const EMPTY_FORM: McpForm = {
  name: "",
  transport: "streamable_http",
  url: "",
  bearerToken: "",
  stdioConfig: "",
}

const STDIO_ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
const STDIO_CONFIG_FIELDS = new Set([
  "command",
  "args",
  "cwd",
  "env",
  "transport",
])
const STDIO_CONFIG_EXAMPLE = `{
  "command": "/usr/local/bin/node",
  "args": ["server.js"],
  "cwd": "/srv/mcp",
  "env": {
    "API_KEY": "secret"
  }
}`
const TEXTAREA_CLASS =
  "min-h-24 w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"

function parseStdioConfig(
  value: string
):
  | Extract<McpServerCreatePayload, { transport: "stdio" }>["stdio_config"]
  | null {
  if (!value.trim() || value.length > 65_536) return null
  let config: unknown
  try {
    config = JSON.parse(value)
  } catch {
    return null
  }
  if (!config || typeof config !== "object" || Array.isArray(config))
    return null

  const record = config as Record<string, unknown>
  if (Object.keys(record).some((key) => !STDIO_CONFIG_FIELDS.has(key)))
    return null
  if (record.transport !== undefined && record.transport !== "stdio")
    return null

  const command =
    typeof record.command === "string" ? record.command.trim() : ""
  const args = record.args ?? []
  const cwd = record.cwd
  const env = record.env ?? {}
  if (
    !command ||
    command.length > 1000 ||
    !Array.isArray(args) ||
    args.length > 64 ||
    args.some(
      (argument) => typeof argument !== "string" || argument.length > 2000
    ) ||
    (cwd !== undefined && cwd !== null && typeof cwd !== "string") ||
    !env ||
    typeof env !== "object" ||
    Array.isArray(env)
  ) {
    return null
  }

  const environment = Object.entries(env as Record<string, unknown>)
  if (
    environment.length > 32 ||
    environment.some(
      ([name, envValue]) =>
        name.length > 255 ||
        !STDIO_ENV_NAME.test(name) ||
        typeof envValue !== "string" ||
        envValue.length > 8000
    )
  ) {
    return null
  }

  const normalizedCwd = typeof cwd === "string" ? cwd.trim() : ""
  return {
    command,
    args: args as string[],
    ...(normalizedCwd ? { cwd: normalizedCwd } : {}),
    env: Object.fromEntries(environment) as Record<string, string>,
  }
}

export function buildMcpServerCreatePayload(
  form: McpForm
): McpServerCreatePayload | null {
  const name = form.name.trim()
  if (!name) return null
  if (form.transport === "stdio") {
    const stdioConfig = parseStdioConfig(form.stdioConfig)
    if (!stdioConfig) return null
    return {
      name,
      transport: "stdio",
      stdio_config: stdioConfig,
    }
  }
  const url = form.url.trim()
  if (!url) return null
  const bearerToken = form.bearerToken.trim()
  return {
    name,
    transport: form.transport,
    url,
    bearer_token: bearerToken || undefined,
  }
}

export function McpToolsPage() {
  const { t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [servers, setServers] = React.useState<McpServer[]>([])
  const [serversHasMore, setServersHasMore] = React.useState(true)
  const [isServersLoadingMore, setIsServersLoadingMore] =
    React.useState(false)
  const serversLoadingRef = React.useRef(false)
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

  const transportOptions: Array<{
    value: McpTransport
    label: string
    description: string
    icon: typeof NetworkIcon
  }> = [
    {
      value: "streamable_http",
      label: t("Streamable HTTP"),
      description: t("推荐的远程连接方式"),
      icon: NetworkIcon,
    },
    {
      value: "sse",
      label: t("SSE"),
      description: t("兼容旧版远程 Server"),
      icon: RadioTowerIcon,
    },
    {
      value: "stdio",
      label: t("stdio"),
      description: t("运行本地 stdio Server"),
      icon: TerminalIcon,
    },
  ]

  const transportLabels: Record<McpTransport, string> = {
    streamable_http: t("Streamable HTTP"),
    sse: t("SSE"),
    stdio: t("stdio"),
  }

  function handleUsePreset(preset: McpPreset) {
    setForm({
      name: preset.name,
      transport: "streamable_http",
      url: preset.url,
      bearerToken: "",
      stdioConfig: "",
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
    serversLoadingRef.current = true
    try {
      const nextServers = await listMcpServers(token, selectedWorkspaceId, {
        limit: CARD_BATCH_SIZE,
        offset: 0,
      })
      setServers(nextServers)
      setServersHasMore(nextServers.length === CARD_BATCH_SIZE)
    } catch (error) {
      setServers([])
      reportError(error)
    } finally {
      serversLoadingRef.current = false
      setIsLoading(false)
    }
  }, [reportError, selectedWorkspaceId, token])

  const loadMoreServers = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId) {
      return
    }
    if (serversLoadingRef.current || !serversHasMore) {
      return
    }
    serversLoadingRef.current = true
    setIsServersLoadingMore(true)
    try {
      const batch = await listMcpServers(token, selectedWorkspaceId, {
        limit: CARD_BATCH_SIZE,
        offset: servers.length,
      })
      setServers((current) => [...current, ...batch])
      setServersHasMore(batch.length === CARD_BATCH_SIZE)
    } catch (error) {
      reportError(error)
    } finally {
      serversLoadingRef.current = false
      setIsServersLoadingMore(false)
    }
  }, [reportError, selectedWorkspaceId, servers.length, serversHasMore, token])

  const serversListEndRef = useInfiniteScroll(loadMoreServers)

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadServers()
  }, [loadServers])

  if (!token || !me) return null

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const payload = buildMcpServerCreatePayload(form)
    if (!token || !selectedWorkspaceId || !payload) return
    setIsSaving(true)
    try {
      const created = await createMcpServer(token, selectedWorkspaceId, payload)
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

  function setDialogOpen(open: boolean) {
    setIsDialogOpen(open)
    if (!open) setForm(EMPTY_FORM)
  }

  function selectTransport(transport: McpTransport) {
    setForm((current) => ({
      ...EMPTY_FORM,
      name: current.name,
      transport,
    }))
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
      !(await confirmAction({
        description: t("确定删除 MCP Server“{name}”吗？", {
          name: server.name,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
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
    if (!token || !selectedWorkspaceId || busyServerId) {
      return
    }
    if (
      mode === "read_only" &&
      !(await confirmAction({
        description: t("确认将工具“{name}”标记为只读并允许自动执行吗？", {
          name: toolName,
        }),
      }))
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
            {t("连接远程或本地 MCP Server，供 Agent 选择和调用工具。")}
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
              onClick={() => setDialogOpen(true)}
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
                    <Badge variant="outline">
                      {transportLabels[server.transport]}
                    </Badge>
                    {server.has_bearer_token ? (
                      <Badge variant="outline" className="gap-1">
                        <KeyRoundIcon className="size-3" />
                        {server.bearer_token_hint}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {server.transport === "stdio"
                      ? t("stdio 命令：{command}", {
                          command: server.stdio_command ?? "-",
                        })
                      : server.url}
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
                            <FilterDropdown
                              value={tool.policy_mode}
                              className="h-8 min-w-32 px-2 text-xs"
                              ariaLabel={t("工具执行策略")}
                              disabled={busyServerId !== null}
                              options={[
                                {
                                  value: "approval_required",
                                  label: t("每次调用前审批"),
                                },
                                {
                                  value: "read_only",
                                  label: t("只读自动执行"),
                                },
                                { value: "disabled", label: t("禁用") },
                              ]}
                              onChange={(value) =>
                                void handlePolicyChange(
                                  server,
                                  tool.name,
                                  value as McpToolPolicyMode,
                                )
                              }
                            />
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
      <div
        ref={serversListEndRef}
        className="flex min-h-12 items-center justify-center gap-2 py-3 text-sm text-muted-foreground"
      >
        {isServersLoadingMore ? (
          <>
            <LoaderCircleIcon className="size-4 animate-spin" />
            {t("正在加载")}
          </>
        ) : servers.length > 0 && !serversHasMore ? (
          t("已加载全部")
        ) : null}
      </div>

      <Dialog open={isDialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("添加 MCP Server")}</DialogTitle>
            <DialogDescription>
              {t("保存时会连接 Server 并发现可用工具。")}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate}>
            <FieldGroup>
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">{t("连接方式")}</legend>
                <div
                  role="radiogroup"
                  aria-label={t("连接方式")}
                  className="grid grid-cols-3 gap-1 rounded-md border bg-muted/30 p-1"
                >
                  {transportOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={form.transport === option.value}
                      className={`flex min-h-20 min-w-0 flex-col items-center justify-center gap-1 rounded-sm px-2 py-2 text-center transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                        form.transport === option.value
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                      onClick={() => selectTransport(option.value)}
                    >
                      <option.icon
                        className="size-4 shrink-0"
                        aria-hidden="true"
                      />
                      <span className="w-full text-xs font-medium break-words">
                        {option.label}
                      </span>
                      <span className="hidden w-full text-[10px] leading-4 sm:block">
                        {option.description}
                      </span>
                    </button>
                  ))}
                </div>
              </fieldset>

              {form.transport === "streamable_http" ? (
                <div className="space-y-3">
                  <div className="space-y-1">
                    <p className="text-sm font-medium">
                      {t("从内置预设快速填写")}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t("点击预设自动填写名称和地址。")}
                    </p>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2 [&>:only-child]:sm:col-span-2">
                    {presets.map((preset) => (
                      <button
                        key={preset.url}
                        type="button"
                        className="group flex w-full items-start gap-3 rounded-md border bg-background p-3.5 text-left transition-[border-color,background-color,box-shadow] outline-none hover:border-primary/50 hover:bg-muted/40 hover:shadow-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                        onClick={() => handleUsePreset(preset)}
                      >
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted text-foreground transition-colors group-hover:text-primary">
                          <preset.icon className="size-4" aria-hidden="true" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                            {preset.name}
                            {preset.requiresToken ? (
                              <Badge
                                variant="outline"
                                className="gap-1 text-[10px]"
                              >
                                <KeyRoundIcon
                                  className="size-3"
                                  aria-hidden="true"
                                />
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
              ) : null}

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
              {form.transport === "stdio" ? (
                <Field>
                  <FieldLabel htmlFor="mcp-stdio-config">
                    {t("stdio 配置（JSON）")}
                  </FieldLabel>
                  <textarea
                    id="mcp-stdio-config"
                    value={form.stdioConfig}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        stdioConfig: event.target.value,
                      }))
                    }
                    className={`${TEXTAREA_CLASS} font-mono`}
                    placeholder={STDIO_CONFIG_EXAMPLE}
                    maxLength={65536}
                    rows={9}
                    autoComplete="off"
                    spellCheck={false}
                    required
                  />
                  <FieldDescription>
                    {form.stdioConfig.trim() &&
                    parseStdioConfig(form.stdioConfig) === null
                      ? t("请输入有效的 stdio JSON 配置。")
                      : t("stdio 配置会加密保存，之后不会返回明文。")}
                  </FieldDescription>
                </Field>
              ) : (
                <>
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
                      placeholder={
                        form.transport === "sse"
                          ? "https://mcp.example.com/sse"
                          : "https://mcp.example.com/mcp"
                      }
                      maxLength={2000}
                      required
                    />
                    <FieldDescription>
                      {t(
                        "支持 HTTP 和 HTTPS；内网地址需由部署管理员启用，HTTP 不加密。"
                      )}
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
                </>
              )}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button
                type="submit"
                disabled={
                  isSaving || buildMcpServerCreatePayload(form) === null
                }
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
      {confirmDialog}
    </>
  )
}

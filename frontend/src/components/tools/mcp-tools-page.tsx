"use client"

import * as React from "react"
import {
  KeyRoundIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

import { McpConnectionDialog } from "@/components/tools/mcp-source-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
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
  type McpTransport,
} from "@/lib/api/mcp"
import { getMembershipRole } from "@/lib/display"
import { CARD_BATCH_SIZE, useInfiniteScroll } from "@/lib/use-infinite-scroll"
import { getErrorMessage } from "@/lib/errors"

export {
  buildMcpServerCreatePayload,
  type McpForm,
} from "@/components/tools/mcp-form"

/**
 * Provides an interface for managing workspace MCP servers and their tools.
 */
export function McpToolsPage() {
  const { t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [servers, setServers] = React.useState<McpServer[]>([])
  const [serversHasMore, setServersHasMore] = React.useState(true)
  const [isServersLoadingMore, setIsServersLoadingMore] = React.useState(false)
  const serversLoadingRef = React.useRef(false)
  const [isLoading, setIsLoading] = React.useState(false)
  const [busyServerId, setBusyServerId] = React.useState<string | null>(null)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)

  const canManage = getMembershipRole(me, selectedWorkspaceId) === "admin"

  const transportLabels: Record<McpTransport, string> = {
    streamable_http: t("Streamable HTTP"),
    sse: t("SSE"),
    stdio: t("stdio"),
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

  function setDialogOpen(open: boolean) {
    setIsDialogOpen(open)
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
    setBusyServerId(server.id)
    try {
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
          <Button type="button" onClick={() => setIsDialogOpen(true)}>
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
                                  value as McpToolPolicyMode
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

      <McpConnectionDialog
        open={isDialogOpen}
        onOpenChange={setDialogOpen}
        canUsePrivileged={canManage}
        onSubmit={async (payload) => {
          if (!token || !selectedWorkspaceId) return
          const created = await createMcpServer(
            token,
            selectedWorkspaceId,
            payload
          )
          setServers((current) => [created, ...current])
          notify("success", t("MCP Server 已添加"))
        }}
        onError={(message) => notify("error", message)}
      />
      {confirmDialog}
    </>
  )
}

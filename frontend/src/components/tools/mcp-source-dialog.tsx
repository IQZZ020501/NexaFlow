"use client"

import * as React from "react"
import {
  KeyRoundIcon,
  LoaderCircleIcon,
  NetworkIcon,
  RadioTowerIcon,
  SearchIcon,
  TerminalIcon,
} from "lucide-react"

import {
  buildMcpServerCreatePayload,
  EMPTY_MCP_FORM,
  isPrivateMcpUrl,
  parseStdioConfig,
  STDIO_CONFIG_EXAMPLE,
  type McpForm,
} from "@/components/tools/mcp-form"
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
  createMcpSource,
  type McpSourceCreatePayload,
  type McpTransport,
  type ToolSourceDetail,
} from "@/lib/api/tools"
import { getErrorMessage } from "@/lib/errors"

const TEXTAREA_CLASS =
  "min-h-24 w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"

export function McpConnectionDialog({
  open,
  onOpenChange,
  canUsePrivileged,
  returnFocusRef,
  onSubmit,
  onError,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  canUsePrivileged: boolean
  returnFocusRef?: React.RefObject<HTMLElement | null>
  onSubmit: (payload: McpSourceCreatePayload) => Promise<void>
  onError: (message: string) => void
}) {
  const { t } = useLanguage()
  const [form, setForm] = React.useState<McpForm>(EMPTY_MCP_FORM)
  const [isSaving, setIsSaving] = React.useState(false)

  React.useEffect(() => {
    // Reset transient credentials whenever the shared dialog closes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!open) setForm(EMPTY_MCP_FORM)
  }, [open])

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
  const privateUrlBlocked =
    !canUsePrivileged && form.transport !== "stdio" && isPrivateMcpUrl(form.url)

  function setOpen(nextOpen: boolean) {
    if (!isSaving) onOpenChange(nextOpen)
  }

  function selectTransport(transport: McpTransport) {
    if (transport === "stdio" && !canUsePrivileged) return
    setForm((current) => ({
      ...EMPTY_MCP_FORM,
      name: current.name,
      transport,
    }))
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (privateUrlBlocked) return
    const payload = buildMcpServerCreatePayload(form)
    if (!payload) return
    setIsSaving(true)
    try {
      await onSubmit(payload)
      onOpenChange(false)
    } catch (error) {
      onError(getErrorMessage(error, t))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        className="max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] overflow-y-auto sm:max-w-xl"
        onCloseAutoFocus={(event) => {
          if (!returnFocusRef?.current) return
          event.preventDefault()
          returnFocusRef.current.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle>{t("添加 MCP Server")}</DialogTitle>
          <DialogDescription>
            {t("保存时会连接 Server 并发现可用工具。")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit}>
          <FieldGroup>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t("连接方式")}</legend>
              <div
                role="radiogroup"
                aria-label={t("连接方式")}
                className="grid grid-cols-3 gap-1 rounded-md border bg-muted/30 p-1"
              >
                {transportOptions.map((option) => {
                  const disabled = option.value === "stdio" && !canUsePrivileged
                  return (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={form.transport === option.value}
                      aria-disabled={disabled}
                      disabled={disabled}
                      title={
                        disabled
                          ? t("仅空间管理员可使用 stdio 或私网地址。")
                          : undefined
                      }
                      className={`flex min-h-20 min-w-0 flex-col items-center justify-center gap-1 rounded-sm px-2 py-2 text-center transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-45 ${
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
                  )
                })}
              </div>
              {!canUsePrivileged ? (
                <FieldDescription>
                  {t("普通成员只能连接公网 HTTP 或 SSE 地址。")}
                </FieldDescription>
              ) : null}
            </fieldset>

            {form.transport === "streamable_http" ? (
              <button
                type="button"
                className="flex w-full items-start gap-3 rounded-md border p-3.5 text-left outline-none hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50"
                onClick={() =>
                  setForm({
                    name: "Tavily",
                    transport: "streamable_http",
                    url: "https://mcp.tavily.com/mcp",
                    bearerToken: "",
                    stdioConfig: "",
                  })
                }
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted">
                  <SearchIcon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2 text-sm font-medium">
                    Tavily
                    <Badge variant="outline" className="gap-1 text-[10px]">
                      <KeyRoundIcon className="size-3" />
                      {t("需要 Token")}
                    </Badge>
                  </span>
                  <span className="mt-1 block truncate font-mono text-xs text-muted-foreground">
                    https://mcp.tavily.com/mcp
                  </span>
                </span>
              </button>
            ) : null}

            <Field>
              <FieldLabel htmlFor="tool-source-mcp-name">
                {t("名称")}
              </FieldLabel>
              <Input
                id="tool-source-mcp-name"
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
                <FieldLabel htmlFor="tool-source-mcp-stdio">
                  {t("stdio 配置（JSON）")}
                </FieldLabel>
                <textarea
                  id="tool-source-mcp-stdio"
                  value={form.stdioConfig}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      stdioConfig: event.target.value,
                    }))
                  }
                  className={`${TEXTAREA_CLASS} font-mono`}
                  placeholder={STDIO_CONFIG_EXAMPLE}
                  maxLength={65_536}
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
                  <FieldLabel htmlFor="tool-source-mcp-url">
                    {t("MCP 地址")}
                  </FieldLabel>
                  <Input
                    id="tool-source-mcp-url"
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
                    {privateUrlBlocked
                      ? t("仅空间管理员可使用 stdio 或私网地址。")
                      : t(
                          "支持 HTTP 和 HTTPS；内网地址需由部署管理员启用，HTTP 不加密。"
                        )}
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="tool-source-mcp-token">
                    {t("Bearer Token（可选）")}
                  </FieldLabel>
                  <Input
                    id="tool-source-mcp-token"
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
              onClick={() => setOpen(false)}
            >
              {t("取消")}
            </Button>
            <Button
              type="submit"
              disabled={
                isSaving ||
                privateUrlBlocked ||
                buildMcpServerCreatePayload(form) === null
              }
            >
              {isSaving ? <LoaderCircleIcon className="animate-spin" /> : null}
              {isSaving ? t("连接并发现中") : t("添加 MCP Server")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function McpSourceDialog({
  open,
  onOpenChange,
  token,
  workspaceId,
  canUsePrivileged,
  returnFocusRef,
  onCreated,
  onError,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string
  workspaceId: string
  canUsePrivileged: boolean
  returnFocusRef?: React.RefObject<HTMLElement | null>
  onCreated: (source: ToolSourceDetail) => void
  onError: (message: string) => void
}) {
  return (
    <McpConnectionDialog
      open={open}
      onOpenChange={onOpenChange}
      canUsePrivileged={canUsePrivileged}
      returnFocusRef={returnFocusRef}
      onSubmit={async (payload) => {
        const source = await createMcpSource(token, workspaceId, payload)
        onCreated(source)
      }}
      onError={onError}
    />
  )
}

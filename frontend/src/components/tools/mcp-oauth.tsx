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
import { ApiError } from "@/lib/api-client"
import { getErrorMessage } from "@/lib/errors"
import { isSafeHttpUrl } from "@/lib/safe-url"
import * as api from "@/lib/api/mcp"

export const EMPTY_MCP_OAUTH: api.McpOAuthConfiguration = {
  authorization_endpoint: "",
  token_endpoint: "",
  revocation_endpoint: "",
  client_id: "",
  client_auth_method: "none",
  scopes: [],
}

export function McpOAuthFields({
  value,
  onChange,
  disabled,
  prefix = "mcp-oauth",
}: {
  value: api.McpOAuthConfiguration
  onChange: (value: api.McpOAuthConfiguration) => void
  disabled?: boolean
  prefix?: string
}) {
  const { t } = useLanguage()
  const fields = [
    ["authorization_endpoint", "授权地址"],
    ["token_endpoint", "令牌地址"],
    ["revocation_endpoint", "撤销地址"],
    ["client_id", "客户端 ID"],
  ] as const
  return (
    <FieldGroup>
      <FieldDescription>
        {t(
          "使用已注册的 OAuth 客户端，填写服务提供方的授权、令牌与撤销地址。连接会使用 PKCE。"
        )}
      </FieldDescription>
      {fields.map(([key, label]) => (
        <Field key={key}>
          <FieldLabel htmlFor={`${prefix}-${key}`}>{t(label)}</FieldLabel>
          <Input
            id={`${prefix}-${key}`}
            type={key === "client_id" ? "text" : "url"}
            value={value[key]}
            required
            disabled={disabled}
            maxLength={key === "client_id" ? 512 : 2048}
            onChange={(event) =>
              onChange({ ...value, [key]: event.target.value })
            }
          />
        </Field>
      ))}
      <Field>
        <FieldLabel htmlFor={`${prefix}-auth`}>{t("客户端认证")}</FieldLabel>
        <select
          id={`${prefix}-auth`}
          className="h-9 rounded-md border bg-background px-3 text-sm"
          disabled={disabled}
          value={value.client_auth_method}
          onChange={(event) =>
            onChange({
              ...value,
              client_auth_method: event.target
                .value as api.McpOAuthConfiguration["client_auth_method"],
              client_secret: "",
            })
          }
        >
          <option value="none">{t("公开客户端（PKCE）")}</option>
          <option value="client_secret_basic">
            {t("客户端密钥（Basic）")}
          </option>
          <option value="client_secret_post">{t("客户端密钥（POST）")}</option>
        </select>
      </Field>
      {value.client_auth_method !== "none" ? (
        <Field>
          <FieldLabel htmlFor={`${prefix}-secret`}>
            {t("客户端密钥")}
          </FieldLabel>
          <Input
            id={`${prefix}-secret`}
            type="password"
            autoComplete="new-password"
            value={value.client_secret ?? ""}
            disabled={disabled}
            required
            maxLength={8000}
            onChange={(event) =>
              onChange({ ...value, client_secret: event.target.value })
            }
          />
          <FieldDescription>
            {t("密钥加密保存；断开连接后需要重新填写。")}
          </FieldDescription>
        </Field>
      ) : null}
      <Field>
        <FieldLabel htmlFor={`${prefix}-scopes`}>
          {t("授权范围（空格分隔）")}
        </FieldLabel>
        <Input
          id={`${prefix}-scopes`}
          value={value.scopes.join(" ")}
          disabled={disabled}
          maxLength={4128}
          onChange={(event) =>
            onChange({ ...value, scopes: event.target.value.split(/ +/) })
          }
          onBlur={() =>
            onChange({ ...value, scopes: value.scopes.filter(Boolean) })
          }
        />
      </Field>
    </FieldGroup>
  )
}

export function McpOAuthDialog({
  token,
  workspaceId,
  serverId,
  onClose,
  onChanged,
  onMessage,
}: {
  token: string
  workspaceId: string
  serverId: string
  onClose: () => void
  onChanged: () => void
  onMessage: (kind: "success" | "error", message: string) => void
}) {
  const { t } = useLanguage()
  const [status, setStatus] = React.useState<api.McpOAuthStatus | null>(null)
  const [configuration, setConfiguration] = React.useState(EMPTY_MCP_OAUTH)
  const [loading, setLoading] = React.useState(true)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => {
    let active = true
    api
      .getMcpOAuth(token, workspaceId, serverId)
      .then((result) => {
        if (active) {
          setStatus(result)
          setConfiguration({ ...result.configuration, client_secret: "" })
        }
      })
      .catch((error) => {
        if (active && !(error instanceof ApiError && error.status === 404))
          setError(getErrorMessage(error, t))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [token, workspaceId, serverId, t])
  const editable = !status || status.status === "disconnected"
  const unsaved =
    !status ||
    Boolean(configuration.client_secret) ||
    (
      [
        "authorization_endpoint",
        "token_endpoint",
        "revocation_endpoint",
        "client_id",
        "client_auth_method",
      ] as const
    ).some((key) => configuration[key] !== status.configuration[key]) ||
    configuration.scopes.join(" ") !== status.configuration.scopes.join(" ")
  async function act(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (error) {
      const message = getErrorMessage(error, t)
      setError(message)
      onMessage("error", message)
    } finally {
      setBusy(false)
    }
  }
  const labels = {
    disconnected: "未连接",
    connected: "已连接",
    refreshing: "正在刷新授权",
    reauthorization_required: "需要重新授权",
  } as const
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
    >
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("OAuth 连接")}</DialogTitle>
          <DialogDescription>
            {t("授权由连接创建者管理。获准使用此来源的工具会使用这份连接。")}
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <p>{t("正在加载")}</p>
        ) : (
          <>
            <p role="status" className="text-sm">
              {t(labels[status?.status ?? "disconnected"])}
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void act(async () => {
                  const saved = await api.configureMcpOAuth(
                    token,
                    workspaceId,
                    serverId,
                    {
                      ...configuration,
                      scopes: configuration.scopes.filter(Boolean),
                    }
                  )
                  setStatus(saved)
                  setConfiguration({
                    ...saved.configuration,
                    client_secret: "",
                  })
                  onChanged()
                  onMessage("success", t("OAuth 配置已保存"))
                })
              }}
            >
              <McpOAuthFields
                value={configuration}
                onChange={setConfiguration}
                disabled={!editable || busy}
                prefix="mcp-oauth-manage"
              />
              <div className="mt-5 flex flex-wrap justify-end gap-2">
                {editable ? (
                  <Button type="submit" disabled={busy}>
                    {t("保存配置")}
                  </Button>
                ) : null}
                {status?.status === "disconnected" ? (
                  <Button
                    type="button"
                    disabled={busy || unsaved}
                    onClick={() =>
                      void act(async () => {
                        const result = await api.authorizeMcpOAuth(
                          token,
                          workspaceId,
                          serverId
                        )
                        if (!isSafeHttpUrl(result.authorization_url)) {
                          throw new Error("Invalid authorization URL.")
                        }
                        window.location.assign(result.authorization_url)
                      })
                    }
                  >
                    {t("前往授权")}
                  </Button>
                ) : null}
                {status && status.status !== "disconnected" ? (
                  <Button
                    variant="outline"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void act(async () => {
                        const result = await api.disconnectMcpOAuth(
                          token,
                          workspaceId,
                          serverId
                        )
                        setStatus(result)
                        setConfiguration({
                          ...result.configuration,
                          client_secret: "",
                        })
                        onChanged()
                        onMessage("success", t("OAuth 连接已断开"))
                      })
                    }
                  >
                    {t("断开连接")}
                  </Button>
                ) : null}
              </div>
            </form>
          </>
        )}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

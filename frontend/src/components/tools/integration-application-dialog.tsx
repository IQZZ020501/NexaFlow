"use client"

import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"

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
  configureIntegrationApplication,
  getIntegrationApplication,
  type IntegrationApplication,
  type IntegrationProvider,
} from "@/lib/api/integrations"
import { getErrorMessage } from "@/lib/errors"
import { integrationCatalog, integrationName } from "@/lib/integrations"

export function IntegrationApplicationDialog({
  provider,
  token,
  workspaceId,
  onClose,
  onSaved,
}: {
  provider: IntegrationProvider
  token: string
  workspaceId: string
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useLanguage()
  const [configuration, setConfiguration] =
    React.useState<IntegrationApplication | null>(null)
  const [clientId, setClientId] = React.useState("")
  const [clientSecret, setClientSecret] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const active = React.useRef(true)
  React.useEffect(() => {
    active.current = true
    void getIntegrationApplication(token, workspaceId, provider)
      .then((result) => {
        if (!active.current) return
        setConfiguration(result)
        setClientId(result.client_id)
      })
      .catch((nextError) => {
        if (active.current) setError(getErrorMessage(nextError, t))
      })
    return () => {
      active.current = false
    }
  }, [token, workspaceId, provider, t])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!configuration || busy) return
    setBusy(true)
    setError(null)
    try {
      await configureIntegrationApplication(token, workspaceId, provider, {
        client_id: clientId.trim(),
        ...(clientSecret ? { client_secret: clientSecret } : {}),
        scopes: configuration.scopes,
      })
      if (!active.current) return
      setClientSecret("")
      onSaved()
      onClose()
    } catch (nextError) {
      if (active.current) setError(getErrorMessage(nextError, t))
    } finally {
      if (active.current) setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t("配置 {name}", { name: t(integrationName(provider)) })}
          </DialogTitle>
          <DialogDescription>
            {t("管理员配置开发者应用后，成员可分别登录自己的账号完成安装。")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={save}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="integration-client-id">
                {t("应用 Client ID")}
              </FieldLabel>
              <Input
                id="integration-client-id"
                value={clientId}
                onChange={(event) => setClientId(event.target.value)}
                maxLength={256}
                required
                autoComplete="off"
                disabled={!configuration || busy}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="integration-client-secret">
                {t("应用 Client Secret")}
              </FieldLabel>
              <Input
                id="integration-client-secret"
                type="password"
                value={clientSecret}
                onChange={(event) => setClientSecret(event.target.value)}
                maxLength={8000}
                required={!configuration?.has_client_secret}
                autoComplete="new-password"
                disabled={!configuration || busy}
              />
              <FieldDescription>
                {configuration?.has_client_secret
                  ? t("留空保留已保存的密钥。")
                  : t("密钥会加密保存，之后不会返回明文。")}
              </FieldDescription>
            </Field>
            {configuration?.redirect_uri ? (
              <Field>
                <FieldLabel htmlFor="integration-redirect-uri">
                  {t("OAuth 回调地址")}
                </FieldLabel>
                <Input
                  id="integration-redirect-uri"
                  value={configuration.redirect_uri}
                  readOnly
                />
                <FieldDescription>
                  {t("在平台开发者后台登记此回调地址，并开通下列权限。")}
                </FieldDescription>
              </Field>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("请先由系统管理员配置公开站点地址。")}
              </p>
            )}
            {configuration?.scopes.length ? (
              <p className="text-xs break-words text-muted-foreground">
                {configuration.scopes.join(" · ")}
              </p>
            ) : null}
            <a
              href={
                integrationCatalog.find((entry) => entry.provider === provider)!
                  .documentation
              }
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-primary underline underline-offset-4"
            >
              {t("打开开发者平台")}
            </a>
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </FieldGroup>
          <DialogFooter className="pt-5">
            <Button type="button" variant="outline" onClick={onClose}>
              {t("取消")}
            </Button>
            <Button
              type="submit"
              disabled={
                !configuration ||
                !clientId.trim() ||
                (!clientSecret && !configuration.has_client_secret) ||
                busy
              }
            >
              {busy ? <LoaderCircleIcon className="animate-spin" /> : null}
              {t("保存")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

"use client"

import * as React from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"

import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  completeIntegrationAuthorization,
  type IntegrationProvider,
} from "@/lib/api/integrations"
import { getErrorMessage } from "@/lib/errors"

export function IntegrationOAuthCallbackPage() {
  const { t } = useLanguage()
  const { token, me, selectWorkspace } = useSession()
  const query = useSearchParams()
  const originalQuery = React.useRef(query.toString())
  const pending = React.useRef<Promise<string> | null>(null)
  const owner = React.useRef<string | null>(null)
  const actorId = me?.user.id
  const [installed, setInstalled] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => {
    // Remove the code even while the persisted session is loading.
    window.history.replaceState(null, "", window.location.pathname)
    if (!token || !actorId) return
    let active = true
    if (!pending.current) {
      owner.current = actorId
      pending.current = (async () => {
        const values = new URLSearchParams(originalQuery.current)
        const state = values.get("state") ?? ""
        const code = values.get("code")
        const match = /^([0-9a-f-]{36})\.(dida)\.[A-Za-z0-9_-]{43}$/.exec(state)
        if (!match || !code || values.has("error"))
          throw new Error(t("授权未完成，集成尚未安装。"))
        const result = await completeIntegrationAuthorization(
          token,
          match[1],
          match[2] as IntegrationProvider,
          { state, code }
        )
        if (result.status !== "connected")
          throw new Error(t("授权未完成，集成尚未安装。"))
        return match[1]
      })()
    }
    const completion =
      owner.current === actorId
        ? pending.current
        : Promise.reject(new Error(t("授权未完成，集成尚未安装。")))
    completion
      .then((workspaceId) => {
        if (active) {
          setInstalled(true)
          selectWorkspace(workspaceId)
        }
      })
      .catch((nextError) => {
        if (active) setError(getErrorMessage(nextError, t))
      })
    return () => {
      active = false
    }
  }, [token, actorId, selectWorkspace, t])
  return (
    <main className="mx-auto max-w-xl space-y-4 p-6">
      <h1 className="text-xl font-semibold">{t("安装集成")}</h1>
      <p
        role={error ? "alert" : "status"}
        className={
          error ? "text-sm text-destructive" : "text-sm text-muted-foreground"
        }
      >
        {error ?? t(installed ? "授权完成，集成已安装。" : "正在完成授权")}
      </p>
      <Link
        href="/app/tools/integrations"
        className="text-sm underline underline-offset-4"
      >
        {t("返回集成")}
      </Link>
    </main>
  )
}

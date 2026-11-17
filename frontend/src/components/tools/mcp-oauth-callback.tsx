"use client"

import * as React from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { completeMcpOAuth, refreshMcpServer } from "@/lib/api/mcp"
import { getErrorMessage } from "@/lib/errors"

export function McpOAuthCallbackPage() {
  const { t } = useLanguage()
  const { token } = useSession()
  const query = useSearchParams()
  const originalQuery = React.useRef(query.toString())
  const pending = React.useRef<Promise<"connected" | "refresh_failed"> | null>(
    null
  )
  const [result, setResult] = React.useState<
    "connected" | "refresh_failed" | null
  >(null)
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => {
    if (!token) return
    let active = true
    const values = new URLSearchParams(originalQuery.current)
    window.history.replaceState(null, "", window.location.pathname)
    if (!pending.current) {
      pending.current = (async () => {
        const state = values.get("state") ?? ""
        const code = values.get("code")
        const match =
          /^([0-9a-f-]{36})\.([0-9a-f-]{36})\.[A-Za-z0-9_-]{43}$/.exec(state)
        if (values.has("error") || !match || !code)
          throw new Error(t("授权未完成，请返回工具页面重新连接。"))
        await completeMcpOAuth(token, match[1], match[2], state, code)
        try {
          await refreshMcpServer(token, match[1], match[2])
        } catch {
          return "refresh_failed" as const
        }
        return "connected" as const
      })()
    }
    pending.current
      .then((value) => {
        if (active) setResult(value)
      })
      .catch((error) => {
        if (active) setError(getErrorMessage(error, t))
      })
    return () => {
      active = false
    }
  }, [token, t])
  return (
    <main className="mx-auto max-w-xl space-y-4 p-6">
      <h1 className="text-xl font-semibold">{t("OAuth 连接")}</h1>
      <p
        role={error ? "alert" : "status"}
        className={error ? "text-destructive" : "text-muted-foreground"}
      >
        {error ??
          (result === "connected"
            ? t("授权已完成，工具已刷新。")
            : result === "refresh_failed"
              ? t("授权已完成，但工具发现失败。请返回工具页面刷新工具。")
              : t("正在完成授权"))}
      </p>
      <Link className="text-sm underline" href="/app/tools">
        {t("返回工具")}
      </Link>
    </main>
  )
}

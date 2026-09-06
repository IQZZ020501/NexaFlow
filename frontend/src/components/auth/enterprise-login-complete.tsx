"use client"

import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import { useRouter } from "next/navigation"

import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"

function safeDestination(next?: string) {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")
    ? next
    : "/app/apps"
}

export function EnterpriseLoginComplete({ next }: { next?: string }) {
  const { t } = useLanguage()
  const session = useSession()
  const router = useRouter()

  React.useEffect(() => {
    if (!session.isSessionRestored) return
    router.replace(session.token ? safeDestination(next) : "/login")
  }, [next, router, session.isSessionRestored, session.token])

  return (
    <main className="flex min-h-svh items-center justify-center gap-2 bg-muted/30 p-6 text-sm text-muted-foreground">
      <LoaderCircleIcon className="size-4 animate-spin" />
      {t("正在完成企业登录")}
    </main>
  )
}

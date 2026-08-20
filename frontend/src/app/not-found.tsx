"use client"

import Link from "next/link"

import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"

/**
 * Renders the localized 404 page with a link to the applications list.
 */
export default function NotFound() {
  const { t } = useLanguage()

  return (
    <main className="flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border bg-background p-8 text-center shadow-sm">
        <p className="text-sm font-medium text-muted-foreground">404</p>
        <h1 className="mt-2 text-2xl font-semibold">{t("页面不存在")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("请求的页面不存在或已移动")}
        </p>
        <Button asChild className="mt-6">
          <Link href="/app/apps">{t("返回应用列表")}</Link>
        </Button>
      </div>
    </main>
  )
}

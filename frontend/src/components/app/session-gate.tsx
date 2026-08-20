"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { ChangePasswordDialog } from "@/components/auth/change-password-dialog"
import { OperationNotification } from "@/components/app/operation-notification"
import { TopLoadingBar } from "@/components/app/top-progress"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"

/**
 * Controls access to session-dependent content and renders the appropriate loading, authentication, or account state.
 *
 * @param children - Content to render when the session is authenticated and the account is available
 * @returns Loading, authentication, authenticated account content, an account error view, or `null`
 */
export function SessionGate({ children }: { children: React.ReactNode }) {
  const { t } = useLanguage()
  const router = useRouter()
  const {
    token,
    me,
    isSessionLoading,
    isSessionRestored,
    sessionError,
    mustChangePassword,
    notification,
    passwordDialogOpen,
    logout,
    notify,
    dismissNotification,
    closePasswordDialog,
    passwordChanged,
  } = useSession()

  React.useEffect(() => {
    if (isSessionRestored && !token) {
      router.replace("/login")
    }
  }, [token, isSessionRestored, router])

  const loadingProgress = isSessionRestored && token ? 65 : 20

  if (!isSessionRestored || (isSessionLoading && !me)) {
    return (
      <>
        <main className="min-h-svh bg-background" aria-busy="true">
          <span className="sr-only" role="status">{t("正在加载")}</span>
        </main>
        <TopLoadingBar progress={loadingProgress} />
      </>
    )
  }

  if (!token) {
    return null
  }

  if (!me) {
    return (
      <>
        <main className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
          <Card className="w-full max-w-sm">
            <CardHeader>
              <CardTitle>{t("无法加载账号")}</CardTitle>
              <CardDescription>
                {sessionError ?? t("请重新登录")}
              </CardDescription>
            </CardHeader>
            <CardFooter>
              <Button className="w-full" onClick={logout}>
                {t("重新登录")}
              </Button>
            </CardFooter>
          </Card>
        </main>
        <OperationNotification
          notification={notification}
          onDismiss={dismissNotification}
        />
      </>
    )
  }

  return (
    <>
      {children}
      <OperationNotification
        notification={notification}
        onDismiss={dismissNotification}
      />
      <ChangePasswordDialog
        open={mustChangePassword || passwordDialogOpen}
        token={token}
        title={mustChangePassword ? t("修改初始密码") : t("修改密码")}
        description={
          mustChangePassword
            ? t("设置新密码后继续使用 NexaFlow")
            : t("设置一个新的登录密码")
        }
        canDismiss={!mustChangePassword}
        requireCurrentPassword
        onOpenChange={closePasswordDialog}
        onNotify={notify}
        onChanged={() => void passwordChanged()}
      />
    </>
  )
}

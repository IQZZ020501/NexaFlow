"use client"

import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import { useRouter } from "next/navigation"

import { ChangePasswordDialog } from "@/components/auth/change-password-dialog"
import { OperationNotification } from "@/components/app/operation-notification"
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

  if (!token) {
    return null
  }

  if (isSessionLoading && !me) {
    return (
      <main className="flex min-h-svh items-center justify-center bg-background">
        <LoaderCircleIcon className="animate-spin text-muted-foreground" />
      </main>
    )
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
        requireCurrentPassword={!mustChangePassword}
        onOpenChange={closePasswordDialog}
        onNotify={notify}
        onChanged={() => void passwordChanged()}
      />
    </>
  )
}

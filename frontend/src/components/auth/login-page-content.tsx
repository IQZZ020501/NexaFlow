"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { LoginScreen } from "@/components/auth/login-screen"
import { OperationNotification } from "@/components/app/operation-notification"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  listPublicEnterpriseConnections,
  type PublicEnterpriseConnection,
} from "@/lib/api/enterprise-identity"
import { safeAuthDestination } from "@/lib/auth-path"
import type { TranslationKey } from "@/i18n"

/**
 * Renders the login interface and redirects authenticated users to the requested destination.
 *
 * @param next - The requested post-login destination.
 * @returns The login screen and operation notification interface.
 */
export function LoginPageContent({
  next,
  workspace,
  error,
}: {
  next?: string
  workspace?: string
  error?: string
}) {
  const { t } = useLanguage()
  const router = useRouter()
  const {
    token,
    isSessionRestored,
    login,
    notify,
    notification,
    dismissNotification,
  } = useSession()
  const destination = safeAuthDestination(next)
  const [enterpriseConnections, setEnterpriseConnections] = React.useState<
    PublicEnterpriseConnection[]
  >([])

  React.useEffect(() => {
    let active = true
    listPublicEnterpriseConnections(workspace)
      .then((payload) => {
        if (active) setEnterpriseConnections(payload.connections)
      })
      .catch(() => {
        if (active) setEnterpriseConnections([])
      })
    return () => {
      active = false
    }
  }, [workspace])

  React.useEffect(() => {
    if (!error) return
    const messages: Record<string, TranslationKey> = {
      identity_not_bound: "企业身份尚未绑定，请联系系统管理员",
      identity_disabled: "企业身份已停用，请联系系统管理员",
      tenant_mismatch: "企业身份不属于当前工作空间",
      access_denied: "你已不在当前工作空间中",
      invalid_state: "企业登录已过期，请重新尝试",
      provider_error: "企业登录服务暂时不可用，请稍后重试",
    }
    notify("error", t(messages[error] ?? "企业登录失败，请重新尝试"))
  }, [error, notify, t])

  React.useEffect(() => {
    if (isSessionRestored && token) {
      router.replace(destination)
    }
  }, [destination, isSessionRestored, router, token])

  return (
    <>
      <LoginScreen
        onLogin={(token, mustChangePassword, expiresIn) => {
          login(token, mustChangePassword, expiresIn)
          router.replace(destination)
        }}
        onNotify={notify}
        enterpriseConnections={enterpriseConnections}
        next={next}
      />
      <OperationNotification
        notification={notification}
        onDismiss={dismissNotification}
      />
    </>
  )
}

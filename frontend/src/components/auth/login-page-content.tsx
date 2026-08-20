"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { LoginScreen } from "@/components/auth/login-screen"
import { OperationNotification } from "@/components/app/operation-notification"
import { useSession } from "@/contexts/session-context"

/**
 * Validates a requested login redirect path.
 *
 * @param next - The requested redirect path
 * @returns The requested path when it is a valid internal path, or `"/app/apps"` otherwise.
 */
function loginDestination(next: string | undefined) {
  return next &&
    next.startsWith("/") &&
    !next.startsWith("//") &&
    !next.startsWith("/\\")
    ? next
    : "/app/apps"
}

/**
 * Renders the login interface and redirects authenticated users to the requested destination.
 *
 * @param next - The requested post-login destination.
 * @returns The login screen and operation notification interface.
 */
export function LoginPageContent({ next }: { next?: string }) {
  const router = useRouter()
  const {
    token,
    isSessionRestored,
    login,
    notify,
    notification,
    dismissNotification,
  } = useSession()
  const destination = loginDestination(next)

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
      />
      <OperationNotification
        notification={notification}
        onDismiss={dismissNotification}
      />
    </>
  )
}

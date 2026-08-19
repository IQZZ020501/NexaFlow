"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { LoginScreen } from "@/components/auth/login-screen"
import { useSession } from "@/contexts/session-context"

function loginDestination(next: string | undefined) {
  return next &&
    next.startsWith("/") &&
    !next.startsWith("//") &&
    !next.startsWith("/\\")
    ? next
    : "/app/apps"
}

export function LoginPageContent({ next }: { next?: string }) {
  const router = useRouter()
  const { token, isSessionRestored, login, notify } = useSession()
  const destination = loginDestination(next)

  React.useEffect(() => {
    if (isSessionRestored && token) {
      router.replace(destination)
    }
  }, [destination, isSessionRestored, router, token])

  return (
    <LoginScreen
      onLogin={(token, mustChangePassword, expiresIn) => {
        login(token, mustChangePassword, expiresIn)
        router.replace(destination)
      }}
      onNotify={notify}
    />
  )
}

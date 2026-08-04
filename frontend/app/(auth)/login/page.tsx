"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { LoginScreen } from "@/components/auth/login-screen"
import { useSession } from "@/contexts/session-context"

export default function LoginPage() {
  const router = useRouter()
  const { token, isSessionRestored, login, notify } = useSession()

  React.useEffect(() => {
    if (isSessionRestored && token) {
      router.replace("/app/apps")
    }
  }, [isSessionRestored, router, token])

  return (
    <LoginScreen
      onLogin={(token, mustChangePassword, expiresIn) => {
        login(token, mustChangePassword, expiresIn)
        router.replace("/app/apps")
      }}
      onNotify={notify}
    />
  )
}

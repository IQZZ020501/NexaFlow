"use client"

import { useRouter } from "next/navigation"

import { LoginScreen } from "@/components/auth/login-screen"
import { useSession } from "@/contexts/session-context"

export default function LoginPage() {
  const router = useRouter()
  const { login, notify } = useSession()

  return (
    <LoginScreen
      onLogin={(token, mustChangePassword) => {
        login(token, mustChangePassword)
        router.replace("/app/apps")
      }}
      onNotify={notify}
    />
  )
}

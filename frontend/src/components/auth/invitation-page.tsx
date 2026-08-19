"use client"

import * as React from "react"
import Link from "next/link"
import { CheckCircle2Icon, LoaderCircleIcon, UserPlusIcon } from "lucide-react"

import { useLanguage } from "@/contexts/language-provider"
import { acceptWorkspaceInvitation } from "@/lib/api/auth"
import { getErrorMessage } from "@/lib/errors"
import { getNewPasswordError } from "@/lib/password"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

export function InvitationPage({ token }: { token: string }) {
  const { t } = useLanguage()
  const [password, setPassword] = React.useState("")
  const [confirm, setConfirm] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [accepted, setAccepted] = React.useState(false)
  const [submitting, setSubmitting] = React.useState(false)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const passwordError = getNewPasswordError(password, confirm, t)
    if (passwordError) {
      setError(passwordError)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await acceptWorkspaceInvitation(token, password)
      setAccepted(true)
    } catch (requestError) {
      setError(getErrorMessage(requestError, t))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/20 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><UserPlusIcon className="size-4" />{t("接受工作空间邀请")}</CardTitle>
          <CardDescription>{t("设置密码后即可登录工作空间")}</CardDescription>
        </CardHeader>
        <CardContent>
          {accepted ? (
            <div className="grid gap-4 text-center"><CheckCircle2Icon className="mx-auto size-10 text-emerald-600" /><p className="text-sm text-muted-foreground">{t("邀请已接受")}</p><Button asChild><Link href="/login">{t("前往登录")}</Link></Button></div>
          ) : (
            <form className="grid gap-4" onSubmit={submit}>
              <label className="grid gap-1 text-sm"><span>{t("新密码")}</span><Input type="password" minLength={6} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
              <label className="grid gap-1 text-sm"><span>{t("确认密码")}</span><Input type="password" minLength={6} autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required /></label>
              <p className="text-xs text-muted-foreground">{t("至少 6 位，并且包含一个大写字母")}</p>
              {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
              <Button disabled={submitting}>{submitting ? <LoaderCircleIcon className="animate-spin" /> : null}{t("接受邀请")}</Button>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  )
}

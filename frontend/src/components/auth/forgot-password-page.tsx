"use client"

import * as React from "react"
import Link from "next/link"
import { CheckCircle2Icon, LoaderCircleIcon, MailIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { requestPasswordReset } from "@/lib/api/auth"
import { getErrorMessage } from "@/lib/errors"

/** Renders the public form used to request a password-reset email. */
export function ForgotPasswordPage() {
  const { t } = useLanguage()
  const [email, setEmail] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [isSubmitted, setIsSubmitted] = React.useState(false)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!event.currentTarget.reportValidity()) return

    setIsSubmitting(true)
    setError(null)
    try {
      await requestPasswordReset(email.trim())
      setIsSubmitted(true)
    } catch (requestError) {
      setError(getErrorMessage(requestError, t))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MailIcon className="size-4" aria-hidden="true" />
            {t("忘记密码")}
          </CardTitle>
          <CardDescription>
            {t("输入你的邮箱，我们会发送密码重置链接")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isSubmitted ? (
            <div
              className="grid gap-4 text-center"
              role="status"
              aria-live="polite"
            >
              <CheckCircle2Icon
                className="mx-auto size-10 text-emerald-600"
                aria-hidden="true"
              />
              <div className="grid gap-1">
                <p className="font-medium">{t("重置链接已发送")}</p>
                <p className="text-sm text-muted-foreground">
                  {t("如果该邮箱已注册，我们已发送重置链接，请检查邮箱")}
                </p>
              </div>
              <Button asChild>
                <Link href="/login">{t("前往登录")}</Link>
              </Button>
            </div>
          ) : (
            <form
              className="grid gap-4"
              onSubmit={submit}
              aria-busy={isSubmitting}
            >
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="password-reset-email">
                    {t("邮箱")}
                  </FieldLabel>
                  <Input
                    id="password-reset-email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(event) => {
                      setEmail(event.target.value)
                      setError(null)
                    }}
                    maxLength={255}
                    required
                    disabled={isSubmitting}
                  />
                </Field>
              </FieldGroup>
              {error ? (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              ) : null}
              <div className="grid gap-2">
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? (
                    <LoaderCircleIcon
                      className="animate-spin"
                      aria-hidden="true"
                    />
                  ) : null}
                  {t("发送重置链接")}
                </Button>
                <Button type="button" variant="ghost" asChild>
                  <Link href="/login">{t("前往登录")}</Link>
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  )
}

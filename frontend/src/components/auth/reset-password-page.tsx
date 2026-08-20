"use client"

import * as React from "react"
import Link from "next/link"
import { CheckCircle2Icon, KeyRoundIcon, LoaderCircleIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { confirmPasswordReset } from "@/lib/api/auth"
import { getErrorMessage } from "@/lib/errors"
import { getNewPasswordError } from "@/lib/password"

/**
 * Renders the public password-reset form for a one-time email token.
 *
 * @param token - The password-reset token supplied by the route
 */
export function ResetPasswordPage({ token }: { token: string }) {
  const { t } = useLanguage()
  const [newPassword, setNewPassword] = React.useState("")
  const [confirmPassword, setConfirmPassword] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [isReset, setIsReset] = React.useState(false)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const passwordError = getNewPasswordError(newPassword, confirmPassword, t)
    if (passwordError) {
      setError(passwordError)
      return
    }

    setIsSubmitting(true)
    setError(null)
    try {
      await confirmPasswordReset(token, newPassword)
      setIsReset(true)
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
            <KeyRoundIcon className="size-4" aria-hidden="true" />
            {t("重置密码")}
          </CardTitle>
          <CardDescription>{t("设置新密码后即可重新登录")}</CardDescription>
        </CardHeader>
        <CardContent>
          {isReset ? (
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
                <p className="font-medium">{t("密码已重置")}</p>
                <p className="text-sm text-muted-foreground">
                  {t("密码重置成功，请使用新密码登录")}
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
                  <FieldLabel htmlFor="reset-new-password">
                    {t("新密码")}
                  </FieldLabel>
                  <Input
                    id="reset-new-password"
                    type="password"
                    autoComplete="new-password"
                    minLength={6}
                    value={newPassword}
                    onChange={(event) => {
                      setNewPassword(event.target.value)
                      setError(null)
                    }}
                    required
                    disabled={isSubmitting}
                    aria-describedby="reset-password-requirements"
                  />
                  <FieldDescription id="reset-password-requirements">
                    {t("至少 6 位，并且包含一个大写字母")}
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="reset-confirm-password">
                    {t("确认密码")}
                  </FieldLabel>
                  <Input
                    id="reset-confirm-password"
                    type="password"
                    autoComplete="new-password"
                    minLength={6}
                    value={confirmPassword}
                    onChange={(event) => {
                      setConfirmPassword(event.target.value)
                      setError(null)
                    }}
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
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                {t("重置密码")}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  )
}

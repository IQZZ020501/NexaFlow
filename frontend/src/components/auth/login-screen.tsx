import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import Image from "next/image"
import { useLanguage } from "@/contexts/language-provider"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { login } from "@/lib/api/auth"
import { ChangePasswordDialog } from "@/components/auth/change-password-dialog"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"

type LoginForm = {
  username: string
  password: string
}

export function LoginScreen({
  onLogin,
  onNotify,
}: {
  onLogin: (token: string, mustChangePassword: boolean, expiresIn: number) => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { t } = useLanguage()
  const [form, setForm] = React.useState<LoginForm>({
    username: "",
    password: "",
  })
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = React.useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)

    try {
      const payload = await login(form.username, form.password)
      onLogin(
        payload.access_token,
        payload.must_change_password,
        payload.expires_in
      )
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <>
      <main className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Image
                src="/NexaFlow-logo.png"
                alt=""
                width={36}
                height={36}
                priority
                className="size-9 rounded-full dark:invert"
              />
              <span>NexaFlow</span>
            </CardTitle>
            <CardDescription>{t("登录到你的工作空间")}</CardDescription>
          </CardHeader>
          <form onSubmit={handleSubmit}>
            <CardContent>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="username">{t("用户名")}</FieldLabel>
                  <Input
                    id="username"
                    autoComplete="username"
                    value={form.username}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        username: event.target.value,
                      }))
                    }
                    required
                  />
                </Field>
                <Field>
                  <div className="flex min-h-5 items-baseline justify-between gap-3">
                    <FieldLabel htmlFor="password">{t("密码")}</FieldLabel>
                    <button
                      type="button"
                      className="rounded-sm text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                      onClick={() => setIsPasswordDialogOpen(true)}
                    >
                      {t("修改密码")}
                    </button>
                  </div>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    value={form.password}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        password: event.target.value,
                      }))
                    }
                    required
                  />
                </Field>
              </FieldGroup>
            </CardContent>
            <CardFooter className="pt-6">
              <Button className="w-full" disabled={isSubmitting}>
                {isSubmitting ? (
                  <LoaderCircleIcon data-icon="inline-start" />
                ) : null}
                {t("登录")}
              </Button>
            </CardFooter>
          </form>
        </Card>
      </main>
      <ChangePasswordDialog
        open={isPasswordDialogOpen}
        title={t("修改密码")}
        description={t("设置一个新的登录密码")}
        canDismiss
        requireCurrentPassword
        onOpenChange={setIsPasswordDialogOpen}
        onNotify={onNotify}
        onChanged={() => {
          setIsPasswordDialogOpen(false)
          onNotify("success", t("密码已修改"))
        }}
      />
    </>
  )
}

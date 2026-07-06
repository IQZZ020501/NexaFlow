import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import { useLanguage } from "@/components/language-provider"
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
import { login } from "@/features/auth/api"
import { getErrorMessage } from "@/app/errors"

type LoginForm = {
  username: string
  password: string
}

export function LoginScreen({
  onLogin,
}: {
  onLogin: (token: string, mustChangePassword: boolean) => void
}) {
  const { t } = useLanguage()
  const [form, setForm] = React.useState<LoginForm>({
    username: "",
    password: "",
  })
  const [error, setError] = React.useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = React.useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      const payload = await login(form.username, form.password)
      onLogin(payload.access_token, payload.must_change_password)
    } catch (error) {
      setError(getErrorMessage(error, t))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>NexaFlow</CardTitle>
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
                <FieldLabel htmlFor="password">{t("密码")}</FieldLabel>
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
              {error ? (
                <p className="text-sm text-destructive">{error}</p>
              ) : null}
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
  )
}

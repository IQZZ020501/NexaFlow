import DingtalkOutlined from "@ant-design/icons/es/icons/DingtalkOutlined"
import WechatWorkOutlined from "@ant-design/icons/es/icons/WechatWorkOutlined"
import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import Image from "next/image"
import Link from "next/link"
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
import { apiUrl } from "@/lib/api-client"
import type {
  EnterpriseProvider,
  PublicEnterpriseConnection,
} from "@/lib/api/enterprise-identity"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"

type LoginForm = {
  username: string
  password: string
}

function EnterpriseProviderIcon({
  provider,
}: {
  provider: EnterpriseProvider
}) {
  if (provider === "feishu") {
    return (
      <Image
        src="/feishu.svg"
        alt=""
        width={20}
        height={20}
        data-provider-icon={provider}
      />
    )
  }
  if (provider === "dingtalk") {
    return (
      <DingtalkOutlined
        aria-hidden="true"
        data-provider-icon={provider}
        className="text-xl text-[#1677ff]"
      />
    )
  }
  return (
    <WechatWorkOutlined
      aria-hidden="true"
      data-provider-icon={provider}
      className="text-xl text-[#07c160]"
    />
  )
}

/**
 * Renders a localized login form and provides access to password recovery.
 *
 * @param onLogin - Called with the access token, password-change requirement, and expiration time after a successful login.
 * @param onNotify - Called with the notification kind and message for user-facing feedback.
 */
export function LoginScreen({
  onLogin,
  onNotify,
  enterpriseConnections = [],
  next,
}: {
  onLogin: (
    token: string,
    mustChangePassword: boolean,
    expiresIn: number
  ) => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
  enterpriseConnections?: PublicEnterpriseConnection[]
  next?: string
}) {
  const { t } = useLanguage()
  const [form, setForm] = React.useState<LoginForm>({
    username: "",
    password: "",
  })
  const [isSubmitting, setIsSubmitting] = React.useState(false)

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
                  <div className="flex justify-end">
                    <Link
                      href="/forgot-password"
                      className="rounded-sm text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                    >
                      {t("忘记密码")}
                    </Link>
                  </div>
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
          {enterpriseConnections.length ? (
            <CardContent className="grid gap-3 border-t pt-6">
              <div className="text-center text-xs text-muted-foreground">
                {t("或使用企业账号登录")}
              </div>
              <div className="flex flex-wrap justify-center gap-3">
                {enterpriseConnections.map((connection) => {
                  const params = new URLSearchParams()
                  if (next) params.set("next", next)
                  const href = apiUrl(
                    `${connection.start_url}${params.size ? `?${params}` : ""}`
                  )
                  const label = t("使用 {provider} 扫码登录", {
                    provider: connection.name,
                  })
                  return (
                    <Button
                      key={connection.id}
                      variant="outline"
                      size="icon-lg"
                      className="size-10 rounded-full"
                      asChild
                    >
                      <a href={href} aria-label={label} title={connection.name}>
                        <EnterpriseProviderIcon
                          provider={connection.provider}
                        />
                      </a>
                    </Button>
                  )
                })}
              </div>
            </CardContent>
          ) : null}
        </Card>
      </main>
    </>
  )
}

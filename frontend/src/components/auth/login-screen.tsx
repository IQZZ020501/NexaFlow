import DingtalkOutlined from "@ant-design/icons/es/icons/DingtalkOutlined"
import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import Image from "next/image"
import Link from "next/link"
import { useLanguage } from "@/contexts/language-provider"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { login } from "@/lib/api/auth"
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
    <Image
      src="/wecom.png"
      alt=""
      width={20}
      height={20}
      data-provider-icon={provider}
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
    <main className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,1.1fr)_minmax(28rem,0.9fr)]">
      <section className="relative hidden min-h-dvh items-center justify-center overflow-hidden border-r bg-white p-10 lg:flex xl:p-16 dark:bg-black">
        <Image
          src="/NexaFlow-logo.svg"
          alt="NexaFlow"
          width={642}
          height={228}
          priority
          sizes="(min-width: 1024px) 55vw, 0px"
          className="h-auto w-full object-contain dark:invert"
        />
      </section>
      <section
        aria-labelledby="login-heading"
        className="flex min-h-dvh items-start justify-center px-6 pt-[max(2rem,env(safe-area-inset-top))] pb-[max(2rem,env(safe-area-inset-bottom))] sm:items-center sm:px-10 lg:px-14 xl:px-20"
      >
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Image
              src="/NexaFlow-logo.svg"
              alt="NexaFlow"
              width={642}
              height={228}
              priority
              sizes="256px"
              className="mx-auto h-auto w-full max-w-64 dark:invert"
            />
          </div>
          <div className="mb-8 space-y-2">
            <h1
              id="login-heading"
              className="text-2xl font-semibold tracking-tight"
            >
              {t("登录")}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("登录到你的工作空间")}
            </p>
          </div>
          <form onSubmit={handleSubmit} className="grid gap-6">
            <FieldGroup className="gap-5">
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
                    className="rounded-sm text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none max-sm:-mr-2 max-sm:inline-flex max-sm:min-h-10 max-sm:items-center max-sm:px-2"
                  >
                    {t("忘记密码")}
                  </Link>
                </div>
              </Field>
            </FieldGroup>
            <Button
              type="submit"
              className="h-11 w-full"
              disabled={isSubmitting}
              aria-busy={isSubmitting}
            >
              {isSubmitting ? (
                <LoaderCircleIcon
                  data-icon="inline-start"
                  aria-hidden="true"
                  className="animate-spin motion-reduce:animate-none"
                />
              ) : null}
              {t(isSubmitting ? "登录中" : "登录")}
            </Button>
          </form>
          {enterpriseConnections.length ? (
            <div className="mt-8 grid gap-4 border-t pt-6">
              <div className="text-center text-xs text-muted-foreground">
                {t("或使用企业账号登录")}
              </div>
              <div className="flex flex-wrap justify-center gap-3">
                {enterpriseConnections.map((connection) => {
                  const params = new URLSearchParams()
                  if (next) params.set("next", next)
                  const href = `${connection.start_url}${params.size ? `?${params}` : ""}`
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
            </div>
          ) : null}
        </div>
      </section>
    </main>
  )
}

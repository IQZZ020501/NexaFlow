import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { changePassword, login } from "@/features/auth/api"
import { getErrorMessage } from "@/app/errors"
import type { AppNotification } from "@/app/notifications"
import { getNewPasswordError } from "@/features/auth/password"

type ChangePasswordForm = {
  username: string
  currentPassword: string
  newPassword: string
  confirmPassword: string
}

export function ChangePasswordDialog({
  open,
  token,
  title,
  description,
  canDismiss = false,
  requireCurrentPassword = false,
  onOpenChange,
  onNotify,
  onChanged,
}: {
  open: boolean
  token?: string
  title?: string
  description?: string
  canDismiss?: boolean
  requireCurrentPassword?: boolean
  onOpenChange?: (open: boolean) => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
  onChanged: () => void
}) {
  const { t } = useLanguage()
  const [form, setForm] = React.useState<ChangePasswordForm>({
    username: "",
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
  })
  const [isSubmitting, setIsSubmitting] = React.useState(false)

  function resetForm() {
    setForm({
      username: "",
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    })
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen || !canDismiss) {
      return
    }

    resetForm()
    onOpenChange?.(false)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (requireCurrentPassword && !form.currentPassword) {
      onNotify("error", t("请输入当前密码"))
      return
    }

    const passwordError = getNewPasswordError(
      form.newPassword,
      form.confirmPassword,
      t
    )
    if (passwordError) {
      onNotify("error", passwordError)
      return
    }

    setIsSubmitting(true)
    try {
      const accessToken =
        token ?? (await login(form.username, form.currentPassword)).access_token
      await changePassword(
        accessToken,
        form.newPassword,
        requireCurrentPassword ? form.currentPassword : undefined
      )
      resetForm()
      onChanged()
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        onEscapeKeyDown={
          canDismiss ? undefined : (event) => event.preventDefault()
        }
        onPointerDownOutside={
          canDismiss ? undefined : (event) => event.preventDefault()
        }
      >
        <DialogHeader>
          <DialogTitle>{title ?? t("修改初始密码")}</DialogTitle>
          <DialogDescription>
            {description ?? t("设置新密码后继续使用 NexaFlow")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <FieldGroup>
            {!token ? (
              <Field>
                <FieldLabel htmlFor="changePasswordUsername">
                  {t("用户名")}
                </FieldLabel>
                <Input
                  id="changePasswordUsername"
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
            ) : null}
            {requireCurrentPassword ? (
              <Field>
                <FieldLabel htmlFor="currentPassword">
                  {t("当前密码")}
                </FieldLabel>
                <Input
                  id="currentPassword"
                  type="password"
                  autoComplete="current-password"
                  value={form.currentPassword}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      currentPassword: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
            ) : null}
            <Field>
              <FieldLabel htmlFor="newPassword">{t("新密码")}</FieldLabel>
              <Input
                id="newPassword"
                type="password"
                autoComplete="new-password"
                minLength={6}
                value={form.newPassword}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    newPassword: event.target.value,
                  }))
                }
                required
              />
              <FieldDescription>
                {t("至少 6 位，并且包含一个大写字母")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="confirmPassword">{t("确认密码")}</FieldLabel>
              <Input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                minLength={6}
                value={form.confirmPassword}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    confirmPassword: event.target.value,
                  }))
                }
                required
              />
            </Field>
          </FieldGroup>
          <DialogFooter className="pt-4">
            <Button className="w-full" disabled={isSubmitting}>
              {isSubmitting ? (
                <LoaderCircleIcon data-icon="inline-start" />
              ) : null}
              {t("保存")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

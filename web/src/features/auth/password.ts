import { type TFunction } from "@/lib/i18n"

export function getNewPasswordError(
  newPassword: string,
  confirmPassword: string,
  t: TFunction
) {
  if (newPassword !== confirmPassword) {
    return t("两次输入的新密码不一致")
  }

  if (newPassword.length < 6 || !/[A-Z]/.test(newPassword)) {
    return t("密码至少 6 位，并且包含一个大写字母")
  }

  return null
}

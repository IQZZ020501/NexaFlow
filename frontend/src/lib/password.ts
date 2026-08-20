import { type TFunction } from "@/i18n"

/**
 * Validates a new password against its confirmation and password requirements.
 *
 * @param newPassword - The new password to validate
 * @param confirmPassword - The password confirmation to compare
 * @returns A translated validation error message, or `null` when the password is valid
 */
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

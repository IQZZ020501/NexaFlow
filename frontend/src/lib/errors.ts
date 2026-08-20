import { ApiError } from "@/lib/api-client"
import { type TFunction, type TranslationKey } from "@/i18n"

const API_ERROR_LABEL_KEYS: Record<string, TranslationKey> = {
  "SMTP settings are not configured.": "尚未配置 SMTP",
  "SMTP test failed.": "SMTP 测试失败，请检查服务器、端口、加密方式和凭据",
  "SMTP host and sender address are required when enabled.":
    "启用 SMTP 时必须填写主机和发件人邮箱",
  "Invalid SMTP sender address.": "发件人邮箱格式无效",
  "Invalid SMTP recipient address.": "收件人邮箱格式无效",
  "Invalid public site URL.": "站点地址格式无效",
  "Value error, Invalid public site URL.": "站点地址格式无效",
  "Public site URL is required when SMTP is enabled.":
    "启用 SMTP 时必须填写站点地址",
  "Email service is not configured.": "邮件服务尚未配置，请联系系统管理员",
  "Password reset is temporarily unavailable.":
    "密码重置暂时不可用，请稍后重试",
  "Too many password reset requests.": "密码重置请求过于频繁，请稍后重试",
  "Password reset link is invalid or expired.": "密码重置链接无效或已过期",
  "New password must be different.": "新密码不能与原密码相同",
}

/**
 * Converts an unknown error into a user-facing message.
 *
 * @param error - The error value to convert
 * @returns A localized message for recognized authentication, authorization, network, or unknown errors; otherwise, the original error message
 */
export function getErrorMessage(error: unknown, t: TFunction) {
  if (error instanceof ApiError) {
    if (error.status === 401 && error.message === "Invalid credentials.") {
      return t("用户名或密码错误")
    }
    if (error.status === 401) return t("请重新登录")
    if (error.status === 403 || error.status === 404) {
      return t("资源不存在或无权访问")
    }
    const labelKey = API_ERROR_LABEL_KEYS[error.message]
    if (labelKey) return t(labelKey)
    return error.message
  }

  if (error instanceof Error) {
    if (/failed to fetch|networkerror|load failed/i.test(error.message)) {
      return t("网络连接失败，请稍后重试")
    }
    return error.message
  }

  return t("请求失败")
}

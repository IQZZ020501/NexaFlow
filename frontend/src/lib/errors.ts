import { ApiError } from "@/lib/api-client"
import { type TFunction } from "@/i18n"

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

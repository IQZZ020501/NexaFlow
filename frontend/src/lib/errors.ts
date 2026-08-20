import { ApiError } from "@/lib/api-client"
import { type TFunction } from "@/i18n"

export function getErrorMessage(error: unknown, t: TFunction) {
  if (error instanceof ApiError) {
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

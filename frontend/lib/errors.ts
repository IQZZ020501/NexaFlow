import { ApiError } from "@/lib/api-client"
import { type TFunction } from "@/i18n"

export function getErrorMessage(error: unknown, t: TFunction) {
  if (error instanceof ApiError) {
    return error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return t("请求失败")
}

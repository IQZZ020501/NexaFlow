"use client"

import { DateTimeField } from "@/components/app/date-time-field"
import { useLanguage } from "@/contexts/language-provider"

export function AnnouncementExpirationField({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  const { t } = useLanguage()
  return (
    <DateTimeField
      value={value}
      onChange={onChange}
      id="announcement-expires-at"
      label={t("公告过期时间")}
      description={t("留空表示永不过期。")}
    />
  )
}

"use client"

import { useLanguage } from "@/contexts/language-provider"
import { languageLocales } from "@/i18n"
import { formatDateTime } from "@/lib/display"

export function MessageTimestamp({ value }: { value?: string | null }) {
  const { language } = useLanguage()
  if (!value) return null

  return (
    <time
      dateTime={value}
      className="mt-1 px-1 text-[11px] leading-5 text-muted-foreground"
    >
      {formatDateTime(value, languageLocales[language])}
    </time>
  )
}

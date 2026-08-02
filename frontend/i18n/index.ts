export type Language = "zh-Hans" | "zh-Hant" | "en"

export const DEFAULT_LANGUAGE: Language = "zh-Hans"
export const LANGUAGE_STORAGE_KEY = "nexaflow.language"

export const languageOptions: Array<{
  value: Language
  label: string
  shortLabel: string
}> = [
  { value: "zh-Hans", label: "简体中文", shortLabel: "简体" },
  { value: "zh-Hant", label: "繁體中文", shortLabel: "繁體" },
  { value: "en", label: "English", shortLabel: "EN" },
]

import { zhHans } from "./zh-hans"
import { zhHant } from "./zh-hant"
import { en } from "./en"

const translations = {
  "zh-Hans": zhHans,
  "zh-Hant": zhHant,
  en,
} satisfies Record<Language, Record<TranslationKey, string>>

export const languageLocales: Record<Language, string> = {
  "zh-Hans": "zh-CN",
  "zh-Hant": "zh-TW",
  en: "en-US",
}

export function isLanguage(value: string | null): value is Language {
  return languageOptions.some((option) => option.value === value)
}

export function translate(
  language: Language,
  key: TranslationKey,
  values?: Record<string, string | number>
) {
  const message = translations[language][key]

  if (!values) {
    return message
  }

  return message.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name)
      ? String(values[name])
      : match
  )
}

export type { TranslationKey, TFunction } from "./zh-hans"
export { zhHans, zhHant, en }
